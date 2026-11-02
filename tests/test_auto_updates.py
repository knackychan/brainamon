"""Backend schedule, restart recovery and coordinated explicit installation."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from desktop import updater
from server.updates import Updates, ATTEMPT, AUTO, INTERVAL
from server.store import Writer
from tests import test_server_app, test_updater, test_sync


class Schedule(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        self.writer = Writer(Path(folder.name) / 'content_manager.db')
        self.writer.start()
        self.addCleanup(self.writer.stop)
        self.service = Updates(self.writer, test_sync.Hub())
        self.addCleanup(self.service.shutdown)
        self.patch = mock.patch.object(updater, '_dl', dict(state='idle', done=0,total=0,name='',version='',sha256='',error=''))
        self.patch.start(); self.addCleanup(self.patch.stop)

    def once(self):
        class Once:
            stopped = False
            waits = []
            def wait(self, seconds):
                self.waits.append(seconds)
                if seconds == 1:
                    self.stopped = True
                return self.stopped
            def is_set(self): return self.stopped
            def set(self): self.stopped = True
        self.service.stop = stop = Once()
        with mock.patch.object(updater, 'recover', return_value={}):
            self.service._loop()
        return stop.waits

    def test_source_never_starts_automatic_worker(self):
        with mock.patch.object(updater.app_paths, 'FROZEN', False):
            self.service.boot()
        self.assertIsNone(self.service.thread)

    def test_contributor_never_checks_downloads_or_starts_worker(self):
        with mock.patch.object(updater.app_paths, 'CONTRIBUTOR', True), \
                mock.patch.object(updater.app_paths, 'FROZEN', True), \
                mock.patch.object(updater, 'check') as check, \
                mock.patch.object(updater, 'start_download') as download:
            self.assertFalse(self.service.enabled())
            self.service.boot()
            self.assertIsNone(self.service.thread)
            self.assertIn('official updates are disabled', self.service.check(download=True)['error'])
            check.assert_not_called()
            download.assert_not_called()

    def test_delayed_daily_check_download_preference_and_manual_retry(self):
        with mock.patch.object(updater, 'check', return_value={'newer': True, 'latest': '99.0.0'}) as check, \
             mock.patch.object(updater, 'start_download') as download:
            self.assertEqual(self.once(), [30, 1])
            check.assert_called_once(); download.assert_called_once()
            self.assertGreater(float(self.writer.read(lambda db: db.get_setting(ATTEMPT, '0'))), 0)
            check.reset_mock(); download.reset_mock()
            self.once(); check.assert_not_called()
            self.service.check(); check.assert_called_once()  # manual ignores the daily interval
            self.writer.call(lambda db: (db.set_setting(ATTEMPT, '0'), db.set_setting(AUTO, '0')))
            check.reset_mock(); self.once(); check.assert_not_called()
            self.service.check(download=True, automatic=True); check.assert_not_called()
            self.service.stop = threading.Event()
            self.service.check(download=True); check.assert_called_once()
            download.assert_called_once()

    def test_shutdown_during_check_cannot_start_a_download(self):
        def checked():
            self.service.stop.set()
            return {'newer':True,'latest':'99.0.0'}
        with mock.patch.object(updater,'check',side_effect=checked), mock.patch.object(updater,'start_download') as download:
            self.service.check(download=True,automatic=True)
            download.assert_not_called()

    def test_concurrent_manual_and_automatic_checks_share_one_operation(self):
        entered, release = threading.Event(), threading.Event()
        def check():
            entered.set(); release.wait(2)
            return {'newer': False, 'current': '0.2.0'}
        with mock.patch.object(updater, 'check', side_effect=check) as check_mock:
            thread = threading.Thread(target=self.service.check); thread.start()
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.service.check(download=True)['state'], 'checking')
            release.set(); thread.join(2)
            check_mock.assert_called_once()


class Recovery(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(updater.update_signing, 'PUBLIC_KEY', test_updater.PUBLIC)
        patch.start(); self.addCleanup(patch.stop)

    def test_installed_or_older_saved_update_is_ignored_on_startup(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)):
            saved = {'name': 'Brainamon-Setup-1.0.6.exe', 'latest': '1.0.6'}
            (Path(folder) / 'release.json').write_text(json.dumps(saved), encoding='utf-8')
            for current in ('1.0.6', '1.0.7'):
                with self.subTest(current=current), mock.patch.object(updater, '__version__', current), \
                     mock.patch.object(updater, '_dl', dict(state='idle', error='')), \
                     mock.patch.object(updater, '_trusted_publisher') as verify:
                    self.assertEqual(updater.recover(), {})
                    self.assertEqual(updater.status()['state'], 'idle')
                    self.assertEqual(updater.status()['error'], '')
                    verify.assert_not_called()
            self.assertTrue((Path(folder) / 'release.json').exists())

    def test_saved_ready_state_rechecks_hash_signature_version_and_tamper(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)), \
             mock.patch.object(updater, '_get', test_updater.release()), \
             mock.patch.object(updater, '_get_chunks', test_updater.chunks), \
             mock.patch.object(updater, '_trusted_publisher', return_value=True) as signer:
            updater.start_download(updater.check())
            deadline = time.monotonic() + 3
            while updater.status()['state'] == 'downloading' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(updater.status()['state'], 'ready')
            updater._dl['state'] = 'idle'
            self.assertEqual(updater.recover()['latest'], '99.0.0')
            self.assertEqual(updater.status()['state'], 'ready')
            (Path(folder) / 'Brainamon-Setup-99.0.0.exe').write_bytes(b'tampered')
            self.assertEqual(updater.recover(), {})
            self.assertEqual(updater.status()['state'], 'error')

    def test_cancellation_removes_partial_and_never_saves_ready(self):
        entered, release = threading.Event(), threading.Event()
        def chunks(url):
            def blocks():
                entered.set(); release.wait(3)
                yield test_updater.EXE
            return len(test_updater.EXE), blocks()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater,'UPDATES',Path(folder)), \
             mock.patch.object(updater,'_get',test_updater.release()), mock.patch.object(updater,'_get_chunks',chunks):
            updater.start_download(updater.check())
            self.assertTrue(entered.wait(2))
            stop = threading.Thread(target=updater.stop_download); stop.start()
            release.set(); stop.join(3)
            self.assertFalse(stop.is_alive())
            self.assertEqual(updater.status()['state'],'error')
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_unsigned_trial_never_becomes_ready_and_redirects_are_restricted(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(updater, 'UPDATES', Path(folder)), \
             mock.patch.object(updater, '_get', test_updater.release()), \
             mock.patch.object(updater, '_get_chunks', test_updater.chunks), \
             mock.patch.object(updater, '_trusted_publisher', return_value=False):
            updater.start_download(updater.check())
            deadline = time.monotonic() + 3
            while updater.status()['state'] == 'downloading' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(updater.status()['state'], 'error')
            self.assertIn('signature', updater.status()['error'])
            self.assertFalse((Path(folder) / 'release.json').exists())
        request = updater.urllib.request.Request(updater.API)
        for url in ('http://github.com/file', 'https://evil.invalid/file', 'https://github.com.evil.invalid/file',
                    'https://api.github.com@evil.invalid/file', 'https://release-assets.githubusercontent.com/file'):
            with self.assertRaisesRegex(ValueError, 'redirect'):
                updater._RedirectGuard().redirect_request(request, None, 302, '', {}, url)
        self.assertTrue(updater._allowed_url('https://release-assets.githubusercontent.com/asset'))


class Install(test_server_app.AppRoutesTest):
    def test_contributor_cannot_enable_download_or_install_official_updates(self):
        with mock.patch.object(updater.app_paths, 'CONTRIBUTOR', True), \
                mock.patch.object(updater.app_paths, 'FROZEN', True), \
                mock.patch.object(updater, 'launch') as launch:
            for action in ('download', 'install'):
                response = self.c.post('/api/app/update/' + action, headers=test_server_app.W, json={'name': 'x'})
                self.assertEqual(response.status_code, 409)
            self.assertEqual(self.c.put('/api/app/update/automatic', headers=test_server_app.W, json={'on': True}).status_code, 409)
            self.assertFalse(self.app.state.install_gate.closing)
            launch.assert_not_called()

    def test_preference_and_status_survive_reopening(self):
        self.assertTrue(self.c.get('/api/app/update/status').json()['automatic'])
        self.assertEqual(self.c.put('/api/app/update/automatic', headers=test_server_app.W, json={'on': 'no'}).status_code, 422)
        self.c.put('/api/app/update/automatic', headers=test_server_app.W, json={'on': False})
        self.assertFalse(self.c.get('/api/app').json()['automatic_updates'])
        self.assertFalse(self.c.get('/api/app/update/status').json()['automatic'])

    def test_install_defers_jobs_reserves_shutdown_and_reopens_gate_on_failure(self):
        state = self.app.state
        state.request_exit = mock.Mock()
        with mock.patch.object(updater.app_paths, 'FROZEN', True), mock.patch.object(updater, 'launch') as launch:
            state.updates.lock.acquire()
            try:
                self.assertEqual(self.c.post('/api/app/update/install', headers=test_server_app.W, json={'name': 'x'}).status_code, 409)
                launch.assert_not_called()
            finally:
                state.updates.lock.release()
            state.jobs.current = mock.Mock()
            self.assertEqual(self.c.post('/api/app/update/install', headers=test_server_app.W, json={'name': 'x'}).status_code, 409)
            launch.assert_not_called(); self.assertFalse(state.install_gate.closing)
            state.jobs.current = None
            launch.side_effect = ValueError('synthetic signature refusal')
            self.assertEqual(self.c.post('/api/app/update/install', headers=test_server_app.W, json={'name': 'x'}).status_code, 422)
            state.request_exit.assert_not_called(); self.assertFalse(state.install_gate.closing)
            launch.side_effect = None
            self.assertEqual(self.c.post('/api/app/update/install', headers=test_server_app.W, json={'name': 'x'}).status_code, 200)
            state.request_exit.assert_called_once()
            self.assertTrue(state.install_gate.closing)
            self.assertEqual(self.c.put('/api/app/tray', headers=test_server_app.W, json={'on': True}).status_code, 403)
            from server.jobs import Busy
            with self.assertRaises(Busy):
                state.jobs.start('thumb', [])
