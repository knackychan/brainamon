"""Every Brainamon logo and icon file, built from the embedded editable vector geometry:
  Kit-1  the wordmark: monoline strokes, "Braina" in navy, "mon" in orange, a diamond dot on the i
  Standalone-icon-day-rounded-green-yellow-spark (design/logo/logo-brainamon-green-01.png) is THE app icon:
         a green tile with a cream "B" and a yellow diamond (the dot) beside it, at every size
  Kit-6  the wordmark in day mode (cream and yellow on green), kept in the kit only
  Standalone-*  the hero tile for web / desktop / PWA, the Android adaptive foreground (the hero
         composition at 0.274 on 108 dp) and the wordmark with its clear space
The geometry below is copied from those files. Every icon keeps the diamond. What this adds
for sizes the kit does not draw: 16 and 32 px tiles hinted to the pixel grid (stroke 2 and 4 px, every
vertical and horizontal edge on a whole pixel, the diamond on whole pixels too), full-bleed versions for masks (PWA maskable, Android
round, iOS) and a single-colour mark for Android's themed icons.

Run on Windows (renders through Microsoft Edge with playwright): py scripts/build_brand.py
  web/public/brand/          icon.svg (favicon, scalable), icon-hero.svg, icon-maskable.svg, wordmark.svg,
                             wordmark-reverse.svg, icon-32.png (tray), icon-192/512.png, icon-maskable-192/512.png,
                             apple-touch-icon.png
  web/public/favicon.ico     16 / 32 / 48
  packaging/brainamon.ico    the exe, the installer and the shortcuts: 16 to 256
  mobile-shell/android/app/src/main/res/   launcher icons (legacy, round, adaptive, monochrome), splash screens
Then rebuild web/dist and run mobile-shell `npm run sync`.
"""
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'web' / 'public' / 'brand'
RES = ROOT / 'mobile-shell' / 'android' / 'app' / 'src' / 'main' / 'res'
SPLASH_SIZES = {
    'drawable-land-hdpi': (800, 480),
    'drawable-land-mdpi': (480, 320),
    'drawable-land-xhdpi': (1280, 720),
    'drawable-land-xxhdpi': (1600, 960),
    'drawable-land-xxxhdpi': (1920, 1280),
    'drawable-port-hdpi': (480, 800),
    'drawable-port-mdpi': (320, 480),
    'drawable-port-xhdpi': (720, 1280),
    'drawable-port-xxhdpi': (960, 1600),
    'drawable-port-xxxhdpi': (1280, 1920),
    'drawable': (480, 320),
}

NAVY, CREAM, ORANGE = '#123456', '#EDE6D6', '#E8542F'     # the wordmark
GREEN, YELLOW = '#1F7A68', '#FFD23F'                      # the icon: green tile, yellow diamond (logo-brainamon-green-01.png)
PAPER = '#E2DFD6'                 # the app's page colour (v6 tokens): the Android splash blends into the page
SVG = 'xmlns="http://www.w3.org/2000/svg"'
STROKE = 'fill="none" stroke-width="16" stroke-linecap="butt" stroke-linejoin="miter"'

# Kit-1, on a 16-unit stroke. The B is 48 x 80 units.
B = 'M8 0V80 M8 8H26L36 18V30L26 40H8 M8 40H30L40 50V62L30 72H8'
BRAINA = (B + ' M64 24V80 M64 48L80 32H92 M118 32H132L142 42V62L132 72H118L108 62V42Z M142 24V80 M166 24V80'
          ' M190 24V80 M190 44L202 32H212L222 42V80 M256 32H270L280 42V62L270 72H256L246 62V42Z M280 24V80')
DOT = 'M166 -2L176 8L166 18L156 8Z'
MON = ('M304 24V80 M304 44L316 32H324L334 42V80 M334 44L346 32H354L364 42V80'
       ' M398 32H412L422 42V62L412 72H398L388 62V42Z M446 24V80 M446 44L458 32H468L478 42V80')
WORD_BOX = (-8, -10, 502, 100)    # the ink (0 -2 486 82) plus the standalone file's clear space

