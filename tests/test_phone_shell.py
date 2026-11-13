"""The phone shell's pure rules (projects/phone-dock-shell): which routes are sections and sheets, where
Back goes, what the sync key's ring draws, the shell glyphs."""
import json
import unittest
from pathlib import Path

from tests.phone_catalog import english
from tests.test_phone_js import TS_RESOLVE, _node_ok, node

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'web' / 'src' / 'mobile'


def source(rel: str) -> str:
    return (MOBILE / rel).read_text(encoding='utf-8').replace('\r\n', '\n')


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class ShellRulesTest(unittest.TestCase):
    def test_sections_sheets_and_bases(self):
        out = json.loads(node(TS_RESOLVE + """
            const { isSection, sheetOf, sheetSub, baseHash } = await import('./web/src/mobile/shell.ts')
            const routes = [{ tab: 'lib' }, { tab: 'lib', search: true }, { tab: 'lib', item: 4 }, { tab: 'cv', canvas: null },
              { tab: 'cv', canvas: 'a' }, { tab: 'notes' }, { tab: 'notes', note: 'a.md' }, { tab: 'jv', chats: true },
              { tab: 'cap' }, { tab: 'cap', imp: true }, { tab: 'cap', save: true }, { tab: 'more' }, { tab: 'more', backup: true }]
            console.log(JSON.stringify({ section: routes.map(isSection), sheet: routes.map(sheetOf),
              sub: routes.map(sheetSub), base: [baseHash('lib'), baseHash('cv')] }))
        """))
        self.assertEqual(out['section'], [True, True, False, True, False, False, False, False, False, False, False, False, False])
        self.assertEqual(out['sheet'], [None, None, None, None, None, 'notes', 'notes', 'jv', 'cap', 'cap', 'cap', None, None])
        self.assertEqual(out['sub'], [False, False, False, False, False, False, True, True, False, True, True, False, False])
        self.assertEqual(out['base'], ['#/lib', '#/canvas'])

    def test_back_knows_search_and_the_sheet_base(self):
        out = json.loads(node(TS_RESOLVE + """
            const { parentHash } = await import('./web/src/mobile/back.ts')
            console.log(JSON.stringify([
              parentHash({ tab: 'lib', search: true }), parentHash({ tab: 'lib', search: true }, 'cv'),
              parentHash({ tab: 'notes' }, 'cv'), parentHash({ tab: 'jv' }, 'cv'), parentHash({ tab: 'cap' }, 'cv'),
              parentHash({ tab: 'cap', imp: true }, 'cv'), parentHash({ tab: 'cap', save: true }, 'cv'),
              parentHash({ tab: 'notes', note: 'a.md' }, 'cv'),
              parentHash({ tab: 'jv', chats: true }, 'cv'), parentHash({ tab: 'notes' }),
              parentHash({ tab: 'cv', canvas: null }, 'cv'), parentHash({ tab: 'lib' }, 'cv')]))
        """))
        self.assertEqual(out, ['#/lib', '#/lib', '#/canvas', '#/canvas', '#/canvas', '#/cap', '#/cap', '#/notes', '#/jv',
                               '#/lib', '#/lib', ''])

    def test_more_back_returns_to_the_screen_that_sent_the_reader(self):
        # projects/phone-wiskit-chat plan 02 Task 6: Wiskit's Add a key sends the reader to More; More's parent is then
        # Wiskit until the reader leaves More's screens (onboard.svelte.ts forgets it); Backup & phones keep More
        out = json.loads(node(TS_RESOLVE + """
            const { parentHash, setMoreFrom } = await import('./web/src/mobile/back.ts')
            const more = { tab: 'more' }, backup = { tab: 'more', backup: true }, recover = { tab: 'more', recover: true }
            const before = parentHash(more)
            setMoreFrom('#/jv')
            const sent = [parentHash(more), parentHash(backup), parentHash(recover), parentHash({ tab: 'lib' })]
            setMoreFrom('')
            console.log(JSON.stringify([before, sent, parentHash(more)]))
        """))
        self.assertEqual(out, ['#/lib', ['#/jv', '#/more', '#/backup', ''], '#/lib'])

    def test_the_search_route_parses(self):
        state = source('state.svelte.ts')
        self.assertIn("    case 'search': return { tab: 'lib', search: true }\n", state)
        self.assertIn('; search?: boolean }', state)

    def test_the_add_recap_route_parses(self):
        # projects/phone-add-confirm plan 01: #/cap/save is Add's recap, a page of the Add sheet
        state = source('state.svelte.ts')
        self.assertIn("    case 'cap': return p[1] === 'save' ? { tab: 'cap', save: true } : { tab: 'cap' }\n", state)
        self.assertIn('imp?: boolean; save?: boolean;', state)

    def test_the_notes_search_is_a_sheet_page(self):
        # projects/phone-notes-manager plan 01: #/notes-search is a page of the Notes sheet; Back and up() step to #/notes
        out = json.loads(node(TS_RESOLVE + """
            const { sheetOf, sheetSub } = await import('./web/src/mobile/shell.ts')
            const { parentHash } = await import('./web/src/mobile/back.ts')
            const r = { tab: 'notes', find: true }
            console.log(JSON.stringify([sheetOf(r), sheetSub(r), parentHash(r), parentHash(r, 'cv')]))
        """))
        self.assertEqual(out, ['notes', True, '#/notes', '#/notes'])
        state = source('state.svelte.ts')
        self.assertIn("    case 'notes-search': return { tab: 'notes', find: true }\n", state)
        self.assertIn('add?: boolean; find?: boolean; search?: boolean }', state)

    def test_the_notes_search_filter(self):
        # projects/phone-notes-manager plan 03: every word (AND), the fields, the category, the whole note, both tabs
        out = json.loads(node(TS_RESOLVE + r"""
            import assert from 'node:assert/strict'
            const { words, findMine, findKnow } = await import('./web/src/mobile/notes-find.ts')
            const mine = [
              { file: 'a.md', title: 'Sourdough starter', category: 'Food', head: 'Feed it <mark data-mark="yellow">twice</mark> a day' },
              { file: 'b.md', title: 'Knee plan', category: 'Health', head: 'Three short sessions', snippet: 'Three short sessions' },
              { file: 'c.md', title: 'Old card', category: 'Health', snippet: 'Rye and spelt' },
              { file: 'd.md', title: 'Empty', category: 'Food', head: '', snippet: '(no content)' },
            ]
            const know = [
              { file: 'k1.md', title: 'Knee rehab', kind: 'Synthesized', snippet: 'Isometrics first' },
              { file: 'k2.md', title: 'Bread basics', kind: 'Topic digest', snippet: 'Hydration and time' },
            ]
            const files = list => list.map(n => n.file)
            assert.deepEqual(words('  Sour  DOUGH '), ['sour', 'dough'])
            assert.deepEqual(words('   '), [])
            assert.deepEqual(files(findMine(mine, [])), ['a.md', 'b.md', 'c.md', 'd.md'])
            assert.deepEqual(files(findMine(mine, words('sour'))), ['a.md'])
            assert.deepEqual(files(findMine(mine, words('SOURDOUGH twice'))), ['a.md'])          // every word, any case
            assert.deepEqual(files(findMine(mine, words('sourdough rye'))), [])                  // AND, not OR
            assert.deepEqual(files(findMine(mine, words('mark'))), [])                           // tags are not words
            assert.deepEqual(files(findMine(mine, words('health'))), ['b.md', 'c.md'])           // the shelf is searched
            assert.deepEqual(files(findMine(mine, words('spelt'))), ['c.md'])                    // a snippet without a head
            assert.deepEqual(files(findMine(mine, words('content'))), [])                        // never "(no content)"
            assert.deepEqual(files(findMine(mine, [], 'Health')), ['b.md', 'c.md'])              // the category alone
            assert.deepEqual(files(findMine(mine, words('rye'), 'Health')), ['c.md'])            // category and words
            assert.deepEqual(files(findMine(mine, words('rye'), 'Food')), [])
            const texts = { 'b.md': 'Three short sessions\n...\nline 20: zucchini', 'k2.md': 'all about zucchini bread' }
            assert.deepEqual(files(findMine(mine, words('zucchini'))), [])                       // not in the head
            assert.deepEqual(files(findMine(mine, words('zucchini'), 'All', texts)), ['b.md'])   // the whole note
            assert.deepEqual(files(findMine(mine, words('twice'), 'All', { 'a.md': 'other words' })), [])  // it replaces the head
            assert.deepEqual(files(findKnow(know, [])), ['k1.md', 'k2.md'])
            assert.deepEqual(files(findKnow(know, words('digest'))), ['k2.md'])                  // the kind is searched
            assert.deepEqual(files(findKnow(know, words('isometrics KNEE'))), ['k1.md'])
            assert.deepEqual(files(findKnow(know, words('zucchini'), texts)), ['k2.md'])
            const shared = words('knee')                                                         // one set of words, both tabs
            assert.deepEqual([files(findMine(mine, shared)), files(findKnow(know, shared))], [['b.md'], ['k1.md']])
            console.log(JSON.stringify({ ok: true }))
        """))
        self.assertEqual(out, {'ok': True})

    def test_the_ring_follows_the_state(self):
        out = json.loads(node(TS_RESOLVE + """
            const { ringOf, RING_C, GLYPH } = await import('./web/src/mobile/sync-ring.ts')
            const f = o => ({ pull: 0, running: false, fill: null, manualPause: false, waiting: false, problem: false, ...o })
            console.log(JSON.stringify({ c: Math.round(RING_C * 10) / 10,
              glyph: Object.fromEntries(Object.entries(GLYPH).map(([k, v]) => [k, v.codePointAt(0)])),
              rings: [ringOf(f({})), ringOf(f({ pull: 0.5 })), ringOf(f({ pull: 1.6 })), ringOf(f({ running: true, fill: 0.5 })),
                ringOf(f({ running: true })), ringOf(f({ running: true, fill: 0 })), ringOf(f({ manualPause: true })),
                ringOf(f({ waiting: true, problem: true })), ringOf(f({ problem: true })),
                ringOf(f({ pull: 0.5, running: true, fill: 0.4 }))] }))
        """))
        self.assertEqual(out['c'], 69.1)
        self.assertEqual(out['glyph'], {'check': 0x2713, 'sync': 0x21BB, 'warn': 0x21, 'pause': 0x2016, 'down': 0x2193})

        def ring(tone, glyph, frac, spin=False, turn=0):
            return {'tone': tone, 'glyph': glyph, 'frac': frac, 'spin': spin, 'turn': turn}
        self.assertEqual(out['rings'], [
            ring('ok', 'check', 1), ring('pull', 'down', 0.5, turn=90), ring('run', 'down', 1, turn=180),
            ring('run', 'sync', 0.5, True), ring('run', 'sync', 0.25, True), ring('run', 'sync', 0.05, True),
            ring('paused', 'pause', 0), ring('paused', 'pause', 0), ring('warn', 'warn', 1),
            ring('pull', 'down', 0.5, turn=90)])

    def test_shell_glyphs_are_12_by_12(self):
        out = json.loads(node(TS_RESOLVE + """
            const { TAB_ICONS, EXTRA, shellIcon } = await import('./web/src/mobile/tabicons.ts')
            const all = [...Object.values(TAB_ICONS).flatMap(g => [g.off, g.on]), ...Object.values(EXTRA)]
            console.log(JSON.stringify({
              ok: all.every(rows => rows.length === 12 && rows.every(r => r.length === 12 && /^[#.]+$/.test(r))),
              names: Object.keys(EXTRA),
              path: shellIcon('search').length > 0 && shellIcon('lib', true) !== shellIcon('lib', false) }))
        """))
        self.assertEqual(out, {'ok': True, 'names': ['cloud', 'sync', 'cat', 'gem', 'disk', 'look', 'info', 'pc', 'key', 'wifi', 'pause', 'clock', 'bang', 'win', 'doc', 'columns', 'search', 'plus', 'rows', 'sort', 'tools', 'back', 'open', 'star', 'tag', 'bin', 'phone', 'check', 'down', 'send', 'stop', 'photo', 'file', 'paste', 'import', 'text', 'play', 'retry', 'x', 'dash', 'mic'], 'path': True})


    def test_item_strip_arithmetic_and_snapshot(self):
        out = json.loads(node(TS_RESOLVE + r"""
            import assert from 'node:assert/strict'
            const { stripLimit, stripPosition, stripIndex, stripThumb, stripWindow, stripList, stripTap } = await import('./web/src/mobile/strip.ts')
            assert.equal(stripLimit(-9, 4), 0)
            assert.equal(stripLimit(9, 4), 3)
            assert.equal(stripLimit(9, 0), 0)
            assert.equal(stripPosition(2, 28, 8), 1)
            assert.equal(stripPosition(2, -14, 8), 2.5)
            assert.equal(stripPosition(0, 28, 8), 0)
            assert.equal(stripPosition(7, -28, 8), 7)
            assert.equal(stripIndex(2.49, 8), 2)
            assert.equal(stripIndex(2.5, 8), 3)
            assert.deepEqual(stripThumb(0, false), { w: 36, h: 50, x: 0 })
            assert.deepEqual(stripThumb(1, false), { w: 28, h: 39, x: 40 })
            assert.deepEqual(stripThumb(2, false), { w: 24, h: 34, x: 70 })
            assert.deepEqual(stripThumb(0, true), { w: 42, h: 58, x: 0 })
            assert.deepEqual(stripThumb(-1, true), { w: 28, h: 39, x: -44 })
            assert.deepEqual(stripThumb(2, true), { w: 26, h: 36, x: 75 })
            assert.deepEqual(stripThumb(3, true), { w: 24, h: 34, x: 104 })
            assert.deepEqual(stripThumb(4, true), { w: 24, h: 34, x: 132 })
            assert.deepEqual(stripThumb(.5, true), { w: 35, h: 48.5, x: 22 })
            const a = stripThumb(.999, true), b = stripThumb(1.001, true)
            assert.ok(Math.abs(a.w - b.w) < .1 && Math.abs(a.x - b.x) < .1)
            assert.deepEqual(stripWindow(0, 3000), [0, 21])
            assert.deepEqual(stripWindow(1500, 3000), [1480, 1521])
            assert.deepEqual(stripWindow(2999, 3000), [2979, 3000])
            assert.deepEqual(stripWindow(0, 0), [0, 0])
            assert.deepEqual(stripList(2, [3, 2], [1, 2, 3]), [3, 2])
            assert.deepEqual(stripList(1, [3, 2], [1, 2, 3]), [1, 2, 3])
            assert.deepEqual(stripList(2, [2, 3], [1, 2, 3], [3, 2]), [3, 2])
            assert.deepEqual(stripList(2, [], [1, 2], [3, 2]), [2])
            assert.deepEqual(stripList(1, [1, 2], [1, 2, 3], [3, 2]), [1, 2])
            assert.deepEqual(stripList(99, [1], [1, 2]), [])
            assert.ok(stripTap(379, 5.99))
            assert.ok(!stripTap(380, 0) && !stripTap(100, 6) && !stripTap(900, 0))
            console.log(JSON.stringify({ ok: true }))
        """))
        self.assertEqual(out, {'ok': True})


