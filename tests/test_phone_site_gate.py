"""Phone site reader, build gate (projects/phone-site-reader/plans/01-engine.md): the reader's code lives
only in the Contributor (debug) build. The plugin finds it by name; the main source set, the main manifest
and a release bundle carry none of it (packaging/payload_guard.py --release-mobile, which
mobile-shell/scripts/release.py runs on the AAB and the APK). The bundles here are small fakes."""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'mobile-shell' / 'android' / 'app' / 'src'
JAVA = Path('java') / 'app' / 'brainamon' / 'mobile'
READER = ('SiteActivity.java', 'SiteReader.java', 'SiteConfig.java', 'SiteRunFile.java')

_spec = importlib.util.spec_from_file_location('payload_guard_sites', ROOT / 'packaging' / 'payload_guard.py')
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class SiteReaderLayoutTest(unittest.TestCase):
    def test_reader_classes_only_in_debug(self):
        for name in READER:
            self.assertTrue((SRC / 'debug' / JAVA / name).is_file(), name)
            self.assertFalse((SRC / 'main' / JAVA / name).exists(), name)
        self.assertTrue((SRC / 'main' / JAVA / 'SiteBridge.java').is_file())

    def test_manifests(self):
        self.assertNotIn('SiteActivity', text(SRC / 'main' / 'AndroidManifest.xml'))
        debug = text(SRC / 'debug' / 'AndroidManifest.xml')
        self.assertIn('android:name=".SiteActivity"', debug)
        self.assertIn('android:exported="false"', debug)

    def test_plugin_finds_the_reader_by_name_only(self):
        plugin = text(SRC / 'main' / JAVA / 'BrainamonPlugin.java')
        self.assertIn('Class.forName("app.brainamon.mobile.SiteReader")', plugin)
        for absent in ('SiteActivity', 'new SiteReader', 'SiteConfig', 'SiteRunFile'):
            self.assertFalse(absent in plugin, absent)

    def test_no_javascript_interface(self):
        for folder in (SRC / 'main' / JAVA, SRC / 'debug' / JAVA):
            for java in folder.glob('*.java'):
                self.assertFalse('addJavascriptInterface' in text(java), java.name)

    def test_build_wiring(self):
        self.assertIn('debugImplementation "androidx.webkit:webkit:$androidxWebkitVersion"',
                      text(ROOT / 'mobile-shell' / 'android' / 'app' / 'build.gradle'))
        self.assertIn("'../android/app/src/debug/assets/sites/'", text(ROOT / 'mobile-shell' / 'scripts' / 'www.mjs'))
        self.assertIn('app/src/debug/assets/sites', text(ROOT / 'mobile-shell' / 'android' / '.gitignore'))
        self.assertIn("'--release-mobile'", text(ROOT / 'mobile-shell' / 'scripts' / 'release.py'))


class ReleaseGateTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='site-gate-test-')
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)

    def bundle(self, name: str, files: dict) -> Path:
        path = self.dir / name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for entry, data in files.items():
                z.writestr(entry, data)
        return path

    def cli(self, path: Path, *flags: str) -> int:
        return subprocess.run([sys.executable, str(ROOT / 'packaging' / 'payload_guard.py'), str(path), *flags],
                              capture_output=True, text=True).returncode

    def test_reader_parts_are_found(self):
        # a release dex keeps SiteBridge and the reader's name as a plain string: both are allowed
        clean_dex = b'dex\n035\x00Lapp/brainamon/mobile/BrainamonPlugin;\x00app.brainamon.mobile.SiteReader\x00Lapp/brainamon/mobile/SiteBridge;'
        page = b'<!doctype html><title>Brainamon</title>'
        apk = self.bundle('asset.apk', {'classes.dex': clean_dex, 'assets/public/mobile.html': page,
                                        'assets/sites/facebook.js': b'var SITE = {}'})
        aab = self.bundle('activity.aab', {'base/dex/classes.dex': clean_dex,
                                           'base/dex/classes2.dex': b'dex\x00Lapp/brainamon/mobile/SiteActivity;'})
        dex = self.bundle('reader.apk', {'classes3.dex': b'dex\x00Lapp/brainamon/mobile/SiteReader;'})
        clean = self.bundle('clean.apk', {'classes.dex': clean_dex, 'assets/public/mobile.html': page})
        self.assertEqual(guard.site_reader_parts(apk), ['assets/sites/facebook.js'])
        self.assertEqual(guard.site_reader_parts(aab), ['base/dex/classes2.dex'])
        self.assertEqual(guard.site_reader_parts(dex), ['classes3.dex'])
        self.assertEqual(guard.site_reader_parts(clean), [])
        for bad in (apk, aab, dex):
            self.assertEqual(self.cli(bad, '--release-mobile'), 1, bad.name)
        self.assertEqual(self.cli(clean, '--release-mobile'), 0)
        self.assertEqual(self.cli(apk), 0)        # without the flag (the debug APK in CI) the reader is allowed


if __name__ == '__main__':
    unittest.main()
