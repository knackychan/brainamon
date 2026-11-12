"""The phone's Notes sheet (projects/phone-notes-manager) in the phone page at 360 x 780, light and dark: the root on
both tabs (the sheet's floating keys, word tabs, the kicker with the category picker and the count, card A with its
whole 14-line preview, Knowledge rows, the raised bar above the simulated bottom inset), the search (#/notes-search:
the whole note on the mirror, the words shared by both tabs, the no-match key, Escape and Android's Back close it),
the empty states, Synthesize with its run bar (found sources, the phone limit, a fake run, the keyboard lift) and a
Knowledge note with its cited sources. Vite alone; a synthetic solo pairing (with an OpenAI key, so Record shows,
and without one); every https and /api request aborted; personal notes go through the phone's change journal
(source.createMyNote / saveMyNote, so myNotes and noteBodies are the mirror's own); Knowledge notes, library rows,
the categories, the smart search and the synthesis are fakes on the page's source. Two more contexts
(projects/phone-solo-synthesize) run the real synthesis of a phone with no PC: links saved through source.saveLink
with details and a note in the journal, the AI endpoint pointed at this Vite server by the pairing's development
override (one fixed answer, the request recorded), the note under Knowledge with its cited sources; and the same
phone with no key. No Drive, no real AI call, no data folder. Screenshots: local/phone-notes/.
Run: py tests/check_phone_notes_browser.py
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local/phone-notes'
VIEW = {'width': 360, 'height': 780}
INSET = 44
RAW = bytes([17]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PAIR = dict(v=2, k=KEY, f=FP, c='', e='', ai={}, at=0, solo=True)
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"
# a long note: the card shows its first 14 lines; "zucchini" is on line 18, so only the whole-note search finds it
GARDEN = '\n'.join([f'- Row {i} of the garden plan' for i in range(1, 18)] + ['- Plant zucchini in May'])
SEED = """async ({ garden, notes }) => {
  const { phone, source } = await import('/src/mobile/state.svelte.ts')
  const row = i => ({ id: i, title: `Saved item ${i}`, creator: 'Fixture', type: 'Reel', cat: 'Health', tags: '', desc: '',
    url: `https://example.com/${i}`, src: 'fixture', thumb: false, ai: false, an: false, nd: 0, fav: false, created: 0, tv: 0 })
  // the library: 40 rows for Synthesize and the cited sources; a refresh (the solo journal holds no item) would
  // put back an empty library, so the source returns these rows too
  const ROWS = Array.from({ length: 40 }, (_, i) => row(i + 1))
  source.rows = async () => ({ rows: ROWS, cats: [] })
  source.synthTextless = async () => []
  phone.rows = ROWS
  const KNOW = [
    { file: 'knee-rehab.md', title: 'Knee rehab: what the saves agree on', kind: 'Synthesized', sources: [1, 2],
      created: '2026-11-06T10:00:00', updated: '2026-11-06T10:00:00', snippet: 'Isometrics first, then slow loading.' },
    { file: 'bread.md', title: 'Bread basics', kind: 'Topic digest', sources: [],
      created: '2026-11-05T10:00:00', updated: '2026-11-05T10:00:00', snippet: 'Hydration and time.' },
  ]
  const BODY = { 'knee-rehab.md': '## What they agree on\\n\\nIsometrics first [id 1], then slow loading [id 2].', 'bread.md': 'Hydration and time.' }
  // a phone with no PC copy: source.notes() rejects, and its own notes must still show (found on Fred's phone)
  source.notes = async () => { if (!notes) throw new Error('library/meta.json is not in the mirror'); return KNOW }
  source.note = async file => {
    const r = KNOW.find(n => n.file === file)
    if (!r) throw new Error('No such note in the mirror.')
    return { file, meta: { topic: r.title, sources: r.sources.join(',') }, body: BODY[file], row: r }
  }
  source.smart = async () => Array.from({ length: 40 }, (_, i) => i + 1)
  window.__runs = []
  source.synthesize = (topic, ids, onLine, signal) => new Promise((ok, bad) => {
    window.__runs.push({ topic, n: ids.length })
    onLine(`Folding ${ids.length} sources into the note (1 of 1)…`)
    window.__finish = () => ok({ file: 'knee-rehab.md', queued: false })
    signal.addEventListener('abort', () => bad(new DOMException('aborted', 'AbortError')))
  })
  if (!notes) return null
  source.myNoteCategories = async () => ['Food', 'General', 'Health', 'Travel']
  const add = async (title, category, body) => {
    const n = await source.createMyNote(title, category)
    await source.saveMyNote(n.file, title, category, body)
  }
  await add('Sourdough starter', 'Food', 'Feed it twice a day.\\n\\n- [ ] Buy rye flour\\n- [x] Clean the jar')
  await add('Knee plan', 'Health', '## The sequence\\n\\nThree short sessions beat one long one.')
  await add('Garden plan', 'General', garden)
  return source.synthMax
}"""
UP = "async () => { const { up } = await import('/src/mobile/shell.svelte.ts'); up(history.length > 1) }"
# a phone with no PC: three links saved on the phone (the journal), two with what their page gave (a details change, as
# the slow picture queue writes it), the first with Fred's note on the card, the third bare; then the library is read
# again so the page's rows hold them. The SEED's fakes on the source go first (own properties shadowing the real
# methods: deleting them brings the mirror's back). `source.changes` is a TypeScript private, reachable at runtime.
SOLO_LINKS = """async () => {
  const { source, refresh } = await import('/src/mobile/state.svelte.ts')
  for (const k of ['rows', 'smart', 'notes', 'note', 'synthesize', 'myNoteCategories']) delete source[k]
  const one = await source.saveLink('https://example.com/sits/one')
  const two = await source.saveLink('https://example.com/sits/two')
  const bare = await source.saveLink('https://example.com/sits/bare')
  const uidOf = id => source.changes.list.find(e => e.op === 'link' && -e.id === id).uid
  await source.changes.add({ op: 'details', uid: uidOf(one.id), title: 'Wall sits', creator: 'Coach', desc: 'Hold 45 s, three rounds.', thumb: '' })
  await source.edit(one.id, { notes: 'Try on Monday' })
  await source.changes.add({ op: 'details', uid: uidOf(two.id), title: 'Rest days', creator: '', desc: 'Rest between rounds.', thumb: '' })
  await refresh()
  return [one.id, two.id, bare.id]
}"""
SYNTH_ENTRIES = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  return source.changes.list.filter(e => e.op === 'synth').map(e => ({ sources: e.sources, uids: e.uids.map(u => u.length), file: e.file }))
}"""
COUNT = '.m-nt-kick > span:last-child'


