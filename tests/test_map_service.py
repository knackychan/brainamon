"""The knowledge map thread, its locks and the owner vault render (server/map_service.py); the Refresh map
job (server/job_kinds.py refresh_map). Spec docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md,
decisions 6, 7, 10.

Run from the project root:  py -m unittest tests.test_map_service -v
Temp library only; AI calls are stubbed; no network.
"""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from core import ai_client
from core.db import Database
from library import map_engine as M
from library import owner_vault as V
from library import search
from server import map_service as MS
from server.store import Writer
from tests.test_sync import Hub


def blob(*xs):
    v = np.zeros(4, dtype=np.float32)
    for i, x in enumerate(xs):
        v[i] = x
    return search.vec_to_blob(v)


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        self.vault = self.root / 'Documents' / 'Brainamon Vault'
        self.home = self.root / 'home'
        self.home.mkdir()
        db = Database(self.data / 'content_manager.db')
        self.ids = []
        for n, (text, vec) in enumerate([('Kettlebell swing', (1, 0.1)), ('Kettlebell press', (1, -0.1)),
                                         ('Blender merge', (0, 1)), ('Blender nodes', (0.1, 1))]):
            iid = db.add_item({'url': f'https://x/{n}', 'description': text, 'tags': 'kb' if 'Kettle' in text else '3d'})
            db.upsert_embedding(iid, ai_client.EMBEDDING_MODEL, 4, 'h', blob(*vec))
            self.ids.append(iid)
        db.library_id()
        db.close()
        self.writer = Writer(self.data / 'content_manager.db')
        self.writer.start()
        self.addCleanup(self.writer.stop)
        self.hub = Hub()
        p = mock.patch.object(MS.app_paths, 'HOME', self.home)
        p.start()
        self.addCleanup(p.stop)
        self.maps = MS.MapService(self.writer, self.hub, self.data)
        self.cache_path = M.cache_path(self.data)

    def setting(self, key, value):
        self.writer.call(lambda db: db.set_setting(key, value))

    def seed_map(self):
        c = M.empty(ai_client.EMBEDDING_MODEL)
        c['clusters']['t-1'] = {'title': 'Kettlebell', 'synthesis': 'Swings and presses.', 'member_ids': self.ids[:2],
                                'name': 'kettlebell-t1', 'summary_basis': {str(i): 'h' for i in self.ids[:2]}, 'stale': False}
        c['clusters']['t-2'] = {'title': 'Blender', 'synthesis': 'Mesh work.', 'member_ids': self.ids[2:],
                                'name': 'blender-t2', 'summary_basis': {str(i): 'h' for i in self.ids[2:]}, 'stale': False}
        c['next_id'] = 3
        M.save(self.cache_path, c)
        return c

    def add_item(self, text, vec, tags='kb'):
        def go(db):
            iid = db.add_item({'url': f'https://x/{text}', 'description': text, 'tags': tags})
            db.upsert_embedding(iid, ai_client.EMBEDDING_MODEL, 4, 'h', blob(*vec))
            return iid
        return self.writer.call(go)

    def hold_vault_lock(self):
        """Hold VAULT_LOCK from another thread (it is an RLock: the test thread itself could re-enter it).
        Returns the function that releases it; it also runs at cleanup."""
        held, release = threading.Event(), threading.Event()

        def holder():
            with MS.VAULT_LOCK:
                held.set()
                release.wait(10)
        t = threading.Thread(target=holder, daemon=True)
        t.start()
        self.assertTrue(held.wait(2))

        def done():
            release.set()
            t.join(2)
        self.addCleanup(done)
        return done


