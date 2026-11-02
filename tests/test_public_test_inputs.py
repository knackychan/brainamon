"""The shared browser harness must never fall back to a contributor's real settings."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires test-only Playwright')
class BrowserHarnessTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('public_test_shots', ROOT / 'tests/helpers/shots.py')
        self.shots = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.shots)
        folder = tempfile.TemporaryDirectory(prefix='public-test-inputs-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'),
                                    port=0, root=str(self.root / 'library'),
                                    out=str(self.root / 'shots'), only=None, themes='dark')

    def test_shared_helper_resolves_checkout_and_refuses_unmarked_folder(self):
        self.assertEqual(self.shots.DEFAULT_REPO, ROOT)
        folder = Path(self.args.root)
        folder.mkdir()
        keep = folder / 'keep.txt'
        keep.write_text('unrelated data')
        with self.assertRaisesRegex(SystemExit, 'was not made by this script'):
            self.shots.Run(self.args).go()
        self.assertEqual(keep.read_text(), 'unrelated data')

    def test_marked_checkout_cannot_be_deleted(self):
        folder = self.root / 'pretend-checkout'
        folder.mkdir()
        (folder / self.shots.MARKER).write_text('marker alone is insufficient')
        self.args.repo = self.args.root = str(folder)
        with self.assertRaisesRegex(SystemExit, 'outside the checkout'):
            self.shots.Run(self.args).go()
        self.assertTrue(folder.is_dir())

    def test_child_environment_is_filtered_before_application_imports(self):
        root = Path(self.args.root)
        root.mkdir()
        run = self.shots.Run(self.args)
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic-never-pass',
                                           'BRAINAMON_HOME': 'synthetic-owner-home',
                                           'CM_DATA_DIR': 'synthetic-owner-library',
                                           'SIGN_PFX_PASSWORD': 'synthetic-never-pass'}), \
                mock.patch.object(self.shots.subprocess, 'Popen') as popen, \
                mock.patch.object(self.shots.subprocess, 'run') as token, \
                mock.patch.object(self.shots, 'urlopen'):
            token.return_value.stdout = 'synthetic-fixture-token'
            run.start(root)
        self.addCleanup(run.log.close)
        env = popen.call_args.kwargs['env']
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('SIGN_PFX_PASSWORD', env)
        self.assertEqual(env['BRAINAMON_HOME'], str(root))
        self.assertEqual(env['CM_DATA_DIR'], str(root / 'data'))
        self.assertEqual(env['TEMP'], str(root / 'temp'))
        self.assertEqual(env['LOCALAPPDATA'], str(root / 'profile'))
        self.assertNotIn(run.port, (0, 18765, 5173, 3001))


if __name__ == '__main__':
    unittest.main()
