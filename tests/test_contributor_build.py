"""Contributor identity, credentials and official update isolation; synthetic inputs only."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from core import app_paths, build_channel, config, uninstall
from desktop import updater

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('contributor_build_script', ROOT / 'packaging/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ContributorBuildTest(unittest.TestCase):
    def test_ci_binary_upload_requires_separate_distribution_clearance(self):
        workflow = (ROOT / '.github/workflows/android.yml').read_text(encoding='utf-8')
        upload = workflow.split('- uses: actions/upload-artifact@')
        self.assertEqual(len(upload), 2, 'Review every APK upload path')
        step = upload[1].split('\n      - ', 1)[0]
        self.assertIn("if: ${{ vars.ANDROID_BINARY_DISTRIBUTION_CLEARED == 'true' }}", step)
        self.assertIn('packaging/payload_guard.py', upload[0])

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='contributor-build-test-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_unknown_and_malformed_channels_do_not_become_official(self):
        self.assertEqual(build_channel.read(self.root), 'unverified')
        for value in ('broken', '{}', '[]', '{"channel":"source"}', '{"channel":"official","extra":true}'):
            (self.root / build_channel.FILENAME).write_text(value)
            with self.assertRaises(ValueError):
                build_channel.read(self.root)

    def test_frozen_contributor_does_not_discover_official_homes_windows_or_autostart(self):
        bundle = self.root / 'bundle'
        bundle.mkdir()
        local = self.root / 'profile'
        for name in ('Brainamon', 'Content Manager'):
            home = local / name
            home.mkdir(parents=True)
            (home / 'valuable.txt').write_text('keep official profile')
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in
               ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'BRAINAMON_', 'CM_DATA_DIR', 'CM_PORT'))}
        env.update(LOCALAPPDATA=str(local), APPDATA=str(local), TEMP=str(self.root), TMP=str(self.root))
        script = '''import json,sys
sys.frozen=True; sys._MEIPASS=sys.argv[1]
from core import app_paths as p
from desktop import autostart,sleep,panel_ghost
from server import settings
print(json.dumps([str(p.HOME),str(p.data_dir()),p.BUILD_CHANNEL,settings.PORT,autostart.VALUE,autostart.OLD_VALUES,sleep.WINDOW_TITLE,panel_ghost.PANEL_TITLE]))
'''
        for channel in ('contributor', None):
            marker = bundle / build_channel.FILENAME
            if channel:
                marker.write_text(json.dumps({'channel': channel}))
            else:
                marker.unlink()
            result = subprocess.run([sys.executable, '-c', script, str(bundle)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, check=True)
            home, data, actual, port, autostart, old, window, panel = json.loads(result.stdout)
            expected = 'contributor' if channel else 'unverified'
            self.assertEqual(Path(home), local / build_channel.HOME_NAMES[expected])
            self.assertEqual(Path(data), Path(home) / 'data')
            self.assertEqual(actual, expected)
            self.assertNotEqual(port, 18765)
            self.assertEqual(autostart, build_channel.DISPLAY_NAMES[expected])
            self.assertEqual(old, [])
            self.assertNotEqual(window, 'Brainamon')
            self.assertNotEqual(panel, 'Brainamon Drop')
        for name in ('Brainamon', 'Content Manager'):
            self.assertEqual((local / name / 'valuable.txt').read_text(), 'keep official profile')

    def test_contributor_oauth_ignores_ambient_registration_and_project_env(self):
        with mock.patch.object(build, 'ROOT', self.root), \
                mock.patch.object(config, 'read_env_file', side_effect=AssertionError('must not read project env')) as read, \
                mock.patch.dict(os.environ, {key: 'synthetic-owner-registration' for key in build.OAUTH_KEYS}):
            build.write_google_oauth(contributor=True)
            output = self.root / 'build/google-oauth.json'
            self.assertEqual(json.loads(output.read_text()), {})
            own = {key: 'synthetic-contributor-registration' for key in build.OAUTH_KEYS}
            path = self.root / 'own-oauth.json'
            path.write_text(json.dumps(own))
            build.write_google_oauth(True, path)
            self.assertEqual(json.loads(output.read_text()), own)
            path.write_text(json.dumps({**own, 'OPENAI_API_KEY': 'not-an-app-registration'}))
            with self.assertRaises(SystemExit):
                build.write_google_oauth(True, path)
            self.assertEqual(json.loads(output.read_text()), own)
            read.assert_not_called()

    def test_contributor_build_environment_is_disposable_and_restored(self):
        with mock.patch.dict(os.environ, {'SIGN_PFX': 'synthetic-owner-key', 'OPENAI_API_KEY': 'synthetic-owner-key',
                                         'BRAINAMON_HOME': 'synthetic-owner-home'}):
            before = dict(os.environ)
            with build.build_environment(True):
                self.assertNotIn('SIGN_PFX', os.environ)
                self.assertNotIn('OPENAI_API_KEY', os.environ)
                home = Path(os.environ['BRAINAMON_HOME'])
                self.assertTrue(home.is_dir())
                self.assertNotEqual(str(home), 'synthetic-owner-home')
            self.assertEqual(dict(os.environ), before)
            self.assertFalse(home.exists())

    def test_official_flags_are_rejected_before_keys_or_builds_are_touched(self):
        for flag in ('--release', '--sign'):
            with mock.patch.object(sys, 'argv', ['build.py', '--contributor', flag]), \
                    mock.patch.object(build, 'run') as run, \
                    mock.patch.object(build, 'cert_args') as certificates, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    build.main()
                run.assert_not_called()
                certificates.assert_not_called()

    def test_pipeline_has_separate_output_and_never_calls_official_signers(self):
        (self.root / 'core').mkdir()
        (self.root / 'core/version.py').write_text("__version__ = '9.9.9'")
        (self.root / 'web/dist').mkdir(parents=True)
        (self.root / 'web/dist/index.html').write_text('synthetic frontend')
        official = self.root / 'dist/Brainamon/keep.txt'
        official.parent.mkdir(parents=True)
        official.write_text('existing official artifact')
        interpreter = self.root / 'python.exe'
        interpreter.touch()
        compiler = self.root / 'iscc.exe'
        commands = []

        def run(command, **kwargs):
            commands.append(list(map(str, command)))
            if command[0] == compiler:
                setup = self.root / 'dist/installer/Brainamon-Contributor-Setup-9.9.9.exe'
                setup.parent.mkdir(parents=True)
                setup.write_bytes(b'synthetic contributor installer')

        args = SimpleNamespace(contributor=True, contributor_oauth=None, release=False, sign=False,
                               installer=True, skip_web=True)
        with mock.patch.object(build, 'ROOT', self.root), mock.patch.object(build, 'PY', interpreter), \
                mock.patch.object(build, 'run', side_effect=run), mock.patch.object(build, 'mcp_smoke', return_value=''), \
                mock.patch.object(build, 'leaked_secrets', return_value=[]), \
                mock.patch.object(build, 'sign') as sign, mock.patch.object(build, 'cert_args') as certificates:
            self.assertEqual(build.build(args, compiler), 0)
        sign.assert_not_called()
        certificates.assert_not_called()
        self.assertFalse(any('update_keys.py' in ' '.join(cmd) for cmd in commands))
        self.assertTrue(any('/DContributor=1' in cmd for cmd in commands))
        self.assertTrue(any('--contributor' in cmd and 'release_check.py' in ' '.join(cmd) for cmd in commands))
        self.assertEqual(official.read_text(), 'existing official artifact')
        self.assertEqual(build_channel.read(self.root / 'build'), 'contributor')

    def test_contributor_uninstall_cannot_enlist_official_settings_or_library(self):
        local = self.root / 'profile'
        own = local / 'Brainamon-Contributor'
        official = local / 'Brainamon'
        for home in (own, official):
            (home / 'data').mkdir(parents=True)
            (home / 'data/content_manager.db').write_text('synthetic library')
        env = {'LOCALAPPDATA': str(local)}
        installation = local / 'Programs/Brainamon-Contributor'
        self.assertEqual(set(uninstall.cleanup_targets(env, installation, 'contributor')), {own, own / 'data'})
        for override in ({'BRAINAMON_HOME': str(official)}, {'CM_DATA_DIR': str(official / 'data')}):
            with self.assertRaises(ValueError):
                uninstall.cleanup_targets({**env, **override}, installation, 'contributor')
        (own / 'location.json').write_text(json.dumps({'data_dir': str(official / 'data')}))
        with self.assertRaises(ValueError):
            uninstall.cleanup_targets(env, installation, 'contributor')
        self.assertTrue((official / 'data/content_manager.db').is_file())

    def test_direct_installer_launch_is_also_disabled_in_contributor_build(self):
        with mock.patch.object(app_paths, 'CONTRIBUTOR', True), \
                mock.patch.object(updater.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, 'Official updates are disabled'):
                updater.launch(self.root / 'Brainamon-Setup-99.0.0.exe')
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