class IndependenceTest(Base):
    def test_maintenance_runs_without_a_vault(self):
        self.seed_map()
        new = self.add_item('Kettlebell snatch', (0.9, 0.2))
        self.assertTrue(self.maps.run_pass())
        c = M.load(self.cache_path)
        self.assertIn(new, c['clusters']['t-1']['member_ids'])
        self.assertFalse(self.vault.exists())
        self.assertEqual(self.maps.status()['topics'], 2)

    def test_render_only_with_owner_vault(self):
        self.seed_map()
        self.vault.mkdir(parents=True)                           # the render never creates a missing vault
        self.setting('obsidian_vault', str(self.vault))          # a classic vault path, no owner mode
        self.assertTrue(self.maps.run_pass())
        self.assertFalse((self.vault / 'Brainamon').exists())
        self.setting('obsidian_mode', 'owner')
        self.assertTrue(self.maps.run_pass())
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())
        self.assertTrue((self.vault / 'Brainamon' / 'Topics' / 'kettlebell-t1.md').is_file())
        self.assertIn('stale: true', (self.vault / 'Brainamon' / 'Topics' / 'kettlebell-t1.md').read_text(encoding='utf-8'))
        self.assertIsNotNone(V.read_manifest(self.vault))
        self.assertGreater(self.maps.status()['last_render'], 0)

    def test_owner_vault_without_map_renders_everything_but_topics(self):
        self.vault.mkdir(parents=True)                           # the render never creates a missing vault
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        self.setting('obsidian_tag_map', json.dumps({'kb': 'kettlebell', '3d': 'blender'}))
        self.writer.call(lambda db: db.update_item(self.ids[0], {'category': 'SPORT', 'analysis_done': 1,
                                                                    'analysis_path': str(self.data / 'items' / str(self.ids[0]) / 'report.md')}))
        (self.data / 'items' / str(self.ids[0])).mkdir(parents=True)
        (self.data / 'items' / str(self.ids[0]) / 'report.md').write_text('# r', encoding='utf-8')
        (self.data / 'notes').mkdir(exist_ok=True)
        (self.data / 'notes' / 'n.md').write_text('---\ntopic: N\n---\nx', encoding='utf-8')
        self.assertTrue(self.maps.run_pass())
        b = self.vault / 'Brainamon'
        self.assertTrue((b / 'Items' / f'kettlebell-swing-{self.ids[0]}.md').is_file())
        self.assertTrue((b / 'Tags' / 'kettlebell.md').is_file())
        self.assertTrue((b / 'Categories' / 'sport.md').is_file())
        self.assertTrue((b / 'Reports' / f'{self.ids[0]}.md').is_file())
        self.assertTrue((b / 'Notes' / 'n.md').is_file())
        self.assertFalse((b / 'Topics').exists())
        self.assertIn('AI topics appear here after the first Refresh map', (b / 'Knowledge Map.md').read_text(encoding='utf-8'))
        self.assertFalse(self.cache_path.exists())                 # no map was made up

    def test_other_library_vault_gets_no_writes(self):
        self.vault.mkdir(parents=True)
        V.write_manifest(self.vault, V.new_manifest('someone-else'))
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        self.assertTrue(self.maps.run_pass())
        self.assertFalse((self.vault / 'Brainamon').exists())
        self.assertTrue(self.maps.status()['other_library'])


