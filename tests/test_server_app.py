"""/api/app (projects/desktop-app): version, Start with Windows, Quit. The registry is mocked.

Run from the project root:  py -m unittest tests.test_server_app -v
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from desktop import autostart
from server.app import create_app
from core.version import __version__

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class AppRoutesTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_view(self):
        with mock.patch.object(autostart, 'is_on', return_value=False):
            r = self.c.get('/api/app').json()
        self.assertEqual(r['version'], __version__)
        self.assertEqual(r['data_dir'], str(self.data))
        self.assertFalse(r['autostart'])
        self.assertFalse(r['can_quit'])

    def test_autostart_toggle(self):
        state = {'on': False}
        with mock.patch.object(autostart, 'set_on', side_effect=lambda on: state.update(on=on) or on), \
             mock.patch.object(autostart, 'is_on', side_effect=lambda: state['on']):
            self.assertTrue(self.c.put('/api/app/autostart', json={'on': True}, headers=W).json()['autostart'])
            self.assertFalse(self.c.put('/api/app/autostart', json={'on': False}, headers=W).json()['autostart'])

    def test_autostart_needs_guard_header(self):
        self.assertEqual(self.c.put('/api/app/autostart', json={'on': True}).status_code, 403)

    def test_widget_toggle(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(autostart, 'WIDGET_FILE', Path(td) / 'widget.json'), \
                mock.patch.object(autostart, 'spawn') as spawn, \
                mock.patch.object(autostart, 'is_on', return_value=False):
            self.assertTrue(self.c.put('/api/app/widget', json={'on': True}, headers=W).json()['widget'])
            spawn.assert_called_once_with('--widget')
            self.assertFalse(self.c.put('/api/app/widget', json={'on': False}, headers=W).json()['widget'])
            self.assertIn('--background', autostart.command())

    def test_widget_toggle_publishes_both_ways(self):
        events = []
        self.app.state.hub.publish = lambda name, data: events.append((name, data)) if name == 'widget' else None
        with tempfile.TemporaryDirectory() as td,                 mock.patch.object(autostart, 'WIDGET_FILE', Path(td) / 'widget.json'),                 mock.patch.object(autostart, 'spawn'),                 mock.patch.object(autostart, 'is_on', return_value=False):
            self.c.put('/api/app/widget', json={'on': True}, headers=W)
            self.c.put('/api/app/widget', json={'on': False}, headers=W)
        self.assertEqual(events, [('widget', {'enabled': True}), ('widget', {'enabled': False})])

    def test_tray_preference(self):
        with mock.patch.object(autostart, 'is_on', return_value=False):
            self.assertTrue(self.c.get('/api/app').json()['tray'])              # on by default: a desktop app lives in the tray
            self.assertFalse(self.c.put('/api/app/tray', json={'on': False}, headers=W).json()['tray'])
            self.assertFalse(self.c.get('/api/app').json()['tray'])
            self.assertTrue(self.c.put('/api/app/tray', json={'on': True}, headers=W).json()['tray'])
        self.assertEqual(self.c.put('/api/app/tray', json={'on': True}).status_code, 403)

    def test_warm_preference_and_app_event(self):
        events = []
        self.app.state.hub.publish = lambda name, data: events.append((name, data)) if name == 'app' else None
        with mock.patch.object(autostart, 'is_on', return_value=False):
            self.assertFalse(self.c.get('/api/app').json()['warm'])             # off by default: asleep closes
            self.assertTrue(self.c.put('/api/app/warm', json={'on': True}, headers=W).json()['warm'])
            self.c.put('/api/app/tray', json={'on': True}, headers=W)
        self.assertEqual(events, [('app', {'tray': True, 'warm': True, 'notice': False}),
                                  ('app', {'tray': True, 'warm': True, 'notice': False})])

    def test_notice_preference(self):
        events = []
        self.app.state.hub.publish = lambda name, data: events.append((name, data)) if name == 'app' else None
        with mock.patch.object(autostart, 'is_on', return_value=False):
            self.assertFalse(self.c.get('/api/app').json()['notice'])           # off by default: no spam on every minimize
            self.assertTrue(self.c.put('/api/app/notice', json={'on': True}, headers=W).json()['notice'])
            self.assertTrue(self.c.get('/api/app').json()['notice'])
            self.assertFalse(self.c.put('/api/app/notice', json={'on': False}, headers=W).json()['notice'])
        self.assertEqual(self.c.put('/api/app/notice', json={'on': True}).status_code, 403)
        self.assertEqual([d['notice'] for _, d in events], [True, False])

    def test_first_tray_notice_is_told_once(self):
        with mock.patch.object(autostart, 'is_on', return_value=False):
            self.assertFalse(self.c.get('/api/app').json()['notice_seen'])
            self.assertEqual(self.c.post('/api/app/tray/seen').status_code, 403)
            self.assertEqual(self.c.post('/api/app/tray/seen', headers=W).status_code, 200)
            self.assertTrue(self.c.get('/api/app').json()['notice_seen'])

    def test_quit(self):
        self.assertEqual(self.c.post('/api/app/quit', headers=W).status_code, 409)
        stopped = []
        self.app.state.request_exit = lambda: stopped.append(1)
        self.assertEqual(self.c.post('/api/app/quit', headers=W).status_code, 200)
        self.assertEqual(stopped, [1])

    def test_restart_starts_a_waiting_launch_then_quits(self):
        self.assertEqual(self.c.post('/api/app/restart', headers=W).status_code, 409)
        order = []
        self.app.state.request_exit = lambda: order.append('quit')
        with mock.patch.object(autostart, 'spawn', side_effect=lambda *a: order.append(a)):
            self.assertEqual(self.c.post('/api/app/restart', headers=W).status_code, 200)
        self.assertEqual(order[0][0], '--restart-after')
        self.assertEqual(order[1], 'quit')

    def test_command_from_source(self):
        for on, flag in ((False, '--background'), (True, '--widget')):    # not the real local/widget.json
            with mock.patch.object(autostart, 'widget_on', return_value=on):
                cmd = autostart.command()
            self.assertTrue(cmd.endswith(f'launch.pyw" {flag}'), cmd)


if __name__ == '__main__':
    unittest.main()
