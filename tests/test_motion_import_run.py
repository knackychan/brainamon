"""The phone's import run (projects/motion-language plan 07): the pure rules of web/src/mobile/import-run.ts under
Node (the sub line, the picture grid's squares, when the pictures are finished, the reasons in three languages),
the arrival record Open in Library writes (arrival.svelte.ts, read by plan 08), and the wiring of ImportRun.svelte
into SiteRead.svelte. Made-up data only."""
import json
import re
import unittest
from pathlib import Path

from tests import test_phone_js

ROOT = Path(__file__).resolve().parent.parent
MOBILE = ROOT / 'web' / 'src' / 'mobile'

SCRIPT = test_phone_js.TS_RESOLVE + r"""
    globalThis.$state = x => x
    const { setup, t } = await import('./web/src/lib/i18n/index.ts')
    const { messages: fr } = await import('./web/src/lib/i18n/fr/index.ts')
    const { messages: zh } = await import('./web/src/lib/i18n/zh-Hant/index.ts')
    const run = await import('./web/src/mobile/import-run.ts')
    const arrival = await import('./web/src/mobile/arrival.svelte.ts')
    const out = {}
    const ids = Array.from({ length: 30 }, (_, i) => 100 + i)
    const has = new Set([100, 101, 129]), running = new Set([102, 103])
    out.squares = run.squares(ids, id => has.has(id), id => running.has(id)).map(x => x[0]).join('')
    out.squareCount = run.squares(ids, () => false, () => false).length
    out.got = run.gotCount(ids, id => has.has(id))
    out.finished = [
      run.picsFinished(ids, id => has.has(id), false, 'idle'), run.picsFinished(ids, id => has.has(id), true, 'run'),
      run.picsFinished(ids, id => has.has(id), true, 'wait'), run.picsFinished(ids, id => has.has(id), true, 'idle'),
      run.picsFinished(ids, () => true, true, 'run'), run.picsFinished([], () => false, true, 'run'), run.picsFinished([], () => false, false, 'run'),
    ]
    out.lang = {}
    for (const lang of ['en', 'fr', 'zh-Hant']) {
      setup({ fr, 'zh-Hant': zh }, lang, [])
      out.lang[lang] = {
        sub: [run.readySub(run.reasonText({ reason: 'end' }, t), 3, 2, t), run.readySub(run.reasonText({ reason: 'known' }, t), 0, 0, t),
          run.readySub(run.reasonText(null, t), 1, 0, t), run.readySub('', 0, 1, t)],
        ready: [t('importrun.ready', { n: 1 }), t('importrun.ready', { n: 0 }), t('importrun.ready', { n: 2 })],
        button: [t('importrun.import', { n: 1 }), t('importrun.import', { n: 2 })],
        finish: [t('importrun.finish', { n: 1 }), t('importrun.finish', { n: 24 })],
        were: [1, 0, 5].map(k => t('importrun.wereThere', { n: k, k })),
        toast: [1, 2].map(n => t('importrun.toast', { n, site: 'Instagram' })),
        added: t('importrun.added', { added: 3, n: 5 }), picsOf: t('importrun.picsOf', { pics: 2, n: 9 }), some: t('importrun.picsSome', { got: 4, n: 9 }),
        reasons: ['end', 'known', 'stop', 'cap', 'empty', 'failure', 'unsave-failed', 'nothing-known'].map(r => run.reasonText({ reason: r }, t)),
        failedNote: run.reasonText({ reason: 'end', unsaveFailed: true }, t),
      }
    }
    setup({ fr, 'zh-Hant': zh }, 'en', [])
    out.capital = [run.capitalise('read to the end'), run.capitalise('')]
    // the arrival record
    arrival.recordArrival('instagram', 'Instagram', [5, 6, 7], 20)
    const first = arrival.arrival.cur
    const started = arrival.takeArrival(1000)
    const again = arrival.takeArrival(5000)
    out.arrival = { base: first.base, total: first.total, ids: [...first.ids], at0: first.at, at: started.at, same: again.at, hold: arrival.HOLD_MS }
    arrival.recordArrival('threads', 'Threads', [], 20)
    out.empty = arrival.arrival.cur
    out.turn = [arrival.turn(0, 0), arrival.turn(3, 0), arrival.turn(3, 100), arrival.turn(3, 270), arrival.turn(3, 600), arrival.turn(0, 320), arrival.turn(-2, 0)]
    arrival.endArrival()
    out.ended = arrival.takeArrival(0)
    console.log(JSON.stringify(out))
"""


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class ImportRunRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = json.loads(test_phone_js.node(SCRIPT))

    def test_the_grid_follows_the_first_24_posts(self):
        o = self.out
        self.assertEqual(o['squareCount'], 24)
        # 100 and 101 have a picture, 102 and 103 are being fetched, the rest wait; only the first 24 show
        self.assertEqual(o['squares'], 'dd' + 'rr' + 'w' * 20)
        self.assertEqual(o['got'], 3)

    def test_the_pictures_are_finished_when_started_and_all_there_or_the_queue_stopped(self):
        # [not started, working, waiting out a slow-down, idle, all there, nothing to fetch, nothing and not started]
        self.assertEqual(self.out['finished'], [False, False, True, True, True, True, False])

    def test_english_lines(self):
        en = self.out['lang']['en']
        self.assertEqual(en['sub'], ['Read to the end of the list · 3 already there · 2 refused', 'Stopped at posts already in the library',
                                     'From a read that was cut off · 1 already there', '1 refused'])
        self.assertEqual(en['ready'], ['1 post ready to import', '0 posts ready to import', '2 posts ready to import'])
        self.assertEqual(en['button'], ['Import 1 post', 'Import 2 posts'])
        self.assertEqual(en['finish'], ['1 post in your library', '24 posts in your library'])
        self.assertEqual(en['were'], ['1 was already there', '0 were already there', '5 were already there'])
        self.assertEqual((en['added'], en['picsOf'], en['some']), ('3 of 5 added', '2 of 9 pictures', '4 of 9 pictures ready'))
        self.assertTrue(en['failedNote'].endswith('Unsave could not be confirmed. Remaining posts were kept saved; scanning continued.'))
        self.assertEqual(len(set(en['reasons'])), 7)
        self.assertEqual(en['reasons'][7], en['reasons'][2])      # an unknown reason reads as a stop

    def test_plurals_follow_each_language(self):
        fr, zh = self.out['lang']['fr'], self.out['lang']['zh-Hant']
        # French: one covers 0 and 1; Chinese: one form
        self.assertEqual(fr['ready'], ['1 publication prête à importer', '0 publication prête à importer', '2 publications prêtes à importer'])
        self.assertEqual(fr['button'], ['Importer 1 publication', 'Importer 2 publications'])
        self.assertEqual(fr['were'], ['1 était déjà présente', '0 était déjà présente', '5 étaient déjà présentes'])
        self.assertEqual(zh['ready'], ['1 則貼文可匯入', '0 則貼文可匯入', '2 則貼文可匯入'])
        self.assertEqual(zh['button'], ['匯入 1 則貼文', '匯入 2 則貼文'])
        self.assertEqual(len(set(zh['were'])), 3)
        self.assertEqual(len(set(zh['reasons'][:7])), 7)
        self.assertEqual(len(set(fr['reasons'][:7])), 7)
        for lang in (fr, zh):
            self.assertNotIn('ready to import', ' '.join(lang['ready']))
            self.assertNotIn('Read to the end', ' '.join(lang['sub']))

    def test_the_arrival_toast_in_three_languages(self):
        lang = self.out['lang']
        self.assertEqual(lang['en']['toast'], ['✓ 1 new from Instagram', '✓ 2 new from Instagram'])
        self.assertEqual(lang['fr']['toast'], ['✓ 1 nouvelle de Instagram', '✓ 2 nouvelles de Instagram'])
        self.assertEqual(lang['zh-Hant']['toast'], ['✓ 從 Instagram 新增 1 則', '✓ 從 Instagram 新增 2 則'])

    def test_capitalise(self):
        self.assertEqual(self.out['capital'], ['Read to the end', ''])

    def test_the_arrival_record_keeps_the_base_and_starts_once_after_the_hold(self):
        a = self.out['arrival']
        self.assertEqual((a['base'], a['total'], a['ids'], a['at0']), (17, 20, [5, 6, 7], 0))
        self.assertEqual((a['hold'], a['at'], a['same']), (280, 1280, 1280))
        self.assertIsNone(self.out['empty'])
        self.assertIsNone(self.out['ended'])

    def test_a_card_arrives_90_ms_after_the_one_before_and_a_late_one_is_simply_there(self):
        self.assertEqual(self.out['turn'], [
            {'delay': 0, 'live': True}, {'delay': 270, 'live': True}, {'delay': 170, 'live': True}, {'delay': 0, 'live': True},
            {'delay': -330, 'live': False}, {'delay': -320, 'live': False}, {'delay': 0, 'live': True}])