class CoordinationTest(Base):
    def test_held_vault_lock_leaves_pending_and_retries(self):
        self.vault.mkdir(parents=True)                           # the render never creates a missing vault
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        release = self.hold_vault_lock()
        self.assertFalse(self.maps.run_pass())
        self.assertTrue(self.maps.status()['pending'])
        self.assertEqual(self.maps.status()['pending_reason'], 'vault')
        self.assertFalse((self.vault / 'Brainamon').exists())
        release()
        self.assertTrue(self.maps.run_pass())
        self.assertFalse(self.maps.status()['pending'])
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())

    def test_update_publishes_real_progress_and_clears_stale_error(self):
        self.vault.mkdir(parents=True)
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        self.maps._set(error='Old failure', pending=True, pending_reason='vault')
        with mock.patch.object(self.maps, '_set', wraps=self.maps._set) as updates:
            self.assertTrue(self.maps.run_pass())
        snapshots = [c.kwargs for c in updates.call_args_list]
        self.assertTrue(any(s.get('state') == 'preparing' for s in snapshots))
        for stage in ('checking', 'saving'):
            counts = [s['progress'] for s in snapshots if s.get('state') == stage]
            self.assertEqual(counts[0]['done'], 0)
            self.assertGreater(counts[-1]['total'], 0)
            self.assertEqual(counts[-1]['done'], counts[-1]['total'])
        self.assertEqual(self.maps.status()['state'], 'idle')
        self.assertIsNone(self.maps.status()['progress'])
        self.assertEqual(self.maps.status()['error'], '')
        self.assertEqual(self.maps.status()['pending_reason'], '')

    def test_thread_retries_a_pending_pass(self):
        self.vault.mkdir(parents=True)                           # the render never creates a missing vault
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        release = self.hold_vault_lock()
        with mock.patch.multiple(MS, POLL=0.05, QUIET=0.05, RETRY=0.1):
            self.maps.boot()
            self.addCleanup(self.maps.shutdown)
            for _ in range(40):
                if self.maps.status()['pending']:
                    break
                time.sleep(0.05)
            self.assertTrue(self.maps.status()['pending'])
            release()
            for _ in range(60):
                if not self.maps.status()['pending'] and (self.vault / 'Brainamon' / 'Knowledge Map.md').is_file():
                    break
                time.sleep(0.05)
            self.assertFalse(self.maps.status()['pending'])
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())

    def test_maintenance_proceeds_while_vault_lock_held(self):
        self.seed_map()
        self.setting('obsidian_vault', str(self.vault))
        self.setting('obsidian_mode', 'owner')
        new = self.add_item('Kettlebell snatch', (0.9, 0.2))
        release = self.hold_vault_lock()
        self.assertFalse(self.maps.run_pass())                  # the render stayed pending...
        release()
        self.assertIn(new, M.load(self.cache_path)['clusters']['t-1']['member_ids'])   # ...the map moved on

    def test_user_action_waits_and_cancels(self):
        release = self.hold_vault_lock()
        waited = threading.Event()
        done = threading.Event()
        box = {}

        def act():
            try:
                box['r'] = MS.with_vault_lock(lambda: 'ran', self.maps.cancel, on_wait=waited.set)
            except V.VaultError as e:
                box['e'] = e
            done.set()
        t = threading.Thread(target=act, daemon=True)
        t.start()
        self.assertTrue(waited.wait(3))                         # it is waiting, visibly
        self.assertFalse(done.is_set())
        self.maps.cancel.set()
        self.assertTrue(done.wait(3))
        self.assertIn('e', box)
        release()
        self.maps.cancel.clear()
        self.assertEqual(MS.with_vault_lock(lambda: 'ran', self.maps.cancel), 'ran')