# Kit-5, on a 256 tile with 56 corners
HERO_B, HERO_DIAMOND = (54, 40, 2.2), 'M186 184L202 200L186 216L170 200Z'
ADAPTIVE = 0.274                  # Standalone Android foreground: the hero composition, scaled about the centre
MASK = ADAPTIVE * 256 / 108       # the same proportion on a full-bleed 256 square (PWA maskable, Android round)


def wordmark(ink: str, accent: str) -> str:
    x, y, w, h = WORD_BOX
    return (f'<svg {SVG} viewBox="{x} {y} {w} {h}" role="img" aria-label="Brainamon"><title>Brainamon</title>'
            f'<g {STROKE}><path stroke="{ink}" d="{BRAINA}"/><path stroke="{accent}" d="{MON}"/></g>'
            f'<path fill="{ink}" d="{DOT}"/></svg>\n')


def _b(x: float, y: float, s: float, colour: str = CREAM) -> str:
    return f'<path transform="translate({x:g} {y:g}) scale({s:g})" {STROKE} stroke="{colour}" d="{B}"/>'


def tile(b=HERO_B, radius=56, diamond=True, label='Brainamon') -> str:
    return (f'<svg {SVG} viewBox="0 0 256 256" role="img" aria-label="{label}"><title>{label}</title>'
            f'<rect width="256" height="256" rx="{radius}" fill="{GREEN}"/>{_b(*b)}'
            + (f'<path fill="{YELLOW}" d="{HERO_DIAMOND}"/>' if diamond else '') + '</svg>\n')


HERO = tile()  # = Standalone-icon-day-rounded-green-yellow-spark


def hero(scale: float, ink: str = CREAM, spark: str = YELLOW) -> str:
    """The hero composition (B and diamond) scaled about the centre of its 256 tile."""
    return (f'<g transform="translate(128 128) scale({scale:.4f}) translate(-128 -128)">{_b(*HERO_B, ink)}'
            f'<path fill="{spark}" d="{HERO_DIAMOND}"/></g>')


def full_bleed(shape: str) -> str:
    """Green square or circle with the hero inside the mask's safe circle (radius 40 %: the farthest ink is at 29 %)."""
    back = (f'<rect width="256" height="256" fill="{GREEN}"/>' if shape == 'square'
            else f'<circle cx="128" cy="128" r="128" fill="{GREEN}"/>')
    return f'<svg {SVG} viewBox="0 0 256 256" role="img" aria-label="Brainamon"><title>Brainamon</title>{back}{hero(MASK)}</svg>\n'


# Hinted tiles: drawn on their own pixel grid. The B is 7 x 12 px (stroke 2) at 16 and 14 x 24 px (stroke 4)
# at 32, the kit's proportions (bars at the top, middle and bottom, the upper bowl one stroke narrower).
HINT16 = (f'<svg {SVG} viewBox="0 0 16 16"><rect width="16" height="16" rx="3.5" fill="{GREEN}"/>'
          f'<path fill="none" stroke="{CREAM}" stroke-width="2" stroke-linecap="butt" stroke-linejoin="miter" '
          f'd="M4 2V14 M4 3H6.5L8 4.5V6.5L6.5 8H4 M4 8H7.5L9 9.5V11.5L7.5 13H4"/>'
          f'<path fill="{YELLOW}" d="M13 10L15 12L13 14L11 12Z"/></svg>')
HINT32 = (f'<svg {SVG} viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="{GREEN}"/>'
          f'<path fill="none" stroke="{CREAM}" stroke-width="4" stroke-linecap="butt" stroke-linejoin="miter" '
          f'd="M7 4V28 M7 6H13L16 9V13L13 16H7 M7 16H14L17 19V23L14 26H7"/>'
          f'<path fill="{YELLOW}" d="M25 20L29 24L25 28L21 24Z"/></svg>')


def adaptive(ink: str = CREAM, spark: str = YELLOW) -> str:
    """Android adaptive foreground, 108 dp (the standalone file): the farthest ink is 31.5 dp from the
    centre, inside the 33 dp safe circle."""
    return f'<svg {SVG} viewBox="0 0 108 108"><g transform="translate(-74 -74)">{hero(ADAPTIVE, ink, spark)}</g></svg>'