class ImportRunWiringTest(unittest.TestCase):
    def test_site_read_hands_the_ready_block_to_import_run(self):
        read = (MOBILE / 'screens' / 'SiteRead.svelte').read_text(encoding='utf-8')
        self.assertIn("import ImportRun from '../ImportRun.svelte'", read)
        self.assertEqual(read.count('<ImportRun'), 1)
        # the old block's literals are gone, the saved-results message stays in SiteRead (passed as onlater)
        self.assertNotIn('ready to import', read)
        self.assertNotIn('Import {review.posts.length}', read)
        self.assertIn('Saved results kept on this phone. Tap Scan to review them later.', read)
        self.assertIn('void runPictures()', read)
        # the finished import keeps the run on screen: its header is frozen when Import is pressed
        self.assertIn('flows = { ...flows, [site]: flowOf(site)! }', read)

    def test_open_in_library_records_the_arrival_and_resets_the_filters(self):
        run = (MOBILE / 'ImportRun.svelte').read_text(encoding='utf-8')
        body = run[run.index('function open()'):]
        for line in ('recordArrival(site, name, ids, phone.rows.length)', 'phone.cat = ALL', 'phone.fav = false', "phone.sort = 'new'",
                     'phone.scroll.lib = 0', "shell.base === 'lib'", 'closeSheet()', "go('#/lib', true)"):
            self.assertIn(line, body)
        self.assertLess(body.index('recordArrival('), body.index('closeSheet()'))
        # the picture grid starts right after the queue was started, from the parent's import
        self.assertIn('picsStarted = true', run)

    def test_the_grid_has_six_columns_of_at_most_24_squares_65_ms_apart(self):
        css = (MOBILE / 'import.css').read_text(encoding='utf-8')
        rules = import_run_ts = (MOBILE / 'import-run.ts').read_text(encoding='utf-8')
        self.assertIn('grid-template-columns:repeat(6,minmax(0,1fr))', css)
        self.assertIn('GRID_MAX = 24, GRID_COLS = 6, GRID_STEP_MS = 65', rules)
        self.assertIn('animation-delay:calc(var(--i,0) * 65ms)', css)
        self.assertIn(':is(.motion-off,.cm-rest) .m-ir-img,:is(.motion-off,.cm-rest) .m-ir-sq{animation:none}', css)
        self.assertNotRegex(re.sub(r'/\*.*?\*/', '', css, flags=re.S), r'\.m-ir-sq\s*\.(?:art|card|slot)\b')