class ActionsTest(Base):
    def test_set_owner_vault_create_and_use_existing(self):
        r = self.maps.set_owner_vault(str(self.vault), create=True)
        self.assertTrue((self.vault / '.obsidian').is_dir())
        self.assertEqual(r['first_open'], 'pending')
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('obsidian_vault'), db.get_setting('obsidian_mode'))),
                         (str(self.vault), 'owner'))
        self.assertEqual(V.read_manifest(self.vault)['library_id'], self.writer.read(lambda db: db.library_id()))
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())      # rendered at once
        # an empty vault the user made in Obsidian: .obsidian/ untouched, no first-open step
        other = self.root / 'Documents' / 'Made in Obsidian'
        (other / '.obsidian').mkdir(parents=True)
        (other / '.obsidian' / 'app.json').write_text('{"x": 1}', encoding='utf-8')
        self.setting('obsidian_first_open', '')
        r = self.maps.set_owner_vault(str(other))
        self.assertEqual(r['first_open'], '')
        self.assertEqual((other / '.obsidian' / 'app.json').read_text(encoding='utf-8'), '{"x": 1}')
        self.assertEqual(sorted(p.name for p in (other / '.obsidian').iterdir()), ['app.json'])

    def test_set_owner_vault_rules(self):
        with self.assertRaises(V.VaultError):
            self.maps.set_owner_vault(str(self.data / 'inside'))                  # inside data/
        with self.assertRaises(V.VaultError):
            self.maps.set_owner_vault(str(self.home / 'v'))                       # inside the settings home
        # spec 1b decision 6 (Fred 2026-10-28): with vault sync on, Create needs a device list from a round in which
        # every phone runs the current app
        self.setting('cloud_vault', 'on')
        with self.assertRaises(V.VaultError) as cm:
            self.maps.set_owner_vault(str(self.vault), create=True)
        self.assertEqual(str(cm.exception), MS.PHONES_UNCHECKED)
        self.maps.vault_devices = lambda: [{'device': 'p1', 'ok': True}, {'device': 'p9', 'ok': False}]
        with self.assertRaises(V.VaultError) as cm:
            self.maps.set_owner_vault(str(self.vault), create=True)
        self.assertEqual(str(cm.exception), 'Update Brainamon on your phone to keep syncing this vault: p9.')
        self.assertFalse(self.vault.exists())
        self.maps.vault_devices = lambda: [{'device': 'p1', 'ok': True}]
        self.maps.set_owner_vault(str(self.vault), create=True)
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())
        self.setting('cloud_vault', 'off')
        self.setting('obsidian_vault', '')
        self.setting('obsidian_mode', '')
        self.maps.vault_devices = lambda: None
        few = self.root / 'few'
        few.mkdir()
        (few / 'one.md').write_text('1')
        with self.assertRaises(MS.NeedsConfirm) as cm:
            self.maps.set_owner_vault(str(few))
        self.assertEqual(cm.exception.count, 1)
        self.maps.set_owner_vault(str(few), confirm=True)
        self.assertEqual((few / 'one.md').read_text(), '1')
        self.assertTrue((few / 'Brainamon').is_dir())
        many = self.root / 'many'
        many.mkdir()
        for i in range(6):
            (many / f'{i}.md').write_text('x')
        with self.assertRaises(V.VaultError):
            self.maps.set_owner_vault(str(many), confirm=True)
        self.assertFalse((many / 'Brainamon').exists())

    def test_move_from_legacy(self):
        old = self.data / 'Fredorama'
        (old / '.obsidian').mkdir(parents=True)
        (old / '.obsidian' / 'app.json').write_text('{}', encoding='utf-8')
        (old / 'Content Manager' / 'items').mkdir(parents=True)
        (old / 'Content Manager' / 'items' / 'x.md').write_text('old', encoding='utf-8')
        self.setting('obsidian_vault', str(old))
        n = self.maps.move(str(self.vault))
        self.assertEqual(n, 1)
        self.assertTrue((self.vault / '.obsidian' / 'app.json').is_file())
        self.assertTrue((self.vault / 'Brainamon' / 'Knowledge Map.md').is_file())
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('obsidian_vault'), db.get_setting('obsidian_mode'))),
                         (str(self.vault), 'owner'))
        self.assertTrue((old / 'Content Manager' / 'items' / 'x.md').is_file())      # the old vault is never deleted

    def test_move_mismatch_leaves_setting(self):
        old = self.data / 'Fredorama'
        old.mkdir(parents=True)
        (old / 'a.md').write_text('a', encoding='utf-8')
        self.setting('obsidian_vault', str(old))
        real = V.file_hash
        with mock.patch.object(V, 'file_hash', lambda p: 'bad' if Path(p).parent == self.vault else real(p)):
            with self.assertRaises(V.VaultError):
                self.maps.move(str(self.vault))
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('obsidian_vault'), db.get_setting('obsidian_mode', ''))),
                         (str(old), ''))
        self.assertFalse((self.vault / 'Brainamon').exists())
        self.assertTrue((self.vault / 'a.md').exists())                                # left for inspection

    def test_move_gate_with_vault_sync_on_and_owner_mode(self):
        """Spec 1b decision 6: a Move with vault sync on is allowed once a round has read every phone list and all
        phones are on the current app; an owner vault has nothing to move."""
        old = self.data / 'Fredorama'
        (old / '.obsidian').mkdir(parents=True)
        self.setting('obsidian_vault', str(old))
        self.setting('cloud_vault', 'on')
        with self.assertRaises(V.VaultError) as cm:
            self.maps.move(str(self.vault))
        self.assertEqual(str(cm.exception), MS.PHONES_UNCHECKED)
        self.maps.vault_devices = lambda: [{'device': 'p9', 'ok': False}]
        with self.assertRaises(V.VaultError) as cm:
            self.maps.move(str(self.vault))
        self.assertEqual(str(cm.exception), MS.phone_old(['p9']))
        self.assertFalse(self.vault.exists())
        self.maps.vault_devices = lambda: [{'device': 'p1', 'ok': True}]
        self.assertEqual(self.maps.move(str(self.vault)), 0)
        self.assertEqual(self.writer.read(lambda db: db.get_setting('obsidian_mode')), 'owner')
        with self.assertRaises(V.VaultError):
            self.maps.move(str(self.root / 'again'))                   # already a Brainamon vault: nothing to move

    def test_reset_reclaim_take_over(self):
        self.maps.set_owner_vault(str(self.vault), create=True)
        page = self.vault / 'Brainamon' / 'Items' / f'kettlebell-swing-{self.ids[0]}.md'
        generated = page.read_text(encoding='utf-8')
        page.write_text('edited', encoding='utf-8')
        self.assertTrue(self.maps.run_pass())
        self.assertEqual(self.maps.status()['adopted'], [f'Brainamon/Items/kettlebell-swing-{self.ids[0]}.md'])
        self.maps.reset(f'Brainamon/Items/kettlebell-swing-{self.ids[0]}.md')
        self.assertEqual(page.read_text(encoding='utf-8'), generated)
        self.assertEqual(self.maps.status()['adopted'], [])
        (self.vault / V.MANIFEST).unlink()
        self.assertTrue(self.maps.run_pass())
        self.assertGreater(self.maps.status()['unlisted'], 0)
        n = self.maps.reclaim()
        self.assertGreater(n, 0)
        self.assertEqual(self.maps.status()['unlisted'], 0)
        man = V.read_manifest(self.vault)
        man['library_id'] = 'someone-else'
        V.write_manifest(self.vault, man)
        self.assertTrue(self.maps.run_pass())
        self.assertTrue(self.maps.status()['other_library'])
        self.maps.take_over()
        self.assertFalse(self.maps.status()['other_library'])
        self.assertEqual(V.read_manifest(self.vault)['library_id'], self.writer.read(lambda db: db.library_id()))

    def test_reconnect_an_earlier_vault(self):
        # an earlier install's vault at the default place: the same folder, another library id
        self.maps.set_owner_vault(str(self.vault), create=True)
        rel = f'Brainamon/Items/kettlebell-swing-{self.ids[0]}.md'
        (self.vault / rel).write_text('edited', encoding='utf-8')
        (self.vault / 'My note.md').write_text('mine', encoding='utf-8')
        gone = self.vault / 'Brainamon' / 'Items' / 'gone-999.md'
        gone.write_text('---\nid: 999\nsource: brainamon\n---\n# gone\n', encoding='utf-8')
        man = V.read_manifest(self.vault)
        man['files']['Brainamon/Items/gone-999.md'] = {'hash': V.file_hash(gone), 'source': 'item', 'key': 999}
        man['library_id'] = 'earlier-install'
        V.write_manifest(self.vault, man)
        self.setting('obsidian_vault', '')
        self.setting('obsidian_mode', '')
        with self.assertRaises(MS.NeedsTakeover) as cm:
            self.maps.set_owner_vault(str(self.vault), create=True)
        self.assertEqual(cm.exception.count, 1)                                  # one leftover
        self.assertIn('1 page(s) you edited', str(cm.exception))
        self.assertEqual(V.read_manifest(self.vault)['library_id'], 'earlier-install')      # nothing changed yet
        self.assertEqual(self.writer.read(lambda db: db.get_setting('obsidian_mode', '')), '')
        self.maps.set_owner_vault(str(self.vault), create=True, takeover=True)
        self.assertEqual(V.read_manifest(self.vault)['library_id'], self.writer.read(lambda db: db.library_id()))
        self.assertEqual(self.writer.read(lambda db: (db.get_setting('obsidian_vault'), db.get_setting('obsidian_mode'))),
                         (str(self.vault), 'owner'))
        st = self.maps.status()
        self.assertEqual((st['adopted'], st['leftovers'], st['unlisted']), ([rel], 1, 0))
        self.assertEqual((self.vault / rel).read_text(encoding='utf-8'), 'edited')
        self.assertEqual((self.vault / 'My note.md').read_text(encoding='utf-8'), 'mine')
        self.assertTrue(gone.is_file())                                           # kept until the user removes it
        self.assertEqual(self.maps.remove_leftovers(), 1)
        self.assertFalse(gone.exists())
        self.assertEqual(self.maps.status()['leftovers'], 0)

    def test_moved_vault_is_not_recreated(self):
        self.maps.set_owner_vault(str(self.vault), create=True)
        moved = self.root / 'Documents' / 'Renamed Vault'
        self.vault.rename(moved)
        self.assertTrue(self.maps.run_pass())
        self.assertTrue(self.maps.status()['missing'])
        self.assertFalse(self.vault.exists())                                     # never recreated at the old path
        # Locate: setup on the new place; this library's manifest, so no question
        self.maps.set_owner_vault(str(moved))
        self.assertFalse(self.maps.status()['missing'])
        self.assertEqual(self.writer.read(lambda db: db.get_setting('obsidian_vault')), str(moved))


    def test_missing_manifest_is_not_recreated_while_vault_sync_is_on(self):
        self.maps.set_owner_vault(str(self.vault), create=True)
        identity = V.read_manifest(self.vault)['vault_id']
        self.maps.vault_id_for = lambda folder: identity
        self.setting('cloud_vault', 'on')
        (self.vault / V.MANIFEST).unlink()
        self.assertFalse(self.maps.run_pass())
        self.assertIsNone(V.read_manifest(self.vault))
        self.assertEqual(self.maps.status()['error'], MS.MANIFEST_MISSING)
        self.assertGreater(self.maps.reclaim(), 0)
        self.assertEqual(V.read_manifest(self.vault)['vault_id'], identity)

    def test_setup_and_move_recheck_phones_after_lock_wait(self):
        self.setting('cloud_vault', 'on')
        old = self.data / 'Fredorama'
        old.mkdir(parents=True)
        self.setting('obsidian_vault', str(old))
        def changed(fn, *args, **kwargs):
            self.maps.vault_devices = lambda: None
            return fn()
        for action in (lambda: self.maps.set_owner_vault(str(self.vault), create=True),
                       lambda: self.maps.move(str(self.vault))):
            self.maps.vault_devices = lambda: [{'device': 'p', 'ok': True}]
            with mock.patch.object(MS, 'with_vault_lock', side_effect=changed):
                with self.assertRaisesRegex(V.VaultError, 'has not checked'):
                    action()
            self.assertFalse(self.vault.exists())

    def test_render_records_removals_only_with_vault_sync_on(self):
        """Spec 1b decision 2 with Fred's answer of 2026-10-28: the render keeps deletion records while
        cloud_vault is on and clears them when it is off."""
        self.maps.set_owner_vault(str(self.vault), create=True)
        rel = f'Brainamon/Items/kettlebell-swing-{self.ids[0]}.md'
        self.assertTrue((self.vault / rel).is_file())
        self.setting('cloud_vault', 'on')
        self.writer.call(lambda db: db.delete_item(self.ids[0]))
        self.assertTrue(self.maps.run_pass())
        self.assertFalse((self.vault / rel).exists())
        man = V.read_manifest(self.vault)
        self.assertIn(rel, man['removed'])
        self.assertEqual(len(man['removed'][rel]), 64)
        self.setting('cloud_vault', 'off')
        self.assertTrue(self.maps.run_pass())
        self.assertNotIn('removed', V.read_manifest(self.vault))

    def test_reclaim_reuses_the_recorded_vault_id(self):
        """Spec 1b decision 4: Reclaim after a lost manifest asks the injected vault_id_for(folder); a recorded
        identity is reused, otherwise a new one is made."""
        asked = []

        def recorded(folder):
            asked.append(str(folder))
            return 'recorded-identity'
        self.maps = MS.MapService(self.writer, self.hub, self.data, vault_id_for=recorded)
        self.maps.set_owner_vault(str(self.vault), create=True)
        first = V.read_manifest(self.vault)['vault_id']
        (self.vault / V.MANIFEST).unlink()
        self.assertGreater(self.maps.reclaim(), 0)
        self.assertEqual(V.read_manifest(self.vault)['vault_id'], 'recorded-identity')
        self.assertEqual(asked, [str(self.vault)])
        self.assertNotEqual(first, 'recorded-identity')
        plain = MS.MapService(self.writer, self.hub, self.data)
        self.assertIsNone(plain.vault_devices())
        self.assertEqual(plain.vault_id_for(self.vault), '')

