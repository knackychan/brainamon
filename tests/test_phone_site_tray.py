"""The Android site window's tray (projects/motion-language plan 06): the pure Java part (SiteText.java: plural
rule, label limits, crop of a reported picture, arrival spacing) compiled and run with a plain javac, the runner's
picture rectangles (scrapers/sites/_runner.js `rectsOf`) under Node, the labels the page sends in every language
(web/src/mobile/site-tray.ts) and the wiring of the native files. Made-up data only. The WebView, PixelCopy and the
animations are Android's: Fred checks them on the phone, Gradle only compiles them."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_phone_js

ROOT = Path(__file__).resolve().parent.parent
JAVA = ROOT / 'mobile-shell' / 'android' / 'app' / 'src' / 'main' / 'java' / 'app' / 'brainamon' / 'mobile'

HARNESS = """
package app.brainamon.mobile;

import java.util.HashMap;
import java.util.Map;

public class SiteTextHarness {
    static String j(Object o) { return o == null ? "null" : o.toString(); }
    static String arr(int[] a) { if (a == null) return "null"; StringBuilder b = new StringBuilder("["); for (int i = 0; i < a.length; i++) b.append(i > 0 ? "," : "").append(a[i]); return b.append("]").toString(); }
    public static void main(String[] args) {
        Map<String, String> fr = new HashMap<>();
        fr.put("known_one", "{k} deja");
        fr.put("known_other", "{k} deja (autres)");
        StringBuilder o = new StringBuilder("{");
        o.append("\\"one\\":[").append(SiteText.one("en", 0)).append(',').append(SiteText.one("en", 1)).append(',').append(SiteText.one("en", 2))
         .append(',').append(SiteText.one("fr", 0)).append(',').append(SiteText.one("fr", 1)).append(',').append(SiteText.one("fr", 2))
         .append(',').append(SiteText.one("zh", 1)).append(',').append(SiteText.one(null, 1)).append("],");
        o.append("\\"count\\":[\\"").append(SiteText.count(fr, "fr", "known", "k", 0)).append("\\",\\"").append(SiteText.count(fr, "fr", "known", "k", 5))
         .append("\\",\\"").append(SiteText.count(null, "en", "doneNew", "n", 1)).append("\\",\\"").append(SiteText.count(null, "en", "doneNew", "n", 3)).append("\\"],");
        o.append("\\"label\\":[\\"").append(SiteText.label(null, "cancel")).append("\\",\\"").append(SiteText.label(fr, "cancel")).append("\\",\\"").append(SiteText.label(fr, "nope")).append("\\"],");
        o.append("\\"gap\\":[").append(SiteText.gapMs(0)).append(',').append(SiteText.gapMs(1)).append(',').append(SiteText.gapMs(3)).append(',').append(SiteText.gapMs(4)).append(',').append(SiteText.gapMs(25)).append("],");
        o.append("\\"keys\\":[").append(SiteText.validKey("signIn")).append(',').append(SiteText.validKey("known_one")).append(',').append(SiteText.validKey("1x")).append(',').append(SiteText.validKey("a b"))
         .append(',').append(SiteText.validKey("")).append(',').append(SiteText.validKey("x".repeat(41))).append(',').append(SiteText.validKey(null)).append("],");
        o.append("\\"clean\\":[").append(SiteText.clean("ok") != null).append(',').append(SiteText.clean("") != null).append(',').append(SiteText.clean("x".repeat(200)) != null)
         .append(',').append(SiteText.clean("x".repeat(201)) != null).append(',').append(SiteText.clean("a\\nb") != null).append(',').append(SiteText.clean(null) != null).append("],");
        o.append("\\"crop\\":[").append(arr(SiteText.crop(10, 20, 100, 200, 400, 800, 1600))).append(',').append(arr(SiteText.crop(-50, -50, 100, 100, 400, 800, 1600)))
         .append(',').append(arr(SiteText.crop(380, 790, 100, 100, 400, 800, 1600))).append(',').append(arr(SiteText.crop(0, 0, 3, 3, 400, 800, 1600)))
         .append(',').append(arr(SiteText.crop(Double.NaN, 0, 10, 10, 400, 800, 1600))).append(',').append(arr(SiteText.crop(0, 0, 10, 10, 0, 800, 1600)))
         .append(',').append(arr(SiteText.crop(0, 0, 10, 10, 400, 0, 1600))).append(',').append(arr(SiteText.crop(0, 0, Double.POSITIVE_INFINITY, 10, 400, 800, 1600)))
         .append(',').append(arr(SiteText.crop(900, 0, 100, 100, 400, 800, 1600))).append("],");
        o.append("\\"head\\":[\\"").append(SiteText.headline("\\n  First line\\nsecond", "https://x.test/p", 80)).append("\\",\\"").append(SiteText.headline("", "https://x.test/p/1", 80))
         .append("\\",\\"").append(SiteText.headline("abcdefghij", "", 5)).append("\\",\\"").append(SiteText.headline(null, null, 5)).append("\\"]");
        System.out.println(o.append('}'));
    }
}
"""


def _javac() -> bool:
    return bool(shutil.which('javac') and shutil.which('java'))


@unittest.skipUnless(_javac(), 'needs a JDK (javac and java)')
class SiteTextJavaTest(unittest.TestCase):
    def test_pure_helpers_compile_and_behave(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'src' / 'app' / 'brainamon' / 'mobile'
            src.mkdir(parents=True)
            shutil.copy(JAVA / 'SiteText.java', src / 'SiteText.java')
            (src / 'SiteTextHarness.java').write_text(HARNESS, encoding='utf-8')
            out = Path(tmp) / 'out'
            built = subprocess.run(['javac', '-encoding', 'UTF-8', '-d', str(out), str(src / 'SiteText.java'), str(src / 'SiteTextHarness.java')],
                                   capture_output=True, text=True, encoding='utf-8', timeout=120)
            self.assertEqual(built.returncode, 0, built.stderr[-2000:])
            ran = subprocess.run(['java', '-Dstdout.encoding=UTF-8', '-cp', str(out), 'app.brainamon.mobile.SiteTextHarness'], capture_output=True, text=True,
                                 encoding='utf-8', timeout=60)
            self.assertEqual(ran.returncode, 0, ran.stderr[-2000:])
            r = json.loads(ran.stdout.strip())
        # English: one for exactly 1. French: one for 0 and 1. Chinese: never. No language: English.
        self.assertEqual(r['one'], [False, True, False, True, True, False, False, True])
        self.assertEqual(r['count'], ['0 deja', '5 deja (autres)', 'new post', 'new posts'])
        self.assertEqual(r['label'], ['Cancel', 'Cancel', ''])
        # a batch of k arrives within 1.1 s, 290 ms apart at the most
        self.assertEqual(r['gap'], [290, 290, 290, 275, 44])
        self.assertEqual(r['keys'], [True, True, False, False, False, False, False])
        self.assertEqual(r['clean'], [True, False, True, False, False, False])
        # {left, top, width, height} in snapshot pixels (scale = snapshot width / viewport width = 2), cut to the snapshot;
        # too small, not finite, a bad viewport or off the snapshot: null
        self.assertEqual(r['crop'], [[20, 40, 200, 400], [0, 0, 100, 100], [760, 1580, 40, 20], None, None, None, None, None, None])
        self.assertEqual(r['head'], ['First line', 'x.test', 'abcd…', ''])


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class RunnerRectsTest(unittest.TestCase):
    def test_rects_follow_the_visible_image_of_each_item(self):
        script = r"""
            import fs from 'node:fs'
            import vm from 'node:vm'
            const ctx = vm.createContext({ console })
            vm.runInContext(fs.readFileSync('scrapers/sites/_runner.js', 'utf8'), ctx, { filename: '_runner.js' })
            const img = (src, box, current = '') => ({ src, currentSrc: current, getBoundingClientRect: () => ({ left: box[0], top: box[1], width: box[2], height: box[3], right: box[0] + box[2], bottom: box[1] + box[3] }) })
            const imgs = [img('https://a.test/1.jpg', [10.4, 20.6, 100, 150]), img('', [0, 0, 50, 50], 'https://a.test/2.jpg'),
              img('https://a.test/3.jpg', [0, 2000, 100, 100]), img('https://a.test/4.jpg', [0, 0, 4, 4]), img('https://a.test/5.jpg', [-300, 0, 100, 100]),
              img('https://a.test/6.jpg', [50, 60, 80, 90])]
            const items = ['1', '2', '3', '4', '5', '7', ''].map(n => ({ pic: n && 'https://a.test/' + n + '.jpg' }))
            const bad = { get 0() { throw new Error('boom') }, length: 1 }
            console.log(JSON.stringify({ rects: ctx.rectsOf(items, imgs, 400, 800), guarded: ctx.rectsOf([{ pic: 'x' }], { length: 1, get 0() { throw new Error('boom') } }, 400, 800),
              none: ctx.rectsOf([], imgs, 400, 800) }))
        """
        out = json.loads(test_phone_js.node(script))
        # visible, numbers rounded; currentSrc counts; below the window, tiny, off to the left, unknown and empty pics: null
        self.assertEqual(out['rects'], [[10, 21, 100, 150], [0, 0, 50, 50], None, None, None, None, None])
        self.assertEqual(out['guarded'], [])
        self.assertEqual(out['none'], [])

    def test_a_batch_carries_rects_and_the_window_width_and_the_scroll_waits(self):
        text = (ROOT / 'scrapers' / 'sites' / '_runner.js').read_text(encoding='utf-8')
        self.assertIn("rects: rectsOf(items, document.images, vw, window.innerHeight), vw: vw", text)
        self.assertIn("await sleep(400)", text)
        self.assertIn("await sleep(800 + Math.random() * 600)", text)
        self.assertLess(text.index('await sleep(400)'), text.index('scroll()\n    await sleep(800'))


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class TrayLabelsTest(unittest.TestCase):
    def test_labels_fit_the_native_limits_in_every_language(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + r"""
            import { setup } from './web/src/lib/i18n/index.ts'
            import { messages as fr } from './web/src/lib/i18n/fr/index.ts'
            import { messages as zh } from './web/src/lib/i18n/zh-Hant/index.ts'
            import { trayLabels } from './web/src/mobile/site-tray.ts'
            const out = {}
            for (const lang of ['en', 'fr', 'zh-Hant']) {
              setup({ fr, 'zh-Hant': zh }, lang, [])
              out[lang] = JSON.parse(trayLabels('Instagram'))
              out[lang + '-size'] = trayLabels('Instagram').length
            }
            console.log(JSON.stringify(out))
        """))
        keys = sorted(out['en'])
        for lang in ('fr', 'zh-Hant'):
            self.assertEqual(sorted(out[lang]), keys, lang)
        for lang in ('en', 'fr', 'zh-Hant'):
            labels = out[lang]
            self.assertLess(out[lang + '-size'], 16 * 1024)
            self.assertLessEqual(len(labels), 64)
            for key, value in labels.items():
                self.assertRegex(key, r'^[A-Za-z][A-Za-z0-9_]{0,39}$')
                self.assertIsInstance(value, str)
                self.assertTrue(0 < len(value) <= 200, (lang, key))
                self.assertNotRegex(value, r'[\x00-\x1f]')
        self.assertEqual((out['en']['lang'], out['fr']['lang'], out['zh-Hant']['lang']), ('en', 'fr', 'zh'))
        self.assertEqual(out['en']['signIn'], 'Sign in to Instagram. Reading starts by itself.')
        self.assertEqual((out['en']['doneNew_one'], out['en']['doneNew_other']), ('new post', 'new posts'))
        self.assertEqual(out['en']['known_one'], '{k} already in library')
        self.assertEqual((out['fr']['doneNew_one'], out['fr']['doneNew_other']), ('nouvelle publication', 'nouvelles publications'))
        self.assertIn('{k}', out['fr']['known_other'])
        self.assertEqual(out['zh-Hant']['known_one'], out['zh-Hant']['known_other'])
        self.assertIn('Instagram', out['zh-Hant']['signIn'])


class TrayWiringTest(unittest.TestCase):
    def read(self, name):
        return (JAVA / name).read_text(encoding='utf-8')

    def test_the_activity_uses_the_tray_and_keeps_the_page_size(self):
        activity = self.read('SiteActivity.java')
        self.assertIn('new SiteTray(', activity)
        self.assertIn('page.bottomMargin = dp(SiteTray.collapsedDp())', activity)
        self.assertIn('NATURAL = Arrays.asList("end", "known", "empty", "cap")', activity)
        # stop, failure and unsave-failed close at once; a natural end waits for the button
        self.assertIn('if (tray == null || !reader || !NATURAL.contains(reason))', activity)
        self.assertIn('if (tray != null && tray.ended()) tray.press();', activity)
        self.assertIn('if (finished || ended) return;', activity)
        self.assertNotIn('addJavascriptInterface', activity + self.read('SiteTray.java'))

    def test_the_new_java_files_are_plain_ascii(self):
        # Gradle's source encoding is the platform's: escapes, never a literal character (the other reader files are ASCII too)
        for name in ('SiteText.java', 'SiteTray.java', 'SiteActivity.java'):
            self.assertTrue(self.read(name).isascii(), name)

    def test_the_page_rectangles_are_bounded_before_the_tray_sees_them(self):
        activity, tray = self.read('SiteActivity.java'), self.read('SiteTray.java')
        self.assertIn('rects.length() <= MAX_BATCH', activity)
        self.assertIn('SiteText.crop(', tray)
        self.assertIn('SiteText.validKey(k)', tray)
        self.assertIn('SiteText.clean(', tray)
        self.assertIn('json.length() > SiteText.MAX_LABELS_BYTES', tray)
        self.assertIn('SiteText.MAX_FLIGHTS', tray)
        self.assertIn('Build.VERSION.SDK_INT >= 26', tray)
        self.assertIn('ANIMATOR_DURATION_SCALE', tray)

    def test_the_plugin_passes_only_labels_and_motion_without_naming_reader_classes(self):
        plugin = self.read('BrainamonPlugin.java')
        self.assertIn('call.getString("labels", "")', plugin)
        self.assertIn('labels.length() <= 16 * 1024', plugin)
        self.assertIn('i.putExtra("motion"', plugin)
        self.assertNotIn('SiteTray', plugin)
        self.assertNotIn('SiteActivity', plugin)

    def test_the_page_passes_the_tray_extras_on_both_openings(self):
        native = (ROOT / 'web' / 'src' / 'mobile' / 'native.ts').read_text(encoding='utf-8')
        read = (ROOT / 'web' / 'src' / 'mobile' / 'screens' / 'SiteRead.svelte').read_text(encoding='utf-8')
        self.assertIn('labels?: string; motion?: boolean', native)
        self.assertEqual(read.count('trayFor('), 2)


if __name__ == '__main__':
    unittest.main()
