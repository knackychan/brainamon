"""Android release versioning is independent of the desktop; no SDK or keys needed."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('android_release_version', ROOT / 'mobile-shell/scripts/release.py')
release = importlib.util.module_from_spec(spec)
with mock.patch.dict(os.environ, {'LOCALAPPDATA': tempfile.gettempdir()}):
    spec.loader.exec_module(release)


class AndroidVersionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='android-version-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shell = self.root / 'mobile-shell'
        self.shell.mkdir()
        (self.root / 'core').mkdir()
        self.pc = self.root / 'core/version.py'
        self.pc.write_text("__version__ = '99.98.97'\n", encoding='utf-8')
        for patch in (mock.patch.object(release, 'ROOT', self.root),
                      mock.patch.object(release, 'SHELL', self.shell), mock.patch.dict(os.environ)):
            patch.start()
            self.addCleanup(patch.stop)
        for key in ('BRAINAMON_VERSION_NAME', 'BRAINAMON_VERSION_CODE'):
            os.environ.pop(key, None)
        self.config()

    def config(self, name='137.1.01', code=1001003):
        (self.shell / 'version.json').write_text(json.dumps({'versionName': name, 'versionCode': code}), encoding='utf-8')

    def test_mobile_version_preserves_leading_zero_and_never_changes_or_needs_pc_version(self):
        before = self.pc.read_bytes()
        self.assertEqual(release.version(), ('137.1.01', 1001003))
        self.assertEqual(self.pc.read_bytes(), before)
        self.pc.unlink()
        self.assertEqual(release.version(), ('137.1.01', 1001003))

    def test_name_and_code_environment_overrides_are_independent(self):
        os.environ['BRAINAMON_VERSION_NAME'] = '137.1.02'
        self.assertEqual(release.version(), ('137.1.02', 1001003))
        os.environ['BRAINAMON_VERSION_CODE'] = '1001004'
        self.assertEqual(release.version(), ('137.1.02', 1001004))
        os.environ.pop('BRAINAMON_VERSION_NAME')
        self.assertEqual(release.version(), ('137.1.01', 1001004))
        os.environ.update(BRAINAMON_VERSION_NAME='', BRAINAMON_VERSION_CODE='')
        self.assertEqual(release.version(), ('137.1.01', 1001003))

    def test_blank_nonstring_and_unsafe_version_names_are_rejected(self):
        for name in ('', ' ', '\t', '../137.1.01', '137/1.01', '137 1.01', None, 137):
            with self.subTest(name=name):
                self.config(name=name)
                with self.assertRaises(ValueError):
                    release.version()
        self.config()
        os.environ['BRAINAMON_VERSION_NAME'] = ' '
        with self.assertRaises(ValueError):
            release.version()

    def test_android_code_rejects_booleans_floats_nonintegers_and_out_of_range_values(self):
        for code in (True, False, 1.0, None, '1.5', 'true', '١٢', 0, -1, 2100000001):
            with self.subTest(code=code):
                self.config(code=code)
                with self.assertRaises(ValueError):
                    release.version()
        self.config()
        for code in (' ', '1.5', '-1', '0', '2100000001'):
            with self.subTest(override=code):
                os.environ['BRAINAMON_VERSION_CODE'] = code
                with self.assertRaises(ValueError):
                    release.version()

    def test_android_code_bounds_are_accepted(self):
        for code in (1, 2100000000):
            with self.subTest(code=code):
                self.config(code=code)
                self.assertEqual(release.version(), ('137.1.01', code))


if __name__ == '__main__':
    unittest.main()