def inset(page):
    page.add_style_tag(content=f'.m-sheet-layer.m-bare{{padding-bottom:{INSET}px}}')


def pad(page):
    return page.locator('.m-sheet-layer.m-bare').evaluate('e => getComputedStyle(e).paddingBottom')


def bar_clear(page, sel='.m-nt-bar', bottom=VIEW['height'] - INSET):
    """The bar ends 8 px above the simulated inset (or the keyboard) and sits 10 px from the sides."""
    box = page.locator(sel).bounding_box()
    assert box['y'] + box['height'] <= bottom - 8 + 0.5, box
    assert abs(box['x'] - 10) <= 0.5 and box['x'] + box['width'] <= page.viewport_size['width'] - 10 + 0.5, box
    return box


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        page.wait_for_timeout(150)
        assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), (name, theme)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def keyboard(page, up):
    page.set_viewport_size({'width': 360, 'height': 400} if up else VIEW)
    page.wait_for_function(f"() => document.documentElement.classList.contains('kb') === {'true' if up else 'false'}")


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-notes-') as td, open(Path(td) / 'vite.log', 'w') as log:
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in
               ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'BRAINAMON_', 'CM_DATA_DIR', 'YTDLP_COOKIES'))}
        env.update(BRAINAMON_HOME=td, CM_DATA_DIR=str(Path(td) / 'data'), LOCALAPPDATA=td, APPDATA=td, TEMP=td, TMP=td, PYTHON_DOTENV_DISABLED='1')
        proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)],
                                cwd=ROOT / 'web', env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urlopen(base + '/src/mobile/main.ts', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Vite did not start')
            cards = {name: ROOT / 'design/card-designs' / name for name in ('cards.css', 'engine.js', 'full-art-v2/fa2.css', 'full-art-v2/fa2.js')}
            errors = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge')

                def phone_page(with_key: bool, notes: bool, dev_ai: bool = False):
                    ctx = browser.new_context(viewport=VIEW, is_mobile=True, has_touch=True, locale='en-US')
                    ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                    ctx.route('https://**/*', lambda r: r.abort())
                    ctx.route('**/api/**', lambda r: r.abort())
                    ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                    ctx.route(base + '/wiskit/**', lambda r: r.fulfill(path=str(ROOT / 'web/public/wiskit' / urlparse(r.request.url).path.removeprefix('/wiskit/'))))
                    # the card engine's THUMBS proxy: Vite proxies /thumb* to the backend (vite.config.ts), which this check
                    # does not run; the cited source opens the item screen, whose cards read it
                    ctx.route(base + '/thumbs-proxy.js', lambda r: r.fulfill(path=str(ROOT / 'web/public/thumbs-proxy.js')))
                    # dev_ai: the pairing's development override points OpenAI at this server (pairing.ts devEndpoint takes
                    # loopback http in a development build only), so the real synthesize() runs against a routed answer
                    pair = dict(PAIR, ai={'openai': 'synthetic-openai-key'} if with_key else {}, **({'x': {'openai': base}} if dev_ai else {}))
                    ctx.add_init_script("Math.random = () => 0; localStorage.setItem('bp-wifi','off'); localStorage.setItem('bp-motion','off');"
                                        " if (!sessionStorage.getItem('fixture')) { sessionStorage.setItem('fixture','1'); localStorage.setItem('bp-pair', "
                                        + json.dumps(json.dumps(pair)) + ") }")
                    page = ctx.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/mobile.html#/more')
                    page.wait_for_function(SETTLED)
                    limit = page.evaluate(SEED, {'garden': GARDEN, 'notes': notes})
                    page.evaluate("async () => { const { go } = await import('/src/mobile/shell.svelte.ts'); go('#/notes') }")
                    page.locator('.m-sheet-layer.m-vt-notes').wait_for(state='visible')
                    inset(page)
                    return ctx, page, limit

                # the root, My notes: keys, tabs, kicker, card A, the bar above the inset
                ctx, page, limit = phone_page(True, True)
                keys = page.locator('.m-sheet-keys')
                expect(page.locator('.m-sheet-head')).to_have_count(0)
                expect(keys).to_have_count(1)
                expect(keys.get_by_role('button', name='Close Notes', exact=True)).to_be_visible()
                expect(keys.locator('.m-ws')).to_have_text('Notes')
                search_key = keys.get_by_role('button', name='Search notes', exact=True)
                expect(search_key).to_be_visible()
                # the Library header's order: the search key at the right edge, the Obsidian gem just left of it
                gem_key = keys.get_by_role('button', name='See my knowledge graph in Obsidian', exact=True)
                expect(gem_key).to_be_visible()
                gb, sb = gem_key.bounding_box(), search_key.bounding_box()
                assert abs(sb['x'] + sb['width'] - (VIEW['width'] - 12)) <= 1, sb
                assert gb['x'] + gb['width'] <= sb['x'] + 0.5, (gb, sb)
                tabs =page.get_by_role('group', name='Notes sections', exact=True)
                expect(tabs.get_by_role('button', name='My notes', exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(page.get_by_role('button', name='Choose category: All', exact=True)).to_be_visible()
                expect(page.locator(COUNT)).to_have_text('3 notes')
                deck = page.locator('.np-cards .np-cd')
                expect(deck).to_have_count(3)
                sour = page.get_by_role('button', name='Sourdough starter', exact=True)
                assert sour.locator('.np-cd-tab').text_content() == 'Food'
                assert sour.locator('.np-cd-page ul.np-check li[data-done]').count() == 1
                box = deck.first.bounding_box()
                assert abs(box['width'] - 161) <= 1 and abs(box['height'] - 161 * 88 / 63) <= 1.5, box
                garden = page.get_by_role('button', name='Garden plan', exact=True)
                lines = garden.locator('.np-cd-page li')
                expect(lines).to_have_count(14)                                   # the whole head
                last, paper = lines.nth(13).bounding_box(), garden.locator('.np-cd-page').bounding_box()
                assert last['y'] + last['height'] <= paper['y'] + paper['height'] + 0.5, (last, paper)
                assert 'zucchini' not in garden.locator('.np-cd-page').inner_text()
                bar = page.locator('.m-nt-bar')
                for name in ('Synthesize a note', 'Record', 'New note'):
                    expect(bar.get_by_role('button', name=name, exact=True)).to_be_visible()
                    assert bar.get_by_role('button', name=name, exact=True).bounding_box()['height'] >= 44
                assert abs(bar_clear(page)['height'] - 62) <= 1
                assert pad(page) == f'{INSET}px', pad(page)
                shoot(page, 'mine')

                # the category picker: one shelf, an empty one, back to All
                def pick(name):
                    page.locator('.m-nt-kick .m-picker-inline').click()
                    sheet = page.get_by_role('dialog', name='Choose category', exact=True)
                    expect(sheet).to_be_visible()
                    sheet.get_by_role('button', name=name, exact=True).click()
                    expect(sheet).to_be_hidden()
                pick('Food')
                expect(page.get_by_role('button', name='Choose category: Food', exact=True)).to_be_visible()
                expect(page.locator(COUNT)).to_have_text('1 note')
                expect(deck).to_have_count(1)
                pick('Travel')
                expect(page.locator('.m-nt-empty h4')).to_have_text('No notes in Travel')
                expect(page.locator('.m-nt-empty p')).to_have_text('Pick another category, or tap + to write one here.')
                expect(page.locator(COUNT)).to_have_text('0 notes')
                shoot(page, 'empty-category')
                pick('All')
                expect(deck).to_have_count(3)

                # the search: the key widens into the field, the whole note is searched, both tabs share the words
                search_key.click()
                expect(page).to_have_url(base + '/mobile.html#/notes-search')
                field = keys.get_by_role('searchbox', name='Search notes', exact=True)
                expect(field).to_be_focused()
                expect(keys.locator('.m-find.open')).to_be_visible()
                page.wait_for_timeout(350)
                assert keys.locator('.m-ws').evaluate('e => getComputedStyle(e).opacity') == '0'
                expect(keys.get_by_role('button', name='Close search', exact=True)).to_be_visible()
                field.fill('zucchini')
                expect(deck).to_have_count(1)
                expect(garden).to_be_visible()
                expect(page.locator(COUNT)).to_have_text('1 note')
                field.fill('isometrics')
                expect(deck).to_have_count(0)
                expect(page.locator('.m-nt-empty h4')).to_have_text('No match')
                expect(page.locator('.m-nt-empty p')).to_have_text('Nothing in My notes has "isometrics".')
                other = page.get_by_role('button', name='1 in Knowledge', exact=True)
                assert other.bounding_box()['height'] >= 44
                shoot(page, 'search-none')
                other.click()
                expect(tabs.get_by_role('button', name='Knowledge', exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.m-nt-row')).to_have_count(1)
                expect(field).to_have_value('isometrics')
                field.fill('knee')
                expect(page.locator('.m-nt-row')).to_have_count(1)
                tabs.get_by_role('button', name='My notes', exact=True).click()
                expect(deck).to_have_count(1)
                expect(page.get_by_role('button', name='Knee plan', exact=True)).to_be_visible()
                shoot(page, 'search')
                # Enter keeps the words; the keyboard hides the bar and drops the inset
                field.press('Enter')
                expect(field).not_to_be_focused()
                expect(field).to_have_value('knee')
                keyboard(page, True)
                expect(page.locator('.m-nt-foot')).to_be_hidden()
                assert pad(page) == '0px', pad(page)
                keyboard(page, False)
                expect(page.locator('.m-nt-foot')).to_be_visible()
                # a note opened from the results, then Back: the search and its words are still there
                page.get_by_role('button', name='Knee plan', exact=True).click()
                expect(page.locator('#nt-title')).to_be_visible()
                page.locator('.np-head').get_by_role('button', name='Back', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/notes-search')
                expect(field).to_have_value('knee')
                # Android's Back closes the search, not the sheet, and clears the words
                page.evaluate(UP)
                expect(page).to_have_url(base + '/mobile.html#/notes')
                expect(page.locator('.m-sheet-layer.m-vt-notes')).to_be_visible()
                expect(field).to_have_value('')
                expect(deck).to_have_count(3)
                # Escape closes it too
                search_key.click()
                expect(page).to_have_url(base + '/mobile.html#/notes-search')
                field.fill('bread')
                field.press('Escape')
                expect(page).to_have_url(base + '/mobile.html#/notes')
                expect(field).to_have_value('')

                # Knowledge: the kicker (no gem in it any more), the rows; the gem stays in the sheet's keys on both tabs
                tabs.get_by_role('button', name='Knowledge', exact=True).click()
                expect(page.locator('.m-nt-kick > span').first).to_have_text('Saved notes · 2')
                gem = keys.get_by_role('button', name='See my knowledge graph in Obsidian', exact=True)
                expect(gem).to_have_count(1)
                expect(page.locator('.m-nt-kick').get_by_role('button')).to_have_count(0)
                gbox = gem.bounding_box()
                assert gbox['width'] >= 36 and gbox['height'] >= 36, gbox
                rows = page.locator('.m-nt-row')
                expect(rows).to_have_count(2)
                expect(rows.first.locator('small')).to_have_text('Synthesized · 2 sources · 06 Nov')
                bar_clear(page)
                shoot(page, 'know')

                # a Knowledge note: Back, the gem in the corner, the kicker, the text on the paper, cited sources
                rows.first.click()
                expect(page).to_have_url(base + '/mobile.html#/notes/knee-rehab.md')
                expect(keys.get_by_role('button', name='Back', exact=True)).to_be_visible()
                expect(keys.get_by_role('button', name='Open in Obsidian', exact=True)).to_be_visible()
                expect(keys.locator('.m-find')).to_have_count(0)
                read = page.locator('.m-nt-read')
                expect(read.locator('.m-nt-meta')).to_have_text('Synthesized · 2 sources · 06 Nov')
                expect(read.locator('.m-nt-title')).to_have_text('Knee rehab: what the saves agree on')
                expect(read.locator('.m-nt-text')).to_contain_text('Isometrics first')
                expect(read.locator('.m-box')).to_have_count(0)
                expect(page.locator('.m-nt-foot')).to_have_count(0)
                cited = read.get_by_role('button', name='Show cited sources', exact=True)
                expect(cited).to_have_attribute('aria-expanded', 'false')
                assert cited.bounding_box()['height'] >= 44
                cited.click()
                expect(read.get_by_role('button', name='Hide cited sources', exact=True)).to_have_attribute('aria-expanded', 'true')
                expect(read.locator('.m-rel button')).to_have_count(2)
                shoot(page, 'note')
                keys.get_by_role('button', name='Back', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/notes')

                # Synthesize: the page, Find, the found sources, the run bar, over the limit, a run
                page.get_by_role('button', name='Synthesize a note', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/synth/')
                expect(keys.get_by_role('button', name='Back', exact=True)).to_be_visible()
                expect(page.locator('.m-nt-title')).to_have_text('Synthesize a note')
                find = page.get_by_role('button', name='Find', exact=True)
                expect(find).to_be_disabled()
                page.get_by_role('textbox', name='Topic', exact=True).fill('knee')
                find.click()
                expect(page.locator('.m-nt-kick')).to_have_text('40 found')
                srcs = page.locator('.m-nt-src')
                expect(srcs).to_have_count(40)
                expect(page.locator('.m-nt-src input:checked')).to_have_count(12)
                top = page.locator('.m-nt-rtop span')
                expect(top.first).to_have_text('12 sources')
                expect(top.nth(1)).to_have_text('1 AI call')
                expect(page.locator('.m-nt-run .m-meter')).to_have_count(0)
                run = page.locator('.m-nt-keys .m-key.wide')
                expect(run).to_have_text('Synthesize')
                expect(run).to_be_enabled()
                bar_clear(page, '.m-nt-run')
                shoot(page, 'synth')
                extra = [srcs.nth(i).locator('input') for i in range(12, limit + 1)]
                for box_ in extra:
                    box_.check()
                expect(top.first).to_have_text(f'{limit + 1} of {limit} sources')
                expect(top).to_have_count(1)
                expect(page.locator('.m-nt-over')).to_have_text(f'Over the phone limit ({limit}): untick 1 source')
                expect(run).to_have_text('Synthesize')
                expect(run).to_be_disabled()
                shoot(page, 'synth-over')
                for box_ in extra:
                    box_.uncheck()
                expect(run).to_have_text('Synthesize')
                run.click()
                expect(page.get_by_role('button', name='Stop', exact=True)).to_be_visible()
                expect(run).to_have_text('Writing…')
                expect(run).to_be_disabled()
                expect(top.first).to_have_text('Folding 12 sources into the note (1 of 1)…')
                assert page.evaluate('window.__runs') == [{'topic': 'knee', 'n': 12}]
                assert page.evaluate("""async () => {
                  const { switchLanguage } = await import('/src/mobile/language-switch.ts')
                  return (await switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})).status
                }""") == 'blocked'
                keyboard(page, True)
                expect(page.locator('.m-nt-runfoot')).to_be_visible()
                bar_clear(page, '.m-nt-run', 400)
                keyboard(page, False)
                page.evaluate('__finish()')
                expect(page).to_have_url(base + '/mobile.html#/notes/knee-rehab.md')
                # the Library's Synthesize button: a topic in the route fills the field and runs Find
                page.evaluate("location.hash = '#/synth/garden'")
                expect(page.get_by_role('textbox', name='Topic', exact=True)).to_have_value('garden')
                expect(page.locator('.m-nt-kick')).to_have_text('40 found')
                page.evaluate("location.hash = '#/notes'")
                expect(tabs.get_by_role('button', name='Knowledge', exact=True)).to_have_attribute('aria-pressed', 'true')
                ctx.close()

                # a phone with no note at all: the empty states, no search key, no kicker
                ctx, page, _ = phone_page(True, False)
                keys = page.locator('.m-sheet-keys')
                expect(page.locator('.m-nt-empty h4')).to_have_text('No notes yet')
                expect(page.locator('.m-nt-empty p')).to_have_text('Tap + to write one, or the mic to say it out loud. It shows up here as a card.')
                expect(page.locator('.m-nt-kick')).to_have_count(0)
                expect(keys.get_by_role('button', name='Search notes', exact=True)).to_be_visible()
                expect(keys.get_by_role('button', name='See my knowledge graph in Obsidian', exact=True)).to_be_visible()
                for name in ('Synthesize a note', 'Record', 'New note'):
                    expect(page.get_by_role('button', name=name, exact=True)).to_be_visible()
                bar_clear(page)
                shoot(page, 'empty-mine')
                page.get_by_role('group', name='Notes sections', exact=True).get_by_role('button', name='Knowledge', exact=True).click()
                expect(page.locator('.m-nt-empty h4')).to_have_text('No knowledge notes yet')
                expect(page.locator('.m-nt-empty p')).to_have_text('Tap Synthesize to write one from your saved items.')
                expect(page.locator('.m-nt-kick > span').first).to_have_text('Saved notes · 0')
                shoot(page, 'empty-know')
                # the bar fits a 320 px phone
                page.set_viewport_size({'width': 320, 'height': 720})
                page.wait_for_timeout(150)
                assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')
                bar_clear(page, bottom=720 - INSET)
                nbox = page.get_by_role('button', name='New note', exact=True).bounding_box()
                assert nbox['x'] + nbox['width'] <= 320 - 10 - 8 + 0.5, nbox
                ctx.close()

                # no OpenAI key: no Record, the other sentence
                ctx, page, _ = phone_page(False, False)
                assert page.evaluate("""async () => {
                  const { source } = await import('/src/mobile/state.svelte.ts')
                  source.synthTextless = Object.getPrototypeOf(source).synthTextless.bind(source)
                  const original = source.synthItems
                  source.synthItems = async () => [{id: 1, ai_desc: 'NO_CONTENT'}, {id: 2, notes: 'Useful note'}]
                  try { return await source.synthTextless([1, 2]) } finally { source.synthItems = original }
                }""") == [1]
                expect(page.locator('.m-nt-empty p')).to_have_text('Tap + to write your first one. It shows up here as a card.')
                # the mic stays without a key, as a reminder: it opens More's Wiskit key box
                record = page.get_by_role('button', name='Record', exact=True)
                expect(record).to_be_visible()
                expect(record).to_have_attribute('title', 'Record: add an OpenAI key first')
                record.click()
                expect(page).to_have_url(base + '/mobile.html#/more')
                expect(page.locator('#m-ai')).to_be_visible()
                page.evaluate("async () => { const { go } = await import('/src/mobile/shell.svelte.ts'); go('#/notes') }")
                page.locator('.m-sheet-layer.m-vt-notes').wait_for(state='visible')
                expect(page.get_by_role('button', name='New note', exact=True)).to_be_visible()
                # a new note starts with an empty title field showing the grey "Untitled" placeholder
                page.get_by_role('button', name='New note', exact=True).click()
                expect(page.locator('#nt-title')).to_have_value('')
                expect(page.locator('#nt-title')).to_have_attribute('placeholder', 'Untitled')
                page.locator('.np-head').get_by_role('button', name='Back', exact=True).click()
                expect(page.locator('.np-cards .np-cd')).to_have_count(1)         # the note shows although source.notes() rejects
                # Fred's solo phone: smart search rejects, keyword search finds links saved on the phone (id < 0): they are
                # listed; these fake rows have no uid, so source.item() fails and each counts as "no text yet" (disabled)
                page.evaluate("""async () => {
                  const { phone, source } = await import('/src/mobile/state.svelte.ts')
                  const ROWS = [-3, -2, -1].map(id => ({ id, title: `Phone link ${-id}`, creator: '', type: 'Link', cat: 'Inbox', tags: '',
                    desc: '', url: `https://example.com/p${-id}`, src: 'phone', thumb: false, ai: false, an: false, nd: 0, fav: false, created: 0, tv: 0 }))
                  source.rows = async () => ({ rows: ROWS, cats: [] })
                  phone.rows = ROWS
                  source.smart = async () => { throw new Error('Smart search needs the PC: it indexes the library by meaning. Keyword search works on this phone.') }
                  source.search = async () => ROWS.map(r => r.id)
                  const item = source.item.bind(source)
                  source.item = async id => id === -1 ? {id, url: ROWS[2].url, description: ROWS[2].url, ai_desc: ' NO_CONTENT ', notes: ''} : item(id)
                }""")
                page.evaluate("location.hash = '#/synth/knee'")
                expect(page.get_by_role('textbox', name='Topic', exact=True)).to_have_value('knee')
                expect(page.locator('.m-nt-kick')).to_have_text('3 found · 3 without text yet')
                expect(page.get_by_text('3 links have no text yet: open them online once (the caption), Describe them, or write a note on the card.', exact=True)).to_be_visible()
                expect(page.get_by_text('Nothing in the library matches that topic.', exact=True)).to_have_count(0)
                expect(page.get_by_text('pair a PC with this phone.', exact=False)).to_have_count(0)
                expect(page.locator('.m-nt-src')).to_have_count(3)
                expect(page.locator('.m-nt-notext')).to_have_count(3)
                expect(page.locator('.m-nt-src input:checked')).to_have_count(0)
                # this context has no key (the Record check above): the run key is the key hand-off
                expect(page.get_by_role('button', name='Add an AI key', exact=True)).to_be_visible()
                ctx.close()

                # a phone with no PC (projects/phone-solo-synthesize): links saved on the phone are found and folded on the
                # phone with its own key. The AI endpoint is this server, so the real synthesize() runs end to end: the
                # request is read, one fixed answer goes back, the journal gets the synth entry with its uids
                ctx, page, _ = phone_page(True, False, dev_ai=True)
                limit = page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).source.synthMax")
                asked = []

                def fake_ai(route):
                    asked.append(json.loads(route.request.post_data))
                    route.fulfill(status=200, content_type='application/json', body=json.dumps({'choices': [{'message': {
                        'content': '## Wall sits\n\nHold 45 s, then rest between rounds.\n\n## Sources\n-1, -2'}}]}))
                ctx.route(base + '/v1/chat/completions', fake_ai)
                one, two, bare = page.evaluate(SOLO_LINKS)
                page.evaluate("location.hash = '#/synth/sits'")
                expect(page.get_by_role('textbox', name='Topic', exact=True)).to_have_value('sits')
                expect(page.locator('.m-nt-kick')).to_have_text('3 found · 1 without text yet')
                expect(page.get_by_text('1 link has no text yet: open it online once (the caption), Describe it, or write a note on the card.', exact=True)).to_be_visible()
                expect(page.locator('.m-nt-src')).to_have_count(3)
                expect(page.locator('.m-nt-src input:checked')).to_have_count(2)
                expect(page.locator('.m-nt-notext')).to_have_count(1)
                expect(page.locator('.m-nt-notext')).to_contain_text('no text yet')
                expect(page.locator('.m-nt-notext input')).to_be_disabled()
                top = page.locator('.m-nt-rtop span')
                expect(top.first).to_have_text('2 sources')
                expect(top.nth(1)).to_have_text('1 AI call')
                run = page.locator('.m-nt-keys .m-key.wide')
                expect(run).to_have_text('Synthesize')
                expect(run).to_be_enabled()
                shoot(page, 'synth-solo')
                run.click()
                expect(page).to_have_url(base + '/mobile.html#/notes/sits.md')
                assert len(asked) == 1, asked
                prompt = asked[0]['messages'][-1]['content']
                for part in (f'### Source {one} — Wall sits', 'Creator: Coach', 'URL: https://example.com/sits/one', 'Category: INTERESTING',
                             'Caption:\nHold 45 s, three rounds.', 'My note:\nTry on Monday',
                             f'### Source {two} — Rest days', 'Caption:\nRest between rounds.'):
                    assert part in prompt, (part, prompt)
                assert f'Source {bare} ' not in prompt and 'Report:' not in prompt and 'Transcript:' not in prompt, prompt
                # the sources in the order found (the newest link first, as the Library lists them), each with its uid
                entries = page.evaluate(SYNTH_ENTRIES)
                assert entries == [{'sources': [two, one], 'uids': [32, 32], 'file': 'sits.md'}], (entries, one, two, bare)
                read = page.locator('.m-nt-read')
                expect(read.locator('.m-nt-meta')).to_contain_text('Synthesized · 2 sources')
                expect(read.locator('.m-nt-title')).to_have_text('sits')
                expect(read.locator('.m-nt-text')).to_contain_text('Hold 45 s')
                read.get_by_role('button', name='Show cited sources', exact=True).click()
                expect(read.locator('.m-rel button')).to_have_count(2)
                shoot(page, 'note-solo')
                read.locator('.m-rel button').first.click()
                expect(page).to_have_url(base + f'/mobile.html#/item/{min(one, two)}')
                page.evaluate("location.hash = '#/notes'")
                page.locator('.m-sheet-layer.m-vt-notes').wait_for(state='visible')
                # back from the card the sheet starts afresh on My notes: the Knowledge tab lists the note
                know = page.get_by_role('group', name='Notes sections', exact=True).get_by_role('button', name='Knowledge', exact=True)
                know.click()
                expect(know).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.m-nt-kick')).to_have_text('Saved notes · 1')
                expect(page.locator('.m-nt-row')).to_have_count(1)
                expect(page.locator('.m-nt-row b')).to_have_text('sits')
                ctx.close()

                # the same phone with no AI key: Find works, the page says what to add, the run key opens More's key box and
                # Back returns to the page
                ctx, page, _ = phone_page(False, False)
                one, two, bare = page.evaluate(SOLO_LINKS)
                page.evaluate("location.hash = '#/synth/sits'")
                expect(page.locator('.m-nt-kick')).to_have_text('3 found · 1 without text yet')
                expect(page.get_by_text('Synthesize writes the note on this phone with your own AI key. Add one under Settings > Wiskit on this phone.', exact=True)).to_be_visible()
                expect(page.locator('.m-nt-rtop span')).to_have_count(1)
                add = page.get_by_role('button', name='Add an AI key', exact=True)
                expect(add).to_be_visible()
                expect(page.locator('.m-nt-keys .m-key.wide')).to_have_count(1)
                shoot(page, 'synth-nokey')
                add.click()
                expect(page).to_have_url(base + '/mobile.html#/more')
                expect(page.locator('#m-ai')).to_be_visible()
                expect(page.locator('#m-ai')).to_be_visible()
                page.evaluate(UP)
                expect(page).to_have_url(base + '/mobile.html#/synth/sits')
                ctx.close()
                browser.close()
            assert not errors, errors
            print(f'PASS: keys and tabs, kicker and picker, card A (14 lines), search (whole note, both tabs, no-match key, '
                  f'Enter, keyboard, Back, Escape), Knowledge rows and note, Synthesize (found, limit, run, keyboard lift, '
                  f'topic route), empty states, 320 px, bar above the {INSET} px inset, a phone with no PC (links saved on the '
                  f'phone found and folded against a fake AI endpoint, the note under Knowledge with its cited sources, no key); '
                  f'screenshots in {ART}')
        finally:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == '__main__':
    main()
