"""projects/phone-settings (spec docs/superpowers/specs/2026-11-07-phone-settings-design.md): the state lines of
Settings and Backup & phones (web/src/mobile/settings-lines.ts, run by Node), and the page pieces read as text: the
top keys on each page, the group rows, one orange key, the link into a group. No browser, no network."""
import json
import re
import unittest
from pathlib import Path

from tests import test_phone_js
from tests.phone_catalog import english

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'web/src/mobile'


def source(rel):
    return (MOBILE / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


LINES = """
import * as L from './web/src/mobile/settings-lines.ts'
const st = (id, tone, action = null) => ({ id, tone, action: action ? { id: action } : null })
const out = {
  sync: [L.syncLine({ signedIn: false, lamp: 'idle', wifiOnly: true }), L.syncLine({ signedIn: true, lamp: 'idle', wifiOnly: true }),
         L.syncLine({ signedIn: true, lamp: 'idle', wifiOnly: false }), L.syncLine({ signedIn: true, lamp: '1 running · 1 queued', wifiOnly: true })],
  phone: [L.phoneLine(true, 'ab12'), L.phoneLine(false, 'ab12')],
  ai: [L.aiLine('OpenAI', true), L.aiLine('', true), L.aiLine('', false)],
  vault: [L.vaultLine({ name: 'Notes', syncing: true, lamp: 'in step' }), L.vaultLine({ name: '', syncing: false, lamp: 'off' }), L.vaultLine({ name: 'Notes', syncing: false, lamp: 'off' })],
  vaultTone: ['queued', 'in step', 'off', 'error'].map(l => L.vaultTone(l, true)).concat([L.vaultTone('error', false) ?? null]),
  storage: [L.storageLine('86 MB', false, 'off'), L.storageLine('1.2 GB', true, 'all')],
  look: L.lookLine('Auto', true), about: [L.aboutLine({ desktop: true, version: '1.0.9' }), L.aboutLine({ desktop: false, version: '1.0.9' }), L.aboutLine({ desktop: false, version: '' })],
  google: [L.googleLine({ signedIn: false, account: '', driveOk: false, lamp: 'off', solo: true }),
           L.googleLine({ signedIn: true, account: 'a@example.com', driveOk: true, lamp: 'connected', solo: false }),
           L.googleLine({ signedIn: true, account: 'a@example.com', driveOk: false, lamp: 'access removed', solo: false })],
  googleTone: [L.googleTone(st('removed', 'next'), { signedIn: true, driveOk: false, busy: false }), L.googleTone(null, { signedIn: true, driveOk: true, busy: false }),
               L.googleTone(null, { signedIn: false, driveOk: false, busy: false })],
  thisPhone: [L.thisPhoneLine({ solo: false, name: 'Pixel 8', unsent: 0 }), L.thisPhoneLine({ solo: false, name: '', unsent: 3 }), L.thisPhoneLine({ solo: true, name: '', unsent: 0 })],
  recovery: ['none', 'prepared', 'saved', 'checked'].map(f => L.recoveryLine(true, f)).concat([L.recoveryLine(false, '')]),
  recoveryTone: [L.recoveryTone(st('solo-recovery', 'next', 'set-up-recovery'), true, 'none'), L.recoveryTone(null, true, 'checked'), L.recoveryTone(null, false, '')],
  tones: [L.settingsTones(st('wifi', 'todo'), { running: false, driveOk: true, ai: true }), L.settingsTones(st('removed', 'next'), { running: false, driveOk: false, ai: false }),
          L.settingsTones(null, { running: true, driveOk: true, ai: true })],
  every: [],
}
// every fixed line (no name the person chose) fits 33 characters, one line at 320 px
for (const keep of ['off', 'fav', 'all']) for (const c of [false, true]) out.every.push(L.storageLine('999.9 MB', c, keep))
for (const f of ['none', 'prepared', 'saved', 'checked']) out.every.push(L.recoveryLine(true, f))
for (const lamp of ['idle', 'paused', 'needs Drive', '1 running · 1 queued']) out.every.push(L.syncLine({ signedIn: true, lamp, wifiOnly: false }))
out.every.push(L.phoneLine(true, ''), L.phoneLine(false, 'abcdef12'), L.aiLine('Anthropic', false), L.aiLine('', false), L.aboutLine({ desktop: true, version: '1.10.10' }),
  L.lookLine('Cover', false), L.thisPhoneLine({ solo: true, name: '', unsent: 999 }), L.syncLine({ signedIn: false, lamp: '', wifiOnly: true }))
out.every = out.every.filter(s => s.length > 33)
console.log(JSON.stringify(out))
"""


class SettingsLinesTest(unittest.TestCase):
    def test_the_state_lines(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + LINES))
        self.assertEqual(out['sync'], ['Google Drive not connected', 'Wi-Fi only · runs on its own', 'Any network · runs on its own', '1 running · 1 queued'])
        self.assertEqual(out['phone'], ['Saving here · a PC is optional', 'Paired · key ab12'])
        self.assertEqual(out['ai'], ['OpenAI on your key', 'No AI key yet', 'No AI key · pair again'])
        self.assertEqual(out['vault'], ['Notes · in step', 'Vault name not set', 'Notes'])
        self.assertEqual(out['vaultTone'], ['busy', 'done', 'todo', 'next', None])        # queued is teal (spec decision)
        self.assertEqual(out['storage'], ['86 MB · keeps favourites', '1.2 GB · favs, canvases, videos'])
        self.assertEqual(out['look'], 'Auto cards · night on')
        self.assertEqual(out['about'], ['Windows app · v1.0.9 · licenses', 'Version 1.0.9 · licenses', 'licenses'])
        self.assertEqual(out['google'], ['Sign in', 'a@example.com', 'Access removed'])     # the lamp, never the sentence again
        self.assertEqual(out['googleTone'], ['next', 'done', 'todo'])
        self.assertEqual(out['thisPhone'], ['Pixel 8 · all sent', 'This phone · 3 not sent', 'All backed up · no PC paired'])
        self.assertEqual(out['recovery'], ['Not set up', 'Passphrase set', 'File saved, not checked', 'Passphrase set · file checked', 'Managed on your PC'])
        self.assertEqual(out['recoveryTone'], ['next', 'done', 'todo'])
        self.assertEqual(out['tones'], [{'sync': 'todo', 'phone': 'done', 'ai': 'done'}, {'sync': 'todo', 'phone': 'next', 'ai': 'todo'},
                                        {'sync': 'busy', 'phone': 'done', 'ai': 'done'}])
        self.assertEqual(out['every'], [])

    def test_badges_steps_and_task_gates_follow_facts(self):
        test_phone_js.node(test_phone_js.TS_RESOLVE + r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import * as S from './web/src/mobile/settings-steps.ts'
          import * as L from './web/src/mobile/settings-lines.ts'
          const fixture = JSON.parse(fs.readFileSync('tests/fixtures/phone_states.json','utf8'))
          for (const {expect:st} of fixture.cases) {
            const want = st.tone === 'done' ? 'done' : st.tone === 'busy' ? 'working'
              : st.tone === 'next' ? ['unreachable','access-invalid'].includes(st.id) ? 'failed' : 'attention'
              : st.id === 'paused' ? 'paused' : ['offline','wifi','confirming','waiting-pc'].includes(st.id) ? 'waiting' : 'empty'
            assert.equal(S.kindOf(st), want, st.id)
            assert.equal(S.connectionGuide(st,false), ['connect','account-mismatch','replaced','removed','confirming','waiting-pc','license','access-invalid','webview','first-backup','no-library','key','backup-off'].includes(st.id))
            assert.equal(S.connectionGuide(st,true),true)
          }
          const words = (key,p={}) => key + JSON.stringify(p)
          const opts = {signedIn:true,connecting:false,refreshing:false,reachable:false,account:'a',pcAccount:'a',connectStep:'',diagnosis:'',count:'2'}
          for (const id of ['connect','account-mismatch','removed','waiting-pc','first-backup','no-library','key','backup-off']) {
            const steps = S.connectionSteps({id,tone:'next',lamp:'access removed'},opts,words)
            assert.equal(steps.length,4)
            if (['connect','account-mismatch'].includes(id)) assert.equal(steps[1].kind,'attention')
            if (['first-backup','no-library','key','backup-off'].includes(id)) assert.equal(steps[2].kind,'done')
            if (id==='removed') assert.equal(steps[2].line,'access removed')
          }
          for (const [fact,kinds] of [['none',['empty','empty','empty']],['prepared',['done','empty','empty']],['saved',['done','done','attention']],['checked',['done','done','done']]])
            assert.deepEqual(S.recoverySteps(fact,'passphrase date',words,'file date').map(s=>s.kind),kinds)
          assert.match(S.recoverySteps('saved','passphrase date',words,'file date')[1].label,/file date/)
          for (const kind of ['replace','delete']) for (const phase of ['prepare','upload','install','delete','disconnect','done']) for (const paused of [false,true]) {
            const steps = S.taskSteps({kind,phase,paused},true,'',words)
            assert.equal(steps.length,kind==='delete'?2:4)
            if(phase!=='done') assert.equal(steps.filter(s=>s.kind===(paused?'paused':'working')).length,1)
          }
          assert.equal(S.kindOf({id:'backup-task',tone:'next'},'failed'),'failed')
          assert.equal(L.thisPhoneLine({solo:true,name:'',unsent:0,signedIn:false}),'Backup off · no PC paired')
          assert.equal(L.thisPhoneTone(null,0,false),'todo')
          for (const id of ['replaced','removed','key','waiting-pc','confirming','access-invalid']) assert.equal(L.thisPhoneTone({id,tone:'next',action:null},0),'next')
          assert.equal(L.recoveryTone(null,true,'saved'),'next')
          assert.equal(L.recoveryTone(null,true,'none',true),'next')
          assert.equal(L.recoveryTone(null,true,'none',false),'todo')
        """)


class SettingsPagesTest(unittest.TestCase):
    def test_each_page_draws_its_own_keys_before_its_content(self):
        for rel, info in (('screens/More.svelte', None), ('screens/Backup.svelte', ('Google Drive sync', 'Google Drive backup')),
                          ('screens/Recover.svelte', ('How recovery works',))):
            src = source(rel)
            self.assertIn("import PageKeys from '../PageKeys.svelte'", src, rel)
            for at in [m.start() for m in re.finditer(r'<PageKeys', src)]:
                self.assertLess(at, src.index('<div class="m-pad m-calm m-page">', at), rel)
            for title in info or ():
                key = {'Google Drive sync': 'backup.group.sync', 'Google Drive backup': 'backup.group.drive', 'How recovery works': 'recovery.help.title'}[title]
                self.assertIn(f"<PageKeys infoTitle={{t('{key}')}}>", src, rel)
                self.assertEqual(english(key), title)
        keys = source('PageKeys.svelte')
        self.assertEqual(keys.count("aria-label={t('common.back')}"), 1)
        self.assertEqual(english('common.back'), 'Back')
        self.assertIn("import './settings.css'", keys)
        self.assertIn('<div class="m-sheet-keys m-page-keys">', keys)
        mobile = source('Mobile.svelte')
        self.assertIn("{:else if !r.item && !compose && r.tab !== 'more'}", mobile)   # the app bar is the canvas detail's only
        self.assertIn("const title = $derived(r.item ? t('shell.route.item') : r.imp ? t('shell.route.import') : r.save ? t('shell.route.save') : tabName(r.tab))", mobile)
        self.assertEqual([english('shell.route.item'), english('shell.route.import'), english('shell.route.save')], ['Item', 'Import', 'Save'])

    def test_hub_rows_open_pages_and_anchors_reveal_disclosures(self):
        more = source('screens/More.svelte')
        for route in ('sync', 'wiskit', 'obsidian', 'storage', 'look', 'about'):
            self.assertIn(f'href="#/more/{route}"', more)
        self.assertIn('href="#/backup"', more)
        self.assertNotIn('setGroups()', more)
        self.assertNotIn('setGroups()', source('screens/Backup.svelte'))
        self.assertIn('node instanceof HTMLDetailsElement', source('onboard.svelte.ts'))
        self.assertNotIn("new Event('m-group-open')", source('onboard.svelte.ts'))
        for rel in ('screens/settings/About.svelte', 'screens/Backup.svelte', 'PhoneRecovery.svelte', 'Vault.svelte'):
            self.assertIn("variant={lead ? 'pri' : 'default'}", source(rel), rel)
        self.assertIn("{confirmClear ? t('settings.storage.confirmClear') : t('settings.storage.clear')}", source('screens/settings/Storage.svelte'))
        self.assertIn('MSteps', source('PhoneRecovery.svelte'))
        self.assertIn('MSteps', source('PhoneBackupChoices.svelte'))
        self.assertNotIn('<TaskSteps', source('PhoneBackupChoices.svelte'))
        for rel in ('screens/Backup.svelte', 'screens/Recover.svelte', 'PhoneRecovery.svelte'):
            self.assertIn('const gated = $derived(!!backup.task || backup.busy)', source(rel))
        self.assertIn('connectionGuide(st, pairingGuide)', source('screens/Backup.svelte'))
        self.assertNotIn('pairingGuide || !phone.reachable', source('screens/Backup.svelte'))

    def test_the_pill_and_the_hero(self):
        button, status = source('ui/MButton.svelte'), source('ui/MStatus.svelte')
        self.assertIn("shape?: 'rect' | 'pill'", button)
        self.assertIn("look?: 'line' | 'hero' | 'page'", status)
        css = source('settings.css')
        self.assertIn('.m-btn.pill.pri{border-color:color-mix(in srgb,var(--accent) 78%,#000)', css)
        self.assertNotRegex(css, r'#(?!000\b|fff\b)[0-9a-fA-F]{3,6}\b(?![-\w])')     # tokens, plus the spec's #000 and #fff
        self.assertIn('<MButton shape="pill"', source('StatusCard.svelte'))
        self.assertEqual(source('screens/Recover.svelte').count('<MButton shape="pill"'), 5)


if __name__ == '__main__':
    unittest.main()
