"""Optional runtime checks use fake subprocesses and app-owned temporary directories."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from library import scraper_runtime as rt, scrape_watch
from core import app_paths


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'scraper'
        for patch in (mock.patch.object(rt, 'ROOT', self.root), mock.patch.object(rt, '_state', None),
                      mock.patch.object(rt, '_users', 0), mock.patch.object(rt, '_checked', None)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_frozen_never_launches_itself(self):
        with mock.patch.object(app_paths, 'FROZEN', True):
            with self.assertRaises(RuntimeError):
                scrape_watch.playwright_args(Path('out'))
            args = scrape_watch.playwright_args(Path('out'), python='isolated/python.exe')
        self.assertEqual(args[0], 'isolated/python.exe')

    def test_discovery_checks_version(self):
        with mock.patch.object(rt, '_run', return_value='python314') as run:
            self.assertTrue(rt.discover_python())
        self.assertTrue(any('3,14' in str(c) for c in run.call_args_list))

    def test_discovery_does_not_launch_or_install_missing_python(self):
        with mock.patch.object(app_paths, 'FROZEN', True), \
                mock.patch.object(rt.shutil, 'which', side_effect=lambda name: 'py.exe' if name == 'py' else None), \
                mock.patch.object(rt, '_run', return_value='') as run:
            self.assertEqual(rt.discover_python(), '')
        self.assertEqual(run.call_args.args[0], ['py.exe', '-0p'])
        self.assertEqual(run.call_args.kwargs['env']['PYTHON_MANAGER_AUTOMATIC_INSTALL'], 'false')

    def test_interrupted_install_is_retryable(self):
        rt._write(self.root / 'install.json', {'state': 'installing'})
        with mock.patch.object(app_paths, 'FROZEN', True), mock.patch.object(rt, 'discover_python', return_value=''):
            self.assertEqual(rt.status()['state'], 'failed')
            self.assertIn('interrupted', rt.status()['error'])

    def test_saved_ready_does_not_override_failed_probe(self):
        rt._write(self.root / 'install.json', {'state': 'ready'})
        with mock.patch.object(app_paths, 'FROZEN', True), mock.patch.object(rt, 'discover_python', return_value=''):
            self.assertEqual(rt.status()['state'], 'failed')

    def test_old_playwright_is_distinct_from_missing_or_failed(self):
        with mock.patch.object(app_paths, 'FROZEN', False), mock.patch.object(rt, 'discover_python', return_value='python'), \
                mock.patch.object(rt, 'probe', side_effect=RuntimeError('wrong version')), \
                mock.patch.object(rt, '_run', return_value='1.60.0'):
            result = rt.status(recheck=True)
        self.assertEqual((result['state'], result['version']), ('older', '1.60.0'))

    def test_ready_requires_browser_probe_and_reports_pin(self):
        with mock.patch.object(app_paths, 'FROZEN', False), mock.patch.object(rt, 'discover_python', return_value='python'), \
                mock.patch.object(rt, 'probe') as probe:
            result = rt.status(recheck=True)
        probe.assert_called_once()
        self.assertEqual((result['state'], result['version']), ('ready', rt.PIN))

    def test_failed_update_preserves_active_runtime(self):
        rt._write(self.root / 'active.json', {'name': 'runtime-old'})
        rt._state = {'state': 'installing'}
        with mock.patch.object(rt, 'discover_python', return_value='python'), \
                mock.patch.object(rt.shutil, 'disk_usage', return_value=mock.Mock(free=10**12)), \
                mock.patch.object(rt, '_run', side_effect=RuntimeError('failed')):
            rt._install()
        self.assertEqual(json.loads((self.root / 'active.json').read_text())['name'], 'runtime-old')
        self.assertEqual(rt._state['state'], 'failed')

    def test_remove_only_owned_runtime_and_reject_in_use(self):
        self.root.mkdir()
        (self.root / 'runtime-old').mkdir()
        (self.root / 'keep.txt').write_text('keep')
        rt._users = 1
        with self.assertRaises(RuntimeError):
            rt.action('remove')
        rt._users = 0
        with mock.patch.object(app_paths, 'FROZEN', True), mock.patch.object(rt, 'discover_python', return_value=''):
            rt.action('remove')
        self.assertTrue((self.root / 'keep.txt').exists())
        self.assertFalse((self.root / 'runtime-old').exists())
        with self.assertRaises(RuntimeError):
            rt._owned(self.root.parent / 'personal-python')

    def test_successful_repair_removes_only_retired_runtimes(self):
        self.root.mkdir()
        old = self.root / 'runtime-old'; old.mkdir()
        keep = self.root / 'keep.txt'; keep.write_text('keep')
        rt._write(self.root / 'active.json', {'name': old.name})
        rt._state = {'state': 'installing'}
        def run(args, *a, **kw):
            if 'venv' in args:
                Path(args[-1]).mkdir()
        with mock.patch.object(rt, 'discover_python', return_value='python'), \
                mock.patch.object(rt.shutil, 'disk_usage', return_value=mock.Mock(free=10**12)), \
                mock.patch.object(rt, '_run', side_effect=run), mock.patch.object(rt, 'probe') as probe:
            for _ in range(2):
                previous = rt._active()
                probe.side_effect = lambda folder: self.assertTrue(previous.is_dir())
                rt._install()
                self.assertEqual(rt._state['state'], 'ready')
                self.assertEqual(list(self.root.glob('runtime-*')), [rt._active()])
                self.assertTrue(keep.is_file())

    def test_retired_runtime_cleanup_failure_keeps_new_runtime_ready(self):
        self.root.mkdir()
        old = self.root / 'runtime-old'; old.mkdir()
        rt._write(self.root / 'active.json', {'name': old.name})
        rt._state = {'state': 'installing'}
        def run(args, *a, **kw):
            if 'venv' in args:
                Path(args[-1]).mkdir()
        with mock.patch.object(rt, 'discover_python', return_value='python'), \
                mock.patch.object(rt.shutil, 'disk_usage', return_value=mock.Mock(free=10**12)), \
                mock.patch.object(rt, '_run', side_effect=run), mock.patch.object(rt, 'probe'), \
                mock.patch.object(rt.shutil, 'rmtree', side_effect=OSError('locked')) as remove:
            rt._install()
        remove.assert_called_once_with(old)
        self.assertEqual(rt._state['state'], 'ready')
        self.assertIn('cleanup failed', rt._state['error'])
        self.assertNotEqual(rt._active(), old)
        self.assertTrue(rt._active().is_dir())

    def test_selected_project_environment_is_probed_used_and_never_removed(self):
        project = Path(self.temp.name) / 'project-venv'
        py = rt.interpreter(project); py.parent.mkdir(parents=True); py.write_bytes(b'')
        with mock.patch.object(app_paths, 'FROZEN', True), mock.patch.object(rt, 'discover_python', return_value=''), mock.patch.object(rt, 'probe') as probe:
            result = rt.select_location('environment', str(project))
            self.assertEqual(result['state'], 'ready')
            self.assertFalse(result['managed'])
            self.assertEqual(result['path'], str(py))
            with rt.use() as (selected, env):
                self.assertEqual(selected, str(py))
            probe.assert_called()
            rt.action('remove')
            self.assertTrue(py.is_file())
            rt.select_location('environment', '')
            self.assertEqual(rt.status()['state'], 'missing')

    def test_invalid_environment_keeps_previous_selection(self):
        project = Path(self.temp.name) / 'project-venv'
        py = rt.interpreter(project); py.parent.mkdir(parents=True); py.write_bytes(b'')
        rt._write(self.root / 'selected.json', {'environment': 'previous'})
        with mock.patch.object(rt, 'probe', side_effect=RuntimeError('Browser check failed')):
            with self.assertRaises(RuntimeError):
                rt.select_location('environment', str(project))
        self.assertEqual(rt._json(self.root / 'selected.json')['environment'], 'previous')
        for kind, raw in [('environment', 'relative'), ('other', str(project)), ('python', 42)]:
            with self.assertRaises(ValueError):
                rt.select_location(kind, raw)

    def test_cancel_kills_child(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        rt._cancel.set()
        self.addCleanup(rt._cancel.clear)
        with mock.patch.object(rt.subprocess, 'Popen', return_value=proc), mock.patch.object(rt, 'kill_tree') as kill:
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                rt._run(['python'])
        kill.assert_called_once_with(proc)