from tests.auth_client import TestClient                     # noqa: E402
from server.app import create_app                            # noqa: E402

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def fake_complete(provider, model, *, prompt, system='', max_tokens=2000):
    if 'raw tags' in prompt:
        return '{"kb": "kettlebell", "3d": "blender"}'
    return 'TITLE: Grouped topic\n\nA summary of the group.'



class RefreshJobTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        db = Database(self.data / 'content_manager.db')
        db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
        self.ids = []
        for n, (text, vec) in enumerate([('Kettlebell swing', (1, 0.1)), ('Kettlebell press', (1, -0.1)), ('Kettlebell clean', (1, 0)),
                                         ('Blender merge', (0, 1)), ('Blender nodes', (0.1, 1)), ('Blender lights', (0, 1, 0.1))]):
            iid = db.add_item({'url': f'https://x/{n}', 'description': text, 'tags': 'kb' if 'Kettle' in text else '3d'})
            db.upsert_embedding(iid, ai_client.EMBEDDING_MODEL, 4, 'h', blob(*vec))
            self.ids.append(iid)
        db.close()
        self.gate = threading.Event()
        self.gate.set()

        def gated(provider, model, *, prompt, system='', max_tokens=2000):
            self.gate.wait(10)
            return fake_complete(provider, model, prompt=prompt, system=system, max_tokens=max_tokens)
        for p in (mock.patch.object(ai_client, 'complete_text', gated),
                  mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}),
                  mock.patch('library.knowledge_graph.cluster_items', lambda ids, matrix: [self.ids[:3], self.ids[3:]]),
                  mock.patch.object(MS.app_paths, 'HOME', self.root / 'home')):
            p.start()
            self.addCleanup(p.stop)
        app = create_app(data_dir=self.data, port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x', cloud_dir=self.root / 'cloud')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        from server.jobs import KINDS
        p = mock.patch.multiple(KINDS['refresh_map'], gap=0.0, error_gap=0.0)
        p.start()
        self.addCleanup(p.stop)
        self.app = app
        self.cache_path = M.cache_path(self.data)
        app.state.maps.shutdown()        # no cm-map thread racing these tests: every pass here is run_pass() by hand

    def wait(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def start(self, rebuild=False):
        p = self.c.post('/api/jobs/preview', json={'kind': 'refresh_map', 'ids': [], 'force': True, 'opts': {'rebuild': rebuild}}, headers=W).json()
        r = self.c.post('/api/jobs', json={'kind': 'refresh_map', 'ids': [], 'force': True, 'opts': {'rebuild': rebuild}}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        return p

    def test_first_refresh_is_a_rebuild_with_tags_and_summaries(self):
        p = self.start()
        self.assertEqual(p['plan'], {'tags': 2, 'rebuild': 2, 'summaries': 2})
        self.assertEqual(p['count'], 4)                              # one tags step, one rebuild step, two summaries
        last = self.wait()
        self.assertEqual(last['err'], 0, last)
        c = M.load(self.cache_path)
        self.assertEqual(sorted(c['clusters']), ['t-1', 't-2'])
        t = c['clusters']['t-1']
        self.assertEqual((t['title'], t['synthesis'], t['name']), ('Grouped topic', 'A summary of the group.', 'grouped-topic-t1'))
        self.assertEqual(sorted(t['summary_basis']), sorted(str(i) for i in self.ids[:3]))
        self.assertFalse(t['stale'])
        tag_map = json.loads(self.app.state.writer.read(lambda db: db.get_setting('obsidian_tag_map')))
        self.assertEqual(tag_map, {'kb': 'kettlebell', '3d': 'blender'})
        again = self.c.post('/api/jobs/preview', json={'kind': 'refresh_map', 'ids': [], 'force': True, 'opts': {}}, headers=W).json()
        self.assertEqual(again['count'], 0)                          # up to date: nothing paid to do

    def test_merge_keeps_membership_records_basis_and_marks_stale(self):
        self.start()
        self.wait()
        writer = self.app.state.writer
        writer.call(lambda db: db.update_item(self.ids[0], {'description': 'Kettlebell swing, corrected text'}))
        preview = self.c.post('/api/jobs/preview', json={'kind': 'refresh_map', 'ids': [], 'force': True, 'opts': {}}, headers=W).json()
        self.assertEqual(preview['plan']['summaries'], 1)              # current text, before maintenance
        self.app.state.maps.run_pass()                               # maintenance: t-1 is now stale (1 of 3 changed = 33%)
        self.assertEqual(json.loads(self.cache_path.read_text(encoding='utf-8'))['clusters']['t-1']['stale'], True)
        self.gate.clear()                                            # block the model
        p = self.start()
        self.assertEqual(p['plan']['summaries'], 1)
        time.sleep(0.3)
        new = writer.call(lambda db: (lambda iid: (db.upsert_embedding(iid, ai_client.EMBEDDING_MODEL, 4, 'h', blob(0.95, 0.05)), iid)[1])(
            db.add_item({'url': 'https://x/new', 'description': 'Kettlebell snatch', 'tags': 'kb'})))
        writer.call(lambda db: db.update_item(self.ids[1], {'description': 'Kettlebell press, edited meanwhile'}))
        self.app.state.maps.run_pass()                               # assigns the new item while the answer is pending
        self.assertIn(new, M.load(self.cache_path)['clusters']['t-1']['member_ids'])
        self.gate.set()
        last = self.wait()
        self.assertEqual(last['err'], 0, last)
        t = json.loads(self.cache_path.read_text(encoding='utf-8'))['clusters']['t-1']
        self.assertIn(new, t['member_ids'])                          # the merge kept the new membership
        self.assertEqual(sorted(t['summary_basis']), sorted(str(i) for i in self.ids[:3]))   # captured at prepare
        self.assertTrue(t['stale'])                                  # 1 added + 1 changed of 3: stale at once

    def make_stale(self):
        """A member's text changes and maintenance runs: t-1 is stale, so the next Refresh map pays for one summary."""
        self.app.state.writer.call(lambda db: db.update_item(self.ids[0], {'description': 'Kettlebell swing, changed'}))
        self.app.state.maps.run_pass()
        self.assertTrue(json.loads(self.cache_path.read_text(encoding='utf-8'))['clusters']['t-1']['stale'])

    def test_refresh_job_drops_retired_answer(self):
        self.start()
        self.wait()
        self.make_stale()
        self.gate.clear()
        p = self.start()
        self.assertEqual(p['plan']['summaries'], 1)
        time.sleep(0.3)
        with MS.MAP_LOCK:                                            # t-1 retires while the model is blocked
            c = M.load(self.cache_path)
            c['clusters'].pop('t-1')
            M.save(self.cache_path, c)
        self.gate.set()
        last = self.wait()
        self.assertEqual(last['err'], 0, last)
        self.assertEqual(list(M.load(self.cache_path)['clusters']), ['t-2'])      # the answer was dropped, nothing revived

    def test_rebuild_then_maintenance_keeps_items_added_during_job(self):
        self.start()
        self.wait()
        self.make_stale()                                            # so the rebuild job also has a summary step to block on
        self.gate.clear()
        p = self.start(rebuild=True)
        self.assertEqual((p['plan']['rebuild'], p['plan']['summaries']), (2, 1))
        time.sleep(0.3)
        writer = self.app.state.writer
        new = writer.call(lambda db: (lambda iid: (db.upsert_embedding(iid, ai_client.EMBEDDING_MODEL, 4, 'h', blob(0.95, 0.05)), iid)[1])(
            db.add_item({'url': 'https://x/late', 'description': 'Kettlebell late', 'tags': 'kb'})))
        self.gate.set()
        last = self.wait()
        self.assertEqual(last['err'], 0, last)
        self.app.state.maps.run_pass()                               # the pass the finished job pokes (run here, synchronously)
        c = M.load(self.cache_path)
        self.assertEqual(sorted(c['clusters']), ['t-1', 't-2'])      # ids carried over by the rebuild
        self.assertIn(new, c['clusters']['t-1']['member_ids'])       # added during the job: assigned, not lost


if __name__ == '__main__':
    unittest.main()
