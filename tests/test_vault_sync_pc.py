"""Vault sync, PC side (projects/vault-sync/plans/02-pc-side.md), against the in-memory Drive of tests/test_sync.py.
A small phone stand-in in this file does what web/src/mobile/vault/sync.ts does, using the same library/vault_sync.py.

Run from the project root:  py -m unittest tests.test_vault_sync_pc -v
"""
import json
import tempfile
import threading
import time
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

from library import drive_client, mirror, vault_sync as V
from server import sync as S
from tests.test_sync import FakeDrive, Hub


WHEN = datetime(2026, 10, 12, 9, 30)


class Phone:
    """The phone's round, what web/src/mobile/vault/sync.ts does (sub-plan 04): the PC's full list (generated,
    removed, identity), a fresh round on an identity change, the own-hash check for deletion records, legacy
    copies kept out of its own list, blobs and the list with its caps. `caps=()` is a phone on an older app:
    files and device only, the classic rules, no caps."""
    def __init__(self, drive, key, root, device='phone-1', caps=V.CAPS):
        self.drive, self.key, self.root, self.base, self.cache = drive, key, Path(root), {}, {}
        self.device, self.caps, self.vault, self.legacy = device, tuple(caps), '', []

    def by_name(self):
        return {n: (i, b) for i, (n, b) in self.drive.files.items()}

    def round(self, force=False):
        names = self.by_name()
        pc = names.get(V.index_name(self.key, 'pc'))
        if not self.caps:
            theirs = V.decode_index(self.key.open(V.INDEX_LOGICAL, pc[1]))[1] if pc else {}
            idx = {'files': theirs, 'generated': None, 'removed': {}, 'vault': ''}
            fresh, base = False, self.base
        else:
            idx = V.decode_index_full(self.key.open(V.INDEX_LOGICAL, pc[1])) if pc else {'files': {}, 'generated': None, 'removed': {}, 'vault': ''}
            theirs, manifest = idx['files'], idx['generated'] is not None
            fresh = bool(self.vault and idx['vault'] and self.vault != idx['vault'])
            base = {r: i for r, i in self.base.items() if manifest and r.startswith(V.ONE_WAY)} if fresh else self.base
            if fresh:
                self.cache = {}
        mine, self.cache = V.scan(self.root, self.key, self.cache)
        mine_hash = {r: V.sha256_hex((self.root / r).read_bytes()) for r in idx['removed'] if r in mine and mine[r] != base.get(r)}
        plan = V.merge(base, mine, theirs, 'phone', WHEN, generated=idx['generated'], removed=idx['removed'], mine_hash=mine_hash, fresh=fresh)
        if plan.brake and not force:
            return plan
        edits = {r: mine[r] for r, h in idx['removed'].items()
                 if not fresh and r in mine and mine[r] != base.get(r) and mine_hash.get(r) != h}
        V.apply(self.root, plan, lambda cid: self.key.open(V.blob_logical(cid), names[V.blob_name(cid)][1]))
        self.base, self.vault, self.legacy = plan.new_base, idx['vault'] or self.vault, list(plan.legacy)
        mine, self.cache = V.scan(self.root, self.key, self.cache)
        listed = {r: i for r, i in mine.items() if r not in set(plan.legacy)}
        kept = {r: idx['removed'][r] for r, cid in edits.items() if listed.get(r) == cid}
        for rel, cid in listed.items():
            if V.blob_name(cid) not in names:
                self.drive.upload(V.blob_name(cid), data=self.key.seal(V.blob_logical(cid), (self.root / rel).read_bytes()))
                names = self.by_name()
        fid = next((i for i, (n, _) in self.drive.files.items() if n == V.index_name(self.key, self.device)), '')
        self.drive.upload(V.index_name(self.key, self.device),
                          data=self.key.seal(V.INDEX_LOGICAL, V.encode_index(listed, self.device, caps=self.caps or None, vault=self.vault if self.caps else '', kept=kept if self.caps else None)), file_id=fid)
        return plan


class VaultSyncPcTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        from tests.license_fixture import activate
        activate(self, root)
        self.pc, self.ph, self.cloud = root / 'pc', root / 'phone', root / 'cloud'
        self.pc.mkdir(); self.ph.mkdir()
        self.key = mirror.MirrorKey(bytes(range(32)))
        self.drive = FakeDrive()
        self.svc = S.SyncService(None, Hub(), root / 'data', self.cloud)
        policy = mock.patch.object(self.svc.recovery, 'guard')
        policy.start()
        self.addCleanup(policy.stop)
        self.phone = Phone(self.drive, self.key, self.ph)

    def put(self, root, rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')

    def pc_round(self, force=False, owner=False):
        self.svc._vault_force = force
        self.svc._vault_round(self.drive, self.key, self.pc, owner=owner)

    def owner_vault(self, root=None, **pages):
        """Make `root` (self.pc) a Brainamon-owned vault: a manifest and exactly these generated pages, tracking
        removals as the render does with vault sync on. Returns the manifest."""
        from library import owner_vault
        root = root or self.pc
        man = owner_vault.read_manifest(root) or owner_vault.new_manifest('lib1')
        files = {rel: {'data': text.encode('utf-8'), 'source': 'item', 'key': rel} for rel, text in pages.items()}
        owner_vault.apply_render(root, man, files, track_removed=True)
        return man

    def pc_index(self):
        return V.decode_index_full(self.key.open(V.INDEX_LOGICAL, self.drive.by_name(V.index_name(self.key, 'pc'))))

    def test_vault_state_replace_retries_sharing_locks_and_preserves_old_file_on_failure(self):
        path = self.cloud / S.VAULT_STATE
        path.parent.mkdir(parents=True)
        original, replacement = {'version': 'old'}, {'version': 'new'}
        path.write_text(json.dumps(original), encoding='utf-8')
        real_replace = Path.replace
        attempts = []
        def transient(source, target):
            attempts.append(source)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)
            if len(attempts) < 3:
                raise PermissionError('synthetic sharing violation')
            return real_replace(source, target)
        with mock.patch.object(Path, 'replace', new=transient), mock.patch.object(S.time, 'sleep') as sleep:
            S._save_vault_state(path, replacement)
        self.assertEqual(len(attempts), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [.1, .2])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), replacement)
        with mock.patch.object(Path, 'replace', side_effect=PermissionError('persistent sharing violation')) as replace, \
             mock.patch.object(S.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                S._save_vault_state(path, {'version': 'uncommitted'})
        self.assertEqual(replace.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), replacement)

    @unittest.skipUnless(S.os.name == 'nt', 'Windows file-sharing semantics')
    def test_vault_state_replace_waits_for_concurrent_windows_reader(self):
        path = self.cloud / S.VAULT_STATE
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'version': 'old'}), encoding='utf-8')
        reader = path.open('rb')
        try:
            with mock.patch.object(S.time, 'sleep', side_effect=lambda _: reader.close()) as sleep:
                S._save_vault_state(path, {'version': 'new'})
            self.assertGreaterEqual(sleep.call_count, 1)
        finally:
            reader.close()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'version': 'new'})

    def test_removal_blocks_old_key_vault_before_download(self):
        self.put(self.ph, 'lost.md', 'lost phone edit')
        self.phone.round()
        rotation = {'old': self.key.text(), 'stage': 'prepared'}
        with mock.patch.object(self.svc, '_rotation', return_value=rotation), \
                mock.patch.object(self.drive, 'download', wraps=self.drive.download) as download:
            with self.assertRaises(S.ExportStopped):
                self.pc_round()
        download.assert_not_called()
        self.assertFalse((self.pc / 'lost.md').exists())

    def test_removal_during_scan_stops_old_key_round(self):
        self.put(self.ph, 'lost.md', 'lost phone edit')
        self.phone.round()
        rotation = None
        scan = V.scan
        def remove_during_scan(*args, **kwargs):
            nonlocal rotation
            result = scan(*args, **kwargs)
            rotation = {'old': self.key.text(), 'stage': 'prepared'}
            return result
        with mock.patch.object(self.svc, '_rotation', side_effect=lambda **kw: rotation), \
                mock.patch.object(V, 'scan', side_effect=remove_during_scan), \
                mock.patch.object(self.drive, 'download', wraps=self.drive.download) as download:
            with self.assertRaises(S.ExportStopped):
                self.pc_round()
        download.assert_not_called()
        self.assertFalse((self.pc / 'lost.md').exists())

    def test_stop_during_comparison_aborts_scan_without_publishing_partial_index(self):
        for i in range(4):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        self.svc._vault_tls.stop = self.svc._vault_stop
        content_id = self.key.content_id

        def stop_after_file(data):
            self.svc._vault_stop.set()
            return content_id(data)

        with mock.patch.object(self.key, 'content_id', side_effect=stop_after_file) as hashed:
            with self.assertRaisesRegex(OSError, 'Vault sync is stopping'):
                self.pc_round()
        self.assertEqual(hashed.call_count, 1)
        self.assertEqual(self.drive.files, {})
        state = json.loads((self.cloud / S.VAULT_STATE).read_text(encoding='utf-8'))
        self.assertEqual(state, {'fp': self.key.fingerprint, 'vault': V.path_identity(self.pc), 'folder': '', 'vault_ids': {},
                                 'bases': {}, 'cache': {}, 'orphans': {}, 'index_sig': '', 'devices': {}})

    def test_first_sync_is_a_union_then_edits_flow_both_ways(self):
        self.put(self.pc, 'Ideas/a.md', 'pc note')
        self.put(self.ph, 'b.md', 'phone note')
        self.pc_round(); self.phone.round(); self.pc_round()
        for root in (self.pc, self.ph):
            self.assertEqual((root / 'Ideas' / 'a.md').read_text(), 'pc note')
            self.assertEqual((root / 'b.md').read_text(), 'phone note')
        self.put(self.pc, 'Ideas/a.md', 'pc edit')
        self.pc_round(); self.phone.round()
        self.assertEqual((self.ph / 'Ideas' / 'a.md').read_text(), 'pc edit')

    def test_conflict_keeps_the_pc_copy_and_makes_a_phone_copy(self):
        self.put(self.pc, 'a.md', 'one')
        self.pc_round(); self.phone.round(); self.pc_round()
        self.put(self.pc, 'a.md', 'pc side')
        self.put(self.ph, 'a.md', 'phone side')
        self.pc_round(); self.phone.round(); self.pc_round()
        self.assertEqual((self.pc / 'a.md').read_text(), 'pc side')
        self.assertEqual((self.ph / 'a.md').read_text(), 'pc side')
        copy = 'a (phone conflict 2026-10-12 0930).md'
        self.assertEqual((self.ph / copy).read_text(), 'phone side')
        self.assertEqual((self.pc / copy).read_text(), 'phone side')

    def test_delete_goes_to_trash_and_the_brake_holds_a_mass_delete(self):
        for i in range(30):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        self.pc_round(); self.phone.round(); self.pc_round()
        (self.ph / 'n0.md').unlink()
        self.phone.round(); self.pc_round()
        self.assertFalse((self.pc / 'n0.md').exists())
        self.assertEqual((self.pc / '.trash' / 'n0.md').read_text(), 'note 0')
        for i in range(1, 26):
            (self.ph / f'n{i}.md').unlink()
        braked = self.phone.round()
        self.assertTrue(braked.brake)
        self.assertTrue((self.pc / 'n1.md').exists())
        self.phone.round(force=True); self.pc_round(force=True)
        self.assertFalse((self.pc / 'n1.md').exists())

    def test_garbage_collection_waits_a_day(self):
        self.put(self.pc, 'a.md', 'one')
        self.pc_round()
        cid = self.key.content_id(b'one')
        (self.pc / 'a.md').write_text('two', encoding='utf-8')
        self.pc_round()
        self.assertIn(V.blob_name(cid), {n for n, _ in self.drive.files.values()})      # still there: first seen
        state = S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)
        state['orphans'][V.blob_name(cid)] -= S.ORPHAN_KEEP + 1
        S._save_vault_state(self.cloud / S.VAULT_STATE, state)
        self.pc_round()
        self.assertNotIn(V.blob_name(cid), {n for n, _ in self.drive.files.values()})

    def test_a_state_from_another_key_is_dropped(self):
        """Content ids are keyed: a vault_base.json kept under another mirror key (Unpair, the installed
        app's key copied in) would hand out ids no blob has."""
        self.put(self.pc, 'a.md', 'one')
        self.pc_round()
        path = self.cloud / S.VAULT_STATE
        self.assertTrue(S._load_vault_state(path, self.key.fingerprint)['index_sig'])      # kept under its own key
        fresh = S._load_vault_state(path, mirror.MirrorKey.generate().fingerprint)
        self.assertEqual((fresh['bases'], fresh['cache'], fresh['orphans'], fresh['index_sig']), ({}, {}, {}, ''))

    def test_blob_names_hide_content_and_vault_files_are_not_strays(self):
        self.put(self.pc, 'secret.md', 'the secret text')
        self.pc_round()
        for name, body in self.drive.files.values():
            self.assertNotIn(b'secret', body)
            self.assertTrue(mirror.is_vault(name))

    def pc_status(self):
        """The sealed `vs-` status file the phone's Vault panel reads."""
        found = [b for n, b in self.drive.files.values() if n == V.status_name(self.key)]
        self.assertEqual(len(found), 1)
        return json.loads(self.key.open(V.STATUS_LOGICAL, found[0]))

    def test_round_progress_reaches_the_settings_window_and_the_phone(self):
        for i in range(3):
            self.put(self.ph, f'p{i}.md', f'phone {i}')
        self.put(self.pc, 'a.md', 'pc note')
        self.pc_round(); self.phone.round()
        self.svc.hub.events.clear()
        self.pc_round()
        vault = [d for k, d in self.svc.hub.events if k == 'cloud']
        steps = [(d['vault_state'], d['vault_step'], d['vault_done'], d['vault_total']) for d in vault]
        self.assertIn(('syncing', "Taking the phone's changes", 0, 3), steps)
        self.assertIn(('syncing', "Taking the phone's changes", 3, 3), steps)
        self.assertEqual(steps[-1], ('idle', '', 0, 0))
        st = self.pc_status()
        self.assertEqual((st['state'], st['step'], st['done'], st['total']), ('idle', '', 0, 0))
        self.assertTrue(st['summary'].startswith('3 pulled'))
        self.assertGreater(st['last'], 0)
        self.assertGreater(st['at'], 0)
        status = self.svc.status()
        for k in ('vault_step', 'vault_done', 'vault_total', 'vault_since'):
            self.assertIn(k, status)

    def test_files_over_the_limit_are_counted_and_the_round_does_not_say_up_to_date(self):
        """C4: a file over the vault's size limit is not synced, and neither the PC nor the phone's panel calls the vault complete."""
        self.put(self.pc, 'small.md', 'ok')
        self.put(self.pc, 'big.md', 'x' * 100)
        with mock.patch.object(V, 'MAX_FILE', 50):
            self.pc_round()
            st = self.svc.status()
            self.assertEqual((st['vault_state'], st['vault_skipped'], st['vault_skipped_note']), ('idle', 1, V.skipped_note(1)))
            self.assertTrue(st['vault_summary'].startswith(V.skipped_note(1).rstrip('.')), st['vault_summary'])
            self.assertNotIn('Already in step', st['vault_summary'])
            body = self.pc_status()                                  # what the phone's Vault panel reads
            self.assertEqual((body['skipped'], body['summary']), (1, st['vault_summary']))
            self.assertEqual(sorted(self.pc_index()['files']), ['small.md'])
            self.pc_round()                                          # nothing else moved: still not "Already in step"
            self.assertEqual(self.svc.status()['vault_summary'], V.skipped_note(1).rstrip('.'))
            (self.pc / 'big.md').unlink()
            self.pc_round()
        st = self.svc.status()
        self.assertEqual((st['vault_skipped'], st['vault_skipped_note'], st['vault_summary']), (0, '', 'Already in step'))
        self.assertEqual(self.pc_status()['skipped'], 0)

    def test_first_upload_runs_in_parallel_and_counts_finished_files(self):
        drive, active, peak = self.drive, [0], [0]
        lock = threading.Lock()
        plain = drive.upload

        def slow(name, **kw):
            if not name.startswith(V.BLOB_PREFIX):
                return plain(name, **kw)
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            try:
                return plain(name, **kw)
            finally:
                with lock:
                    active[0] -= 1
        drive.upload = slow
        for i in range(12):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        self.pc_round()
        blobs = [n for n, _ in drive.files.values() if n.startswith(V.BLOB_PREFIX)]
        self.assertEqual(len(blobs), 12)
        self.assertGreater(peak[0], 1)
        self.assertLessEqual(peak[0], S.VAULT_UPLOAD_WORKERS)
        sending = [d for k, d in self.svc.hub.events if k == 'cloud' and d['vault_step'] == 'Sending to Drive']
        self.assertEqual([d['vault_done'] for d in sending], list(range(13)))       # 0 at the start, then each finished file
        self.assertTrue(all(d['vault_total'] == 12 and d['vault_since'] > 0 for d in sending))
        self.assertEqual(self.svc.status()['vault_since'], 0)                       # cleared when the round ends
        self.assertEqual(self.pc_status()['since'], 0)
        self.assertIn('12 sent', self.svc.status()['vault_summary'])

    def test_an_upload_error_stops_the_round_before_the_index(self):
        plain, sent = self.drive.upload, [0]

        def failing(name, **kw):
            if name.startswith(V.BLOB_PREFIX):
                sent[0] += 1
                if sent[0] == 3:
                    raise drive_client.DriveError('Google Drive answered 403: quota', 403)
                time.sleep(0.01)
            return plain(name, **kw)
        self.drive.upload = failing
        for i in range(40):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        with self.assertRaises(drive_client.DriveError):
            self.pc_round()
        names = [n for n, _ in self.drive.files.values()]
        self.assertNotIn(V.index_name(self.key, 'pc'), names)
        self.assertLess(sum(n.startswith(V.BLOB_PREFIX) for n in names), 40)       # the rest were cancelled
        self.drive.upload = plain                                                    # the next round finishes the job
        self.pc_round()
        names = [n for n, _ in self.drive.files.values()]
        self.assertEqual(sum(n.startswith(V.BLOB_PREFIX) for n in names), 40)
        self.assertIn(V.index_name(self.key, 'pc'), names)

    def test_slow_phone_status_does_not_stall_desktop_completed_count(self):
        entered, release, counted = threading.Event(), threading.Event(), threading.Event()
        errors = []
        for i in range(24):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        plain_report, plain_set = self.svc._vault_report, self.svc._set

        def slow_report(client, key, push=False, **kw):
            if threading.current_thread().name.startswith('cm-vault-status'):
                entered.set()
                if not release.wait(5):
                    raise AssertionError('desktop progress stalled behind phone status')
            return plain_report(client, key, push=push, **kw)

        def record(**kw):
            plain_set(**kw)
            if kw.get('vault_done') == 24:
                counted.set()

        def run():
            try:
                self.pc_round()
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(self.svc, '_vault_report', side_effect=slow_report), \
                mock.patch.object(self.svc, '_set', side_effect=record), \
                mock.patch.object(S, 'VAULT_STATUS_EVERY', 0):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(counted.wait(5))
                self.assertNotIn(V.index_name(self.key, 'pc'), [n for n, _ in self.drive.files.values()])
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.pc_status()['state'], 'idle')

    def test_status_file_is_replaced_not_duplicated_and_carries_the_brake(self):
        for i in range(30):
            self.put(self.pc, f'n{i}.md', f'note {i}')
        self.pc_round(); self.phone.round(); self.pc_round()
        self.assertEqual(self.pc_status()['summary'], 'Already in step')
        for i in range(25):
            (self.ph / f'n{i}.md').unlink()
        self.phone.round(force=True)
        self.pc_round()
        st = self.pc_status()            # one status file only, now braked
        self.assertEqual(st['state'], 'brake')
        self.assertTrue(st['reason'])
        self.assertNotIn(b'note', [b for n, b in self.drive.files.values() if n == V.status_name(self.key)][0])

    def test_excluded_and_unsafe_paths_never_land(self):
        self.put(self.pc, '.obsidian/plugins/p/main.js', 'x')
        self.put(self.pc, 'ok.md', 'ok')
        self.pc_round()
        evil = self.key.seal(V.INDEX_LOGICAL, V.encode_index({'../evil.md': 'a' * 32, 'fine.md': 'b' * 32}, 'phone-9'))
        self.drive.put(V.index_name(self.key, 'phone-9'), evil)
        self.pc_round()
        self.assertFalse((self.pc.parent / 'evil.md').exists())
        listed = V.decode_index(self.key.open(V.INDEX_LOGICAL, next(b for n, b in self.drive.files.values() if n == V.index_name(self.key, 'pc'))))[1]
        self.assertEqual(sorted(listed), ['ok.md'])         # the plugin file was never listed; fine.md has no blob, so that device is skipped


    def test_owner_round_waits_without_a_manifest_and_runs_with_one(self):
        """Spec 1b lifts spec 1's refusal: an owner vault syncs. Its manifest gives identity, generated set and
        deletion records; missing or unreadable (Fred 2026-10-28) the round waits for Reclaim. The round holds
        VAULT_LOCK, as before."""
        from core.db import Database
        from library import owner_vault
        from server import map_service
        from server.store import Writer
        Database(self.pc.parent / 'data' / 'content_manager.db').close()
        writer = Writer(self.pc.parent / 'data' / 'content_manager.db')
        writer.start()
        self.addCleanup(writer.stop)
        self.svc.writer = writer
        writer.call(lambda db: (db.set_setting('cloud_vault', 'on'), db.set_setting('obsidian_vault', str(self.pc)),
                                db.set_setting('obsidian_mode', 'owner')))
        self.svc._vault_tls.stop = self.svc._vault_stop
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.svc.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key.save(self.svc.key_path)
        self.put(self.pc, 'Mine.md', 'my note')
        factory = mock.patch.object(self.svc, '_factory', lambda tok, recovery=False, phone=False: self.drive)
        factory.start()
        self.addCleanup(factory.stop)
        self.svc.st['vault_devices'] = [{'device': 'stale', 'ok': True}]
        for manifest in ('missing', 'unreadable'):
            if manifest == 'unreadable':
                (self.pc / owner_vault.MANIFEST).parent.mkdir(parents=True, exist_ok=True)
                (self.pc / owner_vault.MANIFEST).write_text('{broken', encoding='utf-8')
            with mock.patch.object(V, 'scan', side_effect=AssertionError('the folder was read')):
                self.svc._vault_tick()
            self.assertEqual(self.svc.st['vault_state'], 'error', manifest)
            self.assertEqual(self.svc.st['vault_reason'], map_service.MANIFEST_MISSING, manifest)
            self.assertIsNone(self.svc.st['vault_devices'])
            self.assertFalse(any(n.startswith(V.INDEX_PREFIX) for n, _ in self.drive.files.values()), manifest)
        man = self.owner_vault(**{'Brainamon/Items/a-1.md': 'page a', 'Brainamon/Knowledge Map.md': 'map'})
        seen = []
        real_scan = V.scan

        def scan_under_lock(*a, **k):
            def probe():                                 # another thread cannot take the lock while the round holds it
                got = map_service.VAULT_LOCK.acquire(blocking=False)
                if got:
                    map_service.VAULT_LOCK.release()
                seen.append(not got)
            t = threading.Thread(target=probe)
            t.start()
            t.join(2)
            return real_scan(*a, **k)
        with mock.patch.object(V, 'scan', scan_under_lock):
            self.svc._vault_tick()
        self.assertTrue(seen and all(seen))                 # the round ran on the vault thread holding VAULT_LOCK
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        idx = self.pc_index()
        self.assertEqual((idx['vault'], idx['generated'], idx['removed']), (man['vault_id'], {'Brainamon/Items/a-1.md', 'Brainamon/Knowledge Map.md'}, {}))
        self.assertEqual(sorted(idx['files']), ['Brainamon/Items/a-1.md', 'Brainamon/Knowledge Map.md', 'Mine.md'])
        self.assertEqual(S.recorded_vault_id(self.cloud, self.pc), man['vault_id'])
        self.assertEqual(S.recorded_vault_id(self.cloud, self.pc.parent / 'elsewhere'), '')
        # a classic vault (mode unset) syncs as today: no generated set, a path identity
        writer.call(lambda db: db.set_setting('obsidian_mode', ''))
        self.svc._vault_tick()
        idx = self.pc_index()
        self.assertEqual((idx['vault'], idx['generated']), (V.path_identity(self.pc), None))

    def test_round_skips_while_vault_lock_is_held_elsewhere(self):
        from server import map_service
        from server.store import Writer
        from core.db import Database
        Database(self.pc.parent / 'data' / 'content_manager.db').close()
        writer = Writer(self.pc.parent / 'data' / 'content_manager.db')
        writer.start()
        self.addCleanup(writer.stop)
        self.svc.writer = writer
        writer.call(lambda db: (db.set_setting('cloud_vault', 'on'), db.set_setting('obsidian_vault', str(self.pc))))
        self.svc._vault_tls.stop = self.svc._vault_stop
        self.svc._set(vault_state='starting', vault_reason='')  # start_vault sets this before starting the thread
        held = threading.Event()
        released = threading.Event()

        def holder():
            with map_service.VAULT_LOCK:
                held.set()
                released.wait(5)
        t = threading.Thread(target=holder, daemon=True)
        t.start()
        held.wait(2)
        try:
            with mock.patch.object(V, 'scan', side_effect=AssertionError('the folder was read')):
                self.svc._vault_tick()
            self.assertEqual(self.svc.st['vault_summary'], 'Waiting for the vault')
        finally:
            released.set()
            t.join(2)


    def test_rotation_rounds_run_owner_and_classic_under_lock_and_wait_when_busy(self):
        from server import map_service
        self.svc._account_read = True
        self.svc.st['account'] = 'test-account'
        self.svc.writer = mock.Mock()
        stop = threading.Event()
        client = mock.Mock()
        sealed = self.key.seal(mirror.MANIFEST, b'{"files": {}}')
        client.list.return_value = [{'id': 'manifest', 'name': self.key.name(mirror.MANIFEST), 'size': len(sealed)}]
        client.download.return_value = client.download_bounded.return_value = sealed     # restore.manifests reads bounded, by size
        for phase in ('prepare', 'finish'):
            for mode in ('owner', 'busy', 'classic'):
                with self.subTest(phase=phase, mode=mode):
                    settings = {'obsidian_vault': str(self.pc),
                                'obsidian_mode': 'owner' if mode == 'owner' else ''}
                    db = mock.Mock()
                    db.get_setting.side_effect = settings.get
                    self.svc.writer.read.side_effect = lambda fn: fn(db)
                    self.svc.writer.call.side_effect = lambda fn: fn(db)
                    self.svc.st['vault_state'] = 'idle'  # a skipped round must not count as success
                    record = {'stage': 'prepared' if phase == 'prepare' else 'publishing',
                              'old': self.key.text(), 'new': self.key.text(),
                              'account': 'test-account', 'owned': ['old-file']}
                    held, release = threading.Event(), threading.Event()

                    def holder():
                        with map_service.VAULT_LOCK:
                            held.set()
                            release.wait(10)

                    t = threading.Thread(target=holder, daemon=True) if mode == 'busy' else None
                    if t:
                        t.start()
                    try:
                        if t:
                            self.assertTrue(held.wait(2))

                        def round_probe(*args, **kwargs):
                            seen = []

                            def probe():
                                got = map_service.VAULT_LOCK.acquire(blocking=False)
                                if got:
                                    map_service.VAULT_LOCK.release()
                                seen.append(got)

                            probe_thread = threading.Thread(target=probe)
                            probe_thread.start()
                            probe_thread.join(2)
                            self.assertEqual(seen, [False])
                            raise drive_client.DriveError('round reached under lock')

                        expected = 'Waiting for the vault' if mode == 'busy' else 'round reached under lock'
                        with mock.patch.object(self.svc, '_rotation', return_value=record), \
                                mock.patch.object(self.svc, '_save_rotation') as save, \
                                mock.patch.object(self.svc, '_end_vault'), \
                                mock.patch.object(self.svc, '_intake'), \
                                mock.patch.object(self.svc, '_vault_round', side_effect=round_probe) as run:
                            if phase == 'prepare':
                                self.svc._rotation_prepare(client, stop)
                                run.assert_not_called()  # Remove never drains the old-phone vault.
                                client.delete.assert_not_called()
                                self.assertEqual(record['stage'], 'publishing')
                                continue
                            with self.assertRaises(drive_client.DriveError) as caught:
                                self.svc._rotation_finish(client, self.key, record, stop)
                            self.assertIn(expected, str(caught.exception))
                            self.assertEqual(run.call_count, 0 if mode == 'busy' else 1)
                            if mode != 'busy':
                                self.assertEqual(run.call_args.kwargs.get('owner'), mode == 'owner')
                            save.assert_not_called()
                            client.delete.assert_not_called()
                            self.assertEqual(record['owned'], ['old-file'])
                            self.assertEqual(record['stage'], 'prepared' if phase == 'prepare' else 'publishing')
                    finally:
                        release.set()
                        if t:
                            t.join(2)


    def test_missing_classic_phone_does_not_collect_its_blobs(self):
        self.pc_round(); self.phone.round(); self.pc_round()
        name = V.index_name(self.key, 'phone-1')
        fid = next(i for i, (n, _) in self.drive.files.items() if n == name)
        del self.drive.files[fid]
        data = b'offline phone data'
        cid = self.key.content_id(data)
        blob = V.blob_name(cid)
        self.drive.upload(blob, data=self.key.seal(V.blob_logical(cid), data))
        state_path = self.cloud / S.VAULT_STATE
        state = json.loads(state_path.read_text(encoding='utf-8'))
        state['orphans'][blob] = 1
        state_path.write_text(json.dumps(state), encoding='utf-8')
        self.pc_round()
        self.assertIsNotNone(self.drive.by_name(blob))
        self.assertIn('phone-1', S._load_vault_state(state_path, self.key.fingerprint)['devices'])

    def test_tick_rechecks_settings_after_acquiring_vault_lock(self):
        self.svc.writer = mock.Mock()
        self.svc.writer.read.side_effect = [(True, str(self.pc), ''), (True, str(self.pc), 'owner')]
        with mock.patch.object(self.svc, '_vault_round') as run:
            self.svc._vault_tick()
        run.assert_not_called()

    def test_identity_change_makes_a_non_destructive_round(self):
        """Spec 1b decision 4 (replaces the interim folder guard): the state records the vault identity. A pre-1b
        state for the same folder adopts it and keeps its bases (a phone deletion still lands). Another identity
        (another folder here) drops the bases: nothing is trashed or lost, differences wait for the phone's
        conflict copy as in a first sync; the phone then does the same on its side."""
        self.put(self.pc, 'a.md', 'pc note')
        self.put(self.pc, 'b.md', 'pc two')
        self.pc_round(); self.phone.round(); self.pc_round()
        st = json.loads((self.cloud / S.VAULT_STATE).read_text(encoding='utf-8'))
        self.assertEqual((st['vault'], st['folder']), (V.path_identity(self.pc), ''))
        self.assertIn('b.md', st['bases']['phone-1'])
        st.pop('vault')
        st['folder'] = str(self.pc)
        (self.cloud / S.VAULT_STATE).write_text(json.dumps(st), encoding='utf-8')
        (self.ph / 'b.md').unlink()
        self.phone.round(); self.pc_round()
        self.assertTrue((self.pc / '.trash' / 'b.md').exists())
        self.assertEqual(S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)['vault'], V.path_identity(self.pc))
        other = self.pc.parent / 'other'
        self.put(other, 'z.md', 'new place')
        self.put(other, 'a.md', 'other copy')
        self.svc._vault_round(self.drive, self.key, other)
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        self.assertFalse((other / '.trash').exists())
        self.assertEqual((other / 'a.md').read_text(), 'other copy')
        self.assertTrue((self.pc / 'a.md').exists())                               # the old folder is never touched
        st = json.loads((self.cloud / S.VAULT_STATE).read_text(encoding='utf-8'))
        self.assertEqual((st['vault'], st['bases']), (V.path_identity(other), {'phone-1': {}}))
        self.phone.round()                                                          # the phone sees the new identity: fresh too
        copy = 'a (phone conflict 2026-10-12 0930).md'
        self.assertEqual(((self.ph / 'a.md').read_text(), (self.ph / copy).read_text()), ('other copy', 'pc note'))
        self.assertEqual((self.ph / 'z.md').read_text(), 'new place')
        self.assertFalse((self.ph / '.trash').exists())
        self.svc._vault_round(self.drive, self.key, other)
        self.assertEqual((other / copy).read_text(), 'pc note')

    def test_owner_vault_generated_one_way_removed_records_pruned(self):
        """Spec 1b decisions 1 to 3 on the PC: only generated paths are one way; a phone file under Brainamon/
        and a conflict copy reach the PC as the user's files; a removal travels as a record, the phone trashes
        an unedited copy, the record is pruned once no phone lists the path."""
        from library import owner_vault
        G, R, K = 'Brainamon/Items/a-1.md', 'Brainamon/Items/gone-2.md', 'Brainamon/Knowledge Map.md'
        man = self.owner_vault(**{G: 'page a', R: 'page gone', K: 'map'})
        self.put(self.pc, 'Mine.md', 'my note')
        self.pc_round(owner=True)
        idx = self.pc_index()
        self.assertEqual((idx['vault'], idx['generated'], idx['removed']), (man['vault_id'], {G, R, K}, {}))
        self.phone.round()
        self.assertEqual(((self.ph / G).read_text(), (self.ph / 'Mine.md').read_text()), ('page a', 'my note'))
        (self.ph / G).write_text('phone edit', encoding='utf-8')
        self.put(self.ph, 'Brainamon/Notes/phone.md', 'from the phone')
        self.phone.round()
        copy = 'Brainamon/Items/a-1 (phone conflict 2026-10-12 0930).md'
        self.assertEqual(((self.ph / G).read_text(), (self.ph / copy).read_text()), ('page a', 'phone edit'))
        self.pc_round(owner=True)
        self.assertEqual(((self.pc / copy).read_text(), (self.pc / 'Brainamon/Notes/phone.md').read_text()), ('phone edit', 'from the phone'))
        self.assertEqual((self.pc / G).read_text(), 'page a')
        self.assertEqual(self.svc.st['vault_devices'], [{'device': 'phone-1', 'ok': True}])
        man = self.owner_vault(**{G: 'page a', K: 'map'})                      # the item left: Brainamon removes its page
        self.assertEqual(man['removed'], {R: V.sha256_hex(b'page gone')})
        self.pc_round(owner=True)
        self.assertEqual(self.pc_index()['removed'], {R: V.sha256_hex(b'page gone')})
        self.assertTrue((self.ph / R).exists())
        self.phone.round()
        self.assertFalse((self.ph / R).exists())
        self.assertEqual((self.ph / '.trash' / R).read_text(), 'page gone')
        self.pc_round(owner=True)
        self.assertEqual(owner_vault.read_manifest(self.pc).get('removed') or {}, {})
        self.assertEqual(self.pc_index()['removed'], {})
        self.assertEqual(self.svc.st['vault_state'], 'idle')

    def test_old_phone_pauses_owner_vault_sync_until_dropped(self):
        """Spec 1b decision 5: an owner vault's round runs only while every phone list declares both caps; the
        status names the device; Drop deletes its list and the next round runs. A classic vault is not paused."""
        from server import map_service
        self.owner_vault(**{'Brainamon/Knowledge Map.md': 'map'})
        self.pc_round(owner=True)
        old = Phone(self.drive, self.key, self.ph.parent / 'old-phone', device='phone-9', caps=())
        old.root.mkdir()
        old.round()
        self.phone.round()
        self.pc_round(owner=True)
        self.assertEqual((self.svc.st['vault_state'], self.svc.st['vault_reason']), ('error', map_service.phone_old(['phone-9'])))
        self.assertEqual(self.svc.st['vault_reason'], 'Update Brainamon on your phone to keep syncing this vault: phone-9.')
        self.assertEqual(self.svc.st['vault_devices'], [{'device': 'phone-1', 'ok': True}, {'device': 'phone-9', 'ok': False}])
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.svc.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key.save(self.svc.key_path)
        with mock.patch.object(self.svc, '_factory', lambda tok, recovery=False, phone=False: self.drive):
            self.assertEqual(self.svc.drop_device('phone-9'), 1)
        self.assertFalse(any(n == V.index_name(self.key, 'phone-9') for n, _ in self.drive.files.values()))
        self.assertIsNone(self.svc.st['vault_devices'])
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        self.phone.round()                                                              # the current phone keeps syncing
        self.assertEqual((self.ph / 'Brainamon/Knowledge Map.md').read_text(), 'map')

    def test_classic_vault_unchanged_with_old_and_new_phones(self):
        """Spec 1b decision 5, last bullet: a vault without a manifest keeps today's behavior with any phone."""
        self.put(self.pc, 'Content Manager/items/x.md', 'export')
        self.put(self.pc, 'a.md', 'note')
        old = Phone(self.drive, self.key, self.ph.parent / 'old-phone', device='phone-9', caps=())
        old.root.mkdir()
        self.pc_round(); self.phone.round(); old.round(); self.pc_round()
        for root in (self.ph, old.root):
            self.assertEqual((root / 'Content Manager/items/x.md').read_text(), 'export')
            self.assertEqual((root / 'a.md').read_text(), 'note')
        self.put(self.ph, 'Content Manager/items/x.md', 'phone change')
        self.put(old.root, 'Content Manager/items/x.md', 'old phone change')
        self.phone.round(); old.round(); self.pc_round()
        self.assertEqual((self.pc / 'Content Manager/items/x.md').read_text(), 'export')     # one way: the PC ignores both
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        self.assertEqual(self.svc.st['vault_devices'], [{'device': 'phone-1', 'ok': True}, {'device': 'phone-9', 'ok': False}])
        self.phone.round(); old.round()
        for root in (self.ph, old.root):
            self.assertEqual((root / 'Content Manager/items/x.md').read_text(), 'export')     # taken back, no conflict copy
            self.assertEqual([p.name for p in root.rglob('*conflict*')], [])
        idx = self.pc_index()
        self.assertEqual((idx['vault'], idx['generated'], idx['removed']), (V.path_identity(self.pc), None, {}))

    def test_legacy_pages_after_a_move_are_never_uploaded(self):
        """Spec 1b decision 3, legacy: after a Move the phone's Content Manager/ copies are never listed or sent;
        an unedited one goes to .trash on the round after the identity change, an edited one stays; the new
        vault never receives them."""
        from library import owner_vault
        self.put(self.pc, 'Content Manager/items/x.md', 'export')
        self.put(self.pc, 'Content Manager/items/y.md', 'export y')
        self.put(self.pc, 'Mine.md', 'mine')
        self.pc_round(); self.phone.round(); self.pc_round()
        new = self.pc.parent / 'new-vault'
        self.put(new, 'Mine.md', 'mine')
        self.owner_vault(new, **{'Brainamon/Knowledge Map.md': 'map'})
        self.svc._vault_round(self.drive, self.key, new, owner=True)                  # the identity changed: non-destructive
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        self.assertFalse((new / '.trash').exists())
        self.assertFalse((new / 'Content Manager').exists())                         # a phone's leftover copies are never taken
        (self.ph / 'Content Manager/items/y.md').write_text('phone edit', encoding='utf-8')
        self.phone.round()                                                            # fresh on the phone: nothing trashed
        self.assertTrue((self.ph / 'Content Manager/items/x.md').exists())
        self.assertEqual(sorted(self.phone.legacy), ['Content Manager/items/x.md', 'Content Manager/items/y.md'])
        self.assertEqual((self.ph / 'Brainamon/Knowledge Map.md').read_text(), 'map')
        self.assertFalse((self.ph / '.trash').exists())
        self.phone.round()                                                            # the next round: unedited to .trash, edited kept
        self.assertFalse((self.ph / 'Content Manager/items/x.md').exists())
        self.assertEqual((self.ph / '.trash/Content Manager/items/x.md').read_text(), 'export')
        self.assertEqual((self.ph / 'Content Manager/items/y.md').read_text(), 'phone edit')
        self.assertEqual(self.phone.legacy, ['Content Manager/items/y.md'])
        self.svc._vault_round(self.drive, self.key, new, owner=True)
        self.assertFalse((new / 'Content Manager').exists())
        listed = V.decode_index_full(self.key.open(V.INDEX_LOGICAL, self.drive.by_name(V.index_name(self.key, 'phone-1'))))
        self.assertEqual(sorted(listed['files']), ['Brainamon/Knowledge Map.md', 'Mine.md'])
        self.assertEqual(listed['caps'], {'generated', 'identity'})

    def test_offline_generated_version_is_not_resurrected_before_phone_ack(self):
        rel = 'Brainamon/Items/offline.md'
        self.owner_vault(**{rel: 'v1'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        self.owner_vault(**{rel: 'v2'})
        self.pc_round(owner=True)                         # phone remains offline on v1
        state = json.loads((self.cloud / S.VAULT_STATE).read_text())
        self.assertEqual(state['bases']['phone-1'][rel], self.key.content_id(b'v1'))
        self.owner_vault()                                # render removes v2
        self.pc_round(owner=True)
        self.assertFalse((self.pc / rel).exists())
        self.assertEqual(self.pc_index()['removed'], {rel: V.sha256_hex(b'v2')})
        self.phone.round()                               # its unchanged v1 equals its own base
        self.assertFalse((self.ph / rel).exists())
        self.pc_round(owner=True)
        self.assertEqual(self.pc_index()['removed'], {})
        self.assertFalse((self.pc / rel).exists())

    def test_removed_phone_edit_waits_for_matching_identity_and_record_ack(self):
        rel = 'Brainamon/Items/edited.md'
        self.owner_vault(**{rel: 'v1'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        self.owner_vault(**{rel: 'v2'})
        self.pc_round(owner=True)
        self.owner_vault()
        self.pc_round(owner=True)
        self.put(self.ph, rel, 'phone edit')
        self.phone.round()
        name = V.index_name(self.key, 'phone-1')
        fid = next(i for i, (n, _) in self.drive.files.items() if n == name)
        raw = self.key.open(V.INDEX_LOGICAL, self.drive.by_name(name))
        idx = json.loads(raw)
        self.assertEqual(idx['kept'], {rel: V.sha256_hex(b'v2')})
        idx['vault'] = 'another-vault'
        self.drive.upload(name, data=self.key.seal(V.INDEX_LOGICAL, json.dumps(idx).encode()), file_id=fid)
        self.pc_round(owner=True)
        self.assertFalse((self.pc / rel).exists())
        self.drive.upload(name, data=self.key.seal(V.INDEX_LOGICAL, raw), file_id=fid)
        self.pc_round(owner=True)
        self.assertEqual((self.pc / rel).read_text(), 'phone edit')
        self.assertEqual(self.pc_index()['removed'], {})

    def test_missing_or_unreadable_phone_list_cannot_acknowledge_deletion(self):
        from library import owner_vault
        rel = 'Brainamon/Items/wait.md'
        self.owner_vault(**{rel: 'page'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        self.owner_vault()
        self.pc_round(owner=True)
        expected = {rel: V.sha256_hex(b'page')}
        name = V.index_name(self.key, 'phone-1')
        fid = next(i for i, (n, _) in self.drive.files.items() if n == name)
        entry = self.drive.files.pop(fid)                 # interrupted delete/create publication
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'error')
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], expected)
        state = S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)
        self.assertIn('phone-1', state['devices'])         # survives process restart, not merely the status view
        self.drive.files[fid] = (name, b'not an encrypted index')
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'error')
        self.assertIsNone(self.svc.st['vault_devices'])
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], expected)
        self.drive.files[fid] = (name, self.key.seal(V.INDEX_LOGICAL, b'[]'))
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'error')
        self.assertIsNone(self.svc.st['vault_devices'])
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], expected)
        self.drive.files[fid] = entry
        self.phone.round(); self.pc_round(owner=True)
        self.assertEqual(owner_vault.read_manifest(self.pc).get('removed'), {})

    def test_one_phone_acknowledging_does_not_prune_an_offline_phones_record(self):
        from library import owner_vault
        rel = 'Brainamon/Items/two.md'
        self.owner_vault(**{rel: 'page'})
        second = Phone(self.drive, self.key, self.ph.parent / 'second', device='phone-2')
        second.root.mkdir()
        self.pc_round(owner=True); self.phone.round(); second.round(); self.pc_round(owner=True)
        self.owner_vault(); self.pc_round(owner=True)
        self.phone.round(); self.pc_round(owner=True)
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], {rel: V.sha256_hex(b'page')})
        self.assertFalse((self.pc / rel).exists())
        second.round(); self.pc_round(owner=True)
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], {})

    def test_history_reset_keeps_missing_phone_and_reclaim_identity(self):
        from library import owner_vault
        rel = 'Brainamon/Items/offline.md'
        man = self.owner_vault(**{rel: 'page'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        self.owner_vault()
        name = V.index_name(self.key, 'phone-1')
        fid = next(i for i, (n, _) in self.drive.files.items() if n == name)
        del self.drive.files[fid]
        self.svc.reset_vault_history()
        state = S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)
        self.assertEqual(state['bases'], {})
        self.assertEqual(state['devices'], {'phone-1': True})
        self.assertEqual(S.recorded_vault_id(self.cloud, self.pc), man['vault_id'])
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'error')
        self.assertEqual(owner_vault.read_manifest(self.pc)['removed'], {rel: V.sha256_hex(b'page')})

    def test_unreadable_phone_stays_droppable_without_opening_setup_gate(self):
        from server.map_service import MapService, PHONES_UNCHECKED
        from library.owner_vault import VaultError
        self.owner_vault(**{'Brainamon/a.md': 'page'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        name = V.index_name(self.key, 'phone-1')
        fid = next(i for i, (n, _) in self.drive.files.items() if n == name)
        self.drive.files[fid] = (name, b'unreadable')
        self.pc_round(owner=True)
        self.assertIsNone(self.svc.status()['vault_devices'])
        self.assertEqual(self.svc.status()['vault_members'], ['phone-1'])
        maps = MapService(None, Hub(), self.pc.parent / 'data',
                          vault_devices=lambda: self.svc.status()['vault_devices'])
        with self.assertRaisesRegex(VaultError, PHONES_UNCHECKED):
            maps._phones_ready()
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.key.save(self.svc.key_path)
        with mock.patch.object(self.svc, '_factory', return_value=self.drive):
            self.assertEqual(self.svc.drop_device('phone-1'), 1)
        self.assertEqual(self.svc.status()['vault_members'], [])
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'idle')

    def test_pending_removal_is_recovered_before_sync_and_recovery_files_are_ignored(self):
        from library import owner_vault
        rel = 'Brainamon/Items/pending.md'
        man = self.owner_vault(**{rel: 'page'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        man['pending'] = [{'path': rel, 'old': V.sha256_hex(b'page'), 'new': None, 'record_removed': True}]
        owner_vault.write_manifest(self.pc, man)
        (self.pc / rel).unlink()
        self.drive.upload('vi-recovery-unrelated', data=b'recovery envelope, not a vault index')
        self.pc_round(owner=True)
        self.assertEqual(self.svc.st['vault_state'], 'idle')
        self.assertEqual(self.pc_index()['removed'], {rel: V.sha256_hex(b'page')})
        self.assertNotIn('pending', owner_vault.read_manifest(self.pc))

    def test_failed_drop_invalidates_the_phone_check(self):
        self.owner_vault(**{'Brainamon/Knowledge Map.md': 'map'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.key.save(self.svc.key_path)
        with mock.patch.object(self.svc, '_factory', return_value=self.drive), \
                mock.patch.object(self.drive, 'delete', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.svc.drop_device('phone-1')
        self.assertIsNone(self.svc.st['vault_devices'])
        self.assertIn('phone-1', S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)['devices'])

    def test_drop_serializes_with_round_and_forgets_only_the_pc_membership(self):
        from server.map_service import VAULT_LOCK
        self.owner_vault(**{'Brainamon/Knowledge Map.md': 'map'})
        self.pc_round(owner=True); self.phone.round(); self.pc_round(owner=True)
        phone_base = dict(self.phone.base)
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.svc.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key.save(self.svc.key_path)
        held, release = threading.Event(), threading.Event()

        def hold():
            with VAULT_LOCK:
                held.set()
                release.wait(5)

        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(held.wait(2))
            with self.assertRaisesRegex(drive_client.DriveError, 'Waiting for the vault'):
                self.svc.drop_device('phone-1')
            self.assertTrue(self.drive.by_name(V.index_name(self.key, 'phone-1')))
        finally:
            release.set()
            thread.join(2)
        with mock.patch.object(self.svc, '_factory', lambda tok, recovery=False, phone=False: self.drive):
            self.assertEqual(self.svc.drop_device('phone-1'), 1)
        state = S._load_vault_state(self.cloud / S.VAULT_STATE, self.key.fingerprint)
        self.assertNotIn('phone-1', state['devices'])
        self.assertNotIn('phone-1', state['bases'])
        self.assertIsNone(self.svc.st['vault_devices'])
        self.assertEqual(self.phone.base, phone_base)

if __name__ == '__main__':
    unittest.main()
