"""Settings > Obsidian routes (server/routes/obsidian.py): owner setup (create, use an empty vault, Use it anyway,
refusals), Move, Reset, Reclaim, Take over, options, first open, the view and the Export window's owner pointer.

Run from the project root:  py -m unittest tests.test_server_obsidian -v
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import config
from core.db import Database
from library import owner_vault as V
from library import ytdlp
from server import map_service as MS
from server.app import create_app
from server.routes import io as io_routes

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class ObsidianRoutesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.data = self.root / 'data'
        self.docs = self.root / 'Documents'
        self.vault = self.docs / 'Brainamon Vault'
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://x/a', 'description': 'Hip airplane', 'tags': 'hips'})
        db.close()
        for p in (mock.patch.object(ytdlp, 'registry_get', lambda name: ''),
                  mock.patch.object(config, 'ENV_PATH', self.root / '.env'),
                  mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': ''}),
                  mock.patch.object(MS.app_paths, 'HOME', self.root / 'home'),
                  mock.patch.object(V, 'default_location', lambda: self.vault)):
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, port=8765, web_dist=self.root / 'x', cards_dir=self.root / 'x', cloud_dir=self.root / 'cloud'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        self.c.app.state.maps.shutdown()  # Route tests drive passes explicitly; thread retries are tested separately.

    def view(self):
        return self.c.get('/api/obsidian').json()

    def test_view_before_setup(self):
        v = self.view()
        self.assertEqual((v['vault'], v['mode'], v['legacy']), ('', '', False))
        self.assertEqual(v['default_location'], str(self.vault))
        self.assertFalse(v['earlier_vault'])
        self.assertFalse(v['vault_sync_on'])
        self.assertEqual(v['map']['topics'], 0)
        self.assertEqual(v['map']['coverage'], {'indexed': 0, 'total': 1, 'low': True})
        self.assertIn('pending', v['status'])

    def test_create_makes_folder_and_dot_obsidian_and_first_open(self):
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((self.vault / '.obsidian').is_dir())
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), ['.brainamon', '.obsidian', 'Brainamon'])
        v = self.view()
        self.assertEqual((v['mode'], v['vault'], v['first_open']), ('owner', str(self.vault), 'pending'))
        self.assertEqual(self.c.post('/api/obsidian/first-open/done', headers=W).status_code, 200)
        self.assertEqual(self.view()['first_open'], '')
        self.assertTrue(self.c.get('/api/export/defaults').json()['owner'])

    def test_existing_empty_vault_no_first_open_dot_obsidian_untouched(self):
        made = self.docs / 'Made in Obsidian'
        (made / '.obsidian').mkdir(parents=True)
        (made / '.obsidian' / 'app.json').write_text('{"a": 1}', encoding='utf-8')
        r = self.c.put('/api/obsidian/vault', json={'path': str(made)}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.view()['first_open'], '')
        self.assertEqual(sorted(p.name for p in (made / '.obsidian').iterdir()), ['app.json'])
        self.assertEqual((made / '.obsidian' / 'app.json').read_text(encoding='utf-8'), '{"a": 1}')
        self.assertTrue((made / 'Brainamon' / 'Knowledge Map.md').is_file())

    def test_vault_list_falls_back_when_obsidian_json_missing_or_bad(self):
        with mock.patch.object(V, 'obsidian_vaults', lambda path=None: []):
            self.assertEqual(self.c.get('/api/obsidian/vaults').json(), {'vaults': []})
        listed = [{'path': str(self.docs / 'One'), 'open': True, 'ts': 5}]
        with mock.patch.object(V, 'obsidian_vaults', lambda path=None: listed):
            self.assertEqual(self.c.get('/api/obsidian/vaults').json(), {'vaults': listed})

    def test_use_it_anyway_one_to_five_files(self):
        few = self.docs / 'few'
        (few / '.obsidian').mkdir(parents=True)
        (few / 'Welcome.md').write_text('hello', encoding='utf-8')
        r = self.c.put('/api/obsidian/vault', json={'path': str(few)}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['needs_confirm'], r.json()['count']), (True, 1))
        self.assertEqual(self.view()['mode'], '')                              # nothing changed yet
        r = self.c.put('/api/obsidian/vault', json={'path': str(few), 'confirm': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json().get('needs_confirm'))
        self.assertEqual((few / 'Welcome.md').read_text(encoding='utf-8'), 'hello')
        self.assertEqual(self.view()['mode'], 'owner')

    def test_more_than_five_files_refused(self):
        many = self.docs / 'many'
        many.mkdir(parents=True)
        for i in range(6):
            (many / f'{i}.md').write_text('x')
        r = self.c.put('/api/obsidian/vault', json={'path': str(many), 'confirm': True}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('later update', r.json()['detail'])
        self.assertFalse((many / 'Brainamon').exists())

    def test_location_refusals(self):
        for bad in (self.data / 'v', self.root, self.root / 'home' / 'v', 'relative', ''):
            r = self.c.put('/api/obsidian/vault', json={'path': str(bad), 'create': True}, headers=W)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}).status_code, 403)   # no X-CM

    def test_owner_vault_gate_while_vault_sync_on(self):
        """Spec 1b decision 6: Create with vault sync on answers 409 until a round has read the phones, 409 naming
        an older phone, then 200."""
        self.c.app.state.writer.call(lambda db: db.set_setting('cloud_vault', 'on'))
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        self.assertEqual((r.status_code, r.json()['detail']), (409, MS.PHONES_UNCHECKED))
        self.assertTrue(self.view()['vault_sync_on'])
        self.c.app.state.sync.st['vault_devices'] = [{'device': 'p9', 'ok': False}]
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        self.assertEqual((r.status_code, r.json()['detail']), (409, MS.phone_old(['p9'])))
        self.assertFalse(self.vault.exists())
        self.c.app.state.sync.st['vault_devices'] = [{'device': 'p1', 'ok': True}]
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((self.vault / 'Brainamon').is_dir())

    def test_move_gate_while_vault_sync_on(self):
        old = self.data / 'Fredorama'
        (old / '.obsidian').mkdir(parents=True)
        self.c.app.state.writer.call(lambda db: (db.set_setting('obsidian_vault', str(old)), db.set_setting('cloud_vault', 'on')))
        self.assertTrue(self.view()['legacy'])
        r = self.c.post('/api/obsidian/move', json={'path': str(self.vault)}, headers=W)
        self.assertEqual((r.status_code, r.json()['detail']), (409, MS.PHONES_UNCHECKED))
        self.c.app.state.sync.st['vault_devices'] = [{'device': 'p1', 'ok': True}]
        r = self.c.post('/api/obsidian/move', json={'path': str(self.vault)}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue((self.vault / '.obsidian').is_dir())
        v = self.view()
        self.assertEqual((v['mode'], v['vault'], v['legacy']), ('owner', str(self.vault), False))
        self.assertTrue(old.is_dir())

    def test_reset_reclaim_options(self):
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        page = self.vault / 'Brainamon' / 'Items' / f'hip-airplane-{self.a}.md'
        original = page.read_text(encoding='utf-8')
        page.write_text('edited', encoding='utf-8')
        self.assertTrue(self.c.app.state.maps.run_pass())
        self.assertEqual(self.view()['status']['adopted'], [f'Brainamon/Items/hip-airplane-{self.a}.md'])
        self.assertEqual(self.c.post('/api/obsidian/reset', json={'path': 'Mine.md'}, headers=W).status_code, 400)
        r = self.c.post('/api/obsidian/reset', json={'path': f'Brainamon/Items/hip-airplane-{self.a}.md'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(page.read_text(encoding='utf-8'), original)
        (self.vault / V.MANIFEST).unlink()
        self.assertTrue(self.c.app.state.maps.run_pass())
        self.assertGreater(self.view()['status']['unlisted'], 0)
        r = self.c.post('/api/obsidian/reclaim', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreater(r.json()['reclaimed'], 0)
        self.assertEqual(self.view()['status']['unlisted'], 0)
        self.assertFalse(self.view()['pictures'])
        self.assertEqual(self.c.put('/api/obsidian/options', json={'pictures': True}, headers=W).status_code, 200)
        self.assertTrue(self.view()['pictures'])

    def test_take_over_other_library(self):
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        man = V.read_manifest(self.vault)
        man['library_id'] = 'other'
        V.write_manifest(self.vault, man)
        self.assertTrue(self.c.app.state.maps.run_pass())
        self.assertTrue(self.view()['status']['other_library'])
        r = self.c.post('/api/obsidian/takeover', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(self.view()['status']['other_library'])
        mine = self.c.app.state.writer.read(lambda db: db.get_setting('library_id'))
        self.assertEqual(V.read_manifest(self.vault)['library_id'], mine)

    def test_reconnect_earlier_vault(self):
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        man = V.read_manifest(self.vault)
        man['library_id'] = 'earlier-install'
        V.write_manifest(self.vault, man)
        self.c.app.state.writer.call(lambda db: (db.set_setting('obsidian_vault', ''), db.set_setting('obsidian_mode', '')))
        self.assertTrue(self.view()['earlier_vault'])
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['needs_takeover'])
        self.assertEqual(r.json()['count'], 0)
        self.assertTrue(r.json()['message'].startswith(V.TAKEOVER))
        self.assertEqual(V.read_manifest(self.vault)['library_id'], 'earlier-install')
        r = self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True, 'takeover': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        v = r.json()
        self.assertEqual((v['mode'], v['vault'], v['earlier_vault']), ('owner', str(self.vault), False))
        mine = self.c.app.state.writer.read(lambda db: db.get_setting('library_id'))
        self.assertEqual(V.read_manifest(self.vault)['library_id'], mine)
        r = self.c.post('/api/obsidian/leftovers/remove', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['removed'], 0)

    def test_cancel_and_classic_export_pointer(self):
        self.assertEqual(self.c.post('/api/obsidian/cancel', headers=W).status_code, 200)
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        r = self.c.post('/api/export/obsidian', json={'vault': str(self.vault)}, headers=W)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Settings > Obsidian', r.json()['detail'])

    def test_open_targets_knowledge_map(self):
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        opened = []
        known = [{'path': str(self.vault), 'open': True, 'ts': 1}]          # Obsidian has opened this folder
        with mock.patch.object(io_routes, '_open_uri', opened.append), mock.patch.object(io_routes, '_obsidian_installed', lambda: True),                 mock.patch.object(V, 'obsidian_vaults', lambda path=None: known):
            r = self.c.post('/api/obsidian/graph', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['opened'])
        self.assertTrue(opened[0].startswith('obsidian://open?path='))
        self.assertIn('Knowledge%20Map.md', opened[0])

    def test_open_new_to_obsidian_only_starts_it(self):
        self.c.put('/api/obsidian/vault', json={'path': str(self.vault), 'create': True}, headers=W)
        opened = []
        with mock.patch.object(io_routes, '_open_uri', opened.append), mock.patch.object(io_routes, '_obsidian_installed', lambda: True),                 mock.patch.object(V, 'obsidian_vaults', lambda path=None: []):
            r = self.c.post('/api/obsidian/graph', headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['opened'], r.json()['vault']), (False, str(self.vault)))
        self.assertEqual(opened, ['obsidian://open'])            # a path link to a never-opened folder says Vault not found
        with mock.patch.object(io_routes, '_open_uri', opened.append), mock.patch.object(io_routes, '_obsidian_installed', lambda: False):
            self.assertEqual(self.c.post('/api/obsidian/graph', headers=W).status_code, 400)
        self.assertEqual(opened, ['obsidian://open'])


if __name__ == '__main__':
    unittest.main()
