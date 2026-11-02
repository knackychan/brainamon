"""Uninstall cleanup uses disposable files only; never imports runtime app paths."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core import uninstall

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows uninstaller')
class CleanupTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.local = self.root / 'Local'
        self.home = self.local / 'Brainamon'
        self.home.mkdir(parents=True)
        self.library = self.home / 'data'
        self.library.mkdir()
        (self.library / 'content_manager.db').write_text('synthetic library')
        (self.home / 'settings.txt').write_text('synthetic settings')
        self.env = {'LOCALAPPDATA': str(self.local), 'USERPROFILE': str(self.root),
                    'SystemRoot': str(self.root / 'Windows')}
        self.install = self.local / 'Programs/Brainamon'

    def targets(self):
        return uninstall.cleanup_targets(self.env, self.install)

    def run_cleanup(self, answers, running=False):
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, 'executable', str(self.install / 'Brainamon.exe')), \
                mock.patch.object(uninstall.build_channel, 'read', return_value='official'), \
                mock.patch.object(uninstall, '_message', side_effect=answers) as dialog, \
                mock.patch.object(uninstall, '_app_running', side_effect=running if isinstance(running, list) else None,
                                  return_value=running):
            code = uninstall.main()
        return code, dialog

    def test_confirm_removes_all_owned_data_and_preserves_unrelated_folder(self):
        unrelated = self.local / 'Other app'
        unrelated.mkdir()
        code, dialog = self.run_cleanup([6])
        self.assertEqual(code, 0)
        self.assertFalse(self.home.exists())
        self.assertTrue(unrelated.exists())
        self.assertIn(str(self.library), dialog.call_args_list[0].args[0])
        self.assertIn(str(self.home), dialog.call_args_list[0].args[0])
        self.assertEqual(dialog.call_args_list[0].args[1] & 0x100, 0x100)

    def test_final_no_preserves_data_and_stops_uninstall(self):
        code, _ = self.run_cleanup([7])
        self.assertEqual(code, 2)
        self.assertTrue(self.library.exists())

    def test_discovers_legacy_custom_home_pointer_and_environment_override(self):
        legacy = self.local / 'Content Manager'
        legacy.mkdir()
        custom = self.root / 'Custom home'
        custom.mkdir()
        external = self.root / 'Selected library'
        external.mkdir()
        (external / 'content_manager.db').touch()
        (custom / 'location.json').write_text(json.dumps({'data_dir': str(external)}))
        override = self.root / 'Override library'
        override.mkdir()
        (override / 'content_manager.db').touch()
        self.env.update(BRAINAMON_HOME=str(custom), CM_DATA_DIR=str(override))
        targets = self.targets()
        self.assertTrue({legacy, custom, external, override, self.library, self.home} <= set(targets))
        self.assertLess(targets.index(external), targets.index(custom))
        code, _ = self.run_cleanup([6])
        self.assertEqual(code, 0)
        self.assertTrue(all(not p.exists() for p in targets))

    def test_unsafe_or_malformed_pointer_prevents_any_deletion(self):
        values = ['broken json', 'null', '[]', '{}', '{"data_dir": 12}',
                  json.dumps({'data_dir': 'relative'}),
                  json.dumps({'data_dir': str(self.root)}),
                  json.dumps({'data_dir': str(self.root.anchor)}),
                  json.dumps({'data_dir': str(self.local)}),
                  json.dumps({'data_dir': str(self.install)})]
        for value in values:
            with self.subTest(value=value):
                (self.home / 'location.json').write_text(value)
                code, dialog = self.run_cleanup([1])
                self.assertEqual(code, 1)
                self.assertTrue(self.library.exists())
                self.assertIn('could not finish', dialog.call_args.args[0])

    def test_rejects_unidentified_custom_folders_and_source_home(self):
        custom = self.root / 'Unrelated'
        custom.mkdir()
        (custom / 'valuable.txt').touch()
        for key in ('BRAINAMON_HOME', 'CM_DATA_DIR'):
            with self.subTest(key=key):
                self.env[key] = str(custom)
                with self.assertRaises(ValueError):
                    self.targets()
                del self.env[key]
        (self.home / '.git').mkdir()
        with self.assertRaises(ValueError):
            self.targets()

    def test_rejects_shared_special_folder_even_with_database_marker(self):
        documents = self.root / 'Documents'
        documents.mkdir()
        (documents / 'content_manager.db').touch()
        self.env['CM_DATA_DIR'] = str(documents)
        with self.assertRaises(ValueError):
            self.targets()

    def test_rejects_library_inside_system_or_installation_tree(self):
        for folder in (self.root / 'Windows/Nested', self.install / 'Nested'):
            with self.subTest(folder=folder):
                folder.mkdir(parents=True)
                (folder / 'content_manager.db').touch()
                self.env['CM_DATA_DIR'] = str(folder)
                with self.assertRaises(ValueError):
                    self.targets()

    def test_linked_home_and_nested_junction_are_not_followed(self):
        if os.name != 'nt':
            self.skipTest('Windows junction guard')
        external = self.root / 'Do not remove'
        external.mkdir()
        valuable = external / 'keep.txt'
        valuable.touch()
        for link in (self.library / 'junction', self.local / 'Content Manager'):
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(external)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                code, _ = self.run_cleanup([1])
                self.assertEqual(code, 1)
                self.assertTrue(valuable.exists())
                self.assertTrue(self.library.exists())
            finally:
                link.rmdir()

    def test_running_app_or_restart_during_confirmation_prevents_deletion(self):
        for running, answers in (([True], [1]), ([False, True], [6, 1])):
            with self.subTest(running=running):
                code, _ = self.run_cleanup(answers, running)
                self.assertEqual(code, 1)
                self.assertTrue(self.library.exists())

    def test_delete_failure_is_reported_and_retains_home_pointer(self):
        (self.home / 'location.json').write_text(json.dumps({'data_dir': str(self.library)}))
        with mock.patch.object(uninstall.shutil, 'rmtree', side_effect=PermissionError('fixture locked')):
            code, dialog = self.run_cleanup([6, 1])
        self.assertEqual(code, 1)
        self.assertIn('fixture locked', dialog.call_args.args[0])
        self.assertTrue((self.home / 'location.json').exists())

    def test_tasklist_ignores_cleanup_process_and_detects_other_instances(self):
        own = f'"Brainamon.exe","{os.getpid()}","Console"\n'
        with mock.patch.object(uninstall.subprocess, 'run') as run:
            run.return_value.stdout = own
            self.assertFalse(uninstall._app_running())
            run.return_value.stdout = own + '"Brainamon.exe","0","Console"\n'
            self.assertTrue(uninstall._app_running())
            run.side_effect = subprocess.CalledProcessError(1, 'tasklist')
            with self.assertRaises(subprocess.CalledProcessError):
                uninstall._app_running()


class IntegrationTest(unittest.TestCase):
    def test_launcher_dispatches_before_normal_startup(self):
        with mock.patch.object(sys, 'argv', ['launch.pyw', '--uninstall-data']), \
                mock.patch.object(uninstall, 'main', return_value=2) as cleanup:
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT / 'launch.pyw'), run_name='__main__')
        self.assertEqual(result.exception.code, 2)
        cleanup.assert_called_once_with()

    def test_source_cleanup_mode_cannot_delete_data(self):
        with mock.patch.object(sys, 'frozen', False, create=True), mock.patch.object(uninstall, '_message') as dialog:
            self.assertEqual(uninstall.main(), 1)
            dialog.assert_not_called()

    def test_installer_uses_cleanup_before_removal_and_skips_silent_uninstall(self):
        script = (ROOT / 'packaging/installer.iss').read_text()
        self.assertIn('(CurUninstallStep = usUninstall) and not UninstallSilent', script)
        self.assertIn("'--uninstall-data'", script)
        self.assertIn('ewWaitUntilTerminated, ResultCode', script)
        self.assertIn('MB_YESNOCANCEL or MB_DEFBUTTON2', script)
        self.assertIn('if Choice = IDCANCEL then\n      Abort;', script)
        self.assertLess(script.index('if Choice = IDYES then'), script.index("'--uninstall-data'"))
        self.assertIn('if ResultCode <> 0 then\n        Abort;', script)


if __name__ == '__main__':
    unittest.main()