class ShellSourceTest(unittest.TestCase):
    def test_the_shell_replaced_the_tab_bar(self):
        shell, lib, css = source('Mobile.svelte'), source('screens/Library.svelte'), source('mobile.css')
        for gone in ('m-tabs', 'PullSync', 'SyncStrip', 'tabIcon', 'Wordmark'):
            self.assertNotIn(gone, shell)
        for gone in ('PullSync.svelte', 'SyncStrip.svelte'):
            self.assertFalse((MOBILE / gone).exists(), gone)
        self.assertNotIn('~/library $', lib)
        self.assertIn('{#if !phone.route.search}', lib)
        for gone in ('.m-tabs', '.m-tab{', '.m-lib-search', '#m-app.m-capturing'):
            self.assertNotIn(gone, css)
        self.assertNotRegex(css, r'\.m-pull\b')
        self.assertIn('.m-sheet-layer.m-capturing>.m-sheet-body', css)
        self.assertIn("closest('.m-sheet-body')", source('screens/Wiskit.svelte'))
        self.assertIn('html.np-ed .m-dock{display:none}', source('note.css'))

    def test_the_library_toolbar_is_one_row_of_round_keys(self):
        # Sort / View / Select stay with the library; Tools stays reachable in the dock.
        lib, proc, css = source('screens/Library.svelte'), source('Processing.svelte'), source('mobile.css')
        for key in ('<MKey as="label" class="m-lib-sort"', "aria-label={t('library.sort.title')}", "t('library.view.grid') : t('library.view.rows')",
                    "aria-label={t('library.select')}", 'class="m-lib-sum"',
                    "{#if phoneOnly}<MInfo class=\"m-key m-lib-phone\" title={t('library.phoneOnly.title')}>"):
            self.assertIn(key, lib)
        self.assertIn("aria-label={t('common.tools')}", source('Dock.svelte'))
        # the words moved to the English catalog unchanged
        self.assertEqual([english(key) for key in ('library.sort.title', 'library.view.grid', 'library.view.rows', 'common.tools', 'library.phoneOnly.title')],
                         ['Sort', 'Show as grid', 'Show as rows', 'Tools', 'On this phone only'])
        for gone in ('m-cnt', 'class="m-sort"', 'Gallery layout', '>Process<', 'MHint', 'Saved on this phone.'):
            self.assertNotIn(gone, lib)
        self.assertIn("<h2>{t('common.tools')}</h2>", proc)
        self.assertEqual(english('common.tools'), 'Tools')
        self.assertIn('<dialog class="m-cap-pop m-process-pop"', proc)
        self.assertIn('dialog.m-cap-pop[open]', source('Mobile.svelte'))
        self.assertNotIn('Process items', proc)
        for gone in ('.m-cnt', '.m-sort', '.m-gallery-view', '.m-gallery-heading'):
            self.assertNotIn(gone, css)
        self.assertIn('.m-lib-sort select{', css)
        self.assertIn('.m-lib-tail{white-space:nowrap}', css)

    def test_item_screen_uses_felt_keys_and_persistent_strip(self):
        item, mobile, css = source('screens/Item.svelte'), source('Mobile.svelte'), source('mobile.css')
        for key in ('class="m-it-felt"', "aria-label={t('common.back')}", "aria-label={t('common.delete')}", 'class="m-it-kicker"',
                    "<MPicker label={t('item.collection')}", 'class="m-phone-key"', "aria-label={t('item.favourite')}",
                    "aria-label={t('item.editTags')}", "aria-label={t('common.tools')}", 'look="tabs"', '<MDialog', 'onToolsDone(',
                    'openLibrarySearch(row.creator)', 'source.edit(id, { category })'):
            self.assertIn(key, item)
        self.assertEqual([english(key) for key in ('common.back', 'common.delete', 'item.collection', 'item.favourite', 'item.editTags', 'common.tools')],
                         ['Back', 'Delete', 'Collection', 'Favourite', 'Edit tags', 'Tools'])
        for gone in ('class="m-it-meta"', 'class="m-open"', '<MRow', 'About processing', 'Process item',
                     'Tap Describe', 'No transcript. Video analysis runs on the PC.', 'Sure? Delete',
                     'async function describeIt', 'async function categorizeIt'):
            self.assertNotIn(gone, item)
        self.assertIn("{:else if !r.item && !compose && r.tab !== 'more'}", mobile)
        self.assertIn('{#if r.item}<ItemStrip />{/if}', mobile)
        self.assertIn('{#key r.item}<Item id={r.item} scroller={main} />{/key}', mobile)
        pinned = "      <button type=\"button\" class=\"m-back\" onclick={() => history.back()} aria-label={t('common.back')}>‹</button>"
        self.assertIn(pinned + '\n', mobile)
        self.assertIn('dialog.m-dialog[open]', mobile)
        self.assertIn('export function openLibrarySearch(text: string)', source('state.svelte.ts'))
        self.assertIn('phone.lastItem', source('Grid.svelte'))
        self.assertIn('await screenDone?.()', source('tools-run.svelte.ts'))
        self.assertIn('leave()', source('Processing.svelte'))
        self.assertIn('.m-tabline', css)
        self.assertIn('color-mix(in srgb,var(--m-teal) 14%,transparent)', css)
        self.assertIn('color-mix(in srgb,var(--m-teal) 70%,#000)', css)
        strip = source('ItemStrip.svelte')
        for key in ("aria-label={t('item.strip.label')}", 'aria-current=', 'stripList', 'stripThumb', 'stripWindow', 'go(`#/item/${id}`, true)'):
            self.assertIn(key, strip)
        self.assertEqual(english('item.strip.label'), 'Items')

    def test_the_bare_sheet_and_its_blocks(self):
        # projects/phone-wiskit-chat plan 01: Sheet's bare mode, the shared keyboard rule, MKey mid, MSeg pill
        sheet, mobile, css = source('Sheet.svelte'), source('Mobile.svelte'), source('mobile.css')
        for key in ('bare = false', 'keys = false', "name = ''", 'corner?: Snippet', '{#if keys}', 'class="m-sheet-keys"', 'class:m-bare={keys}',
                    '{:else if !bare}', "aria-label={t('shell.sheet.close', { title })}", "aria-label={t('common.back')}", 'class="m-sheet-name"', '{@render corner?.()}', '`m-vt-${kind}`'):
            self.assertIn(key, sheet)
        for key in ("bare={!!r.mynote}", "keys={sheet === 'jv' || sheet === 'cap' || (sheet === 'notes' && !r.mynote)}", "aria-label={t('shell.chats')}", '<ShellIcon name="rows" />', "go('#/jv/chats')", "let jvName = $state('')"):
            self.assertIn(key, mobile)
        self.assertEqual([english('shell.chats'), english('shell.sheet.close'), english('common.back')], ['Chats', 'Close {title}', 'Back'])
        self.assertIn('export function watchKeyboard(', source('keyboard.ts'))
        self.assertIn("size?: 'top' | 'mid' | 'dock'", source('ui/MKey.svelte'))
        self.assertIn("look?: 'seg' | 'tabs' | 'pill'", source('ui/MSeg.svelte'))
        for rule in ('.m-sheet-layer.m-bare{padding-bottom:env(safe-area-inset-bottom,0px)}',
                     'html.kb .m-sheet-layer.m-bare{padding-bottom:0}', '.m-sheet-keys{', '.m-sheet-keys::before{',
                     '.m-sheet-layer.m-bare:has(>.m-strip)>.m-sheet-body{margin-top:0}',
                     '.m-key.mid{', '.m-key.add:disabled{', '.m-segpill{', '.m-segpill button[aria-pressed="true"]{'):
            self.assertIn(rule, css)

    def test_wiskit_is_the_thumb_composer(self):
        # projects/phone-wiskit-chat plan 02: C1, C2, C3, the composer, follow / Latest, the Chats page
        jv, mobile, css = source('screens/Wiskit.svelte'), source('Mobile.svelte'), source('mobile.css')
        for key in ("name = $bindable('')", "closest('.m-sheet-body')", 'watchKeyboard(', 'class="m-jv-feed"', 'class="m-jv-need"',
                    'class="m-jv-rug"', "t('wiskit.need.keyTitle')", "t('wiskit.need.pcTitle')", "openMoreBox('m-ai')", 'class="m-jv-hello"',
                    'class="m-jv-try"', 'pickExample', 'class="m-jv-foot"', 'class="m-jv-latest"', "aria-label={t('wiskit.latest')}",
                    'class="m-jv-comp"', '<WiskitSprite pose={pet} crop', 'class="m-jv-stat"', 'look="pill"', "label={t('wiskit.mode.label')}",
                    '<textarea', "aria-label={t('wiskit.question')}", "placeholder={need ? need.hint : deep ? t('wiskit.deepPlaceholder') : t('wiskit.placeholder')}",
                    'e.isComposing || e.keyCode === 229', "size=\"mid\" tone=\"dark\" aria-label={t('notes.synthesize.stop')}", "size=\"mid\" tone=\"add\" type=\"submit\" aria-label={t('wiskit.send')}",
                    '<ShellIcon name="send" />', '<ShellIcon name="stop" />', 'scrollEnd(false)', 'class="m-jv-review"', "<b>{t('wiskit.chat.new')}</b>"):
            self.assertIn(key, jv)
        for gone in ('m-jv-win', 'm-jv-modes', 'm-jv-card', 'm-jv-sugs', 'm-jv-name', 'm-jv-empty', 'm-jv-in', 'class="m-chat"', '<Sprite',
                     'Add an AI key in More to ask.', 'Pair again with an AI key to ask.', 'Answers on your PC.', 'Needs the PC.',
                     '<input bind:this={qEl}', 'class="m-jv-modes"'):
            self.assertNotIn(gone, jv)
        self.assertIn('<Wiskit chats={!!r.chats} bind:name={jvName} />', mobile)
        for rule in ('.m-jv{', '.m-jv-feed{', '.m-jv-need{', '.m-jv-rug{', '.m-jv-hello{', '.m-jv-try{', '.m-jv-foot{', '.m-jv-comp{',
                     '.m-jv-field{', '.m-jv-field textarea{', '.m-jv-latest{', '.m-a{max-width:94%;padding:11px 12px;border-radius:14px 14px 14px 3px;background:var(--wg-2);font-size:13.5px;line-height:1.6;overflow-wrap:anywhere}'):
            self.assertIn(rule, css)
        for gone in ('.m-jv-win{', '.m-jv-modes', '.m-jv-card', '.m-jv-in{', '.m-chat{', '.m-rep,.m-a,.m-q,.m-steps{font-size:14px}'):
            self.assertNotIn(gone, css)

    def test_the_drafts_key_pieces(self):
        # projects/phone-add-sheet plan 01, then projects/phone-add-confirm plan 01: the corner key for Add (Import &
        # drafts), its shared counter, the glyph it draws; the recap has no corner key and is titled Save
        mobile, key, ui = source('Mobile.svelte'), source('CaptureKey.svelte'), source('capture-ui.svelte.ts')
        for needle in ("import CaptureKey from './CaptureKey.svelte'", "{:else if sheet === 'cap' && !r.imp && !r.save}<CaptureKey />{/if}",
                       "r.imp ? t('shell.route.import') : r.save ? t('shell.route.save') : tabName(r.tab)", 'dialog.m-dialog[open], dialog.m-cap-pop[open]'):
            self.assertIn(needle, mobile)
        self.assertEqual([english('shell.route.import'), english('shell.route.save'), english('shell.captureTray')], ['Import', 'Save', 'Import & drafts'])
        for needle in ("aria-label={t('shell.captureTray')}", 'aria-haspopup="dialog"', 'aria-expanded={capUi.open}', '<ShellIcon name="import" />',
                       "capUi.drafts > 99 ? '99+'", 'class="m-cap-badge" aria-hidden="true"', 'onclick={() => capUi.tray++}'):
            self.assertIn(needle, key)
        self.assertNotIn('Drafts & outbox', key)
        self.assertIn('export const capUi = $state({ drafts: 0, tray: 0, open: false })', ui)

    def test_the_add_sheet_is_the_thumb_composer(self):
        # projects/phone-add-sheet plan 02, then projects/phone-add-confirm plan 02: Add in the sheet's keys mode, the
        # composer (Photo, File, Paste, Save), the inline confirm line
        cap, mobile, css = source('screens/Capture.svelte'), source('Mobile.svelte'), source('mobile.css')
        for needle in ('class="m-cap-hello"', '<a class="m-cap-try" href="#/import" aria-label={t(\'imports.title\')}', 'class="m-cap-say"',
                       '<footer class="m-cap-dock">', 'class="m-cap-actions"',
                       '<ShellIcon name="photo" />', '<ShellIcon name="file" />', '<ShellIcon name="paste" />', 'class="m-cap-choice"',
                       "<span class=\"sr\">{t('capture.destination.item')}</span>", 'class="m-cap-chip m-cap-destination"', "aria-label={t('capture.destination.noteToAdd')}",
                       "<MPicker label={t('notes.category')}", "<MPicker label={t('item.collection')}",
                       '<MKey size="mid" tone="add" type="submit" class="m-cap-save"', 'aria-describedby="cap-help"',
                       "aria-busy={busy === 'Saving…'}", 'class="m-cap-ask"', 'bind:ref={goBtn}', ">{t('capture.attachment.continue')}</MButton>", ">{t('common.cancel')}</MTextButton>",
                       'watchKeyboard()', '<footer class="m-cap-dock done">',
                       "aria-label={t('capture.outbox.addAnother')}", ">{t('capture.outbox.openNote')}</MButton>", ">{t('capture.outbox.openCard')}</MButton>"):
            self.assertIn(needle, cap)
        self.assertEqual([english(k) for k in ('imports.title','capture.destination.item','capture.destination.noteToAdd',
            'notes.category','item.collection','capture.attachment.continue','common.cancel','capture.outbox.addAnother',
            'capture.outbox.openNote','capture.outbox.openCard')],
            ['Import saved posts','item','Note to add to','Category','Collection','Continue','Cancel','Add another','Open the note','Open the card'])
        for gone in ('window.confirm', 'm-cap-meta', 'm-cap-drop', 'Outbox ({box.entries.length})', '<MButton onclick={back}>Back</MButton>',
                     'import { back,', 'size="sm" aria-haspopup="dialog"', 'innerHeight < tallest * 0.8', 'class="m-cap-top"'):
            self.assertNotIn(gone, cap)
        self.assertIn("keys={sheet === 'jv' || sheet === 'cap' || (sheet === 'notes' && !r.mynote)}", mobile)
        for rule in ('.m-sheet-layer.m-capturing>.m-sheet-body{display:flex;flex-direction:column;overflow:hidden}', '.m-cap-dock{position:relative;',
                     '.m-cap-chip{position:relative;', '.m-cap-badge{position:absolute;',
                     '.m-cap-choice input{position:absolute;', 'html.kb .m-cap-form:has(.m-cap-editor :is(textarea,input):focus) :is(.m-cap-actions,'):
            self.assertIn(rule, css)
        for gone in ('.m-cap-meta', '.m-cap-drop', '.m-cap-lbl', '.m-cap-icon', '>:is(.m-sheet-head,.m-strip)', '.m-cap-commit .m-cap-choices{',
                     '.m-cap-top', '.m-cap-menu{position:absolute;'):
            self.assertNotIn(gone, css)

    def test_the_add_recap_pieces(self):
        # projects/phone-add-confirm plan 02: Save opens the recap (#/cap/save) on the same screen; it saves with the
        # destination it shows; General instead of Inbox; the Import & drafts panel; each note list loads on its own
        cap, css = source('screens/Capture.svelte'), source('mobile.css')
        for needle in ('const recap = $derived(!!phone.route.save)', "goTo('#/cap/save')", "if (phone.route.save) goTo('#/cap', true)",
                       'if (phone.route.save) stepBack()', '<section class="m-cap-recap" aria-labelledby="cap-pv">', 'class="m-cap-pv m-cap-pv-lib"',
                       'class="m-cap-pv-body"', 'class="m-cap-att"', '<fieldset class="m-cap-where">',
                       "<legend class=\"m-lbl m-cap-kick\">{t('capture.destination.where')}</legend>", 'disabled={!!block}', "aria-label={t('capture.destination.collectionName')}",
                       "aria-label={t('item.info.tags')}", '<input id="cap-comment"', '{@render acts(true)}', '{@render acts(false)}',
                       'const s = { ...($state.snapshot(d) as Draft), dest }', 'Promise.allSettled([source.myNotes(), source.myNoteCategories()])',
                       'const category = s.category || GENERAL', '<dialog class="m-cap-pop"', "<h2 id=\"cap-pop-title\">{t('shell.captureTray')}</h2>",
                       'capUi.drafts = others.length', "aria-label={t('common.save')} title={t('common.save')}", "t('capture.draft.sharedNotice')",
                       # the PC's API counts each request in a state (lib/api.ts net.n): an effect that read it looped
                       'untrack(() => source.myNote(file)).then('):
            self.assertIn(needle, cap)
        self.assertEqual([english(k) for k in ('capture.destination.where','capture.destination.collectionName','item.info.tags',
            'shell.captureTray','common.save','capture.draft.sharedNotice')],
            ['Where it goes','New collection name','Tags','Import & drafts','Save','Kept as a draft. Press Save to choose where it goes.'])
        for gone in ('INBOX', "'Inbox'", 'box.entries', 'm-q-list', 'Drafts &amp; outbox', 'm-cap-more', 'class="m-cap-tools"'):
            self.assertNotIn(gone, cap)
        # chrome never takes a card class name: design/card-designs/cards.css styles .new and .on everywhere
        for gone in ('class="new"', 'class="old"', 'class="wait"', 'class:on=', 'class:no=', 'class:shot=', 'class:all=', 'class:cut='):
            self.assertNotIn(gone, cap)
        # decision 13: no "PC decides"; the last collection used on this phone, else INTERESTING; Suggest with the
        # phone's own key asks first, writes nothing, and Save waits for it
        for needle in ("const LAST = 'bp-cap-collection'", 'const start = $derived(startCollection(last))',
                       'const name = (newMode ? s.collection : s.collection || start).trim().slice(0, 80)', 'keepCollection(name)',
                       'const canSuggest = $derived(!!source.suggestCategory && !!source.ai?.())',
                       "<MButton variant=\"pri\" size=\"sm\" bind:ref={catGo} onclick={suggest}>{t('capture.attachment.continue')}</MButton>",
                       'const ok = $derived(v.ok && !unnamed && !asking)', 'disabled={!ok || !!busy}'):
            self.assertIn(needle, cap)
        for gone in ('PC decides', "solo ? 'Default'"):
            self.assertNotIn(gone, cap)
        self.assertIn('async suggestCategory(item: ItemText, categories: string[])', source('source/mirror.ts'))
        self.assertIn('suggestCategory?(item: ItemText, categories: string[])', source('source/types.ts'))
        self.assertIn('.m-cap-dest>.m-cap-ask{', css)
        self.assertIn('.m-cap-commit .m-cap-suggest[aria-expanded="true"]{background:var(--ink);', css)
        for rule in ('.m-cap-recap{', '.m-cap-pv{', '.m-cap-dest.m-cap-on{', '.m-cap-menu{display:flex;', '.m-cap-pop{position:fixed;',
                     '.m-cap-pop::backdrop{', '.m-cap-tools{position:fixed;'):
            self.assertIn(rule, css)

    def test_import_saved_posts_takes_the_add_sheets_look(self):
        # projects/phone-add-sheet plan 03: one intro line and raised rows; the screen's logic is untouched
        read, imp = source('screens/SiteRead.svelte'), source('import.css')
        self.assertIn("<h1>{t('imports.title')}</h1><MHint as=\"p\">{t('imports.intro')}</MHint>", read)
        self.assertEqual([english('imports.title'),english('imports.intro')],
                         ['Import saved posts','Posts you saved on these sites become cards in your library.'])
        for rule in ('.m-pad.m-import-screen{padding:0 16px 16px}',
                     '.m-import-screen h1{margin:0;font:800 24px/1.15 var(--display);font-stretch:85%;color:var(--ink)}',
                     '.m-import-screen .m-import-fold.m-box{padding:0;gap:0;background:var(--case-hi);box-shadow:0 2px 0 var(--wg-edge)}'):
            self.assertIn(rule, imp)
        self.assertNotIn('border:1px solid var(--wg-line);border-radius:12px;background:var(--case)}', imp)

    def test_the_note_card_and_the_notes_pieces(self):
        # projects/phone-notes-manager plan 01: card A, the wide 44 px key, the mirror's whole note text
        card, note_css, css = source('NoteCard.svelte'), source('note.css'), source('mobile.css')
        for key in ('class="np-cd"', '<span class="np-cd-tab">', '<b class="np-cd-nm">', '<span class="np-cd-page" aria-hidden="true">',
                    "aria-label={n.title || t('notes.editor.untitled')}"):
            self.assertIn(key, card)
        for gone in ('np-cd-win', 'np-cd-hd', 'np-cd-stage', 'np-cd-rank', 'np-cd-pn', 'np-cd-stats', 'np-cd-ft', 'np-cd-bc', 'n.words', '{n.file}'):
            self.assertNotIn(gone, card)
        for rule in ('.np-cd{', 'background:var(--m-dot-grid) 0 0/12px 12px,var(--np-paper)', '.np-cd-tab{',
                     '.np-cd:active{transform:translateY(3px);box-shadow:none}', 'linear-gradient(transparent,var(--np-paper))',
                     '.np-cards{', '.motion-off .np-cd{transition:none}'):
            self.assertIn(rule, note_css)
        for gone in ('.np-cd-win', '.np-cd-hd', '.np-cd-stage', '.np-cd-rank', '.np-cd-pn', '.np-cd-stats', '.np-cd-ft', '.np-cd-bc', '#f7f6f2 radial'):
            self.assertNotIn(gone, note_css)
        self.assertIn('.m-key.mid.wide{width:auto;gap:8px;padding:0 16px 0 14px}', css)
        self.assertIn('noteBodies?(): Promise<Record<string, string>>', source('source/types.ts'))
        mirror = source('source/mirror.ts')
        self.assertIn('async noteBodies() {', mirror)
        self.assertIn('out[n.file] = plain(n.body)', mirror)
        # projects/phone-solo-synthesize: the sources from the journal, the uids, Knowledge without the meta, phone source ids
        for key in ('private async synthItems(', "await this.changes.add({ op: 'synth', topic, sources, uids, body: note, file })",
                    '/^-?\\d+$/', 'if (!this.solo) throw e', "if (this.solo) throw new Error(say(words, 'notes.synthesize.limit'"):
            self.assertIn(key, mirror)

    def test_the_notes_screen(self):
        # projects/phone-notes-manager plan 02: the keys' corner, tabs, kicker, bar, search, Synthesize page, Knowledge note
        notes, mobile, css = source('screens/Notes.svelte'), source('Mobile.svelte'), source('mobile.css')
        for key in ('corner = $bindable()', '{#snippet keys()}', 'look="tabs"', "label={t('notes.sections')}", "<MPicker label={t('notes.category')}",
                    "aria-label={t('notes.search')}", "placeholder={t('notes.searchPlaceholder')}", "aria-label={t('notes.closeSearch')}", "go('#/notes-search')",
                    "aria-label={t('notes.synthesize.title')}", "aria-label={t('notes.record')}", "aria-label={t('notes.new')}", "aria-label={t('notes.openObsidian')}",
                    "aria-label={t('notes.graph')}", 'onMount(() => watchKeyboard())', 'findMine(', 'findKnow(',
                    'source.noteBodies', 'class="m-nt-foot m-nt-runfoot"', "t('notes.synthesize.limit'", "t('notes.synthesize.addKey')",
                    "t('notes.synthesize.without'", 'found = (solo ? hits : hits.filter(r => r.id > 0))', 'await source.item(r.id)',
                    "t('notes.synthesize.queue')", 'class="m-pad np-bleed"', "t('notes.save.unsaved'"):
            self.assertIn(key, notes)
        for gone in ('m-segrow', 'm-obs', '"m-syn"', 'm-syn-srcs', 'class="m-note"', 'm-note-ttl', 'm-est', '<MBox', '+ New', 'm-chip',
                     'Keep for a PC', 'waits for a PC', 'pair a PC with this phone'):
            self.assertNotIn(gone, notes)
        for key in ("|| (sheet === 'notes' && !r.mynote)}", 'bind:corner={notesCorner}',
                    '{@render notesCorner?.()}', 'search={!!r.find}'):
            self.assertIn(key, mobile)
        for rule in ('.m-nt{', '.m-nt-foot{position:sticky;bottom:0;', 'html.kb .m-nt-foot:not(.m-nt-runfoot){display:none}', '.m-nt .m-err{',
                     '.m-nt-src small{', '.m-nt-notext>span:last-child{',
                     '.m-sheet-keys>.m-find{top:0;right:0}', '.m-sheet-keys>.m-find.open{width:100%}', '.m-notes{', '.m-meter{'):
            self.assertIn(rule, css)
        for gone in ('.m-segrow', '.m-obs', '.m-syn{', '.m-syn ', '.m-syn-srcs', '.m-note{', '.m-note+', '.m-note b', '.m-note-ttl', '.m-est{'):
            self.assertNotIn(gone, css)
        self.assertIn('export function findMine<', source('notes-find.ts'))

    def test_plan03_moved_words_stay_english(self):
        for key, text in {
            'notes.sections': 'Notes sections', 'notes.category': 'Category', 'notes.search': 'Search notes',
            'notes.searchPlaceholder': 'search titles and text', 'notes.closeSearch': 'Close search',
            'notes.synthesize.title': 'Synthesize a note', 'notes.synthesize.addKey': 'Add an AI key',
            'notes.synthesize.queue': 'Queue for the PC', 'notes.editor.untitled': 'Untitled',
            'notes.record': 'Record', 'notes.new': 'New note', 'notes.openObsidian': 'Open in Obsidian',
            'notes.graph': 'See my knowledge graph in Obsidian', 'notes.synthesize.without': ' · {n} without text yet',
            'notes.save.unsaved': '"{title}" is not saved ({detail}). Open it again to keep its changes.',
            'wiskit.need.keyTitle': 'Wiskit needs an AI key', 'wiskit.need.pcTitle': 'Wiskit needs the PC',
            'wiskit.latest': 'Latest', 'wiskit.mode.label': 'Mode', 'wiskit.question': 'Question',
            'wiskit.deepPlaceholder': 'Ask Wiskit to research…', 'wiskit.placeholder': 'Ask your library…',
            'notes.synthesize.stop': 'Stop', 'wiskit.send': 'Send', 'wiskit.chat.new': '+ New chat',
        }.items():
            self.assertEqual(english(key), text)

    def test_the_dock_keys_and_their_sheets_share_a_transition_name(self):
        dock, sheet, css = source('Dock.svelte'), source('Sheet.svelte'), source('mobile.css')
        for kind in ('notes', 'jv', 'cap'):
            self.assertIn(f'm-vt-{kind}', source('TopBar.svelte') if kind == 'notes' else dock)
            self.assertIn(f'.m-vt-{kind}{{view-transition-name:m-vt-{kind}}}', css)
        self.assertIn('`m-vt-${kind}`', sheet)
        self.assertIn('<WiskitSprite pose="happy" crop', dock)


if __name__ == '__main__':
    unittest.main()
