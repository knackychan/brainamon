"""Desktop backup state uses frozen synthetic server facts, without Svelte or network access."""
import json
import unittest
from pathlib import Path

from tests.test_phone_js import node, TS_RESOLVE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/desktop_backup_states.json'


def states(script):
    return json.loads(node(TS_RESOLVE + """
        import fs from 'node:fs'
        const { backupState } = await import('./web/src/lib/backup-state.ts')
        const fx = JSON.parse(fs.readFileSync('tests/fixtures/desktop_backup_states.json', 'utf8'))
    """ + script))


class DesktopBackupStateTest(unittest.TestCase):
    def test_vault_checks_show_counts_and_network_waits_show_the_phase(self):
        got = states("""
          console.log(JSON.stringify([
            {vault_step:'Checking generated notes', vault_done:12, vault_total:40},
            {vault_step:'Listing files in Google Drive', vault_done:0, vault_total:0},
            {vault_step:'Finding vault files', vault_done:12, vault_total:0},
          ].map(step => backupState({...fx.cloud, licensed:true, vault_state:'syncing', ...step}, fx.recovery, fx.now).rows.vault)))
        """)
        self.assertEqual([row['text'] for row in got], ['Checking generated notes · 12 of 40 files',
                                                      'Listing files in Google Drive', 'Finding vault files · 12 files'])
        self.assertTrue(all(row['kind'] == 'working' for row in got))

    def test_old_phone_reports_do_not_claim_a_lost_connection(self):
        got = states("""
          console.log(JSON.stringify([0, 59*60000, 61*60000, 7*86400000].map(age => backupState(
            {...fx.cloud, phones:[{device:'a',name:'Phone',seen:fx.now-age}]}, fx.recovery, fx.now))))
        """)
        for state in got:
            self.assertEqual(state['rows']['phones']['text'], '1 phone has reported a sync.')
            self.assertEqual(state['rows']['phones']['kind'], 'done')
            self.assertIn('30 minutes', state['rows']['phones']['detail'])
            self.assertIn('current sync status', state['rows']['phones']['detail'])
            self.assertNotIn('in sync', state['hero']['detail'])

    def test_replacement_recovery_file_is_optional(self):
        state = states("""
          console.log(JSON.stringify(backupState(fx.cloud, {...fx.recovery,file_outdated:true}, fx.now)))
        """)
        self.assertEqual(state['id'], 'file-outdated')
        self.assertEqual(state['kind'], 'done')
        self.assertNotIn('primary', state['hero'])
        self.assertEqual(state['hero']['quiet'][0]['id'], 'save-file')
        self.assertIn('optional', state['hero']['detail'])
        self.assertIn('unlocked by your passphrase.', state['hero']['text'])
        self.assertEqual(state['rows']['recovery']['kind'], 'done')

    def test_pairing_follows_server_readiness_and_gate(self):
        reasons = states("""
          const { pairingReason } = await import('./web/src/lib/backup-state.ts')
          const ready = {...fx.cloud, pair_ready:true}
          console.log(JSON.stringify([
            pairingReason(ready),
            pairingReason({...ready, rotation:'pending'}),
            pairingReason({...ready, pair_ready:false, rotation:'pending'}),
            pairingReason({...ready, pair_ready:false, recovery_gate_active:true,
              recovery_activity:{action:'unpair', state:'running', step:'Locking phones out…', started:fx.now}}),
            pairingReason({...ready, pair_ready:false, key_missing:true}),
            pairingReason({...ready, pair_ready:undefined}),
          ]))
        """)
        self.assertEqual(reasons[:2], ['', ''])
        self.assertIn('usable pairing key', reasons[2])
        self.assertIn('Locking phones out', reasons[3])
        self.assertIn('Unlock', reasons[4])
        self.assertTrue(reasons[5])

    def test_running_backup_offers_pause(self):
        states_for_upload = states("""
          const cloud = {...fx.cloud, state:'publishing', running:true, task:null}
          console.log(JSON.stringify([
            backupState({...cloud, last_publish:0}, fx.recovery, fx.now),
            backupState(cloud, fx.recovery, fx.now),
            backupState({...cloud, last_publish:0, running:false}, fx.recovery, fx.now),
          ]))
        """)
        self.assertEqual([a['id'] for a in states_for_upload[0]['hero']['quiet']], ['pause'])
        self.assertEqual([a['id'] for a in states_for_upload[1]['hero']['quiet']], ['pause'])
        self.assertEqual(states_for_upload[2]['hero']['quiet'], [])

    def test_dismissals_do_not_hide_unrelated_notices(self):
        got = states("""
          const cloud = {...fx.cloud, rotation:'complete', rotation_locked_at:fx.now, phones:[]}
          const rec = {...fx.recovery, updated:{at:fx.now, published:fx.now, kept:0, folder:''}}
          console.log(JSON.stringify([
            backupState(cloud, rec, fx.now, {}),
            backupState(cloud, rec, fx.now, {dismissedRemoval:true}),
            backupState(cloud, rec, fx.now, {dismissedRemoval:true, dismissedUpdate:true}),
          ]))
        """)
        self.assertEqual([s['id'] for s in got], ['phones-removed', 'updated', 'safe'])

    def test_matrix(self):
        fx = json.loads(FIXTURE.read_text(encoding='utf-8'))
        got = states("""
          console.log(JSON.stringify(fx.cases.map(c => backupState(c.cloud === null ? null : {...fx.cloud, ...c.cloud},
            c.rec === null || c.rec === 'error' ? c.rec : {...fx.recovery, ...c.rec}, fx.now, c.local))))
        """)
        self.assertEqual(len(fx['cases']), 88)
        for case, actual in zip(fx['cases'], got):
            with self.subTest(case=case['id']):
                self.assertEqual(actual['id'], case['state'])
                primary = (actual['task'] or {}).get('primary') or actual['hero'].get('primary')
                self.assertEqual(primary['id'] if primary else None, case['expected_primary'])
                self.assertEqual('Your library is safe' in actual['hero']['text'], case['expected_safe_claim'])
                self.assertEqual('or recovery file' in actual['hero']['text'], case['expected_checked_file_claim'])
                expected_task = case['expected_task']
                if expected_task is None:
                    self.assertIsNone(actual['task'])
                else:
                    self.assertIsNotNone(actual['task'])
                    self.assertEqual((actual['task']['step'], actual['task']['of']), (expected_task['step'], expected_task['of']))
                    self.assertEqual([t['id'] for t in actual['task']['also']], case['expected_waiting_ids'])
                    if expected_task['pct'] is None:
                        self.assertNotIn('pct', actual['task'])
                    else:
                        self.assertAlmostEqual(actual['task']['pct'], expected_task['pct'])
                for line in [actual['hero'], *actual['rows'].values()]:
                    if line['kind'] == 'working':
                        self.assertEqual(line['tone'], 'busy')
                words = ' '.join([actual['hero']['text'], actual['hero'].get('detail') or '',
                                  actual['task']['line'] if actual['task'] else '',
                                  ' '.join(s['label'] for s in actual['task']['steps']) if actual['task'] else ''])
                self.assertIn(case['expect'], words)

    def test_recovery_truth_and_unknown_reads(self):
        got = states("""
          const rows = [null, 'error', {...fx.recovery, setup_at:0, saved_at:0, verified_at:0, verified:true},
            {...fx.recovery, account:'other@example.com'}].map(r => backupState(fx.cloud, r, fx.now))
          console.log(JSON.stringify(rows))
        """)
        self.assertEqual([s['id'] for s in got], ['recovery-loading', 'recovery-unread', 'safe', 'no-recovery'])
        self.assertEqual(got[1]['hero']['primary']['id'], 'retry-status')
        self.assertEqual(got[2]['rows']['recovery']['text'], 'Passphrase set')
        self.assertNotIn('recovery file', got[2]['hero']['text'])

    def test_update_task_actions_and_automatic_wait(self):
        got = states("""
          const caseOf = id => fx.cases.find(c => c.id === id)
          const view = id => { const c=caseOf(id); return backupState({...fx.cloud,...c.cloud},
            c.rec ? {...fx.recovery,...c.rec} : fx.recovery, fx.now) }
          const c=caseOf('update-failed'), base={...fx.cloud,...c.cloud}
          console.log(JSON.stringify({downloaded:view('update-downloaded'), swap:view('update-swap'),
            failed:view('update-failed'), wait:backupState({...base,error_action:'wait'},fx.recovery,fx.now),
            none:backupState({...base,error_action:'none'},fx.recovery,fx.now),
            offline:backupState({...base,error_code:'offline'},fx.recovery,fx.now)}))
        """)
        self.assertEqual(got['downloaded']['task']['primary']['id'], 'restart')
        self.assertEqual([a['id'] for a in got['downloaded']['task']['quiet']], ['stop-update'])
        self.assertEqual(got['swap']['task']['primary']['id'], 'restart')
        self.assertNotIn('stop-update', [a['id'] for a in got['swap']['task']['quiet']])
        self.assertEqual(got['failed']['task']['primary']['id'], 'retry-update')
        for name in ('wait', 'none', 'offline'):
            self.assertNotIn('primary', got[name]['task'], name)

    def test_queue_pause_counts_reconnect_and_removal(self):
        got = states("""
          const base = fx.cases.find(c => c.id === 'removing-checking') || fx.cases.find(c => c.cloud?.task?.kind === 'remove_phones')
          const task = {...base.cloud.task, step:4, done:25, total:100, bytes_done:0, bytes_total:0, paused_snapshot:true}
          const cloud = {...fx.cloud, ...base.cloud, task, tasks:[{id:task.id, kind:task.kind, title:task.title, stage:task.stage, error:'', code:''},
            {id:'second', kind:'enroll', title:'Saving the recovery passphrase', stage:'queued', error:'', code:''}]}
          const active = backupState(cloud, fx.recovery, fx.now)
          const paused = backupState({...cloud, on:false, running:false, paused_since:fx.now}, fx.recovery, fx.now)
          const draining = backupState({...cloud, on:false, running:true, state:'stopping', paused_since:fx.now}, fx.recovery, fx.now)
          const restarted = backupState({...cloud, on:false, running:false, paused_since:fx.now, task:{...task, paused_snapshot:false}}, fx.recovery, fx.now)
          const cleanup = backupState({...cloud, task:{...task, step:5, done:200, total:1000, bytes_done:50, bytes_total:100}}, fx.recovery, fx.now)
          const reconnect = backupState({...fx.cloud, recovery_activity:{action:'reconnect', state:'running', step:'Actual server sentence', started:fx.now, step_index:2, step_count:4}}, fx.recovery, fx.now)
          const reconnectWithQueue = backupState({...cloud, recovery_activity:{action:'reconnect', state:'running', step:'Checking', started:fx.now, step_index:1, step_count:4}}, fx.recovery, fx.now)
          console.log(JSON.stringify({active, paused, draining, restarted, cleanup, reconnect, reconnectWithQueue}))
        """)
        self.assertEqual(got['active']['task']['pct'], 25)
        self.assertEqual(got['active']['task']['also'], [{'id': 'second', 'kind': 'enroll', 'title': 'Saving the recovery passphrase', 'stage': 'queued', 'error': '', 'code': ''}])
        self.assertIn('Last reported when Pause was requested.', got['paused']['task']['notes'])
        self.assertEqual(got['paused']['task']['primary']['id'], 'resume')
        self.assertFalse(got['draining']['task']['running'])
        self.assertIn('Last reported when Pause was requested.', got['draining']['task']['notes'])
        self.assertNotIn('primary', got['draining']['task'])
        self.assertEqual(got['paused']['rows']['phones']['kind'], 'paused')
        self.assertEqual(got['paused']['rows']['recovery']['kind'], 'paused')
        self.assertEqual(got['restarted']['task']['progress'], 'steps')
        self.assertNotIn('pct', got['restarted']['task'])
        self.assertEqual(got['cleanup']['task']['pct'], 20)
        self.assertIn('200 of 1,000 files confirmed', got['cleanup']['task']['steps'][4]['label'])
        self.assertEqual((got['reconnect']['task']['step'], got['reconnect']['task']['of']), (2, 4))
        self.assertEqual(got['reconnect']['task']['steps'][1]['label'], 'Actual server sentence')
        self.assertEqual([q['id'] for q in got['reconnectWithQueue']['task']['also']], [got['active']['task']['id'], 'second'])

    def test_blockers_and_automatic_wait_do_not_offer_retry(self):
        got = states("""
          const task = {id:'x', kind:'reset_backup', stage:'backing-up', title:'Resetting', step:2, of:3,
            steps:[{label:'One',state:'done'},{label:'Two',state:'active'},{label:'Three',state:'waiting'}],
            done:5,total:10,bytes_done:0,bytes_total:0,since:fx.now,error:'',code:'',lock:''}
          const wait = backupState({...fx.cloud, task, state:'error', error:'Waiting.', error_action:'wait'}, fx.recovery, fx.now)
          const blocked = backupState({...fx.cloud, task, on:false, running:false, paused_since:fx.now, token_expired:true}, fx.recovery, fx.now)
          const foreign = backupState({...fx.cloud, task:null, rotation:'pending', rotation_lock:'Another library is removing phones.'}, fx.recovery, fx.now)
          const full = backupState({...fx.cloud, task:null, error_code:'drive_full', error_action:'wait'}, fx.recovery, fx.now)
          const reset = backupState({...fx.cloud, task:{...task, stage:'cleanup', step:3, uploaded_items:3000, uploaded_items_total:3000, uploaded_files:4000}}, fx.recovery, fx.now)
          const preparing = backupState({...fx.cloud, upload_step:'Preparing the encrypted library for upload…', task:{...task, total:0}}, fx.recovery, fx.now)
          const pausedFailed = backupState({...fx.cloud, on:false, running:false, paused_since:fx.now, task:{...task, error:'Stopped.', total:0, of:1, step:1, steps:[{label:'Work',state:'active'}]}}, fx.recovery, fx.now)
          console.log(JSON.stringify({wait,blocked,foreign,full,reset,preparing,pausedFailed}))
        """)
        self.assertNotIn('primary', got['wait']['task'])
        self.assertEqual(got['blocked']['hero']['primary']['id'], 'sign-in-again')
        self.assertNotIn('primary', got['blocked']['task'])
        self.assertEqual(got['foreign']['hero']['text'], 'Another library is removing phones.')
        self.assertIsNone(got['foreign']['task'])
        self.assertNotIn('progress above', json.dumps(got['foreign']))
        self.assertNotIn('primary', got['full']['hero'])
        self.assertIn('3,000 / 3,000 item records · 4,000 / 4,000 files', got['reset']['task']['steps'][1]['label'])
        self.assertEqual(got['preparing']['task']['steps'][1]['label'], 'Preparing the encrypted library for upload…')
        self.assertEqual(got['pausedFailed']['task']['primary']['id'], 'resume')
        self.assertEqual(got['pausedFailed']['task']['progress'], 'steps')


if __name__ == '__main__':
    unittest.main()
