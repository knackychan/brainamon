"""Phone site reader build wiring and release payload gate; bundles here are small fakes."""
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
    def test_reader_classes_in_both_builds(self):
        for name in READER:
            self.assertTrue((SRC / 'main' / JAVA / name).is_file(), name)
            self.assertFalse((SRC / 'debug' / JAVA / name).exists(), name)
        self.assertTrue((SRC / 'main' / JAVA / 'SiteBridge.java').is_file())

    def test_manifests(self):
        main = text(SRC / 'main' / 'AndroidManifest.xml')
        self.assertIn('android:name=".SiteActivity"', main)
        self.assertIn('android:exported="false"', main)

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
        self.assertIn('implementation "androidx.webkit:webkit:$androidxWebkitVersion"',
                      text(ROOT / 'mobile-shell' / 'android' / 'app' / 'build.gradle'))
        self.assertIn("'../android/app/src/main/assets/sites/'", text(ROOT / 'mobile-shell' / 'scripts' / 'www.mjs'))
        self.assertIn('app/src/main/assets/sites', text(ROOT / 'mobile-shell' / 'android' / '.gitignore'))
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

    def test_reader_parts_required(self):
        base_dex = b'dex\n035\x00Lapp/brainamon/mobile/BrainamonPlugin;\x00app.brainamon.mobile.SiteReader\x00Lapp/brainamon/mobile/SiteBridge;'
        reader_dex = base_dex + b'\x00'.join(guard.SITE_CLASSES)
        page = b'<!doctype html><title>Brainamon</title>'
        scripts = {f'assets/sites/{p.name}': b'var SITE = {}' for p in (ROOT / 'scrapers' / 'sites').glob('*.js')
                   if p.name.islower()}
        complete = self.bundle('complete.apk', {'classes.dex': reader_dex, 'assets/public/mobile.html': page, **scripts})
        missing_script = self.bundle('missing-script.aab', {'base/dex/classes.dex': reader_dex,
                                                              **{k: v for k, v in scripts.items() if not k.endswith('/_runner.js')}})
        missing_class = self.bundle('missing-class.apk', {'classes.dex': base_dex, **scripts})
        self.assertEqual(guard.missing_site_reader_parts(complete), [])
        self.assertIn('_runner.js', guard.missing_site_reader_parts(missing_script))
        self.assertIn('Lapp/brainamon/mobile/SiteReader;', guard.missing_site_reader_parts(missing_class))
        self.assertEqual(self.cli(complete, '--release-mobile'), 0)
        for bad in (missing_script, missing_class):
            self.assertEqual(self.cli(bad, '--release-mobile'), 1, bad.name)
        self.assertEqual(self.cli(missing_class), 0)  # Contributor uses the private-file gate only.


if __name__ == '__main__':
    unittest.main()