class Renderer:
    """SVG -> RGBA image at an exact pixel size, drawn by Edge (the same engine as the app's window)."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel='msedge')
            self._page = self._browser.new_page(device_scale_factor=1)
        except BaseException:
            self._pw.stop()
            raise
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def __call__(self, svg: str, w: int, h: int | None = None) -> Image.Image:
        h = h or w
        svg = svg.replace('<svg ', f'<svg width="{w}" height="{h}" ', 1)
        self._page.set_viewport_size({'width': w, 'height': h})
        self._page.set_content(f'<html><body style="margin:0;background:transparent">{svg}</body></html>')
        return Image.open(io.BytesIO(self._page.screenshot(omit_background=True))).convert('RGBA')


def save_ico(path: Path, images: list[Image.Image]) -> None:
    images = sorted(images, key=lambda im: im.width, reverse=True)
    images[0].save(path, format='ICO', sizes=[im.size for im in images], append_images=images[1:])


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def android(render: Renderer) -> None:
    for name, k in {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}.items():
        d = RES / f'mipmap-{name}'
        d.mkdir(parents=True, exist_ok=True)
        n, f = round(48 * k), round(108 * k)
        render(HERO, n).save(d / 'ic_launcher.png')
        render(full_bleed('circle'), n).save(d / 'ic_launcher_round.png')
        render(adaptive(), f).save(d / 'ic_launcher_foreground.png')
        render(adaptive('#FFFFFF', '#FFFFFF'), f).save(d / 'ic_launcher_monochrome.png')   # themed icons use its alpha
    for icon in ('ic_launcher', 'ic_launcher_round'):
        write(RES / 'mipmap-anydpi-v26' / f'{icon}.xml',
              '<?xml version="1.0" encoding="utf-8"?>\n'
              '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
              '    <background android:drawable="@color/ic_launcher_background"/>\n'
              '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
              '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome"/>\n'
              '</adaptive-icon>\n')
    write(RES / 'values' / 'ic_launcher_background.xml',
          '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
          f'    <color name="ic_launcher_background">{GREEN}</color>\n</resources>\n')
    for folder, (w, h) in SPLASH_SIZES.items():
        p = RES / folder / 'splash.png'
        p.parent.mkdir(parents=True, exist_ok=True)
        splash = Image.new('RGBA', (w, h), PAPER)
        t = round(min(w, h) * 0.24)
        splash.alpha_composite(render(HERO, t), ((w - t) // 2, (h - t) // 2))
        splash.convert('RGB').save(p)


def main() -> None:
    (ROOT / 'packaging').mkdir(parents=True, exist_ok=True)
    write(BRAND / 'icon.svg', tile())
    write(BRAND / 'icon-hero.svg', HERO)
    write(BRAND / 'icon-maskable.svg', full_bleed('square'))
    write(BRAND / 'wordmark.svg', wordmark(NAVY, ORANGE))
    write(BRAND / 'wordmark-reverse.svg', wordmark(CREAM, ORANGE))
    with Renderer() as render:
        h16, h32 = render(HINT16, 16), render(HINT32, 32)
        h32.save(BRAND / 'icon-32.png')
        for n in (192, 512):
            render(HERO, n).save(BRAND / f'icon-{n}.png')
            render(full_bleed('square'), n).save(BRAND / f'icon-maskable-{n}.png')
        render(tile(radius=0), 180).convert('RGB').save(BRAND / 'apple-touch-icon.png')   # iOS rounds it itself
        save_ico(ROOT / 'web' / 'public' / 'favicon.ico', [h16, h32, render(tile(), 48)])
        save_ico(ROOT / 'packaging' / 'brainamon.ico',
                 [h16, h32, *(render(tile(), n) for n in (20, 24, 40, 48, 64, 128)), render(HERO, 256)])
        android(render)
    print('logo files ready')


if __name__ == '__main__':
    main()