class LibraryArrivalWiringTest(unittest.TestCase):
    css = (MOBILE / 'mobile.css').read_text(encoding='utf-8')
    grid = (MOBILE / 'Grid.svelte').read_text(encoding='utf-8')
    library = (MOBILE / 'screens' / 'Library.svelte').read_text(encoding='utf-8')

    def test_the_scan_is_the_shared_face_overlay_and_a_picture_lands(self):
        self.assertIn('<span class="m-w-scan mo-scan" aria-hidden="true">', self.grid)
        self.assertIn("class:m-w-pic={w?.lane === 'pics'}", self.grid)
        self.assertIn('.m-w-scan{position:absolute;left:0;right:0;top:0;z-index:4;height:min(var(--m-card-height),100%);border-radius:calc(var(--m-card-height) * .0334);pointer-events:none}', self.css)
        self.assertIn('.m-cell.m-w-done.m-w-pic img.art{animation:mo-land var(--mo-land) var(--mo-ease) both}', self.css)
        self.assertIn(':is(.motion-off,.cm-rest) .m-cell::before,:is(.motion-off,.cm-rest) .m-cell.m-w-done.m-w-pic img.art{animation:none}', self.css)
        self.assertNotIn('@keyframes m-w-scan', self.css)

    def test_cards_of_the_arrival_take_their_turn_by_attachment(self):
        self.assertIn('{@attach arrives(r.id, first * cols + si)}', self.grid)
        self.assertIn("node.dataset.mo = 'arrive'", self.grid)
        self.assertIn("node.style.setProperty('--mo-d'", self.grid)
        motion = (ROOT / 'web' / 'src' / 'lib' / 'motion' / 'motion.css').read_text(encoding='utf-8')
        self.assertIn('[data-mo="arrive"]{animation:mo-arrive var(--mo-arrive) var(--mo-ease) var(--mo-d,0ms) both}', motion)
        self.assertIn(':is(.motion-off,.cm-rest) [data-mo="arrive"]{animation:none}', motion)

    def test_the_library_counts_up_from_the_base_and_shows_the_toast_once(self):
        lib = self.library
        self.assertIn('<Count as="small" value={c.n} jump={phone.loaded} />', lib)
        # the summary keeps today's markup; its number ticks (a Tween) only while an arrival counts up
        self.assertIn("t('library.summary', { n: shown, count: fmtNum(shown, 'en'), order })", lib)
        self.assertIn('const summaryTween = new Tween(0, v => { ticked = v })', lib)
        self.assertNotIn('<Count value={n', lib)
        self.assertIn("if (r.tab !== 'lib' || r.item || r.search || !cur || cur.at) return", lib)
        self.assertIn('takeArrival()', lib)
        self.assertIn("t('importrun.toast', { n: a.ids.size, site: a.name })", lib)
        self.assertIn('<MToast text={toast}', lib)

    def test_the_toast_is_a_status_pill_for_3_6_seconds_above_the_dock(self):
        toast = (MOBILE / 'ui' / 'MToast.svelte').read_text(encoding='utf-8')
        self.assertIn('ms = 3600', toast)
        self.assertIn('role="status"', toast)
        self.assertIn('bottom:calc(84px + env(safe-area-inset-bottom,0px))', self.css)
        self.assertIn('pointer-events:none', self.css[self.css.index('.m-toast{'):self.css.index('.m-toast>span')])


if __name__ == '__main__':
    unittest.main()
