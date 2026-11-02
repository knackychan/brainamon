"""The logo files (scripts/build_brand.py) are where the app, the installer
and the Android app look for them, at the sizes each needs."""
import json
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'web' / 'public'
RES = ROOT / 'mobile-shell' / 'android' / 'app' / 'src' / 'main' / 'res'


class BrandAssetsTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('playwright'), 'requires test-only Playwright')
    def test_failed_renderer_start_stops_the_driver_and_event_loop(self):
        spec = importlib.util.spec_from_file_location('failed_brand_renderer', ROOT / 'scripts/build_brand.py')
        brand = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(brand)
        driver = mock.Mock()
        driver.chromium.launch.side_effect = RuntimeError('Synthetic unavailable browser')
        with mock.patch('playwright.sync_api.sync_playwright') as playwright:
            playwright.return_value.start.return_value = driver
            with self.assertRaisesRegex(RuntimeError, 'Synthetic unavailable browser'):
                with brand.Renderer():
                    self.fail('A failed browser cannot render')
        driver.stop.assert_called_once_with()

    @unittest.skipUnless(sys.platform == 'win32' and importlib.util.find_spec('playwright'),
                         'logo rasterization requires Windows, Playwright and Edge')
    def test_logo_generator_matches_shipped_pixels_and_vectors(self):
        spec = importlib.util.spec_from_file_location('public_brand_parity', ROOT / 'scripts/build_brand.py')
        brand = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(brand)
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(brand, 'ROOT', Path(td)), \
                mock.patch.object(brand, 'BRAND', Path(td) / 'web/public/brand'), \
                mock.patch.object(brand, 'RES', Path(td) / 'mobile-shell/android/app/src/main/res'):
            brand.main()
            for path in Path(td).rglob('*'):
                if not path.is_file():
                    continue
                relative = path.relative_to(td)
                shipped = ROOT / relative
                with self.subTest(asset=relative.as_posix()):
                    if path.suffix in ('.png', '.ico'):
                        with Image.open(path) as actual, Image.open(shipped) as expected:
                            if path.suffix == '.ico':
                                self.assertEqual(actual.ico.sizes(), expected.ico.sizes())
                                for size in actual.ico.sizes():
                                    self.assertEqual(actual.ico.getimage(size).convert('RGBA').tobytes(),
                                                     expected.ico.getimage(size).convert('RGBA').tobytes())
                            else:
                                self.assertEqual(actual.size, expected.size)
                                self.assertEqual(actual.convert('RGBA').tobytes(), expected.convert('RGBA').tobytes())
                    else:
                        self.assertEqual(path.read_text(encoding='utf-8'), shipped.read_text(encoding='utf-8'))

    def test_logo_generator_builds_missing_outputs_without_existing_splash_images(self):
        spec = importlib.util.spec_from_file_location('public_brand_generator', ROOT / 'scripts/build_brand.py')
        brand = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(brand)
        # Exercise fresh-output paths cheaply; real Edge rasterization is a separate parity check.
        def render(svg, width, height=None):
            return Image.new('RGBA', (width, height or width), '#1f7a68')
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(brand, 'ROOT', Path(td)), \
                mock.patch.object(brand, 'BRAND', Path(td) / 'web/public/brand'), \
                mock.patch.object(brand, 'RES', Path(td) / 'res'), \
                mock.patch.object(brand, 'Renderer') as renderer:
            renderer.return_value.__enter__.return_value = render
            brand.main()
            actual = {p.parent.name for p in brand.RES.glob('drawable*/splash.png')}
            self.assertEqual(actual, set(brand.SPLASH_SIZES))
            for folder, expected in brand.SPLASH_SIZES.items():
                with Image.open(brand.RES / folder / 'splash.png') as generated, \
                        Image.open(RES / folder / 'splash.png') as shipped:
                    self.assertEqual(generated.size, shipped.size)
                    self.assertEqual(generated.size, tuple(expected))
            self.assertTrue((Path(td) / 'packaging/brainamon.ico').is_file())
            self.assertTrue((brand.RES / 'mipmap-xxxhdpi/ic_launcher.png').is_file())

    def test_styles_rebuild_without_private_template_and_check_staleness(self):
        spec = importlib.util.spec_from_file_location('public_style_generator', ROOT / 'web/scripts/extract_v6_css.py')
        css = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(css)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(css, 'OUT', Path(td) / 'styles'):
            css.main([])
            css.main(['--check'])
            for name in ('v6-page.css', 'v6-cards-theme.css'):
                self.assertEqual((css.OUT / name).read_text(), (PUBLIC / 'styles' / name).read_text())
            (css.OUT / 'v6-page.css').write_text('stale')
            with self.assertRaisesRegex(SystemExit, 'stale'):
                css.main(['--check'])

    def test_pages_and_manifest_name_existing_files(self):
        manifest = json.loads((PUBLIC / 'manifest.webmanifest').read_text(encoding='utf-8'))
        refs = [i['src'] for i in manifest['icons']]
        self.assertEqual({i['purpose'] for i in manifest['icons']}, {'any', 'maskable'})
        for page in ('index.html', 'mobile.html'):
            refs += re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', (ROOT / 'web' / page).read_text(encoding='utf-8'))
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertTrue((PUBLIC / ref.lstrip('/')).is_file())
        for icon in manifest['icons']:
            if icon['sizes'] != 'any':
                with Image.open(PUBLIC / icon['src'].lstrip('/')) as im:
                    self.assertEqual(f'{im.width}x{im.height}', icon['sizes'])

    def test_windows_icons_carry_every_size(self):
        for path, sizes in ((ROOT / 'packaging' / 'brainamon.ico', {16, 20, 24, 32, 40, 48, 64, 128, 256}),
                            (PUBLIC / 'favicon.ico', {16, 32, 48})):
            with self.subTest(path=path.name), Image.open(path) as ico:
                self.assertEqual({w for w, _ in ico.info['sizes']}, sizes)
        self.assertIn("icon=str(ROOT / 'packaging' / 'brainamon.ico')", (ROOT / 'packaging' / 'brainamon.spec').read_text(encoding='utf-8'))
        self.assertIn('SetupIconFile=brainamon.ico', (ROOT / 'packaging' / 'installer.iss').read_text(encoding='utf-8'))

    def test_hinted_small_icons_sit_on_whole_pixels(self):
        with Image.open(ROOT / 'packaging' / 'brainamon.ico') as ico:
            ico.size = (16, 16)
            im = ico.convert('RGBA')
        stem = [im.getpixel((x, 8))[:3] for x in (3, 4)]
        self.assertEqual(stem, [(0xED, 0xE6, 0xD6)] * 2)        # the B's stem: two full cream pixels
        self.assertEqual(im.getpixel((2, 8))[:3], (0x1F, 0x7A, 0x68))        # the green tile
        self.assertEqual(im.getpixel((13, 12))[:3], (0xFF, 0xD2, 0x3F))        # the yellow diamond

    def test_android_launcher_icons(self):
        for name, k in {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}.items():
            for icon, dp in (('ic_launcher', 48), ('ic_launcher_round', 48), ('ic_launcher_foreground', 108),
                             ('ic_launcher_monochrome', 108)):
                with self.subTest(density=name, icon=icon), Image.open(RES / f'mipmap-{name}' / f'{icon}.png') as im:
                    self.assertEqual(im.size, (round(dp * k),) * 2)
        for xml in ('ic_launcher.xml', 'ic_launcher_round.xml'):
            self.assertIn('@mipmap/ic_launcher_monochrome', (RES / 'mipmap-anydpi-v26' / xml).read_text(encoding='utf-8'))

    def test_no_wiskit_app_icons_remain(self):
        self.assertFalse((PUBLIC / 'wiskit' / 'icon-192.png').exists())
        self.assertFalse((PUBLIC / 'wiskit' / 'icon-512.png').exists())


if __name__ == '__main__':
    unittest.main()
