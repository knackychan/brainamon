"""Phone startup localization in disposable browser contexts; no accounts or network APIs."""
import importlib.util
import json
import re
import unittest

from tests.phone_pages import open_group

from tests.test_mobile_info_browser import PAIR, ROOT, mobile_browser, synthetic_phone
from tests import test_phone_note_page_browser

REVIEW = ROOT / 'local/i18n-review'      # gitignored: scene screenshots for Fred's and the native reader's look

# Screen run inside the page on a shown scene (plan 02): no sideways page scroll, no raw catalog key as text or in an aria-label /
# title / placeholder, fixed rows inside the viewport and not overlapping, short labels not clipped.
SCENE_CHECK = r"""() => {
  const out = [], vw = document.documentElement.clientWidth
  if (document.documentElement.scrollWidth > vw + 1) out.push('page scrolls sideways: ' + document.documentElement.scrollWidth)
  const rawKey = /\b(?:common|shell|library|item)\.[a-z][A-Za-z]*(?:\.[A-Za-z]+)*\b/
  const shown = e => { for (let n = e; n; n = n.parentElement) { const s = getComputedStyle(n); if (s.display === 'none' || s.visibility === 'hidden') return false } return true }
  const name = e => (e.getAttribute('aria-label') || e.textContent || e.className || '').trim().slice(0, 36)
  for (const e of document.querySelectorAll('#m-app *, dialog[open], dialog[open] *')) {
    for (const a of ['aria-label', 'title', 'placeholder']) { const v = e.getAttribute(a); if (v && rawKey.test(v)) out.push('raw key in ' + a + ': ' + v) }
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')
    if (own && rawKey.test(own) && shown(e)) out.push('raw key on screen: ' + own.trim())
  }
  const rows = ['.m-top', '.m-dock', '.m-lib-keys', '.m-syncp-btns', '.m-tabline', '.m-it-keyrow', '.m-sheet-keys', '.m-info-head', '.m-dialog-actions']
  for (const sel of rows) for (const row of document.querySelectorAll(sel)) {
    if (!shown(row)) continue
    const kids = [...row.children].filter(e => shown(e) && e.getBoundingClientRect().width > 0 && !e.classList.contains('m-find') && getComputedStyle(e).position !== 'absolute')
    kids.sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left)
    kids.forEach((e, i) => {
      const r = e.getBoundingClientRect(), next = kids[i + 1]
      if (r.left < -0.5 || r.right > vw + 0.5) out.push(sel + ' child outside the page: ' + name(e))
      if (next) { const n = next.getBoundingClientRect()
        if (n.left < r.right - 0.5 && Math.abs(n.top - r.top) < r.height / 2) out.push(sel + ' children overlap: ' + name(e) + ' / ' + name(next)) }
    })
  }
  for (const e of document.querySelectorAll('.m-askbox > span:last-child, .m-key.wide > span, .m-chip, .m-btn, .m-key, .m-tg, .m-tabline > *, .m-it-info > dt')) {
    if (!shown(e) || e.scrollWidth <= e.clientWidth + 1) continue
    // a label that gives way with an ellipsis keeps its full name in the control's aria-label: reported apart, never silent
    out.push((getComputedStyle(e).textOverflow === 'ellipsis' && e.closest('[aria-label]') ? 'ellipsized: ' : 'text wider than its control: ') + name(e))
  }
  for (const dt of document.querySelectorAll('.m-it-info > dt')) {
    const dd = dt.nextElementSibling
    if (dd && shown(dt) && dt.getBoundingClientRect().right > dd.getBoundingClientRect().left + 0.5) out.push('info label overlaps its value: ' + name(dt))
  }
  return out
}"""


SCENE_CHECK03 = SCENE_CHECK.replace('common|shell|library|item', 'common|shell|library|item|notes|canvas|wiskit|processing').replace("'.m-dialog-actions']", "'.m-dialog-actions', '.np-head', '.np-sh-hd', '.m-cp-header', '.m-cp-bar', '.m-jv-row', '.m-tl-head', '.m-tl-ask-keys']")
SCENE_CHECK04 = SCENE_CHECK03.replace('notes|canvas|wiskit|processing', 'notes|canvas|wiskit|processing|capture|imports|voice').replace("'.m-tl-ask-keys']", "'.m-tl-ask-keys', '.m-cap-dock', '.m-cap-quick', '.m-cap-ask-go', '.m-import-actions', '.m-voice-acts']")
SCENE_CHECK05 = SCENE_CHECK04.replace('capture|imports|voice', 'capture|imports|voice|settings|backup|recovery|shared').replace("'.m-voice-acts']", "'.m-voice-acts', '.m-recover-tabs', '.m-keyrow', '.m-seg.sm']")
# Legal bodies remain exact source documents (asserted against their files), whose prose can resemble catalog keys.
SCENE_CHECK06 = SCENE_CHECK05.replace('settings|backup|recovery|shared', 'settings|backup|recovery|shared|onboarding|legal').replace("'.m-seg.sm']", "'.m-seg.sm', '.m-ob-top', '.m-gs h3', '.m-coach']").replace('if (own && rawKey.test(own) && shown(e))', "if (own && rawKey.test(own) && shown(e) && !e.matches('.legal-documents pre'))")


def check_scene(test, page, language, theme, name, sweep='02', expected=()):
    """Shoot the scene into local/i18n-review/ and fail on a layout or raw-key problem (named by language, theme, scene)."""
    REVIEW.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(REVIEW / f'{sweep}-{language}-{theme}-{name}.png'), animations='disabled' if sweep in ('04', '05', '06') else 'allow',
                    mask=[page.locator('input[type=password], input[readonly], input[autocomplete=off], #phone-original-code span[style]')] if sweep in ('05', '06') else [])
    test.assertEqual(page.evaluate(SCENE_CHECK06 if sweep in ('06', '07', '08', '09') else SCENE_CHECK05 if sweep == '05' else SCENE_CHECK04 if sweep == '04' else SCENE_CHECK03 if sweep == '03' else SCENE_CHECK), list(expected), f'{language} {theme} {name}')


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneLanguageStartupBrowser(unittest.TestCase):
    def test_rich_links_are_safe_and_actions_are_keyboard_operable(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate("""async () => {
              const {mount} = await import('/node_modules/.vite/deps/svelte.js')
              const {default:T} = await import('/src/lib/i18n/T.svelte')
              const {setup} = await import('/src/lib/i18n/index.ts')
              setup({fr:{'common.retry':'<b>{detail}</b> <a:action>Action</a> <a:safe>Safe</a> <a:bad>Unsafe</a> <a:both>Both</a>',
                'shell.startup.loading':'<b>broken</i>'}},'fr',[])
              const target = document.createElement('div'); target.id='rich-review'; document.body.append(target)
              mount(T,{target,props:{id:'common.retry',params:{detail:'<img src=x onerror=alert(1)> {name}'},links:{
                action:{action:()=>window.__actionCount=(window.__actionCount||0)+1},
                safe:{href:'https://example.test/help'},bad:{href:'javascript:alert(1)'},
                both:{href:'https://example.test/',action:()=>{throw Error('mixed binding')}}}}})
              const malformed = document.createElement('div'); malformed.id='rich-malformed'; document.body.append(malformed)
              mount(T,{target:malformed,props:{id:'shell.startup.loading'}})
            }""")
            target = page.locator('#rich-review')
            expect(target.locator('b')).to_have_text('<img src=x onerror=alert(1)> {name}')
            self.assertEqual(target.locator('img').count(), 0)
            expect(target.get_by_role('link', name='Safe', exact=True)).to_have_attribute('href', 'https://example.test/help')
            self.assertEqual(target.get_by_role('link').count(), 1)
            self.assertEqual(target.get_by_role('button').count(), 1)
            action = target.get_by_role('button', name='Action', exact=True)
            action.focus(); action.press('Enter')
            self.assertEqual(page.evaluate('window.__actionCount'), 1)
            expect(page.locator('#rich-malformed')).to_have_text('<b>broken</i>')
            self.assertEqual(page.locator('#rich-malformed b').count(), 0)
            self.assertEqual(errors, [])

    def test_language_reload_preserves_queued_changes_and_pending_reviews(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light', language=None) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("""async () => {
              const {setSyncPaused} = await import('/src/mobile/network.svelte.ts')
              const {outbox, changes, putCanvasPending} = await import('/src/mobile/store.ts')
              const {mirrorSource} = await import('/src/mobile/state.svelte.ts')
              setSyncPaused(true)
              await outbox.add({url:'https://example.test/queued', note:'Synthetic', category:'', added:1, state:'waiting', src:'W'})
              await changes.add({op:'fav', uid:'synthetic-queued-item', on:true, at:1, state:'queued'})
              await putCanvasPending('wiskit-category-proposal:' + mirrorSource.pair.f, {entries:[{id:1, from:'A', category:'B'}]})
              await putCanvasPending('wiskit-canvas-proposal:' + mirrorSource.pair.f, {token:'synthetic-token', raw:{new_name:'Synthetic', elements:[]}, refs:{}, preview:{}})
              const {saveOnb}=await import('/src/mobile/onboard.svelte.ts')
              await saveOnb({answer:'phone',hidden:true,coach:true})
            }""")
            snapshot = """async () => {
              const {outbox, changes, kv} = await import('/src/mobile/store.ts')
              const {mirrorSource} = await import('/src/mobile/state.svelte.ts')
              const {secrets} = await import('/src/mobile/native.ts')
              const f = mirrorSource.pair.f
              return {pair:secrets.get('bp-pair'), pause:localStorage.getItem('bp-sync-paused'),
                outbox:await outbox.all(), changes:await changes.all(),
                category:await kv.get('wiskit-category-proposal:' + f), canvas:await kv.get('wiskit-canvas-proposal:' + f), onboard:await kv.get('onboard')}
            }"""
            before = page.evaluate(snapshot)
            open_group(page, 'Look')
            with page.expect_navigation(wait_until='domcontentloaded'):
                page.get_by_role('group', name='Language', exact=True).get_by_role('button', name='FR', exact=True).click()
            expect(page.locator('.m-page-keys')).to_be_visible()
            self.assertEqual(page.evaluate(snapshot), before)
            self.assertEqual(errors, [])

    def test_journal_load_and_merge_are_guarded_before_their_first_write(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            result = page.evaluate("""async () => {
              const {Changes} = await import('/src/mobile/mirror/changes.ts')
              const {switchLanguage} = await import('/src/mobile/language-switch.ts')
              const attempt = () => switchLanguage('fr', 'en', async () => {}, {setItem() {}}, () => {})
              const states = []
              for (const method of ['add', 'merge']) {
                const journal = new Changes(), load = journal.load.bind(journal)
                let release
                journal.load = () => new Promise(resolve => { release = () => load().then(resolve) })
                const pending = method === 'add' ? journal.add({op:'link', uid:'synthetic', url:'https://example.test'}) : journal.merge([])
                while (!release) await Promise.resolve()
                states.push((await attempt()).reason)
                release()
                await pending
              }
              return states
            }""")
            self.assertEqual(result, ['settings.language.unsavedWork', 'settings.language.unsavedWork'])
            self.assertEqual(errors, [])

    def test_language_choices_fit_narrow_phone_in_preview_languages(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base):
            for language, label in [('en', 'Language'), ('fr', 'Langue'), ('zh-Hant', '語言')]:
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 320, 720, theme, language=language) as (page, errors):
                        page.route('**/api/**', lambda route: route.abort())
                        page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                        open_group(page, WORDS05[language]['look'])
                        group = page.get_by_role('group', name=label, exact=True)
                        expect(group).to_be_visible()
                        for button in group.get_by_role('button').all():
                            box = button.bounding_box()
                            self.assertGreaterEqual(box['x'], 0)
                            self.assertLessEqual(box['x'] + box['width'], 320)
                        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                        self.assertEqual(errors, [])

    def test_clearing_phone_copy_blocks_language_reload_until_finished(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            open_group(page, 'Storage')
            page.evaluate("""async () => {
              const { items } = await import('/src/mobile/store.ts')
              const all = items.all
              items.all = () => new Promise(resolve => { window.__finishClear = () => { items.all = all; resolve([]) } })
            }""")
            page.get_by_role('button', name='Clear', exact=True).click()
            page.get_by_role('button', name='Sure? Clear', exact=True).click()
            page.wait_for_function('()=>!!window.__finishClear')
            open_group(page, 'Look')
            page.get_by_role('group', name='Language', exact=True).get_by_role('button', name='FR', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Finish or save your work')
            self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"), 'en')
            page.evaluate('window.__finishClear()')
            page.wait_for_function("async () => { const {switchLanguage} = await import('/src/mobile/language-switch.ts'); return (await switchLanguage('fr', 'en', async () => {}, {setItem() {}}, () => {})).status === 'reloaded' }")
            self.assertEqual(errors, [])

    def test_language_control_reloads_and_preserves_a_draft(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 320, 720, 'light', language=None) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("async () => (await import('/src/mobile/capture.svelte.ts')).shareIn('Synthetic preserved draft')")
            open_group(page, 'Look')
            group = page.get_by_role('group', name='Language', exact=True)
            expect(group).to_be_visible()
            page.evaluate('window.__noReload = true')
            group.get_by_role('button', name='Auto', exact=True).click()
            self.assertTrue(page.evaluate('window.__noReload'))
            self.assertIsNone(page.evaluate("localStorage.getItem('bp-lang')"))
            for choice, stored, html_lang, group_name in [('FR', 'fr', 'fr', 'Langue'), ('繁中', 'zh-Hant', 'zh-Hant-TW', '語言'), ('自動', 'auto', 'en', 'Language')]:
                with page.expect_navigation(wait_until='domcontentloaded'):
                    group.get_by_role('button', name=choice, exact=True).click()
                expect(page.locator('.m-page-keys')).to_be_visible()
                self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"), stored)
                self.assertEqual(page.locator('html').get_attribute('lang'), html_lang)
                self.assertTrue(page.evaluate("async () => (await (await import('/src/mobile/store.ts')).drafts.all()).some(d => d.text === 'Synthetic preserved draft')"))
                title = {'en': 'Look', 'fr': 'Style', 'zh-Hant-TW': '外觀'}[html_lang]
                open_group(page, title)
                group = page.get_by_role('group', name=group_name, exact=True)
                expect(group).to_be_visible()
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            self.assertEqual(errors, [])

    def test_language_control_handles_storage_and_pending_work_failures(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light', language=None) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            open_group(page, 'Look')
            group = page.get_by_role('group', name='Language', exact=True)
            page.evaluate("""async () => {
              const { registerLanguageCheck } = await import('/src/mobile/language-switch.ts')
              window.__releaseGuard = registerLanguageCheck(() => new Promise(resolve => { window.__finishGuard = resolve }))
            }""")
            group.get_by_role('button', name='FR', exact=True).click()
            page.wait_for_function('!!window.__finishGuard')
            self.assertTrue(page.locator('#m-app').evaluate('(node) => node.inert'))
            expect(group.get_by_role('button', name='FR', exact=True)).to_be_disabled()
            page.evaluate("window.__finishGuard('settings.language.unsavedWork')")
            expect(page.get_by_role('alert')).to_contain_text('Finish or save your work')
            self.assertFalse(page.locator('#m-app').evaluate('(node) => node.inert'))
            page.evaluate("""() => {
              window.__releaseGuard()
              const set = Storage.prototype.setItem
              Storage.prototype.setItem = function(k, v) { if (k === 'bp-lang') throw new Error('denied'); return set.call(this, k, v) }
            }""")
            group.get_by_role('button', name='FR', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Could not save the language')
            self.assertFalse(page.locator('#m-app').evaluate('(node) => node.inert'))
            self.assertIsNone(page.evaluate("localStorage.getItem('bp-lang')"))
            expect(group.get_by_role('button', name='Auto', exact=True)).to_have_attribute('aria-pressed', 'true')
            self.assertEqual(errors, [])

    def test_new_work_during_awaited_check_blocks_and_second_switch_is_refused(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light', language=None) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            page.wait_for_function("async () => { const {phone} = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            open_group(page, 'Look')
            group = page.get_by_role('group', name='Language', exact=True)
            page.evaluate("""async () => {
              const { registerLanguageCheck } = await import('/src/mobile/language-switch.ts')
              window.__releaseGuard = registerLanguageCheck(() => new Promise(resolve => { window.__finishGuard = resolve }))
            }""")
            group.get_by_role('button', name='FR', exact=True).click()
            page.wait_for_function('!!window.__finishGuard')
            second = page.evaluate("""async () => {
              const { switchLanguage, beginLanguageWork } = await import('/src/mobile/language-switch.ts')
              const second = await switchLanguage('zh-Hant', 'auto', async () => {}, { setItem() { throw Error('must not write') } }, () => { throw Error('must not reload') })
              window.__endWork = beginLanguageWork()
              window.__releaseGuard()
              window.__finishGuard(null)
              return second
            }""")
            self.assertEqual(second, {'status': 'busy'})
            expect(page.get_by_role('alert')).to_contain_text('Finish or save your work')
            self.assertIsNone(page.evaluate("localStorage.getItem('bp-lang')"))
            self.assertFalse(page.locator('#m-app').evaluate('(node) => node.inert'))
            expect(group.get_by_role('button', name='FR', exact=True)).to_be_enabled()
            page.evaluate('window.__endWork()')
            with page.expect_navigation(wait_until='domcontentloaded'):
                group.get_by_role('button', name='FR', exact=True).click()
            self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"), 'fr')
            self.assertEqual(errors, [])

    def test_auto_startup_skips_malformed_tags_and_uses_language_fallback(self):
        with mobile_browser() as (browser, base):
            for tags, single in [(['', 'not a tag!!', 'fr-FR', 'en-US'], 'fr-FR'), ([], 'zh-TW'), (['x-invalid-', 'de-DE'], 'de-DE')]:
                with self.subTest(tags=tags):
                    context = browser.new_context(locale='en-US')
                    try:
                        context.route('**/*', lambda route: route.abort() if
                                      not route.request.url.startswith(base + '/') or
                                      '/src/lib/local-auth.ts' in route.request.url or
                                      '/api/' in route.request.url else route.continue_())
                        context.add_init_script("""(([tags, single]) => {
                          localStorage.setItem('bp-lang', 'auto')
                          Object.defineProperty(Navigator.prototype, 'languages', { get: () => tags, configurable: true })
                          Object.defineProperty(Navigator.prototype, 'language', { get: () => single, configurable: true })
                        })(%s)""" % json.dumps([tags, single]))
                        page = context.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(base + '/mobile.html', wait_until='domcontentloaded')
                        page.wait_for_function("document.querySelector('#m-startup-title')?.textContent === 'Brainamon could not start'")
                        self.assertEqual(page.locator('html').get_attribute('lang'), 'en')
                        self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"), 'auto')
                        self.assertEqual(errors, [])
                    finally:
                        context.close()

    def test_recovered_results_fit_narrow_preview(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base):
            for language in ('fr', 'zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser, base, 320, 720, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
                    expect(page.locator('#cap-text')).to_be_visible()
                    page.evaluate("""async () => {
                      const c = await import('/src/mobile/capture.svelte.ts')
                      c.retainRead('synthetic', 'document.pdf', 'text', 'digest')
                      c.retainSuggestion('Synthetic', 'tag')
                      c.retainFile(new File(['x'], 'image.png', {type:'image/png'}))
                    }""")
                    expect(page.locator('.m-cap-hello')).to_have_count(0)
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                    for button in page.locator('.m-cap-editor .m-row button').all():
                        box = button.bounding_box()
                        self.assertGreaterEqual(box['x'], 0)
                        self.assertLessEqual(box['x'] + box['width'], 320)
                    self.assertEqual(errors, [])

    def test_capture_save_does_not_delete_newer_edits_after_navigation(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            field = page.locator('#cap-text')
            expect(field).to_be_visible()
            page.evaluate("""async () => {
              const { source } = await import('/src/mobile/state.svelte.ts')
              const save = source.saveMyNote.bind(source)
              source.saveMyNote = (...args) => new Promise((resolve, reject) => {
                window.__finishCaptureSave = () => save(...args).then(resolve, reject)
              })
            }""")
            field.fill('Original synthetic capture')
            page.get_by_role('button', name='Save', exact=True).click()
            page.get_by_role('button', name='Save to note', exact=True).click()
            page.wait_for_function('() => !!window.__finishCaptureSave')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate("location.hash = '#/cap'")
            expect(field).to_have_value('Original synthetic capture')
            field.fill('Newer synthetic edit')
            page.evaluate('window.__finishCaptureSave()')
            page.wait_for_function("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return (await switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})).status === 'reloaded'
            }""")
            page.wait_for_function("async () => (await (await import('/src/mobile/store.ts')).drafts.all()).some(d => d.text === 'Newer synthetic edit')")
            self.assertEqual(errors, [])

    def test_paste_finished_after_navigation_is_retained_for_review(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            expect(page.locator('#cap-text')).to_be_visible()
            page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', { configurable:true, value:{
              readText: () => new Promise(resolve => { window.__finishPaste = resolve })
            }})""")
            page.get_by_role('button', name='Paste', exact=True).click()
            page.wait_for_function('!!window.__finishPaste')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate("window.__finishPaste('Synthetic clipboard text')")
            page.wait_for_function("async () => (await import('/src/mobile/capture.svelte.ts')).cap.recoveredReads.length === 1")
            page.evaluate("navigator.clipboard.readText = async () => ''")
            page.evaluate("location.hash = '#/cap'")
            page.get_by_role('button', name='Add text to this draft', exact=True).click()
            expect(page.locator('#cap-text')).to_have_value('Synthetic clipboard text')
            self.assertEqual(errors, [])

    def test_file_open_finished_after_navigation_is_retained_for_review(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            expect(page.locator('#cap-text')).to_be_visible()
            page.evaluate("""() => {
              HTMLImageElement.prototype.decode = () => new Promise(resolve => { window.__finishDecode = resolve })
            }""")
            page.locator('input[type=file]').first.set_input_files(
                {'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': b'synthetic-image'})
            page.wait_for_function('!!window.__finishDecode')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate('window.__finishDecode()')
            page.wait_for_function("async () => (await import('/src/mobile/capture.svelte.ts')).cap.recoveredFiles.length === 1")
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt)['reason'], 'settings.language.unsavedDraft')
            page.evaluate("HTMLImageElement.prototype.decode = async () => {}")
            page.evaluate("location.hash = '#/cap'")
            page.get_by_role('button', name='Add file to this draft', exact=True).click()
            expect(page.get_by_role('button', name='Remove the attachment', exact=True)).to_be_visible()
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertTrue(page.evaluate("""async () => (await (await import('/src/mobile/store.ts')).drafts.all()).some(d => d.pic?.name === 'synthetic.png')"""))
            self.assertEqual(errors, [])

    def test_suggestion_finished_after_navigation_is_retained_for_review(self):
        from playwright.sync_api import expect

        pair = dict(PAIR, ai={'openai': 'synthetic-key'})
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light', pair=pair) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            page.evaluate("""async () => {
              const { source } = await import('/src/mobile/state.svelte.ts')
              source.suggestCategory = () => new Promise(resolve => { window.__finishSuggestion = resolve })
            }""")
            page.locator('#cap-text').fill('https://example.test/synthetic')
            page.get_by_role('button', name='Save', exact=True).click()
            page.get_by_role('button', name='Suggest', exact=True).click()
            page.get_by_role('group', name='Confirm: Suggest', exact=True).get_by_role('button', name='Continue').click()
            page.wait_for_function('!!window.__finishSuggestion')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate("window.__finishSuggestion({category:'INTERESTING', tags:'synthetic-tag'})")
            page.wait_for_function("async () => (await import('/src/mobile/capture.svelte.ts')).cap.recoveredSuggestions.length === 1")
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt)['reason'], 'settings.language.unsavedDraft')
            page.evaluate("location.hash = '#/cap'")
            page.get_by_role('button', name='Apply suggestion', exact=True).click()
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertTrue(page.evaluate("""async () => (await (await import('/src/mobile/store.ts')).drafts.all()).some(d => d.tags === 'synthetic-tag')"""))
            self.assertEqual(errors, [])

    def test_file_read_finished_after_navigation_is_retained_for_review(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            expect(page.locator('#cap-text')).to_be_visible()
            page.evaluate("""async () => {
              const { source } = await import('/src/mobile/state.svelte.ts')
              source.readFile = () => new Promise(resolve => { window.__finishRead = resolve })
            }""")
            page.locator('input[type=file]').first.set_input_files(
                {'name': 'synthetic.txt', 'mimeType': 'text/plain', 'buffer': b'Example'})
            page.wait_for_function('!!window.__finishRead')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            page.evaluate("window.__finishRead('Recovered synthetic text')")
            page.wait_for_function("async () => (await import('/src/mobile/capture.svelte.ts')).cap.recoveredReads.length === 1")
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt)['reason'], 'settings.language.unsavedDraft')
            page.evaluate("location.hash = '#/cap'")
            page.get_by_role('button', name='Add text to this draft', exact=True).click()
            expect(page.locator('#cap-text')).to_have_value('Recovered synthetic text')
            result = page.evaluate(attempt)
            self.assertEqual(result['status'], 'reloaded', result)
            self.assertTrue(page.evaluate("""async () => (await (await import('/src/mobile/store.ts')).drafts.all()).some(d => d.text === 'Recovered synthetic text')"""))
            self.assertEqual(errors, [])

    def test_phone_tools_run_blocks_switch_after_panel_closes(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.wait_for_function("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("""async () => {
              const { phone, source } = await import('/src/mobile/state.svelte.ts')
              phone.rows = [{ id:-1, uid:'synthetic-uid', title:'Synthetic item' }]
              source.describe = () => new Promise(resolve => { window.__finishTool = resolve })
              source.rows = async () => { throw Error('synthetic offline') }
            }""")
            page.wait_for_function("async () => (await import('/src/mobile/state.svelte.ts')).phone.byId.has(-1)")
            page.evaluate("""async () => {
              const { runPhone } = await import('/src/mobile/tools-run.svelte.ts')
              window.__toolRun = runPhone('describe', [-1], { scope:{item:false,heading:'Synthetic',count:1} })
            }""")
            page.wait_for_function('!!window.__finishTool')
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt)['status'], 'blocked')
            page.evaluate('window.__finishTool(null)')
            page.evaluate('window.__toolRun')
            self.assertEqual(page.evaluate(attempt)['reason'], 'settings.language.unsavedProcessing')
            page.evaluate("async () => (await import('/src/mobile/tools-run.svelte.ts')).dismiss('phone')")
            page.evaluate("""async () => {
              const {runs, newRun} = await import('/src/mobile/work.svelte.ts')
              runs.pc = newRun('pc', 'describe', [], {scope:{item:false,heading:'Synthetic PC run',count:0}})
            }""")
            self.assertEqual(page.evaluate(attempt)['reason'], 'settings.language.unsavedProcessing')
            page.evaluate("""async () => {
              const {runs} = await import('/src/mobile/work.svelte.ts')
              runs.pc.ended = true
              ;(await import('/src/mobile/tools-run.svelte.ts')).dismiss('pc')
            }""")
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertEqual(errors, [])

    def test_chinese_phone_type_overrides_leave_english_unchanged(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base):
            for language, size, spacing in (('en', '10.5px', 0.84), ('zh-Hant', '11px', 0)):
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
                    label = page.locator('.m-cap-try > i')
                    expect(label).to_be_visible()
                    style = label.evaluate("element => { const s = getComputedStyle(element); return { size: s.fontSize, spacing: s.letterSpacing, family: s.fontFamily } }")
                    self.assertEqual(style['size'], size)
                    self.assertAlmostEqual(0 if style['spacing'] == 'normal' else float(style['spacing'].removesuffix('px')), spacing)
                    if language == 'zh-Hant':
                        self.assertIn('PingFang TC', style['family'])
                    self.assertEqual(errors, [])

    def test_chinese_tools_text_respects_phone_minimum(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light', language='zh-Hant') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
            expect(page.locator('#m-app')).to_be_visible()
            styles = page.evaluate("""() => {
              const fixture = document.createElement('div')
              fixture.innerHTML = '<span class="m-tl-scope">範圍</span><div class="m-step-nm"><small>進行中</small></div><span class="m-step-tag">完成</span><div class="m-tl-li"><small>完成</small></div><span class="m-tl-st">等待</span><button class="m-tl-fold">展開</button><span class="m-tl-kick">工具</span><div class="m-runbar-top">進度</div><span class="m-tools-n">1</span>'
              document.querySelector('#m-app').append(fixture)
              const values = [...fixture.querySelectorAll('.m-tl-scope,.m-step-nm small,.m-step-tag,.m-tl-li small,.m-tl-st,.m-tl-fold,.m-tl-kick,.m-runbar-top,.m-tools-n')].map(e => ({size:parseFloat(getComputedStyle(e).fontSize), spacing:getComputedStyle(e).letterSpacing}))
              fixture.remove()
              return values
            }""")
            self.assertEqual(len(styles), 9)
            self.assertTrue(all(style['size'] >= 11 for style in styles), styles)
            self.assertEqual(errors, [])

    def test_chinese_populated_phone_has_no_visible_text_below_minimum(self):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        # Visible own text and generated content below 11 px, outside the locked card designs (.win) and
        # visually hidden helpers. The ▸/▾ disclosure glyph is a marker, not text.
        small = """() => {
          const shown = e => { for (let n = e; n; n = n.parentElement) { const s = getComputedStyle(n)
            if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false }
            const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2 }
          const out = []
          for (const e of document.querySelectorAll('#m-app *')) {
            if (e.closest('.win, svg')) continue
            const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
            if (!own || !shown(e)) continue
            const size = parseFloat(getComputedStyle(e).fontSize)
            if (size < 10.995) out.push(e.className + ' ' + size)
          }
          return out
        }"""
        fixture = """() => {
          const box = document.createElement('div')
          box.innerHTML = '<div class="m-a"><p>來源 <span class="gk">general knowledge</span></p></div><div class="m-oit"><button>開啟</button></div>'
          document.querySelector('#m-app').append(box)
          const read = e => { const s = getComputedStyle(e); return [parseFloat(s.fontSize), s.letterSpacing] }
          const values = [read(box.querySelector('.gk')), read(box.querySelector('button'))]
          box.remove()
          return values
        }"""
        with mobile_browser() as (browser, base):
            for language in ('en', 'zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                    seed_items(page)
                    gk, link = page.evaluate(fixture)
                    if language == 'en':
                        self.assertEqual((gk[0], link[0]), (10, 11))
                        self.assertNotIn(gk[1], ('0px', 'normal'))
                        self.assertNotIn(link[1], ('0px', 'normal'))
                        continue
                    self.assertEqual((gk, link), ([11, 'normal'], [11, 'normal']))
                    self.assertEqual(page.evaluate(small), [], 'library')
                    page.locator('.m-cell-a[href="#/item/1"]').click()
                    expect(page.locator('.m-it-tools')).to_be_visible()
                    self.assertEqual(page.evaluate(small), [], 'item')
                    page.locator('.m-it-tools').click()
                    expect(page.get_by_role('dialog', name='工具', exact=True)).to_be_visible()
                    self.assertEqual(page.evaluate(small), [], 'item tools')
                    self.assertEqual(errors, [])

    def test_import_blocks_switch_during_commit(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/import', wait_until='domcontentloaded')
            expect(page.locator('.m-sheet-layer')).to_be_visible()
            page.evaluate("""async () => {
              const { mirrorSource } = await import('/src/mobile/state.svelte.ts')
              mirrorSource.importLinks = () => new Promise(resolve => { window.__finishImport = resolve })
            }""")
            content = json.dumps([{'label_values': [{'label': 'URL', 'value': 'https://example.test/item'}]}]).encode()
            page.locator('input[type=file]').last.set_input_files(
                {'name': 'synthetic.json', 'mimeType': 'application/json', 'buffer': content})
            page.wait_for_function('!!window.__finishImport')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result['status'], 'blocked')
            page.evaluate('window.__finishImport({ids:[],dups:0})')
            expect(page.get_by_text('Added 0 links.', exact=True)).to_be_visible()
            self.assertEqual(errors, [])

    def test_unsaved_provider_key_blocks_switch_without_saving_it(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            open_group(page, page.evaluate("async()=>{const {t}=await import('/src/lib/i18n/index.ts');return t('settings.group.ai')}"))
            key = page.get_by_label('OpenAI API key', exact=True)
            expect(key).to_be_visible()
            key.fill('synthetic-unsaved-key')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              const { source } = await import('/src/mobile/state.svelte.ts')
              const before = source.pair.ai.openai ?? null
              const result = await switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
              return { result, before, after: source.pair.ai.openai ?? null }
            }""")
            self.assertEqual(result['result'], {'status': 'blocked', 'reason': 'settings.language.unsavedKeys'})
            self.assertEqual((result['before'], result['after']), (None, None))
            open_group(page, 'Look')
            page.get_by_role('group', name='Language', exact=True).get_by_role('button', name='FR', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Save or clear your key draft')
            self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"), 'en')
            open_group(page, page.evaluate("async()=>{const {t}=await import('/src/lib/i18n/index.ts');return t('settings.group.ai')}"))
            expect(key).to_have_value('synthetic-unsaved-key')
            self.assertIsNone(page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).source.pair.ai.openai ?? null"))
            self.assertEqual(errors, [])

    def test_background_link_read_blocks_switch_while_running(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.wait_for_function("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("""async () => {
              const { mirrorSource, fillLinks } = await import('/src/mobile/state.svelte.ts')
              const read = mirrorSource.linkDetails
              mirrorSource.linkDetails = () => new Promise(resolve => { window.__finishLinks = resolve })
              window.__links = fillLinks().finally(() => { mirrorSource.linkDetails = read })
            }""")
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result['status'], 'blocked')
            page.evaluate('window.__finishLinks([])')
            page.evaluate('window.__links')
            self.assertEqual(errors, [])

    def test_pairing_link_draft_blocks_switch_until_cleared(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/backup', wait_until='domcontentloaded')
            open_group(page, page.evaluate("async()=>{const {t}=await import('/src/lib/i18n/index.ts');return t('backup.group.thisPhone')}"))
            page.get_by_text('Paste the pairing link instead', exact=True).click()
            link = page.get_by_label('Pairing link', exact=True)
            expect(link).to_be_visible()
            link.fill('synthetic pairing draft')
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt), {'status': 'blocked', 'reason': 'settings.language.unsavedPairing'})
            link.fill('')
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertEqual(errors, [])

    def test_refresh_blocks_switch_while_reading(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.wait_for_function("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("""async () => {
              const { source, refresh } = await import('/src/mobile/state.svelte.ts')
              const rows = source.rows
              source.rows = () => new Promise((_, reject) => { window.__failRefresh = reject })
              window.__refresh = refresh().finally(() => { source.rows = rows })
            }""")
            page.wait_for_function('!!window.__failRefresh')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result['status'], 'blocked')
            page.evaluate("window.__failRefresh(Error('synthetic read failure'))")
            page.evaluate('window.__refresh')
            self.assertEqual(errors, [])

    def test_recovery_restore_check_blocks_switch_while_running(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            page.wait_for_function("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }")
            page.evaluate("""async () => {
              const { changes } = await import('/src/mobile/store.ts')
              const { useWithoutPc } = await import('/src/mobile/state.svelte.ts')
              const read = changes.forChat
              changes.forChat = () => new Promise((_, reject) => { window.__failRestoreCheck = reject })
              window.__restoreCheck = useWithoutPc('synthetic-code').finally(() => { changes.forChat = read })
            }""")
            page.wait_for_function('!!window.__failRestoreCheck')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result['status'], 'blocked')
            page.evaluate("window.__failRestoreCheck(Error('synthetic read failure'))")
            self.assertFalse(page.evaluate('window.__restoreCheck'))
            self.assertEqual(errors, [])

    def test_recovery_code_blocks_switch_until_cleared(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/recover', wait_until='domcontentloaded')
            page.get_by_role('button', name='Code', exact=True).click()
            code = page.get_by_label('Original recovery code', exact=True)
            expect(code).to_be_visible()
            code.fill('synthetic-code')
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt), {'status': 'blocked', 'reason': 'settings.language.unsavedRecovery'})
            code.fill('')
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertEqual(errors, [])

    def test_unsent_question_survives_navigation_and_blocks_switch(self):
        from playwright.sync_api import expect

        pair = dict(PAIR, ai={'openai': 'synthetic-key'})
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light', pair=pair) as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/jv', wait_until='domcontentloaded')
            field = page.get_by_role('textbox', name='Question', exact=True)
            expect(field).to_be_enabled()
            field.fill('Keep this synthetic question')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt), {'status': 'blocked', 'reason': 'settings.language.unsentQuestion'})
            page.evaluate("""async () => {
              const { cap } = await import('/src/mobile/capture.svelte.ts')
              cap.ask = { label: 'synthetic attachment', text: 'context' }
            }""")
            page.evaluate("location.hash = '#/jv'")
            expect(field).to_have_value('Keep this synthetic question')
            field.fill('')
            expect(field).to_have_value('What in my library relates to this?')
            expect(page.get_by_text('With synthetic attachment')).to_be_visible()
            field.fill('')
            page.get_by_role('button', name='Leave it out').click()
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertEqual(errors, [])

    def test_canvas_name_blocks_switch_until_cleared(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/canvas/new', wait_until='domcontentloaded')
            name = page.get_by_role('textbox', name='Canvas name')
            expect(name).to_be_visible()
            name.fill('A synthetic canvas')
            attempt = """async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})
            }"""
            self.assertEqual(page.evaluate(attempt), {'status': 'blocked', 'reason': 'settings.language.unsavedCanvas'})
            name.fill('')
            self.assertEqual(page.evaluate(attempt)['status'], 'reloaded')
            self.assertEqual(errors, [])

    def test_capture_file_read_blocks_switch_while_running(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            expect(page.locator('#cap-text')).to_be_visible()
            page.evaluate("""async () => {
              const { source } = await import('/src/mobile/state.svelte.ts')
              source.readFile = () => new Promise(resolve => { window.__finishRead = resolve })
            }""")
            page.locator('input[type=file]').first.set_input_files(
                {'name': 'synthetic.txt', 'mimeType': 'text/plain', 'buffer': b'Example'})
            page.wait_for_function('!!window.__finishRead')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result['status'], 'blocked')
            page.evaluate("window.__finishRead('Synthetic extracted text')")
            expect(page.locator('#cap-text')).to_have_value('Synthetic extracted text')
            self.assertEqual(errors, [])

    def test_pending_capture_debounce_finishes_before_switch(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/cap', wait_until='domcontentloaded')
            field = page.locator('#cap-text')
            expect(field).to_be_visible()
            field.fill('Synthetic capture waiting for the debounce')
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              const { drafts } = await import('/src/mobile/store.ts')
              const result = await Promise.race([
                switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {}),
                new Promise(resolve => setTimeout(() => resolve({status:'timeout'}), 5000))
              ])
              return { result, drafts: await drafts.all() }
            }""")
            self.assertEqual(result['result']['status'], 'reloaded')
            self.assertTrue(any(draft['text'] == 'Synthetic capture waiting for the debounce' for draft in result['drafts']))
            self.assertEqual(errors, [])

    def test_failed_note_save_after_navigation_blocks_reload_until_retry(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            note = test_phone_note_page_browser.PhoneNotePageBrowser().open_note(page, base, expect)
            page.evaluate("""async () => {
              const { source } = await import('/src/mobile/state.svelte.ts')
              const save = source.saveMyNote.bind(source)
              window.__failNoteSave = true
              source.saveMyNote = (...args) => window.__failNoteSave ? Promise.reject(Error('synthetic failure')) : save(...args)
            }""")
            page.get_by_role('textbox', name='Note text', exact=True).fill('Unsaved synthetic note')
            page.evaluate("location.hash = '#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            result = page.evaluate("""async () => {
              const { switchLanguage } = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})
            }""")
            self.assertEqual(result, {'status': 'blocked', 'reason': 'settings.language.unsavedNote'})
            page.evaluate("window.__failNoteSave = false")
            page.evaluate('(file) => { location.hash = `#/mynotes/${encodeURIComponent(file)}` }', note['file'])
            expect(page.get_by_role('textbox', name='Note text', exact=True)).to_have_text('Unsaved synthetic note')
            expect(page.locator('.np-tag')).to_have_attribute('data-s', 'saved')
            self.assertEqual(page.evaluate("""async file => (await (await import('/src/mobile/state.svelte.ts')).source.myNote(file)).body""", note['file']), 'Unsaved synthetic note')
            self.assertEqual(errors, [])

    def test_preview_and_auto_startup_with_failed_import(self):
        from playwright.sync_api import expect

        cases = [
            ('fr', 'en-US', 'fr', 'Brainamon n’a pas pu démarrer', 'Réessayer'),
            ('zh-Hant', 'en-US', 'zh-Hant-TW', '無法啟動 Brainamon', '重試'),
            ('auto', 'fr-FR', 'en', 'Brainamon could not start', 'Retry'),
            ('denied', 'fr-FR', 'en', 'Brainamon could not start', 'Retry'),
        ]
        with mobile_browser() as (browser, base):
            for choice, locale, html_lang, title, retry in cases:
                with self.subTest(choice=choice):
                    context = browser.new_context(locale=locale)
                    try:
                        context.route('**/*', lambda route: route.abort() if
                                      not route.request.url.startswith(base + '/') or
                                      '/src/lib/local-auth.ts' in route.request.url or
                                      '/api/' in route.request.url else route.continue_())
                        context.add_init_script("""(choice => {
                          localStorage.setItem('brainamon-language', 'fr');
                          if (choice !== 'denied') localStorage.setItem('bp-lang', choice);
                          else { const get = Storage.prototype.getItem; Storage.prototype.getItem = function(key) {
                            if (key === 'bp-lang') throw new Error('denied'); return get.call(this, key);
                          }; }
                        })(%s)""" % json.dumps(choice))
                        page = context.new_page()
                        page.goto(base + '/mobile.html', wait_until='domcontentloaded')
                        expect(page.locator('#m-startup-title')).to_have_text(title)
                        expect(page.locator('#m-startup-retry')).to_have_text(retry)
                        self.assertEqual(page.locator('html').get_attribute('lang'), html_lang)
                        self.assertEqual(page.evaluate("localStorage.getItem('brainamon-language')"), 'fr')
                    finally:
                        context.close()


def _text(page, selector, nth=0):
    return page.locator(selector).nth(nth).evaluate('e => e.textContent.trim()')


def _attr(page, selector, name, nth=0):
    return page.locator(selector).nth(nth).get_attribute(name)


# Today's English and the draft French / 繁中 words (unreviewed, projects/phone-languages/GLOSSARY.md) of the controls the scenes read back from the
# page. French keeps the spaces the core pass adds: U+00A0 before ":" and inside « », U+202F before "?".
NB, NN = ' ', ' '
WORDS = {
    'en': dict(
        grid=dict(settings='Settings', library='Library', canvas='Canvas', search='Search', placeholder='search titles, creators, tags',
                  field='Search the library', dock='Actions', notes='Notes', ask='Ask Wiskit', ask_text='Ask Wiskit', add='Add',
                  collections='Collections', favs='★ Favs0', heading='Art', sort='Sort', sorts=['Newest', 'Oldest', 'A to Z', 'Z to A'],
                  view='Show as rows', tools='Tools', summary='80 items · newest first'),
        search=dict(smart='Smart', rank='Rank by meaning', close='Close search', heading='Results', synthesize='Synthesize'),
        sync=dict(label='Sync', head='Sync with Google Drive', close='Close the sync panel', now='Sync now', backup='Backup & phones ›'),
        item=dict(title='Item', back='Back', delete='Delete', open='Open in Instagram', collection='Choose collection: Art', type='· Reel',
                  tabs=['Description', 'Info'], fav='Favourite', edit_tags='Edit tags', tools='Tools', by='by @chef.marco', strip='Items'),
        info=dict(labels=['No.', 'Saved', 'Link', 'Tags', 'Notes', 'AI'], ai='Not described yet', tags='none', edit='Edit',
                  date=r'^\d{2} [A-Z][a-z]{2} 202[56]$'),
        video=dict(title='Video from your PC', line='0.0 MB · downloads from Google Drive · plays the PC’s copy, not the original site', play='▶ Play'),
        delete=dict(title='Delete "Saved item 2"?', body='It is deleted for good.', buttons=['Cancel', 'Delete']),
        help=dict(title='On this phone', label='More info: On this phone', close='Close'),
        picker=dict(title='Choose collection', field='Search collection', placeholder='Search…', group='Collection choices', close='Close'),
        tags=dict(placeholder='comma, separated, tags', cancel='Cancel', save='Save')),
    'fr': dict(
        grid=dict(settings='Paramètres', library='Bibliothèque', canvas='Canvas', search='Rechercher', placeholder='rechercher titres, auteurs, tags',
                  field='Rechercher dans la bibliothèque', dock='Actions', notes='Notes', ask='Demander à Wiskit', ask_text='Demander à Wiskit', add='Ajouter',
                  collections='Collections', favs='★ Favoris0', heading='Art', sort='Trier', sorts=['Plus récents', 'Plus anciens', 'A à Z', 'Z à A'],
                  view='Afficher en lignes', tools='Outils', summary='80 éléments · plus récents d’abord'),
        search=dict(smart='Sémantique', rank='Trier par sens', close='Fermer la recherche', heading='Résultats', synthesize='Synthèse'),
        sync=dict(label='Synchronisation', head='Synchronisation avec Google Drive', close='Fermer le panneau de synchronisation', now='Synchroniser',
                  backup='Sauvegarde et téléphones ›'),
        item=dict(title='Élément', back='Retour', delete='Supprimer', open='Ouvrir dans Instagram', collection=f'Choisir{NB}: collection (Art)', type='· Reel',
                  tabs=['Description', 'Infos'], fav='Favori', edit_tags='Modifier les tags', tools='Outils', by='par @chef.marco', strip='Éléments'),
        info=dict(labels=['No.', 'Enregistré', 'Lien', 'Tags', 'Notes', 'IA'], ai='Pas encore décrit', tags='aucun', edit='Modifier',
                  date=r'^\d{2} (janv\.|févr\.|mars|avr\.|mai|juin|juil\.|août|sept\.|oct\.|nov\.|déc\.) 202[56]$'),
        video=dict(title='Vidéo depuis votre PC', line='0,0 Mo · se télécharge depuis Google Drive · lit la copie du PC, pas le site d’origine', play='▶ Lire'),
        delete=dict(title=f'Supprimer «{NB}Saved item 2{NB}»{NN}?', body='Il est supprimé définitivement.', buttons=['Annuler', 'Supprimer']),
        help=dict(title='Sur ce téléphone', label=f'Plus d’informations{NB}: Sur ce téléphone', close='Fermer'),
        picker=dict(title=f'Choisir{NB}: collection', field=f'Rechercher{NB}: collection', placeholder='Rechercher…', group=f'Collection{NB}: choix', close='Fermer'),
        tags=dict(placeholder='tags, séparés, par des virgules', cancel='Annuler', save='Enregistrer')),
    'zh-Hant': dict(
        grid=dict(settings='設定', library='資料庫', canvas='畫布', search='搜尋', placeholder='搜尋標題、作者、標籤', field='搜尋資料庫', dock='操作',
                  notes='筆記', ask='詢問 Wiskit', ask_text='詢問 Wiskit', add='新增', collections='收藏分類', favs='★ 最愛0', heading='Art', sort='排序',
                  sorts=['最新', '最舊', 'A 到 Z', 'Z 到 A'], view='以列表顯示', tools='工具', summary='80 個項目・最新優先'),
        search=dict(smart='語意', rank='依語意排序', close='關閉搜尋', heading='搜尋結果', synthesize='綜合'),
        sync=dict(label='同步', head='與 Google 雲端硬碟同步', close='關閉同步面板', now='立即同步', backup='備份與手機 ›'),
        item=dict(title='項目', back='返回', delete='刪除', open='在 Instagram 開啟', collection='選擇收藏分類：Art', type='· Reels',
                  tabs=['描述', '資訊'], fav='最愛', edit_tags='編輯標籤', tools='工具', by='作者 @chef.marco', strip='項目'),
        info=dict(labels=['No.', '已儲存', '連結', '標籤', '筆記', 'AI'], ai='尚未描述', tags='無', edit='編輯', date=r'^202[56]年11月\d{2}日$'),
        video=dict(title='來自你電腦的影片', line='0.0 MB・從 Google 雲端硬碟下載・播放的是電腦上的副本，而非原始網站', play='▶ 播放'),
        delete=dict(title='刪除「Saved item 2」？', body='將永久刪除。', buttons=['取消', '刪除']),
        help=dict(title='在這支手機上', label='更多資訊：在這支手機上', close='關閉'),
        picker=dict(title='選擇收藏分類', field='搜尋收藏分類', placeholder='搜尋……', group='收藏分類的選項', close='關閉'),
        tags=dict(placeholder='以逗號分隔多個標籤', cancel='取消', save='儲存')),
}


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneShellLibraryItemScenes(unittest.TestCase):
    """Plan 02: shell, Library, Item, strip and card words, 360 x 740 in light and dark (synthetic rows, API blocked).
    French and 繁中 read back their draft words and shoot every scene into local/i18n-review/; English reads back today's words."""

    def play(self, page, language, theme, shoot):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        words = WORDS[language]
        seed_items(page)
        expect(page.locator('.m-top')).to_be_visible()
        self.assertEqual(page.locator('html').get_attribute('lang'), {'en': 'en', 'fr': 'fr', 'zh-Hant': 'zh-Hant-TW'}[language])
        # S1: the Library page with the top bar, dock, chips, toolbar and summary line
        got = dict(settings=_attr(page, '.m-top a[href="#/more"]', 'aria-label'), library=_attr(page, '.m-top a[href="#/lib"]', 'aria-label'),
                   canvas=_attr(page, '.m-top a[href="#/canvas"]', 'aria-label'), search=_attr(page, '.m-find-key', 'aria-label'),
                   placeholder=_attr(page, '.m-find-in', 'placeholder'), field=_attr(page, '.m-find-in', 'aria-label'),
                   dock=_attr(page, '.m-dock', 'aria-label'), notes=_attr(page, '.m-vt-notes', 'aria-label'), ask=_attr(page, '.m-askbox', 'aria-label'),
                   ask_text=_text(page, '.m-askbox > span:last-child'), add=_attr(page, '.m-vt-cap', 'aria-label'),
                   collections=_attr(page, '.m-chips', 'aria-label'), favs=_text(page, '.m-chips .m-chip'), heading=_text(page, '.m-mathd h3'),
                   sort=_attr(page, '.m-lib-sort select', 'aria-label'), sorts=page.locator('.m-lib-sort option').all_text_contents(),
                   view=_attr(page, '.m-lib-view', 'aria-label'), tools=_attr(page, '.m-lib-tools', 'aria-label'), summary=_text(page, '.m-lib-sum'))
        self.assertEqual(got, words['grid'])
        self.assertEqual(_text(page, '.m-top a[href="#/lib"]'), words['grid']['library'])
        self.assertEqual(page.locator('.m-askbox b').count(), 1)
        shoot('lib-grid')
        page.locator('.m-lib-view').click()
        expect(page.locator('.m-gallery-row').first).to_be_visible()
        shoot('lib-rows')
        page.locator('.m-lib-view').click()
        expect(page.locator('.m-grid .slot').first).to_be_visible()
        # S2: search with the Smart toggle, the Results heading and Synthesize
        page.locator('.m-find-key').click()
        page.locator('.m-find-in').fill('@chef')
        expect(page.locator('.m-tg')).to_be_visible()
        expect(page.locator('.m-mathd a.m-btn')).to_be_visible()      # the query has been taken: Results and Synthesize
        got = dict(smart=_text(page, '.m-tg'), rank=_attr(page, '.m-tg', 'title'), close=_attr(page, '.m-find-x', 'aria-label'),
                   heading=_text(page, '.m-mathd h3'), synthesize=_text(page, '.m-mathd a.m-btn'))
        self.assertEqual(got, words['search'])
        shoot('lib-search')
        page.locator('.m-find-in').press('Escape')
        expect(page.locator('.m-top.searching')).to_have_count(0)
        expect(page.locator('.m-mathd h3')).to_have_text(words['grid']['heading'])      # the query is cleared again
        # S3: the sync panel (the paired-or-not branch changes its buttons; these two are in both)
        page.locator('.m-sync-key').click()
        expect(page.locator('#m-sync-panel')).to_be_visible()
        buttons = page.locator('.m-syncp-btns > *').all_text_contents()
        got = dict(label=_attr(page, '#m-sync-panel', 'aria-label'), head=_text(page, '.m-syncp-head span'), close=_attr(page, '.m-syncp-fold', 'aria-label'))
        self.assertEqual(got, {k: words['sync'][k] for k in ('label', 'head', 'close')})
        self.assertIn(words['sync']['now'], buttons)
        self.assertIn(words['sync']['backup'], buttons)
        shoot('sync-panel')
        page.keyboard.press('Escape')
        expect(page.locator('#m-sync-panel')).to_have_count(0)
        # S11: processing marks over the cards: the six known tokens get words, any other token shows as stored
        page.evaluate("""async () => { const { work } = await import('/src/mobile/work.svelte.ts')
          const marks = [['wait', 'FETCH'], ['run', 'DESCRIBE'], ['done', 'SORT'], ['err', 'ANALYZE'], ['skip', 'INDEX'], ['run', 'YT-DLP'], ['run', 'NOTE']]
          marks.forEach(([st, tag], i) => work.set(i + 1, { st, lane: 'phone', tag, keep: true })) }""")
        expect(page.locator('.m-w-tag').first).to_be_visible()
        tags = page.locator('.m-w-tag').all_text_contents()
        expected_tags = dict(
            en=['WAITING', 'DESCRIBE', 'SORT', 'ANALYZE', 'INDEX', 'YT-DLP', 'NOTE'],
            fr=['ATTENTE', 'DÉCRIRE', 'CLASSER', 'ANALYSER', 'INDEXER', 'YT-DLP', 'NOTE'],
            **{'zh-Hant': ['等待中', '描述', '分類', '分析', '索引', 'YT-DLP', '筆記']})[language]
        self.assertEqual(tags[:7], expected_tags)
        labels = [_attr(page, f'.m-cell-a[href="#/item/{i}"]', 'aria-label') for i in (1, 2, 3, 4, 5)]
        states = dict(
            en=['waiting for processing', 'processing now', 'processed', 'processing failed', 'processing failed'],
            fr=['en attente de traitement', 'en cours de traitement', 'traité', 'échec du traitement', 'échec du traitement'],
            **{'zh-Hant': ['等待處理中', '處理中', '已處理', '處理失敗', '處理失敗']})[language]
        for label, state in zip(labels, states):
            self.assertTrue(label.endswith(', ' + state) or label.endswith('，' + state), label)
        shoot('lib-work')
        page.evaluate("async () => { (await import('/src/mobile/work.svelte.ts')).work.clear() }")
        # S5: the Library without a card, its error with Try again, its loading line and an empty search
        page.evaluate("""async () => { const { phone } = await import('/src/mobile/state.svelte.ts')
          window.__rows = phone.rows; window.__cats = phone.cats; phone.rows = []; phone.cats = []; phone.cat = 'all'; phone.loaded = true; phone.error = '' }""")
        expect(page.locator('.m-ob-empty')).to_be_visible()
        empty = dict(en=('Your library is empty', 'Share a post to Brainamon from any app, or add one here.', 'Add your first save'),
                     fr=('Votre bibliothèque est vide', 'Partagez une publication vers Brainamon depuis n’importe quelle application, ou ajoutez-en une ici.',
                         'Ajouter votre premier enregistrement'),
                     **{'zh-Hant': ('你的資料庫是空的', '從任何應用程式分享貼文到 Brainamon，或在這裡新增。', '新增你的第一筆收藏')})[language]
        self.assertEqual((_text(page, '.m-ob-empty h3'), _text(page, '.m-ob-empty p'), _text(page, '.m-ob-empty button')), empty)
        shoot('lib-empty')
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); phone.error = 'Synthetic failure' }")
        expect(page.locator('.m-err')).to_be_visible()
        retry = dict(en='Try again', fr='Réessayer', **{'zh-Hant': '再試一次'})[language]
        self.assertEqual(_text(page, '.m-err button'), retry)
        shoot('lib-error')
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); phone.error = ''; phone.load = { text: '', frac: 0 }; phone.loaded = false }")      # no refresh words yet: the catalog's Starting
        expect(page.locator('.m-load')).to_be_visible()
        loading = dict(en=('Loading the library…', 'Starting'), fr=('Chargement de la bibliothèque…', 'Démarrage'),
                       **{'zh-Hant': ('正在載入資料庫……', '啟動中')})[language]
        self.assertEqual((page.locator('.m-load').evaluate('e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join("").trim()'), _text(page, '.m-load small')), loading)
        self.assertEqual(_attr(page, '.m-load-bar', 'aria-label'), loading[0].rstrip('…'))
        shoot('lib-loading')
        page.evaluate("""async () => { const { phone } = await import('/src/mobile/state.svelte.ts')
          phone.rows = window.__rows; phone.cats = window.__cats; phone.cat = 'Art'; phone.loaded = true; phone.q = 'zzzz'; phone.searchIds = new Set() }""")
        none = dict(en='Nothing matches.', fr='Aucun résultat.', **{'zh-Hant': '沒有符合的項目。'})[language]
        self.assertEqual(_text(page, '.m-main .m-empty'), none)
        shoot('lib-nomatch')
        page.evaluate("""async () => { const { phone } = await import('/src/mobile/state.svelte.ts')
          phone.q = ''; phone.searchIds = null; phone.signIn = true }""")
        expect(page.locator('.m-lib-tail')).to_be_visible()
        tail = dict(en='Google Drive disconnected', fr='Google Drive déconnecté', **{'zh-Hant': 'Google 雲端硬碟已中斷連線'})[language]
        self.assertTrue(_text(page, '.m-lib-tail').startswith('· ' + tail), _text(page, '.m-lib-tail'))
        shoot('lib-drive-off')
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); phone.signIn = false }")
        # S6: the Item screen, Cover first
        page.locator('.m-cell-a[href="#/item/2"]').click()
        expect(page.locator('.m-it-stage .slot')).to_be_visible()
        item = words['item']
        got = dict(title=_text(page, '.m-it-over .m-ws'), back=_attr(page, '.m-it-over .m-key', 'aria-label'), delete=_attr(page, '.m-it-delete', 'aria-label'),
                   open=_attr(page, '.m-it-open-corner', 'aria-label'), collection=_attr(page, '.m-it-collection', 'aria-label'),
                   type=_text(page, '.m-it-format'), tabs=page.locator('.m-tabline button').all_text_contents(), fav=_attr(page, '.m-it-fav', 'aria-label'),
                   edit_tags=_attr(page, '.m-it-keys > .m-key:nth-child(2)', 'aria-label'), tools=_attr(page, '.m-it-tools', 'aria-label'),
                   by=_text(page, '.m-it-by'), strip=_attr(page, '.m-item-strip', 'aria-label'))
        self.assertEqual(got, item)
        self.assertEqual(_text(page, '.m-it-open'), item['open'])
        self.assertTrue(page.locator('.m-it-stage .slot.v-full').count() == 1)
        shoot('item-cover')
        page.locator('.m-tabline button').nth(1).click()
        expect(page.locator('.m-it-info')).to_be_visible()
        info = words['info']
        self.assertEqual(page.locator('.m-it-info dt').all_text_contents(), info['labels'])
        dates = page.locator('.m-it-info dd').all_text_contents()
        self.assertRegex(dates[0] if info['labels'][0] != 'No.' else dates[1], info['date'])
        self.assertEqual(_text(page, '.m-it-tags span'), info['tags'])
        self.assertEqual(_text(page, '.m-it-tags button'), info['edit'])
        self.assertEqual(dates[-1], info['ai'])
        columns = page.locator('.m-it-info').evaluate('e => getComputedStyle(e).gridTemplateColumns.split(" ")[0]')
        self.assertTrue(float(columns[:-2]) >= 52 and (language != 'en' or columns == '52px'), columns)    # English keeps its 52 px label column
        shoot('item-info')
        page.locator('.m-it-tags button').click()
        expect(page.locator('.m-it-tags input')).to_be_visible()
        tags = words['tags']
        self.assertEqual((_attr(page, '.m-it-tags input', 'placeholder'), page.locator('.m-it-tags .m-acts button').all_text_contents()),
                         (tags['placeholder'], [tags['cancel'], tags['save']]))
        shoot('item-tags')
        page.locator('.m-it-tags .m-acts button').first.click()
        # Holo after Favourite
        page.locator('.m-it-fav').click()
        expect(page.locator('.m-it-stage .slot.v-fa2')).to_be_visible()
        shoot('item-holo')
        page.locator('.m-it-fav').click()
        expect(page.locator('.m-it-stage .slot.v-full')).to_be_visible()
        # delete dialog (this phone is solo, so one scope)
        page.locator('.m-it-delete').click()
        dialog = page.locator('dialog.m-dialog[open]')
        expect(dialog).to_be_visible()
        gone = words['delete']
        self.assertEqual((dialog.locator('h2').evaluate('e => e.textContent'), dialog.locator('.m-dialog-body p').evaluate('e => e.textContent'),
                          dialog.locator('.m-dialog-actions button').all_text_contents()), (gone['title'], gone['body'], gone['buttons']))
        shoot('item-delete')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        # S9: the Collection picker and the phone help
        page.locator('.m-it-collection').click()
        sheet = page.locator('dialog.m-picker-sheet[open]')
        expect(sheet).to_be_visible()
        pick = words['picker']
        got = dict(title=sheet.locator('h2').evaluate('e => e.textContent'), field=sheet.locator('input[type=search]').get_attribute('aria-label'),
                   placeholder=sheet.locator('input[type=search]').get_attribute('placeholder'),
                   group=sheet.locator('.m-picker-options').get_attribute('aria-label'), close=sheet.locator('.m-cap-tools-head button').evaluate('e => e.textContent'))
        self.assertEqual(got, pick)
        shoot('picker')
        sheet.locator('input[type=search]').fill('zzzzzz')
        none = dict(en='No matches.', fr='Aucun résultat.', **{'zh-Hant': '沒有符合的項目。'})[language]
        self.assertEqual(sheet.locator('.m-picker-options p').evaluate('e => e.textContent'), none)
        page.keyboard.press('Escape')
        expect(sheet).to_have_count(0)
        page.locator('.m-it-phone .m-info').click()
        help_dialog = page.locator('dialog.m-info-dialog[open]')
        expect(help_dialog).to_be_visible()
        aid = words['help']
        self.assertEqual((_attr(page, '.m-it-phone .m-info', 'aria-label'), help_dialog.locator('h2').evaluate('e => e.textContent'),
                          help_dialog.locator('.m-info-head button').evaluate('e => e.textContent')), (aid['label'], aid['title'], aid['close']))
        shoot('item-help')
        page.keyboard.press('Escape')
        expect(help_dialog).to_have_count(0)
        # a video held on the PC
        page.evaluate("location.hash = '#/item/3'")
        expect(page.locator('.m-vid')).to_be_visible()
        video = words['video']
        self.assertEqual((_text(page, '.m-vid b'), _text(page, '.m-vid small'), _text(page, '.m-vid button')), (video['title'], video['line'], video['play']))
        shoot('item-video')
        # S7: the strip while a finger moves along it
        box = page.locator('.m-item-strip').bounding_box()
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 70, y, steps=6)
        expect(page.locator('.m-item-preview')).to_be_visible()
        self.assertRegex(_text(page, '.m-item-preview .m-ws'), r'^\d+ / \d+$')
        shoot('strip-drag')
        page.mouse.up()
        # S8 / S10: the sheets and the pages' keys
        for hash_, name, sel in (('#/notes', 'sheet-notes', '.m-sheet-layer'), ('#/jv', 'sheet-wiskit', '.m-sheet-layer'), ('#/cap', 'sheet-add', '.m-sheet-layer'),
                                 ('#/more', 'page-more', '.m-page-keys'), ('#/backup', 'page-backup', '.m-page-keys'), ('#/recover', 'page-recover', '.m-page-keys')):
            page.evaluate("h => { location.hash = h }", hash_)
            expect(page.locator(sel).first).to_be_visible()
            page.wait_for_timeout(250)
            if sel == '.m-page-keys':
                tag = dict(en=dict(more='Settings', backup='Backup', recover='Recover'), fr=dict(more='Paramètres', backup='Sauvegarde', recover='Récupérer'),
                           **{'zh-Hant': dict(more='設定', backup='備份', recover='復原')})[language][name.split('-')[1]]
                self.assertEqual(_text(page, '.m-page-keys .m-ws'), tag)
                self.assertEqual(_attr(page, '.m-page-keys .m-key', 'aria-label'), item['back'])
            else:
                key = dict(en=dict(notes='Close Notes', wiskit='Close Wiskit', add='Close Add'), fr=dict(notes='Fermer Notes', wiskit='Fermer Wiskit', add='Fermer Ajouter'),
                           **{'zh-Hant': dict(notes='關閉筆記', wiskit='關閉Wiskit', add='關閉新增')})[language][name.split('-')[1]]
                self.assertEqual(_attr(page, '.m-sheet-keys .m-key, .m-sheet-head .m-back', 'aria-label'), key)
            shoot(name)

    def test_scenes_in_the_preview_languages(self):
        with mobile_browser() as (browser, base):
            for language in ('fr', 'zh-Hant'):
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        stacks = []
                        page.on('pageerror', lambda error: stacks.append(getattr(error, 'stack', None) or str(error)))
                        page.route('**/api/**', lambda route: route.abort())
                        page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                        self.play(page, language, theme, lambda name: check_scene(self, page, language, theme, name))
                        self.assertEqual(errors, [], stacks)

    def test_card_words_never_touch_user_text_and_keep_the_rows(self):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        rows = r"""async () => { const { phone } = await import('/src/mobile/state.svelte.ts')
          const base = { tags: '', desc: 'Flag Interesting {name} "q" \'s', src: 'web', thumb: true, ai: true, an: false, nd: 0, tv: 0 }
          phone.rows = [
            { ...base, id: 1, title: 'NEW', creator: 'Common', type: 'Short', cat: 'unknown', url: 'https://example.com/NEW/Common/unknown', fav: false, created: Date.now() - 3600e3 },
            { ...base, id: 2, title: '<img src=x onerror="window.__xss=1">', creator: '', type: 'Reel', cat: 'Art', url: 'https://example.com/b', fav: true, created: Date.now() - 3600e3 },
            { ...base, id: 3, title: 'Plain', creator: 'unknown', type: 'Post', cat: 'Art', url: 'https://example.com/c', fav: false, created: Date.now() - 30 * 86400e3 }]
          phone.cats = [{ name: 'Art', color: '#39776b', count: 2 }, { name: 'unknown', color: '#bc6c25', count: 1 }]
          phone.cat = 'all'; phone.fav = false; phone.q = ''; phone.sort = 'old'; phone.loaded = true; phone.error = ''
          window.__before = JSON.stringify(phone.rows) }"""
        read = """slot => { const text = sel => slot.querySelector(sel)?.textContent ?? null, stat = n => slot.querySelector(`.st>div:nth-child(${n}), .fa-st>div:nth-child(${n})`)
          return { holo: slot.classList.contains('v-fa2'), title: text('.nm, .fa-nm'), cat: text('.ab em, .fa-ab em'), chip: text('.new, .fa-new'),
            stage: text('.stage, .fa-stage'), evo: text('.evo, .fa-evo'), added: stat(1).querySelector('small').textContent,
            label: stat(2).querySelector('small').textContent, creator: stat(2).querySelector('b').textContent,
            size: stat(3).querySelector('small').textContent, type: stat(3).querySelector('b').textContent,
            illus: text('.il, .fa-il'), desc: text('.ds, .fa-ds') } }"""
        words = dict(
            en=dict(chip='NEW', stage='Reel', evo=r'^Saved from Web · \d{2} [A-Z][a-z]{2} 20\d{2}$', added='added', label='creator', size='size',
                    unknown='unknown', illus='Illus. ', types={'Reel': 'Reel', 'Post': 'Post'}),
            fr=dict(chip='NOUVEAU', stage='Reel', evo=r'^Enregistré depuis Web · \d{2} .+ 20\d{2}$', added='ajouté', label='auteur', size='taille',
                    unknown='inconnu', illus='Illus. ', types={'Reel': 'Reel', 'Post': 'Publication'}),
            **{'zh-Hant': dict(chip='新增', stage='Reels', evo=r'^儲存自 網頁・.+$', added='加入於', label='作者', size='大小',
                               unknown='不詳', illus='插畫家 ', types={'Reel': 'Reels', 'Post': '貼文'})})
        hostile_title = '<img src=x onerror="window.__xss=1">'
        with mobile_browser() as (browser, base):
            for language, w in words.items():
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                    seed_items(page)
                    page.evaluate(rows)
                    expect(page.locator('.m-cell .slot')).to_have_count(3)
                    got = {i: page.locator(f'.m-cell:has(a[href="#/item/{i}"]) .slot').evaluate(read) for i in (1, 2, 3)}
                    for i, card in got.items():
                        self.assertEqual((card['stage'], card['added'], card['label'], card['size']), (w['stage'], w['added'], w['label'], w['size']), (language, i))
                        self.assertRegex(card['evo'], w['evo'])
                        self.assertEqual(card['desc'], 'Flag Interesting {name} "q" \'s')          # user text, braces and quotes included
                    # a title, creator and category that read like engine words stay as stored; an unknown type is not a known one
                    self.assertEqual((got[1]['title'], got[1]['cat'], got[1]['creator'], got[1]['illus'], got[1]['type'], got[1]['chip'], got[1]['holo']),
                                     ('NEW', 'unknown', 'Common', w['illus'] + 'Common', 'Short', w['chip'], False))
                    # hostile markup is text, never an element; an empty creator falls back, a stored "unknown" does not; a favourite is the Holo
                    self.assertEqual((got[2]['title'], got[2]['creator'], got[2]['illus'], got[2]['type'], got[2]['chip'], got[2]['holo']),
                                     (hostile_title, w['unknown'], w['illus'] + w['unknown'], w['types']['Reel'], w['chip'], True))
                    self.assertEqual((got[3]['creator'], got[3]['illus'], got[3]['type'], got[3]['chip'], got[3]['holo']),
                                     ('unknown', w['illus'] + 'unknown', w['types']['Post'], None, False))
                    self.assertIsNone(page.evaluate('window.__xss'))
                    self.assertEqual(page.locator('.m-grid img[src="x"]').count(), 0)
                    # the same words on the Item screen's own card, and the row list is exactly as it was
                    for i in (1, 2):
                        page.evaluate("id => { location.hash = '#/item/' + id }", i)
                        expect(page.locator('.m-it-stage .slot')).to_be_visible()
                        card = page.locator('.m-it-stage .slot').evaluate(read)
                        self.assertEqual((card['title'], card['creator'], card['chip'], card['holo']), (got[i]['title'], got[i]['creator'], got[i]['chip'], i == 2), (language, i))
                    self.assertEqual(_text(page, '.m-it-format'), '· ' + w['types']['Reel'])
                    self.assertIsNone(page.evaluate('window.__xss'))
                    self.assertEqual(page.evaluate("async () => JSON.stringify((await import('/src/mobile/state.svelte.ts')).phone.rows) === window.__before"), True)
                    self.assertEqual(errors, [])

    def test_one_many_and_long_items_and_larger_text_hold_in_the_preview_languages(self):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed, seed_items

        one = r"""async () => { const { phone } = await import('/src/mobile/state.svelte.ts')
          phone.rows = [{ id: 1, title: 'A very long synthetic title that keeps going '.repeat(5) + 'x'.repeat(70), creator: '@' + 'creatorname'.repeat(9), type: 'Reel',
            cat: 'Art', tags: 'one, two', desc: 'Caption', url: 'https://example.com/' + 'segment-'.repeat(20) + 'end', src: 'instagram', thumb: false, ai: false, an: false,
            nd: 0, fav: false, created: Date.UTC(2026, 10, 6), tv: 0 }]
          phone.cats = [{ name: 'Art', color: '#39776b', count: 1 }]; phone.cat = 'all'; phone.q = ''; phone.loaded = true; phone.error = '' }"""
        summary = dict(en='1 item · newest first', fr='1 élément · plus récents d’abord', **{'zh-Hant': '1 個項目・最新優先'})
        many = dict(en='3,000 items · newest first', fr='3 000 éléments · plus récents d’abord', **{'zh-Hant': '3,000 個項目・最新優先'})
        counts = {}
        with mobile_browser() as (browser, base):
            for language in ('en', 'fr', 'zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                    shoot = lambda name: (check_scene(self, page, language, 'light', name) if language != 'en' else self.assertEqual(page.evaluate(SCENE_CHECK), [], 'en ' + name))
                    # many: 3,000 cards, the grouped count in the page language
                    seed(page)
                    expect(page.locator('.m-lib-sum')).to_be_visible()
                    self.assertEqual(re.sub('[  ]', ' ', _text(page, '.m-lib-sum')), many[language])
                    shoot('lib-many')
                    # one card with a long title, a long creator and an unbreakable URL: grid, rows, Item and its info
                    page.evaluate(one)
                    expect(page.locator('.m-cell')).to_have_count(1)
                    self.assertEqual(_text(page, '.m-lib-sum'), summary[language])
                    shoot('lib-one-long')
                    page.locator('.m-lib-view').click()
                    expect(page.locator('.m-gallery-row')).to_be_visible()
                    shoot('lib-rows-long')
                    page.locator('.m-cell-a').click()
                    expect(page.locator('.m-it-tt')).to_be_visible()
                    shoot('item-long')
                    self.assertEqual(page.locator('.m-item-strip').count(), 0)      # one card: no strip
                    page.locator('.m-tabline button').nth(1).click()
                    expect(page.locator('.m-it-info')).to_be_visible()
                    shoot('item-info-long')
                    # larger text: the browser cannot set Android's font scale, so a 320 px wide page (the narrowest phone, and what a larger scale
                    # leaves a row) stands in; a preview language may not add a kind of problem that English does not have there
                    page.evaluate("location.hash = '#/lib'")
                    seed_items(page)
                    page.set_viewport_size({'width': 320, 'height': 720})
                    page.wait_for_timeout(300)
                    kinds = {}
                    for problem in page.evaluate(SCENE_CHECK):
                        kind = re.sub(r':.*', '', problem)
                        kinds[kind] = kinds.get(kind, 0) + 1
                    counts[language] = kinds
                    if language != 'en':
                        REVIEW.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(REVIEW / f'02-{language}-light-lib-320.png'))
                    self.assertEqual(errors, [])
        for language in ('fr', 'zh-Hant'):
            for kind, n in counts[language].items():
                # at 320 px the active top pill may give way with an ellipsis (French "Bibliothèque"); nothing else may be new
                self.assertLessEqual(n, counts['en'].get(kind, 0) + (1 if kind == 'ellipsized' else 0), f'{language}: {kind} (English: {counts["en"]})')

    def test_two_scope_delete_dialog_in_every_language(self):
        # a phone paired with a PC offers "This phone" and "Phone and PC"; the solo scenes above only show the one-scope dialog
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        want = dict(
            en=('From this phone hides it here only; the PC library keeps it. Phone and PC deletes it on the PC too, the next time the PC runs.',
                ['Cancel', 'This phone', 'Phone and PC']),
            fr=('Ce téléphone le masque ici seulement ; la bibliothèque du PC le conserve. Téléphone et PC le supprime aussi sur le PC, au prochain lancement du PC.',
                ['Annuler', 'Ce téléphone', 'Téléphone et PC']),
            **{'zh-Hant': ('選「這支手機」只會在這裡隱藏它，電腦的資料庫仍會保留。選「手機和電腦」則會在電腦下次執行時一併刪除。', ['取消', '這支手機', '手機和電腦'])})
        with mobile_browser() as (browser, base):
            for language, (body, buttons) in want.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language,
                                                                                       pair={**PAIR, 'solo': False}) as (page, errors):
                        page.route('**/api/**', lambda route: route.abort())
                        page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                        seed_items(page)
                        page.locator('.m-cell-a[href="#/item/2"]').click()
                        expect(page.locator('.m-it-delete')).to_be_visible()
                        page.locator('.m-it-delete').click()
                        dialog = page.locator('dialog.m-dialog[open]')
                        expect(dialog).to_be_visible()
                        # French typography adds U+00A0 before ";" and U+202F ... compare with the plain spaces the catalog holds
                        shown = re.sub('[  ]', ' ', dialog.locator('.m-dialog-body p').evaluate('e => e.textContent'))
                        self.assertEqual(shown, body)
                        self.assertEqual(dialog.locator('.m-dialog-actions button').all_text_contents(), buttons)
                        if language == 'en':
                            self.assertEqual(page.evaluate(SCENE_CHECK), [], 'en item-delete-two')
                        else:
                            check_scene(self, page, language, theme, 'item-delete-two')
                        self.assertEqual(errors, [])

    def test_keyboard_reaches_the_translated_controls(self):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        with mobile_browser() as (browser, base):
            for language in ('fr', 'zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                    seed_items(page)
                    expect(page.locator('.m-top')).to_be_visible()
                    names = []
                    for _ in range(14):
                        page.keyboard.press('Tab')
                        names.append(page.evaluate("() => { const e = document.activeElement; return (e.getAttribute('aria-label') || e.title || e.textContent || '').trim() }"))
                    self.assertTrue(all(names), names)
                    self.assertFalse([n for n in names if re.search(r'\b(?:common|shell|library|item)\.[a-z]', n)], names)
                    grid = WORDS[language]['grid']
                    for name in (grid['settings'], grid['library'], grid['canvas'], grid['search']):
                        self.assertIn(name, names)
                    self.assertEqual(page.locator(':focus-visible').count() >= 1, True)
                    self.assertEqual(errors, [])

    def test_video_play_is_disabled_while_downloading_and_works_again_after_a_failure(self):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items

        want = {'en': ('Downloading 42%', 'Synthetic video failure'), 'fr': ('Téléchargement 42 %', 'Une erreur est survenue : Synthetic video failure'),
                'zh-Hant': ('正在下載 42%', '發生錯誤：Synthetic video failure')}
        with mobile_browser() as (browser, base):
            for language, (downloading, failure) in want.items():
                with self.subTest(language=language), synthetic_phone(browser, base, 360, 740, 'light', language=language) as (page, errors):
                    page.route('**/api/**', lambda route: route.abort())
                    page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
                    seed_items(page)
                    page.evaluate("""async () => { const { source } = await import('/src/mobile/state.svelte.ts'); const inner = source.video
                      window.__videoCalls = 0; source.video = (...args) => { window.__videoCalls++; return inner(...args) } }""")
                    page.evaluate("location.hash = '#/item/3'")
                    play = page.locator('.m-vid button')
                    expect(play).to_be_enabled()
                    # a failure shows its detail inside a sentence of the page language (English: the detail alone) and Play can be tried again
                    page.evaluate("window.__items.fail = 'video'")
                    play.click()
                    expect(page.locator('.m-vid small')).to_contain_text(failure)
                    if language == 'en':
                        self.assertTrue(_text(page, '.m-vid small').startswith('Synthetic video failure'))
                    expect(play).to_be_enabled()
                    # in flight: the progress words show, Play is disabled in every language, and a second click starts nothing
                    page.evaluate("window.__items.fail = ''")
                    play.click()
                    expect(page.locator('.m-vid small')).to_contain_text(downloading)
                    expect(play).to_be_disabled()
                    play.click(force=True)
                    self.assertEqual(page.evaluate('window.__videoCalls'), 2)          # the failed try and the one in flight
                    page.evaluate('window.__items.finishVideo()')
                    expect(page.locator('video.m-video')).to_be_visible()
                    self.assertEqual(errors, [])

    def test_english_words_are_today_s(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light', language='en') as (page, errors):
            page.route('**/api/**', lambda route: route.abort())
            page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
            self.play(page, 'en', 'light', lambda name: self.assertEqual(page.evaluate(SCENE_CHECK), [], 'en ' + name))
            self.assertEqual(errors, [])


def _shots():
    spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/dist/mobile.html').is_file(),
                     'requires installed Playwright and a built web/dist')
class PhoneLanguageBuiltAppBrowser(unittest.TestCase):
    """The built phone page on a disposable seeded server (carried over from the retired
    tests/check_language_browser.py; its desktop French and live-switch parts were accidental)."""

    def test_built_phone_choice_persists_across_reload_and_returns_to_english(self):
        import tempfile
        from types import SimpleNamespace
        from playwright.sync_api import expect

        shots = _shots()

        class Review(shots.Run):
            def first_start(self, browser, theme):
                pass

            def desktop(self, browser, theme):
                pass

            def phone(self, browser, theme):
                # English first, then the page's own choice survives each reload (the shared pin rewrites it)
                pin = "localStorage.setItem('bp-lang', 'en')"
                assert pin in shots.INIT
                shots.INIT = shots.INIT.replace(pin, "if (sessionStorage.getItem('i18n-seeded') === null) { " + pin +
                                                "; sessionStorage.setItem('i18n-seeded', '1') }")
                ctx = self.context(browser, theme, phone=True)
                try:
                    page = ctx.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(self.url('/mobile.html'))
                    page.wait_for_selector('#m-app')
                    expect(page.get_by_role('link', name='Library', exact=True)).to_be_visible()

                    def language(name):
                        page.evaluate("location.hash = '#/more'")
                        look = {'en': 'Look', 'fr': 'Style', 'zh-Hant-TW': '外觀'}[page.locator('html').get_attribute('lang')]
                        open_group(page, look)
                        group = page.get_by_role('group', name=name, exact=True)
                        expect(group).to_be_visible()
                        # Mounted controls can precede startup's guarded refresh and cache writes.
                        expect(page.locator('#m-conn button.m-btn')).to_be_enabled()
                        self.settle(page)
                        return group

                    group = language('Language')
                    expect(group.get_by_role('button', name='EN', exact=True)).to_have_attribute('aria-pressed', 'true')
                    for choice, stored, html_lang, name in [('FR', 'fr', 'fr', 'Langue'), ('EN', 'en', 'en', 'Language')]:
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            group.get_by_role('button', name=choice, exact=True).click()
                        page.wait_for_selector('#m-app')
                        assert page.evaluate("localStorage.getItem('bp-lang')") == stored
                        assert page.locator('html').get_attribute('lang') == html_lang
                        group = language(name)
                        expect(group.get_by_role('button', name=choice, exact=True)).to_have_attribute('aria-pressed', 'true')
                        page.reload(wait_until='domcontentloaded')
                        page.wait_for_selector('#m-app')
                        assert page.locator('html').get_attribute('lang') == html_lang
                        group = language(name)
                        expect(group.get_by_role('button', name=choice, exact=True)).to_have_attribute('aria-pressed', 'true')
                    page.evaluate("location.hash = '#/'")
                    expect(page.get_by_role('link', name='Library', exact=True)).to_be_visible()
                    # A controlled online reload warms the actual production shell and its lazy assets.
                    page.wait_for_function("navigator.serviceWorker.controller?.scriptURL.endsWith('/sw.js')")
                    page.reload(wait_until='domcontentloaded')
                    page.wait_for_selector('#m-app')
                    group = language('Language')
                    page.wait_for_function("""async () => {
                      const assets = performance.getEntriesByType('resource').filter(e => new URL(e.name).pathname.startsWith('/assets/'))
                      return assets.length > 0 && (await Promise.all(assets.map(e => caches.match(e.name)))).every(Boolean)
                    }""")
                    ctx.set_offline(True)
                    for choice, stored, html_lang, name in [('FR', 'fr', 'fr', 'Langue'),
                                                            ('繁中', 'zh-Hant', 'zh-Hant-TW', '語言'),
                                                            ('EN', 'en', 'en', 'Language')]:
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            group.get_by_role('button', name=choice, exact=True).click()
                        page.wait_for_selector('#m-app')
                        assert page.evaluate("localStorage.getItem('bp-lang')") == stored
                        assert page.locator('html').get_attribute('lang') == html_lang
                        group = language(name)
                        expect(group.get_by_role('button', name=choice, exact=True)).to_have_attribute('aria-pressed', 'true')
                    ctx.set_offline(False)
                    assert not errors, errors
                finally:
                    ctx.close()

        with tempfile.TemporaryDirectory(prefix='brainamon-i18n-phone-') as output:
            Review(SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                                   out=output, only=None, root=None, themes='light')).go()


# Plan 03 reads literal expected words back from controls; the catalogs are not the test oracle.
WORDS03 = {
    'en': dict(mine='My notes', knowledge='Knowledge', search='Search notes', all='All', new='New note',
               body='Note text', actions='Note actions', stamps='Stamps', style='Text style', ink='Ink colour',
               marker='Highlighter', hide='Hide keyboard', back='Back', close='Close', add='Add', cancel='Cancel',
               category='Category', category_name='Category name', new_category='+ New category…', new_category_title='New category',
               synth='Synthesize', synth_title='Synthesize a note', find='Find', stop='Stop', no_text='no text yet',
               canvas_new='New canvas', canvas_name='Canvas name', canvas_hint='Name this canvas', rows='Rows', columns='Columns',
               write='Write a note', discard='Discard', discard_title='Discard these picks?', keep='Keep editing',
               need='Wiskit needs an AI key', quick='Quick', deep='Deep', question='Question', send='Send',
               hello='Ask your library.', chat='+ New chat', review='Review category changes', apply='Apply batch', decline='Decline',
               tools='Tools', describe='Describe', categorize='Auto-categorize', done='Done', failed='Failed', skipped='Skipped',
               saved='Saved', dated='+ Dated section'),
    'fr': dict(mine='Mes notes', knowledge='Connaissances', search='Rechercher des notes', all='Tout', new='Nouvelle note',
               body='Texte de la note', actions='Actions de la note', stamps='Tampons', style='Style de texte', ink='Couleur de l’encre',
               marker='Surligneur', hide='Masquer le clavier', back='Retour', close='Fermer', add='Ajouter', cancel='Annuler',
               category='Catégorie', category_name='Nom de la catégorie', new_category='+ Nouvelle catégorie…', new_category_title='Nouvelle catégorie',
               synth='Synthétiser', synth_title='Synthétiser une note', find='Trouver', stop='Arrêter', no_text='pas encore de texte',
               canvas_new='Nouveau canvas', canvas_name='Nom du canvas', canvas_hint='Nommez ce canvas', rows='Lignes', columns='Colonnes',
               write='Écrire une note', discard='Abandonner', discard_title='Abandonner ces choix\u202f?', keep='Continuer',
               need='Wiskit a besoin d’une clé IA', quick='Rapide', deep='Approfondi', question='Question', send='Envoyer',
               hello='Interrogez votre bibliothèque.', chat='+ Nouvelle conversation', review='Vérifier les catégories', apply='Appliquer le lot', decline='Refuser',
               tools='Outils', describe='Décrire', categorize='Classer', done='Terminé', failed='Échec', skipped='Ignoré',
               saved='Enregistré', dated='+ Section datée'),
    'zh-Hant': dict(mine='我的筆記', knowledge='知識', search='搜尋筆記', all='全部', new='新增筆記',
                    body='筆記內文', actions='筆記操作', stamps='印章', style='文字樣式', ink='墨水顏色',
                    marker='螢光筆', hide='收起鍵盤', back='返回', close='關閉', add='新增', cancel='取消',
                    category='分類', category_name='分類名稱', new_category='+ 新增分類…', new_category_title='新增分類',
                    synth='綜合', synth_title='綜合成筆記', find='尋找', stop='停止', no_text='尚無文字',
                    canvas_new='新增畫布', canvas_name='畫布名稱', canvas_hint='為畫布命名', rows='橫列', columns='直欄',
                    write='撰寫筆記', discard='捨棄', discard_title='要捨棄這些選取項目嗎？', keep='繼續編輯',
                    need='Wiskit 需要 AI 金鑰', quick='快速', deep='深入', question='問題', send='傳送',
                    hello='詢問你的資料庫。', chat='+ 新增對話', review='檢視分類變更', apply='套用整批', decline='拒絕',
                    tools='工具', describe='描述', categorize='自動分類', done='完成', failed='失敗', skipped='略過',
                    saved='已儲存', dated='+ 日期段落'),
}


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneNotesCanvasWiskitProcessingScenes(unittest.TestCase):
    def test_voice_permission_and_final_save_remain_guarded_after_unmount(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            file = self.boot(page, base)
            page.evaluate("""async file => {
              const {source} = await import('/src/mobile/state.svelte.ts')
              source.canTranscribe = () => true
              source.transcribe = () => new Promise(resolve => window.__transcribed = resolve)
              navigator.mediaDevices.getUserMedia = () => new Promise(resolve => window.__permission = resolve)
              window.MediaRecorder = class {
                state = 'inactive'; mimeType = 'audio/webm'
                start(){this.state='recording'}
                stop(){this.state='inactive'; this.ondataavailable({data:new Blob(['synthetic audio'])}); this.onstop()}
              }
              location.hash = '#/mynotes/' + encodeURIComponent(file)
            }""", file)
            page.get_by_role('button', name='Note actions', exact=True).click()
            page.get_by_role('button', name='Record', exact=True).click()
            page.wait_for_function('!!window.__permission')
            switch = """async () => {
              const {switchLanguage} = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr','en',async()=>{}, {setItem(){window.__writes=(window.__writes||0)+1}},()=>{})
            }"""
            self.assertEqual(page.evaluate(switch)['status'], 'blocked')
            page.evaluate('window.__permission({getTracks:()=>[{stop(){}}]})')
            expect(page.get_by_role('button', name='Stop and transcribe', exact=True)).to_be_visible()
            self.assertEqual(page.evaluate(switch)['status'], 'blocked')
            page.evaluate("location.hash='#/more'")
            page.wait_for_function('!!window.__transcribed')
            self.assertEqual(page.evaluate(switch)['status'], 'blocked')
            page.evaluate("""async () => {
              const {source} = await import('/src/mobile/state.svelte.ts')
              const save = source.saveMyNote.bind(source)
              source.saveMyNote = (...args) => new Promise(resolve => window.__voiceSave = async () => resolve(await save(...args)))
              window.__transcribed('Retained synthetic transcript')
            }""")
            page.wait_for_function('!!window.__voiceSave')
            self.assertEqual(page.evaluate(switch)['status'], 'blocked')
            self.assertIsNone(page.evaluate('window.__writes ?? null'))
            page.evaluate('window.__voiceSave()')
            page.wait_for_function("""async file => (await (await import('/src/mobile/state.svelte.ts')).source.myNote(file)).body.includes('Retained synthetic transcript')""", arg=file)
            self.assertEqual(page.evaluate(switch)['status'], 'reloaded')
            self.assertEqual(page.evaluate('window.__writes'), 1)
            self.assertEqual(errors, [])

    def test_review_exceptional_states_keep_detail_and_translate_known_hint(self):
        from playwright.sync_api import expect
        detail = '<img src=x onerror=alert(1)> {name} synthetic'
        words = {
            'en': ('', '', 'Update Brainamon on the PC to rename.'),
            'fr': ('Erreur de note\u00a0: ', 'Erreur du canvas\u00a0: ', 'Mettez Brainamon à jour sur le PC pour renommer.'),
            'zh-Hant': ('筆記錯誤：', '畫布錯誤：', '請更新電腦上的 Brainamon，才能重新命名。'),
        }
        with mobile_browser() as (browser, base):
            for language, (note_error, canvas_error, rename) in words.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        file = self.boot(page, base)
                        actual = page.evaluate("""async () => {
                          const {source} = await import('/src/mobile/state.svelte.ts')
                          const {toolText} = await import('/src/mobile/tools-words.ts')
                          const pair = source.pair, manifest = source.manifest
                          source.pair = {...pair,solo:false}; source.manifest = {...manifest,note_category:0}
                          const result = [source.renameBlocked(), source.renameBlocked(toolText)]
                          source.manifest.note_category = 1; result.push(source.renameBlocked(toolText))
                          source.pair = pair; source.manifest = manifest
                          result.push(source.renameBlocked(toolText))
                          return result
                        }""")
                        self.assertEqual(actual, [words['en'][2], rename, '', ''])
                        page.evaluate("""async ({file,detail}) => {
                          const {source} = await import('/src/mobile/state.svelte.ts')
                          source.pair.solo = false; source.manifest = {...source.manifest,note_category:0}
                          source.smart = source.search = async () => {throw Error(detail)}
                          location.hash = '#/mynotes/' + encodeURIComponent(file)
                        }""", {'file': file, 'detail': detail})
                        page.locator('.np-tag').click()
                        expect(page.get_by_role('dialog').locator('.m-hint')).to_contain_text(rename)
                        check_scene(self, page, language, theme, 'review-rename-hint', sweep='03')
                        page.get_by_role('dialog').get_by_role('button', name=WORDS03[language]['close'], exact=True).click()
                        page.evaluate("location.hash='#/synth/'")
                        page.locator('.m-nt-topic input').fill('Synthetic topic')
                        page.get_by_role('button', name=WORDS03[language]['find'], exact=True).click()
                        expect(page.locator('.m-nt .m-hint').filter(has_text=detail)).to_have_text(note_error + detail)
                        self.assertEqual(page.locator('.m-nt .m-hint img').count(), 0)
                        check_scene(self, page, language, theme, 'review-synthesis-error', sweep='03')
                        page.evaluate("""async detail => {
                          const {source,phone} = await import('/src/mobile/state.svelte.ts')
                          source.smart = async () => phone.rows.map(row => row.id)
                          source.synthesize = async () => {window.__synthCalls = (window.__synthCalls||0)+1; throw Error(detail)}
                        }""", detail)
                        page.get_by_role('button', name=WORDS03[language]['find'], exact=True).click()
                        expect(page.locator('.m-nt-src')).to_have_count(60)
                        page.locator('.m-nt-run .m-nt-keys .m-key').last.click()
                        expect(page.locator('.m-nt .m-hint').filter(has_text=detail)).to_have_text(note_error + detail)
                        self.assertEqual(page.evaluate('window.__synthCalls'), 1)
                        page.evaluate("""async detail => {
                          const {source} = await import('/src/mobile/state.svelte.ts')
                          source.smart = async () => {throw Error(detail)}
                        }""", detail)
                        page.evaluate("location.hash='#/canvas'")
                        page.get_by_role('button', name=WORDS03[language]['canvas_new'], exact=True).click()
                        page.locator('.m-cp-search input').fill('Synthetic query')
                        toggle = page.locator('.m-cp-search .m-tg')
                        if toggle.get_attribute('aria-pressed') != 'true':
                            toggle.click()
                        expect(page.locator('.m-cp-notice span')).to_have_text(canvas_error + detail)
                        self.assertEqual(page.locator('.m-cp-notice img').count(), 0)
                        check_scene(self, page, language, theme, 'review-canvas-search-error', sweep='03')
                        self.assertEqual(errors, [])

    def test_post_answer_proposal_load_blocks_reload_after_wiskit_unmounts(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light') as (page, errors):
            self.boot(page, base)
            page.evaluate("""async () => {
              const {source} = await import('/src/mobile/state.svelte.ts')
              source.categoryProposal = async () => null
              source.ask = async () => {
                source.categoryProposal = () => new Promise(resolve => window.__proposalDone = resolve)
              }
              location.hash = '#/jv'
            }""")
            page.locator('.m-jv-field textarea').fill('Synthetic question')
            page.locator('.m-jv-field textarea').press('Enter')
            page.wait_for_function('!!window.__proposalDone')
            page.evaluate("location.hash='#/more'")
            expect(page.locator('#m-status')).to_be_visible()
            switch = """async () => {
              const {switchLanguage} = await import('/src/mobile/language-switch.ts')
              return switchLanguage('fr','en',async()=>{}, {setItem(){window.__writes=(window.__writes||0)+1}},()=>{})
            }"""
            self.assertEqual(page.evaluate(switch)['status'], 'blocked')
            self.assertIsNone(page.evaluate('window.__writes ?? null'))
            page.evaluate('window.__proposalDone(null)')
            self.assertEqual(page.evaluate(switch)['status'], 'reloaded')
            self.assertEqual(page.evaluate('window.__writes'), 1)
            self.assertEqual(errors, [])

    def boot(self, page, base):
        from playwright.sync_api import expect
        from tests.test_phone_gallery_browser import seed_items
        page.route('**/api/**', lambda route: route.abort())
        page.goto(base + '/mobile.html#/lib', wait_until='domcontentloaded')
        seed_items(page)
        expect(page.locator('.m-top')).to_be_visible()
        return page.evaluate(r"""async () => {
          const {phone,source} = await import('/src/mobile/state.svelte.ts')
          const {setSyncPaused}=await import('/src/mobile/network.svelte.ts'); setSyncPaused(true)
          source.ai=()=>({provider:'openai',model:'fixture',label:'Fixture model',providers:[{id:'openai',label:'OpenAI',models:[]}],smart:false,synth:'fixture'})
          source.canTranscribe=()=>false
          const row={file:'original-knowledge.md',title:'Original knowledge title',kind:'Synthesized',sources:[1,2],created:'2026-11-06T10:00:00',updated:'2026-11-06T10:00:00',snippet:'Original knowledge text'}
          source.notes=async()=>[row]
          source.note=async file=>({file,meta:{topic:row.title,kind:'synthesized',category:'Original category'},body:'## Original section\n\nOriginal knowledge text [id 1].',row})
          source.smart=async()=>phone.rows.map(r=>r.id)
          source.synthTextless=async()=>[1]
          source.myNoteCategories=async()=>['General','Original category','Other category']
          const note=await source.createMyNote('Original note title','Original category')
          await source.saveMyNote(note.file,note.title,note.category,'## Original section\n\nOriginal body with français 中文.',[{k:'flower',at:'Original section',x:-3,y:0,s:2,c:'indigo',r:0}])
          window.__note=note;window.__knowledgeRow=row
          window.__counts={apply:0,decline:0,categorize:[]}
          return note.file
        }""")

    def play(self, page, base, language, theme):
        from playwright.sync_api import expect
        w = WORDS03[language]
        file = self.boot(page, base)

        def shoot(name):
            if language != 'en':
                check_scene(self, page, language, theme, name, sweep='03')
            else:
                self.assertEqual(page.evaluate(SCENE_CHECK03), [], 'en ' + name)

        def route(path):
            page.evaluate('(path)=>location.hash=path', path)

        route('#/notes')
        expect(page.locator('.np-cd')).to_be_visible()
        self.assertEqual(page.locator('.m-tabline button').all_text_contents(), [w['mine'], w['knowledge']])
        self.assertEqual(page.locator('.m-sheet-keys .m-find-key').get_attribute('aria-label'), w['search'])
        self.assertEqual(page.locator('.np-cd-nm').inner_text(), 'Original note title')
        shoot('notes-mine')
        page.locator('.m-sheet-keys .m-find-key').click()
        page.locator('.m-sheet-keys .m-find-in').fill('No matching original text')
        expect(page.locator('.m-nt-empty h4')).to_have_text({'en':'No match','fr':'Aucun résultat','zh-Hant':'沒有符合的結果'}[language])
        shoot('notes-no-match')
        page.locator('.m-sheet-keys .m-find-in').fill('')
        page.locator('.m-sheet-keys .m-find-in').press('Escape')
        expect(page.locator('.np-cd')).to_be_visible()
        page.locator('.m-nt-cat').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        self.assertIn(w['all'], page.get_by_role('dialog').inner_text())
        shoot('notes-category-picker')
        page.get_by_role('dialog').get_by_role('button', name=w['close'], exact=True).click()
        page.get_by_role('button', name=w['knowledge'], exact=True).click()
        expect(page.locator('.m-nt-row')).to_be_visible()
        shoot('notes-knowledge')
        route('#/more')
        page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).source.notes=async()=>[]}")
        route('#/notes')
        page.get_by_role('button',name=w['knowledge'],exact=True).click()
        expect(page.locator('.m-nt-empty')).to_be_visible()
        shoot('notes-knowledge-empty')
        page.evaluate("async()=>{(await import('/src/mobile/state.svelte.ts')).source.notes=async()=>[window.__knowledgeRow]}")
        route('#/notes/original-knowledge.md')
        expect(page.locator('.m-nt-text')).to_contain_text('Original section')
        shoot('notes-reader')

        route('#/mynotes/' + file)
        expect(page.locator('#nt-body')).to_contain_text('Original body')
        self.assertEqual(page.locator('#nt-body').get_attribute('aria-label'), w['body'])
        self.assertEqual(page.locator('.np-head .m-key').last.get_attribute('aria-label'), w['actions'])
        shoot('editor')
        page.get_by_role('button', name=w['actions'], exact=True).click()
        expect(page.locator('.np-more')).to_be_visible()
        self.assertIn(w['saved'], page.locator('.np-sh-led').inner_text())
        shoot('editor-menu')
        page.locator('.np-more').get_by_role('button', name=w['close'], exact=True).click()
        for key, name in [('style','editor-styles'),('ink','editor-inks'),('marker','editor-markers')]:
            page.get_by_role('button', name=w[key], exact=True).click()
            shoot(name)
            page.get_by_role('button', name=w[key], exact=True).click()
        page.get_by_role('button', name=w['stamps'], exact=True).click()
        expect(page.locator('.np-tray')).to_be_visible()
        self.assertEqual(page.locator('.np-grid button').count(), 20)
        self.assertNotEqual(page.locator('.np-grid button').first.get_attribute('aria-label'), 'Add flower stamp') if language != 'en' else None
        shoot('editor-stamps')
        page.locator('.np-tray .np-x').click()
        page.locator('.np-tag').click()
        page.get_by_role('button', name=w['new_category'], exact=True).click()
        expect(page.get_by_role('dialog', name=w['new_category_title'], exact=True)).to_be_visible()
        page.get_by_role('textbox', name=w['category_name'], exact=True).fill('Original category')
        shoot('editor-new-category')
        page.get_by_role('dialog').get_by_role('button', name=w['cancel'], exact=True).click()
        page.locator('.np-tag').click()
        rename={'en':'Rename','fr':'Renommer','zh-Hant':'重新命名'}[language]
        page.get_by_role('button',name=re.compile('^'+rename+' ' if language!='zh-Hant' else '^'+rename+'「')).click()
        page.get_by_role('textbox',name=w['category_name'],exact=True).fill('Other category')
        page.get_by_role('dialog').get_by_role('button',name=rename,exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Other category')
        shoot('editor-merge-category')
        page.get_by_role('dialog').press('Escape')
        page.locator('#nt-body').focus()
        page.evaluate("document.documentElement.classList.add('kb')")
        shoot('editor-keyboard')
        page.evaluate("document.activeElement.blur();document.documentElement.classList.remove('kb')")

        route('#/synth/')
        expect(page.locator('.m-nt-topic input')).to_be_visible()
        page.locator('.m-nt-topic input').fill('Original topic')
        page.get_by_role('button', name=w['find'], exact=True).click()
        expect(page.locator('.m-nt-src')).to_have_count(60)
        self.assertEqual(page.locator('.m-nt-src small').first.inner_text(), w['no_text'])
        shoot('synth-textless')
        page.evaluate("""async()=>{const {source}=await import('/src/mobile/state.svelte.ts')
          source.synthesize=(topic,ids,onLine,signal,words)=>new Promise((ok,bad)=>{
            onLine(words('notes.synthesize.folding',{n:ids.length,at:1,total:1}))
            signal.addEventListener('abort',()=>bad(new DOMException('aborted','AbortError')))
          })
        }""")
        page.locator('.m-nt-run .m-nt-keys .m-key').last.click()
        expect(page.get_by_role('button',name=w['stop'],exact=True)).to_be_visible()
        shoot('synth-busy')
        page.get_by_role('button',name=w['stop'],exact=True).click()
        expect(page.locator('.m-nt-run .m-nt-keys .m-key')).to_have_count(1)
        shoot('synth-stopped')
        page.locator('.m-nt-src input:not(:disabled)').evaluate_all('es=>es.forEach(e=>{if(!e.checked)e.click()})')
        expect(page.locator('.m-nt-over')).to_be_visible()
        shoot('synth-limit')
        route('#/more')
        page.evaluate("async()=>{const {source}=await import('/src/mobile/state.svelte.ts');source.ai=()=>null}")
        route('#/synth/')
        expect(page.locator('.m-nt .m-hint')).to_be_visible()
        shoot('synth-no-key')

        route('#/canvas')
        expect(page.locator('.m-cv-list')).to_be_visible()
        self.assertEqual(page.locator('.m-cp-new').locator('..').get_attribute('aria-label'), w['canvas_new'])
        shoot('canvas-list')
        page.get_by_role('button', name=w['canvas_new'], exact=True).click()
        expect(page.get_by_role('textbox', name=w['canvas_name'], exact=True)).to_be_visible()
        self.assertEqual(page.locator('.m-cp-name').get_attribute('placeholder'), w['canvas_hint'])
        shoot('canvas-composer')
        page.get_by_role('button', name=w['write'], exact=True).click()
        page.locator('.m-cp-note-pane textarea').fill('Original canvas text')
        page.locator('.m-cp-add').click()
        expect(page.locator('.m-cp-error')).to_be_visible()
        shoot('canvas-name-error')
        page.locator('.m-cp-name').fill('Original canvas name')
        page.locator('.m-cp-note-pane textarea').focus()
        page.evaluate("document.activeElement.blur()")
        shoot('canvas-note')
        page.locator('.m-cp-header .m-back').click()
        expect(page.get_by_role('dialog', name=w['discard_title'], exact=True)).to_be_visible()
        shoot('canvas-discard')
        page.get_by_role('button', name=w['discard'], exact=True).click()

        route('#/jv')
        expect(page.locator('.m-jv-need h4')).to_have_text(w['need'])
        shoot('wiskit-no-key')
        route('#/more')
        page.evaluate("""async()=>{const {source}=await import('/src/mobile/state.svelte.ts')
          source.ai=()=>({provider:'openai',model:'fixture',label:'Fixture model',providers:[{id:'openai',label:'OpenAI',models:[]}],smart:false,synth:'fixture'})
          source.chats=async()=>({chats:[],active:''})
        }""")
        route('#/jv')
        expect(page.locator('.m-jv-hello>b')).to_have_text(w['hello'])
        self.assertEqual(page.locator('.m-jv-row .m-segpill button').all_text_contents(), [w['quick'], w['deep']])
        self.assertEqual(page.locator('.m-jv-ask textarea').get_attribute('aria-label'), w['question'])
        shoot('wiskit-empty')
        page.locator('.m-jv-row button[aria-haspopup="dialog"]').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        shoot('wiskit-help')
        page.get_by_role('dialog').get_by_role('button', name=w['close'], exact=True).click()
        page.evaluate(r"""async()=>{
          const {source}=await import('/src/mobile/state.svelte.ts')
          source.ask=(q,chat,on,signal,mode,words)=>new Promise((ok,bad)=>{
            on({ev:'context',line:'Sent 1 item(s)',ids:[1]},words('wiskit.info.sent',{n:1}))
            on({ev:'progress',line:'Original PC progress'})
            window.__answer=()=>{on({ev:'error',message:'<img src=x onerror=alert(1)> synthetic provider failure'});ok()}
            signal.addEventListener('abort',()=>bad(new DOMException('aborted','AbortError')))
          })
        }""")
        page.get_by_role('textbox', name=w['question'], exact=True).fill('Original question')
        page.get_by_role('button', name=w['send'], exact=True).click()
        expect(page.get_by_role('button', name=w['stop'], exact=True)).to_be_visible()
        expect(page.locator('.m-ctx')).to_have_text({'en':'Original PC progress','fr':'Progression\u00a0: Original PC progress','zh-Hant':'進度：Original PC progress'}[language])
        shoot('wiskit-busy')
        page.evaluate('window.__answer()')
        expect(page.locator('.m-a.err')).to_be_visible()
        self.assertEqual(page.locator('.m-a.err img').count(), 0)
        shoot('wiskit-error')
        route('#/more')
        page.evaluate("""async()=>{const {source}=await import('/src/mobile/state.svelte.ts')
          const p={entries:[{id:1,title:'Original item',from:'Original category',category:'Other category'}]}
          source.categoryProposal=async()=>p
          source.applyCategoryProposal=async()=>{window.__counts.apply++;source.categoryProposal=async()=>null}
          source.declineCategoryProposal=async()=>{window.__counts.decline++;source.categoryProposal=async()=>null}
        }""")
        route('#/jv')
        expect(page.locator('.m-jv-proposal h3')).to_contain_text(w['review'])
        shoot('wiskit-category-proposal')
        page.get_by_role('button', name=w['apply'], exact=True).evaluate('e=>{e.click();e.click()}')
        expect(page.locator('.m-jv-proposal')).to_have_count(0)
        self.assertEqual(page.evaluate('window.__counts.apply'), 1)
        self.assertEqual(page.evaluate('window.__counts.decline'), 0)
        route('#/jv/chats')
        expect(page.locator('.m-chats')).to_be_visible()
        self.assertEqual(page.locator('.m-chats button b').first.inner_text(), w['chat'])
        shoot('wiskit-chats')

        route('#/more')
        page.evaluate("""async()=>{
          const {source}=await import('/src/mobile/state.svelte.ts')
          const preview={target:{id:null,name:'Original canvas proposal',new:true,count:0},layout:'rows',arrange:false,
            counts:{thumbnail:1,frame:0,text:1,sections:0,moves:0},sections:[{title:'Original group',elements:[{kind:'text',text:'Original text'}]}],explicit:[]}
          source.canvasProposal=async()=>({mode:'local',token:'synthetic',preview})
        }""")
        route('#/jv')
        expect(page.locator('.m-canvas-review')).to_be_visible()
        shoot('wiskit-canvas-proposal')
        self.assertIn('Original group', page.locator('.m-canvas-review').inner_text())

        route('#/lib')
        page.evaluate("""async()=>{
          const {source,phone}=await import('/src/mobile/state.svelte.ts')
          const rows=phone.rows.slice(0,21).map(r=>({...r,cat:'',tags:'',nd:6}))
          source.rows=async()=>({rows,cats:[{name:'Original category',count:0}]})
          source.rowsByIds=async ids=>rows.filter(r=>ids.includes(r.id))
          source.categoryProposal=async()=>null;source.canvasProposal=async()=>null
          source.categorize=async id=>{
            window.__counts.categorize.push(id)
            if(window.__counts.categorize.length===1)await new Promise(r=>window.__releaseCategorize=r)
            const at=rows.findIndex(r=>r.id===id);rows[at]={...rows[at],cat:'Original category',tags:'original, tags'};return rows[at]
          }
          phone.rows=rows;phone.cat='all';phone.cats=[{name:'Original category',count:0}]
        }""")
        page.locator('.m-lib-tools').click()
        panel=page.get_by_role('dialog', name=w['tools'], exact=True)
        expect(panel).to_be_visible()
        self.assertEqual(panel.locator('.m-step-rw').first.get_attribute('aria-label'), w['describe'])
        shoot('processing-actions')
        panel.get_by_role('button', name=w['categorize'], exact=True).click()
        expect(panel.locator('.m-tl-ask')).to_be_visible()
        self.assertEqual(page.evaluate('window.__counts.categorize.length'),0)
        shoot('processing-review')
        panel.locator('.m-tl-ask-keys .m-btn').evaluate('e=>{e.click();e.click()}')
        page.wait_for_function("() => typeof window.__releaseCategorize === 'function'")
        expect(panel.locator('.m-tl-li').first).to_be_visible()
        shoot('processing-running')
        page.evaluate('window.__releaseCategorize()')
        page.wait_for_function("async()=>!!(await import('/src/mobile/tools-run.svelte.ts')).current()?.ended")
        self.assertEqual(page.evaluate('window.__counts.categorize.length'),21)
        self.assertEqual(page.evaluate('new Set(window.__counts.categorize).size'),21)
        self.assertEqual(page.evaluate('window.__counts.apply'),1)
        self.assertEqual(page.locator('.m-jv-proposal').count(),0)
        shoot('processing-finished')
        panel.get_by_role('button', name=w['done'], exact=True).click()
        page.evaluate("""async()=>{
          const {runs,newRun}=await import('/src/mobile/work.svelte.ts')
          runs.phone=newRun('phone','describe',[
            {id:1,title:'Original failed item',st:'err',why:'Synthetic provider failure'},
            {id:2,title:'Original skipped item',st:'skip',why:'Original detail'},
            {id:3,title:'Original done item',st:'done',why:''}],{ended:true,scope:{item:false,heading:'Original category',count:3}})
        }""")
        expect(panel.locator('.m-tl-gh').first).to_contain_text(w['failed'])
        expect(panel.locator('.m-tl-gh').nth(1)).to_contain_text(w['skipped'])
        shoot('processing-failed-skipped')
        panel.get_by_role('button', name=w['done'], exact=True).click()

    def test_scenes_in_three_languages_and_both_preview_themes(self):
        with mobile_browser() as (browser, base):
            for language in ('en','fr','zh-Hant'):
                for theme in (('light',) if language == 'en' else ('light','dark')):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        self.play(page,base,language,theme)
                        self.assertEqual(errors,[])

    def test_failed_save_blocks_switch_and_retry_keeps_exact_note_in_each_language(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base):
            for language in ('en','fr','zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser,base,360,740,'light',language=language) as (page,errors):
                    file=self.boot(page,base)
                    page.evaluate('(file)=>location.hash="#/mynotes/"+file',file)
                    expect(page.locator('#nt-body')).to_be_visible()
                    before=page.evaluate("async file=>(await import('/src/mobile/state.svelte.ts')).source.myNote(file)",file)
                    page.evaluate("""async()=>{const {source}=await import('/src/mobile/state.svelte.ts');const save=source.saveMyNote.bind(source)
                      window.__saveFails=true;source.saveMyNote=(...args)=>window.__saveFails?Promise.reject(Error('Synthetic save failure')):save(...args)
                    }""")
                    page.locator('#nt-body p').last.fill('Exact edited français 中文')
                    page.evaluate('location.hash="#/more"')
                    expect(page.locator('.m-page-keys')).to_be_visible()
                    blocked=page.evaluate("""async current=>{
                      const {switchLanguage}=await import('/src/mobile/language-switch.ts')
                      return switchLanguage(current==='fr'?'zh-Hant':'fr',current,async()=>{},{setItem(){throw Error('must not write')}},()=>{throw Error('must not reload')})
                    }""",language)
                    self.assertEqual(blocked,{'status':'blocked','reason':'settings.language.unsavedNote'})
                    open_group(page, WORDS05[language]['look'])
                    label={'en':'Language','fr':'Langue','zh-Hant':'語言'}[language]
                    page.get_by_role('group',name=label,exact=True).get_by_role('button',name='EN' if language=='fr' else 'FR',exact=True).click()
                    expect(page.get_by_role('alert')).to_be_visible()
                    if language!='en':
                        check_scene(self,page,language,'light','save-failed-switch-blocked',sweep='03')
                    page.evaluate('window.__saveFails=false')
                    page.evaluate('(file)=>location.hash="#/mynotes/"+file',file)
                    expect(page.locator('#nt-body')).to_contain_text('Exact edited français 中文')
                    expect(page.locator('.np-tag')).to_have_attribute('data-s','saved')
                    after=page.evaluate("async file=>(await import('/src/mobile/state.svelte.ts')).source.myNote(file)",file)
                    for key in ('title','category','stamps'):
                        self.assertEqual(after[key],before[key])
                    self.assertEqual(after['body'],'## Original section\n\nExact edited français 中文')
                    page.reload(wait_until='domcontentloaded')
                    expect(page.locator('#nt-body')).to_contain_text('Exact edited français 中文')
                    reloaded=page.evaluate("async file=>(await import('/src/mobile/state.svelte.ts')).source.myNote(file)",file)
                    for key in ('title','body','category','stamps'):
                        self.assertEqual(reloaded[key],after[key])
                    if language!='en':
                        check_scene(self,page,language,'light','save-retried',sweep='03')
                    self.assertEqual(errors,[])

    def test_pending_proposals_survive_real_safe_switch_without_answering(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base):
            for language in ('fr','zh-Hant'):
                with self.subTest(language=language), synthetic_phone(browser,base,360,740,'light',language=None) as (page,errors):
                    self.boot(page,base)
                    snapshot=r"""async()=>{
                      const {kv}=await import('/src/mobile/store.ts');const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
                      return [await kv.get('wiskit-category-proposal:'+mirrorSource.pair.f),await kv.get('wiskit-canvas-proposal:'+mirrorSource.pair.f)]
                    }"""
                    page.evaluate("""async()=>{
                      const {putCanvasPending}=await import('/src/mobile/store.ts');const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
                      await putCanvasPending('wiskit-category-proposal:'+mirrorSource.pair.f,{entries:[{id:1,title:'Original item',from:'Original category',category:'Other category'}]})
                      const preview={target:{id:null,name:'Original canvas',new:true,count:0},layout:'rows',counts:{thumbnail:0,frame:0,text:1,sections:0,moves:0},sections:[{title:null,elements:[{kind:'text',text:'Original text'}]}],explicit:[]}
                      await putCanvasPending('wiskit-canvas-proposal:'+mirrorSource.pair.f,{token:'synthetic-token',raw:{new_name:'Original canvas',layout:'rows',elements:[{kind:'text',text:'Original text'}]},refs:{},preview})
                      location.hash='#/more'
                    }""")
                    before=page.evaluate(snapshot)
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        page.evaluate("""async language=>{const {switchLanguage}=await import('/src/mobile/language-switch.ts');void switchLanguage(language,'en',async()=>{},localStorage,()=>location.reload())}""",language)
                    expect(page.locator('.m-page-keys')).to_be_visible()
                    self.assertEqual(page.locator('html').get_attribute('lang'),{'fr':'fr','zh-Hant':'zh-Hant-TW'}[language])
                    self.assertEqual(page.evaluate(snapshot),before)
                    page.evaluate('location.hash="#/jv"')
                    expect(page.locator('.m-canvas-review')).to_be_visible()
                    check_scene(self,page,language,'light','pending-after-switch',sweep='03')
                    self.assertEqual(page.evaluate(snapshot),before)
                    page.evaluate("""async()=>{
                      const {source}=await import('/src/mobile/state.svelte.ts')
                      const canvas=source.declineCanvasProposal.bind(source),category=source.declineCategoryProposal.bind(source)
                      window.__declines={canvas:0,category:0}
                      source.declineCanvasProposal=async p=>{window.__declines.canvas++;return canvas(p)}
                      source.declineCategoryProposal=async()=>{window.__declines.category++;return category()}
                    }""")
                    page.locator('.m-canvas-review .m-review-actions button').first.evaluate('e=>{e.click();e.click()}')
                    expect(page.locator('.m-canvas-review')).to_have_count(0)
                    expect(page.locator('.m-jv-proposal')).to_be_visible()
                    self.assertEqual(page.evaluate(snapshot),[before[0],None])
                    page.locator('.m-jv-proposal .m-acts button').first.evaluate('e=>{e.click();e.click()}')
                    expect(page.locator('.m-jv-proposal')).to_have_count(0)
                    self.assertEqual(page.evaluate(snapshot),[None,None])
                    self.assertEqual(page.evaluate('window.__declines'),{'canvas':1,'category':1})
                    self.assertEqual(errors,[])


WORDS04 = {
    'en': dict(save='Save', title='Note title', preview='Preview', tray='Import & drafts', close='Close', cancel='Cancel',
               read='Read text', describe='Describe', ask='Ask Wiskit', remove='Remove the attachment', go='Continue',
               note='Note', library='Library item', add_to='Note to add to', new='New note', search='Search your notes',
               save_note='Save to note', append='Add to note', save_library='Save to Library', suggest='Suggest',
               new_collection='+ New collection', name_collection='New collection name', collection='Collection',
               imported='Import saved posts', export='Export', scan='Scan', file='File', request='Request export',
               import_file='Import file', how='How importing works', record='Record', stop='Stop and transcribe',
               discard='Discard', audio='Audio file', transcribing='Transcribing audio…', recording='Recording',
               added='Added 1 link', no_saved="This is not Instagram's saved posts.", saved='Saved to a new note',
               pending='Waiting for the PC', failed='Not saved:', actions='Note actions', retry='Retry saving recording'),
    'fr': dict(save='Enregistrer', title='Titre de la note', preview='Aperçu', tray='Importation et brouillons', close='Fermer', cancel='Annuler',
               read='Lire le texte', describe='Décrire', ask='Demander à Wiskit', remove='Retirer la pièce jointe', go='Continuer',
               note='Note', library='Bibliothèque élément', add_to='Note à compléter', new='Nouvelle note', search='Rechercher vos notes',
               save_note='Enregistrer dans une note', append='Ajouter à la note', save_library='Enregistrer en bibliothèque', suggest='Suggérer',
               new_collection='+ Nouvelle collection', name_collection='Nom de la collection', collection='Collection',
               imported='Importer les favoris', export='Export', scan='Parcourir', file='Fichier', request='Demander un export',
               import_file='Importer un fichier', how='Fonctionnement de l’import', record='Enregistrer', stop='Arrêter et transcrire',
               discard='Abandonner', audio='Fichier audio', transcribing='Transcription audio…', recording='Enregistrement',
               added='1 lien ajouté', no_saved='Ce fichier ne contient pas les favoris Instagram.', saved='Enregistré dans une nouvelle note',
               pending='En attente du PC', failed='Non enregistré', actions='Actions de la note', retry='Réessayer de conserver l’enregistrement'),
    'zh-Hant': dict(save='儲存', title='筆記標題', preview='預覽', tray='匯入與草稿', close='關閉', cancel='取消',
                    read='讀取文字', describe='描述', ask='詢問 Wiskit', remove='移除附件', go='繼續',
                    note='筆記', library='資料庫 項目', add_to='要加入的筆記', new='新筆記', search='搜尋你的筆記',
                    save_note='儲存到筆記', append='加入筆記', save_library='儲存到資料庫', suggest='建議',
                    new_collection='+ 新收藏分類', name_collection='新收藏分類名稱', collection='收藏分類',
                    imported='匯入已收藏的貼文', export='匯出', scan='掃描', file='檔案', request='申請匯出',
                    import_file='匯入檔案', how='匯入方式說明', record='錄音', stop='停止並轉錄',
                    discard='捨棄', audio='音訊檔案', transcribing='正在轉錄音訊…', recording='錄音中',
                    added='已新增 1 個連結', no_saved='這不是 Instagram 的收藏貼文。', saved='已儲存為新筆記',
                    pending='等待電腦', failed='尚未儲存', actions='筆記操作', retry='重試儲存錄音'),
}


WORDS05 = {
    'en': dict(sync='Sync', ai='Wiskit on this phone', storage='Storage', look='Look', about='About',
               save='Save', change='Change', failed='Key could not be saved securely.', clear='Clear', sure_clear='Sure? Clear',
               clearing='Clearing…', recovery='Recovery', account='Google account', phone='This phone',
               password='Passphrase', file='File', code='Code', forgot='Forgot passphrase?', close='Close', cancel='Cancel',
               find='Find backup', find_setups='Find recovery setups', manage='Manage phone backups…',
               replace='Replace with this phone’s content…', delete='Delete backup and disconnect…',
               confirm_replace='Confirm replacement', resume='Resume task', retry='Retry task'),
    'fr': dict(sync='Synchronisation', ai='Wiskit sur ce téléphone', storage='Stockage', look='Style', about='À propos',
               save='Enregistrer', change='Changer', failed='La clé n’a pas pu être enregistrée', clear='Vider', sure_clear='Confirmer',
               clearing='Suppression…', recovery='Récupération', account='Compte Google', phone='Ce téléphone',
               password='Phrase secrète', file='Fichier', code='Code', forgot='Phrase secrète oubliée\u202f?', close='Fermer', cancel='Annuler',
               find='Trouver la sauvegarde', find_setups='Chercher les configurations', manage='Gérer les sauvegardes…',
               replace='Remplacer par ce téléphone…', delete='Supprimer et déconnecter…',
               confirm_replace='Confirmer', resume='Reprendre la tâche', retry='Réessayer'),
    'zh-Hant': dict(sync='同步', ai='此手機上的 Wiskit', storage='儲存空間', look='外觀', about='關於',
                    save='儲存', change='變更', failed='無法安全儲存金鑰', clear='清除', sure_clear='確定清除？',
                    clearing='清除中…', recovery='復原', account='Google 帳戶', phone='此手機',
                    password='密碼片語', file='檔案', code='復原碼', forgot='忘記密碼片語？', close='關閉', cancel='取消',
                    find='尋找備份', find_setups='尋找復原設定', manage='管理手機備份…',
                    replace='以此手機的內容取代…', delete='刪除備份並中斷連線…',
                    confirm_replace='確認取代', resume='繼續工作', retry='重試工作'),
}


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneSettingsBackupRecoveryScenes(unittest.TestCase):
    def test_native_vault_groups_lanes_and_silent_picker_cancellation(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language in ('fr', 'zh-Hant'):
                for theme in ('light', 'dark'):
                    pair = dict(PAIR, solo=False, l='A' * 122, d=base, g='synthetic@example.test')
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, pair=pair, language=language) as (page, errors):
                        page.add_init_script("""(() => {
                          window.androidBridge={};window.__nativeCalls=[]
                          const methods=['secretGet','secretSet','networkStatus','deviceName','vaultPick','siteState','getInfo','addListener','removeListener']
                          window.Capacitor={PluginHeaders:['Brainamon','App'].map(name=>({name,methods:methods.map(name=>({name,rtype:'promise'}))})),
                            nativePromise:async(plugin,method,o)=>{
                              window.__nativeCalls.push(method)
                              if(method==='secretGet')return {value:localStorage.getItem(o.key)}
                              if(method==='secretSet'){if(o.value===null)localStorage.removeItem(o.key);else localStorage.setItem(o.key,o.value);return {}}
                              if(method==='networkStatus')return {connected:true,type:'wifi'}
                              if(method==='deviceName')return {name:'Synthetic device'}
                              if(method==='getInfo')return {version:'synthetic',build:'synthetic'}
                              if(method==='siteState')return {supported:false}
                              if(method==='vaultPick')throw Error(window.__pickerError||'cancelled')
                              return {}
                            }}
                        })()""")
                        self.boot(page, base)
                        page.evaluate("""async(theme)=>{
                          const {source,phone}=await import('/src/mobile/state.svelte.ts')
                          const {vault}=await import('/src/mobile/vault/auto.svelte.ts')
                          source.vaultPc=async()=>null
                          vault.opts={on:true,uri:'synthetic-folder',name:'Original vault name'};vault.legacy=2
                          phone.reachable=true;phone.answered=true
                          document.documentElement.dataset.theme=theme
                        }""", theme)
                        vault_group = self.group(page, 'Obsidian')
                        expect(vault_group.locator('input')).to_have_value('Original vault name')
                        self.shot(page, language, theme, 'native-vault-group')
                        page.locator('.m-page-keys button.m-info').click()
                        self.shot(page, language, theme, 'native-vault-help')
                        page.keyboard.press('Escape')
                        result = page.evaluate("""async()=>{
                          const {vault,pickVaultFolder}=await import('/src/mobile/vault/auto.svelte.ts')
                          const before=JSON.stringify(vault.opts)
                          await pickVaultFolder()
                          return {line:vault.line,unchanged:JSON.stringify(vault.opts)===before}
                        }""")
                        self.assertEqual(result, dict(line='', unchanged=True))
                        page.evaluate("""async()=>{window.__pickerError='<img src=x onerror=alert(1)> Original picker detail';const {pickVaultFolder}=await import('/src/mobile/vault/auto.svelte.ts');await pickVaultFolder()}""")
                        for state in ('paused', 'queued', 'running', 'held', 'error', 'offline'):
                            page.evaluate("""async(state)=>{
                              const {network}=await import('/src/mobile/network.svelte.ts')
                              const {vault}=await import('/src/mobile/vault/auto.svelte.ts')
                              const {phoneWords}=await import('/src/mobile/settings-words.ts')
                              network.manualPause=state==='paused';network.online=state!=='offline';network.wifiOnly=false
                              vault.busy=state==='running';vault.queued=state==='queued';vault.prog={pct:45,left:''}
                              vault.step=phoneWords('backup.vault.step.listing')
                              vault.brake=state==='held'?phoneWords('backup.vault.brakeHere',{n:101,files:100,percent:20}):''
                              vault.outcome=state==='error'?'error':'ok'
                            }""", state)
                            self.group(page, WORDS05[language]['sync'])
                            lanes = page.evaluate("async()=> (await import('/src/mobile/lanes.ts')).syncLanes()")
                            self.assertTrue(any(lane['key'] == 'vault' for lane in lanes))
                            self.assertEqual(next(lane['pct'] for lane in lanes if lane['key'] == 'vault'), 45 if state == 'running' else None)
                            self.assertEqual(page.locator('.m-page img').count(), 0)
                            self.shot(page, language, theme, 'native-vault-' + state)
                        self.assertEqual(page.evaluate("window.__nativeCalls.filter(m=>m==='vaultPick').length"), 2)
                        self.assertEqual(errors, [])

    def test_paired_and_direct_pc_groups_account_guide_and_invalid_pairing(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, w in WORDS05.items():
                for theme in ('light', 'dark'):
                    pair = dict(PAIR, solo=False, e='synthetic-pc@example.test', l='A' * 122)
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, pair=pair, language=language) as (page, errors):
                        self.boot(page, base, '#/backup')
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        self.shot(page, language, theme, 'paired-guide')
                        for group in ('account', 'phone', 'recovery'):
                            self.group(page, w[group])
                            self.shot(page, language, theme, 'paired-' + group)
                        phone = self.group(page, w['phone'])
                        disclosure = phone.locator('details:not(.m-more-foot)').first
                        disclosure.locator('summary').first.click()
                        link = disclosure.locator('input')
                        link.fill('https://example.test/#pair=invalid')
                        pair_key = {'en': 'Pair', 'fr': 'Associer', 'zh-Hant': '配對'}[language]
                        disclosure.get_by_role('button', name=pair_key, exact=True).click()
                        expected = page.evaluate("async()=> (await import('/src/lib/i18n/index.ts')).t('settings.pair.unreadable')")
                        expect(page.locator('#m-backup-status')).to_contain_text(expected)
                        self.shot(page, language, theme, 'paired-invalid-link')
                        link.fill('')
                        page.evaluate("location.hash='#/more'")
                        expect(page.locator('.m-page-keys')).to_be_visible()
                        self.group(page, w['sync'])
                        self.shot(page, language, theme, 'paired-more-sync')
                        self.group(page, w['ai'])
                        self.shot(page, language, theme, 'paired-more-ai')
                        self.assertEqual(errors, [])
                    with synthetic_phone(browser, base, 360, 740, theme, pair=None, language=language) as (page, errors):
                        page.route('**/api/**', lambda route: route.abort())
                        page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                        expect(page.locator('#m-conn')).to_be_visible()
                        self.shot(page, language, theme, 'direct-pc')
                        self.assertEqual(errors, [])

    def test_paused_saved_task_queue_and_reviews_survive_real_language_reload(self):
        from playwright.sync_api import expect
        task = dict(kind='delete', phase='delete', paused=True, account='synthetic@example.test', prefix='solo-' + 'a' * 32 + '-',
                    owner=PAIR['k'], files=[dict(id='synthetic-kept-file', name='synthetic-kept-name')], removed=0)
        pair = dict(PAIR, backupTask=task)
        calls = []
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 740, 'light', pair=pair, language=None) as (page, errors):
            page.route('**/drive/v3/**', lambda route: (calls.append(route.request.url), route.abort()))
            self.boot(page, base)
            page.evaluate("""async()=>{
              const {outbox,changes,putCanvasPending}=await import('/src/mobile/store.ts')
              const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
              await outbox.add({url:'https://example.test/original',note:'Original queued words',added:1,state:'waiting',src:'W'})
              await changes.add({op:'fav',uid:'synthetic-pending',on:true,at:1,state:'queued'})
              await putCanvasPending('wiskit-category-proposal:'+mirrorSource.pair.f,{entries:[{id:1,from:'Original',category:'Original next'}]})
            }""")
            snapshot = """async()=>{
              const {outbox,changes,kv}=await import('/src/mobile/store.ts')
              const {secrets}=await import('/src/mobile/native.ts')
              const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
              const {backup}=await import('/src/mobile/backup.svelte.ts')
              return {pair:secrets.get('bp-pair'),outbox:await outbox.all(),changes:await changes.all(),
                review:await kv.get('wiskit-category-proposal:'+mirrorSource.pair.f),pause:localStorage.getItem('bp-sync-paused'),busy:backup.busy,task:backup.task}
            }"""
            before = page.evaluate(snapshot)
            for choice, group in [('FR', WORDS05['en']['look']), ('繁中', WORDS05['fr']['look']), ('EN', WORDS05['zh-Hant']['look'])]:
                self.group(page, group)
                with page.expect_navigation(wait_until='domcontentloaded'):
                    page.get_by_role('button', name=choice, exact=True).click()
                expect(page.locator('.m-page-keys')).to_be_visible()
                page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
                self.assertEqual(page.evaluate(snapshot), before)
            self.assertEqual(calls, [])
            self.assertEqual(errors, [])

    def test_backup_choice_confirmations_and_protected_work(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, w in WORDS05.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base, '#/backup')
                        page.evaluate("""async(base)=>{
                          const {secrets,secretsSaved}=await import('/src/mobile/native.ts')
                          const {validateStoredPairing,pairing}=await import('/src/mobile/mirror/pairing.ts')
                          const {mirrorSource:m,phone}=await import('/src/mobile/state.svelte.ts')
                          const {Drive}=await import('/src/mobile/mirror/drive.ts')
                          secrets.set('bp-pair',JSON.stringify({...m.pair,d:base,g:'synthetic@example.test'}));await secretsSaved();await validateStoredPairing();m.pair=pairing();phone.tokenAt++
                          Drive.prototype.about=async()=> 'synthetic@example.test'
                          Drive.prototype.list=async()=>[{id:'synthetic-a',name:'solo-'+ 'a'.repeat(32)+'-'+ 'b'.repeat(32),size:3000}]
                          window.__cloudWrites=0
                          Drive.prototype.createReplacement=async()=>{window.__cloudWrites++;throw Error('blocked synthetic upload')}
                          Drive.prototype.removeSoloMany=async()=>{window.__cloudWrites++;throw Error('blocked synthetic deletion')}
                          location.hash='#/backup/manage'
                        }""", base)
                        panel = page.locator('#phone-backup-choices')
                        expect(panel.locator('.m-picker')).to_be_visible()
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        self.shot(page, language, theme, 'backup-choice')
                        panel.get_by_role('button', name=w['replace'], exact=True).click()
                        expect(panel.locator('[role=alert]')).to_be_visible()
                        self.assertEqual(page.evaluate('window.__cloudWrites'), 0)
                        self.shot(page, language, theme, 'backup-replace-confirmation')
                        panel.get_by_role('button', name=w['cancel'], exact=True).click()
                        panel.get_by_role('button', name=w['delete'], exact=True).click()
                        self.assertEqual(page.evaluate('window.__cloudWrites'), 0)
                        self.shot(page, language, theme, 'backup-delete-confirmation')
                        panel.get_by_role('button', name=w['cancel'], exact=True).click()
                        result = page.evaluate("""async()=>{
                          const {runBackup,backup}=await import('/src/mobile/backup.svelte.ts')
                          const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts')
                          const {Drive}=await import('/src/mobile/mirror/drive.ts')
                          const {switchLanguage}=await import('/src/mobile/language-switch.ts')
                          let finish;Drive.prototype.list=()=>new Promise(resolve=>finish=resolve)
                          const running=runBackup(m.changes,'delete','solo-'+ 'a'.repeat(32)+'-')
                          const deadline=performance.now()+5000
                          while(!finish&&performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,0))
                          if(!finish)throw Error('synthetic backup preflight did not start')
                          const result=await switchLanguage('fr','en',async()=>{}, {setItem(){throw Error('must not write')}},()=>{throw Error('must not reload')})
                          finish([]);await running;return result
                        }""")
                        self.assertEqual(result, dict(status='blocked', reason='settings.language.unsavedWork'))
                        self.assertEqual(page.evaluate('window.__cloudWrites'), 0)
                        self.assertEqual(errors, [])

    def boot(self, page, base, route='#/more'):
        from playwright.sync_api import expect
        page.route('**/api/**', lambda route: route.abort())
        page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
        page.goto(base + '/mobile.html' + route, wait_until='domcontentloaded')
        expect(page.locator('#m-status' if route == '#/more' else '#m-backup-status')).to_be_visible()
        page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
        page.evaluate("""async()=>{
          const {mirrorSource:m,phone}=await import('/src/mobile/state.svelte.ts')
          m.rows=async()=>({rows:[],cats:[]});m.tints=async()=>({});m.watch=()=>{}
          m.drive.list=async()=>[];m.drive.about=async()=>m.pair.g||'synthetic@example.test'
          phone.motionOff=true
        }""")

    def group(self, page, title):
        return open_group(page, title)

    def shot(self, page, language, theme, name):
        check_scene(self, page, language, theme, name, sweep='05')

    def test_more_groups_provider_drafts_clear_once_and_layout(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, w in WORDS05.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base)
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        for name in ('sync', 'ai', 'storage', 'look', 'about'):
                            group = self.group(page, w[name])
                            if name == 'storage':
                                labels = page.evaluate("async()=>{const {t}=await import('/src/lib/i18n/index.ts');return ['settings.storage.opened','settings.storage.saved'].map(k=>t(k))}")
                                for label in labels:
                                    expect(group.locator('.m-keys3 b').get_by_text(label, exact=True)).to_be_visible()
                            self.shot(page, language, theme, 'more-' + name)
                            info = page.locator('.m-page-keys button.m-info')
                            if info.count():
                                info.click()
                                expect(page.get_by_role('dialog')).to_be_visible()
                                self.shot(page, language, theme, 'more-' + name + '-help')
                                page.keyboard.press('Escape')
                        ai = self.group(page, w['ai'])
                        fields = ai.locator('input[type=password]')
                        fields.nth(0).fill('synthetic-openai-draft')
                        fields.nth(1).fill('synthetic-anthropic-draft')
                        result = page.evaluate("""async()=>{
                          const {switchLanguage}=await import('/src/mobile/language-switch.ts')
                          let effects=0;const r=await switchLanguage('fr','en',async()=>{}, {setItem(){effects++}},()=>effects++)
                          return {r,effects}
                        }""")
                        self.assertEqual(result, dict(r=dict(status='blocked', reason='settings.language.unsavedKeys'), effects=0))
                        page.evaluate("""async()=>{const {secrets}=await import('/src/mobile/native.ts');window.__setSecret=secrets.set;secrets.set=()=>{throw Error('synthetic secure write failure')}}""")
                        ai.locator('.m-keyrow').nth(0).get_by_role('button').click()
                        expect(ai.get_by_role('status')).to_contain_text(w['failed'])
                        expect(fields.nth(0)).to_have_value('synthetic-openai-draft')
                        expect(fields.nth(1)).to_have_value('synthetic-anthropic-draft')
                        self.shot(page, language, theme, 'keys-failed-write')
                        page.evaluate("""async()=>{const {secrets}=await import('/src/mobile/native.ts');secrets.set=window.__setSecret}""")
                        ai.locator('.m-keyrow').nth(0).get_by_role('button').click()
                        expect(fields.nth(0)).to_have_value('')
                        expect(fields.nth(1)).to_have_value('synthetic-anthropic-draft')
                        ai.locator('.m-keyrow').nth(1).get_by_role('button').click()
                        expect(fields.nth(1)).to_have_value('')
                        self.shot(page, language, theme, 'keys-saved-independent')
                        ai.locator('.m-keyrow').nth(0).get_by_role('button').click()
                        fields.nth(0).fill('synthetic-retained-key-draft')
                        self.group(page, w['look'])
                        self.group(page, w['ai'])
                        expect(fields.nth(0)).to_have_value('synthetic-retained-key-draft')
                        fields.nth(0).fill('')
                        storage = self.group(page, w['storage'])
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          const {network}=await import('/src/mobile/network.svelte.ts')
                          network.manualPause=false;network.wifiOnly=false
                          window.__clears=0
                          source.rows=()=>{window.__clears++;return new Promise(resolve=>window.__finishClear=()=>resolve({rows:[],cats:[]}))}
                        }""")
                        storage.get_by_role('button', name=w['clear'], exact=True).click()
                        storage.get_by_role('button', name=w['sure_clear'], exact=True).evaluate('e=>{e.click();e.click();e.click()}')
                        page.wait_for_function('()=>!!window.__finishClear')
                        expect(storage.get_by_role('button', name=w['clear'], exact=True)).to_be_disabled()
                        expect(storage).to_contain_text(w['clearing'])
                        self.assertEqual(page.evaluate('window.__clears'), 1)
                        self.shot(page, language, theme, 'clear-in-flight')
                        page.evaluate('window.__finishClear()')
                        page.wait_for_function("async()=>!(await import('/src/mobile/state.svelte.ts')).phone.refreshing")
                        self.assertEqual(page.evaluate('window.__clears'), 1)
                        page.set_viewport_size(dict(width=320, height=740))
                        self.group(page, w['look'])
                        self.shot(page, language, theme, 'more-larger-text-standin')
                        self.assertEqual(errors, [])

    def test_recovery_methods_focus_errors_and_paused_tasks(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, w in WORDS05.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base, '#/backup')
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        self.group(page, w['recovery'])
                        self.shot(page, language, theme, 'recovery-group-no-key')
                        page.get_by_text(w['forgot'], exact=True).click()
                        self.shot(page, language, theme, 'recovery-forgot')
                        page.evaluate("location.hash='#/recover'")
                        expect(page.locator('#m-recover')).to_be_visible()
                        tabs = page.locator('#phone-unlock-method')
                        for method in ('password', 'file', 'code'):
                            tabs.get_by_role('button', name=w[method], exact=True).click()
                            self.shot(page, language, theme, 'recover-' + method)
                        code = page.locator('#m-recover input[type=password]')
                        code.fill('synthetic-invalid-code')
                        page.get_by_role('button', name=w['find'], exact=True).click()
                        expect(page.locator('#m-recover [role=alert]')).to_be_visible()
                        expect(code).to_have_value('')
                        self.assertEqual(page.locator('#m-recover img').count(), 0)
                        self.shot(page, language, theme, 'recover-invalid-code')
                        tabs.get_by_role('button', name=w['file'], exact=True).click()
                        page.get_by_text(w['forgot'], exact=True).click()
                        # The code method in the guide moves keyboard focus to the existing method region.
                        guide = page.locator('#m-recover details').last
                        page.evaluate("""()=>{for(const d of document.querySelectorAll('#m-recover details'))d.open=true}""")
                        code_key = page.get_by_role('button', name={'en':'Use recovery code','fr':'Utiliser le code','zh-Hant':'使用復原碼'}[language], exact=True)
                        code_key.focus(); code_key.press('Enter')
                        expect(tabs).to_be_focused()
                        self.shot(page, language, theme, 'recover-keyboard-focus')
                        page.evaluate("location.hash='#/backup/manage'")
                        expect(page.locator('#phone-backup-choices')).to_be_visible()
                        page.evaluate("""async()=>{
                          const {backup}=await import('/src/mobile/backup.svelte.ts')
                          const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts')
                          backup.task={kind:'replace',phase:'delete',paused:true,account:'synthetic@example.test',prefix:'solo-'+ 'a'.repeat(32)+'-',owner:m.pair.k,
                            files:[{id:'synthetic-a',name:'synthetic-a'},{id:'synthetic-b',name:'synthetic-b'}],removed:1,items:3000,uploaded:true,bytes:1610612736}
                        }""")
                        expect(page.get_by_role('button', name=w['resume'], exact=True)).to_be_visible()
                        expect(page.locator('#phone-backup-choices .m-steps')).to_be_visible()
                        self.shot(page, language, theme, 'backup-paused-task')
                        page.evaluate("""async()=>{const {backup}=await import('/src/mobile/backup.svelte.ts');const {nativeError}=await import('/src/mobile/settings-words.ts');backup.task.paused=false;backup.error=nativeError('backup',new Error('<img src=x onerror=alert(1)> original Drive detail'));}""")
                        expect(page.get_by_role('button', name=w['retry'], exact=True)).to_be_visible()
                        self.assertEqual(page.locator('#phone-backup-choices img').count(), 0)
                        self.shot(page, language, theme, 'backup-failed-task-detail')
                        page.evaluate("""async()=>{const {backup}=await import('/src/mobile/backup.svelte.ts');backup.error='';backup.busy=true;backup.task.phase='upload';backup.step='Original historical step'}""")
                        self.shot(page, language, theme, 'backup-running-upload')
                        page.evaluate("""async()=>{const {backup}=await import('/src/mobile/backup.svelte.ts');backup.busy=false;backup.task.phase='done'}""")
                        self.shot(page, language, theme, 'backup-result')
                        self.assertEqual(errors, [])

    def test_fixture_presentations_native_failures_and_vault_lanes(self):
        from playwright.sync_api import expect
        fixture = json.loads((ROOT / 'tests/fixtures/phone_states.json').read_text(encoding='utf-8'))
        with mobile_browser() as (browser, base):
            for language, w in WORDS05.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base, '#/backup')
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        # Use the shipped status/primary-button components with every fixture's exact facts.
                        page.evaluate("""async()=>{
                          const {mount,unmount,createRawSnippet}=await import('/node_modules/.vite/deps/svelte.js')
                          const {default:Status}=await import('/src/mobile/ui/MStatus.svelte')
                          const {default:Button}=await import('/src/mobile/ui/MButton.svelte')
                          const {phoneState}=await import('/src/mobile/mirror/phone-state.ts')
                          const {phoneWords}=await import('/src/mobile/settings-words.ts')
                          const {t}=await import('/src/lib/i18n/index.ts')
                          const box=document.querySelector('#m-backup-status');for(const child of box.children)child.style.display='none'
                          const target=document.createElement('div');box.append(target);let mounted=[]
                          window.__showFixture=async f=>{
                            for(const m of mounted)await unmount(m);mounted=[]
                            const s=phoneState(f,phoneWords)
                            mounted.push(mount(Status,{target,props:{look:'hero',kicker:t('backup.state.title'),tone:s.tone,text:s.text,detail:s.detail}}))
                            if(s.action){const label=s.action.label.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');mounted.push(mount(Button,{target,props:{shape:'pill',variant:s.action.primary?'pri':'default',children:createRawSnippet(()=>({render:()=>`<span>${label}</span>`})), 'aria-label':s.action.label,onclick:()=>window.__fixtureAction=s.action.id}}))}
                            return s
                          }
                        }""")
                        for i, case in enumerate(fixture['cases']):
                            facts = dict(fixture['base'], **case['facts'])
                            shown = page.evaluate('f=>window.__showFixture(f)', facts)
                            self.assertEqual([shown['id'], shown['tone'], shown['strip']], [case['expect']['id'], case['expect']['tone'], case['expect']['strip']])
                            expect(page.locator('#m-backup-status')).to_contain_text(shown['text'])
                            if shown['action']:
                                button = page.locator('#m-backup-status').get_by_role('button', name=shown['action']['label'], exact=True)
                                button.focus(); button.press('Enter')
                                self.assertEqual(page.evaluate('window.__fixtureAction'), shown['action']['id'])
                            self.shot(page, language, theme, f'state-{i:02d}-{shown["id"]}')
                        page.evaluate("location.hash='#/more'")
                        expect(page.locator('.m-page-keys')).to_be_visible()
                        page.evaluate("""async()=>{
                          const {phone,source}=await import('/src/mobile/state.svelte.ts'),{vault}=await import('/src/mobile/vault/auto.svelte.ts')
                          source.syncVault=async()=>({state:'idle',reason:'',summary:'Original PC summary'})
                          phone.sync={steps:[{key:'read',label:'Original retained step',state:'run',note:''}],end:'',msg:''}
                          vault.opts={on:true,uri:'synthetic-folder',name:'Original vault name'};vault.queued=true
                        }""")
                        self.group(page, w['sync'])
                        self.shot(page, language, theme, 'sync-queued-and-paused')
                        page.evaluate("""async()=>{const {network}=await import('/src/mobile/network.svelte.ts');const {vault}=await import('/src/mobile/vault/auto.svelte.ts');network.manualPause=false;network.wifiOnly=false;vault.queued=false;vault.busy=true;vault.step='Original native step';vault.prog={pct:45,left:''}}""")
                        self.shot(page, language, theme, 'sync-running-vault')
                        page.evaluate("""async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');const {vault}=await import('/src/mobile/vault/auto.svelte.ts');phone.sync=null;vault.busy=false}""")
                        page.evaluate("location.hash='#/backup'")
                        expect(page.locator('#m-recovery')).to_be_visible()
                        self.group(page, w['recovery'])
                        for operation, code in [('google','denied'),('google','consent'),('google','timeout'),('scanner','failed'),('secure','write'),('network','network'),('vault','unknown'),('openUri','unknown')]:
                            text = page.evaluate("""async([operation,code])=>{const {rec}=await import('/src/mobile/recovery.svelte.ts');const {nativeError}=await import('/src/mobile/settings-words.ts');return rec.error=nativeError(operation,{code,message:'<img src=x onerror=alert(1)> Original native detail'})}""", [operation, code])
                            expect(page.locator('#m-recovery [role=alert]')).to_have_text(text)
                            self.assertEqual(page.locator('#m-recovery [role=alert] img').count(), 0)
                            self.shot(page, language, theme, 'native-' + operation + '-' + code)
                        self.assertEqual(errors, [])


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneCaptureImportVoiceScenes(unittest.TestCase):
    boot = PhoneNotesCanvasWiskitProcessingScenes.boot

    def shot(self, page, language, theme, name):
        check_scene(self, page, language, theme, name, sweep='04')

    def test_capture_destinations_attachments_suggest_and_save_once(self):
        from playwright.sync_api import expect
        from base64 import b64decode
        image = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
        hostile = '<img src=x onerror="window.__injected=true"> {name}'
        with mobile_browser() as (browser, base):
            for language, w in WORDS04.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        file = self.boot(page, base)
                        page.evaluate("""async () => {
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          const create=source.createMyNote.bind(source),save=source.saveMyNote.bind(source)
                          window.__saves={create:0,save:0,append:0,link:0}
                          source.createMyNote=(...args)=>{window.__saves.create++;return create(...args)}
                          source.saveMyNote=(...args)=>{window.__saves.save++;return save(...args)}
                          source.readFile=async()=> 'Original attachment text français 中文'
                          source.linkPreview=async url=>({asked:url,url,found:true,title:'Original page title',desc:'Original caption',creator:'User creator',image:''})
                          source.suggestCategory=()=>new Promise(resolve=>window.__suggest=resolve)
                          location.hash='#/cap'
                        }""")
                        expect(page.locator('#cap-text')).to_be_visible()
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                        expect(page.get_by_role('link', name=w['imported'], exact=True)).to_be_visible()
                        self.shot(page, language, theme, 'capture-empty')
                        page.locator('#cap-title').fill('Original title français 中文')
                        page.locator('#cap-text').fill('Original words\n' + 'https://example.test/' + 'long-path/' * 20)
                        page.evaluate("""async () => {
                          const {keepDraft}=await import('/src/mobile/capture.svelte.ts')
                          const {newDraft}=await import('/src/lib/capture.ts')
                          await keepDraft(newDraft('share','Other original draft'))
                        }""")
                        page.get_by_role('button', name=w['tray'], exact=True).click()
                        expect(page.get_by_role('dialog', name=w['tray'], exact=True)).to_be_visible()
                        self.shot(page, language, theme, 'capture-drafts')
                        page.keyboard.press('Escape')
                        page.get_by_role('button', name=w['save'], exact=True).click()
                        expect(page.locator('#cap-pv')).to_have_text(w['preview'])
                        self.assertEqual(page.evaluate('window.__saves'), dict(create=0, save=0, append=0, link=0))
                        self.shot(page, language, theme, 'recap-new-note')
                        page.get_by_role('button', name=w['add_to'], exact=True).click()
                        page.get_by_role('searchbox', name=w['search'], exact=True).fill('no match')
                        self.shot(page, language, theme, 'recap-note-search')
                        page.get_by_role('searchbox', name=w['search'], exact=True).fill('Original')
                        page.get_by_role('option').filter(has_text='Original note title').click()
                        expect(page.locator('.m-cap-pv-new')).to_contain_text('## From Note - ')
                        expect(page.locator('.m-cap-pv-old')).to_contain_text('Original body')
                        self.shot(page, language, theme, 'recap-existing-note')
                        page.get_by_role('button', name=w['add_to'], exact=True).click()
                        page.locator('.m-cap-new').click()
                        page.locator('.m-cap-category .m-picker-inline').click()
                        expect(page.get_by_role('dialog').filter(has=page.locator('.m-picker-options'))).to_be_visible()
                        self.shot(page, language, theme, 'recap-category-picker')
                        page.get_by_role('dialog').get_by_role('button', name=w['close'], exact=True).click()
                        page.evaluate("location.hash='#/cap'")
                        expect(page.locator('#cap-text')).to_be_visible()
                        # All attachment kinds; filenames stay literal and payload text stays in its original language.
                        for filename, mime, content in [('Long-original-' + 'a' * 80 + '.png','image/png',image),
                                                        ('Original document.pdf','application/pdf',b'%PDF-synthetic'),
                                                        ('Original text.txt','text/plain',b'Original file text')]:
                            page.locator('input[type=file]').first.set_input_files({'name': filename, 'mimeType': mime, 'buffer': content})
                            expect(page.locator('.m-cap-pic b')).to_have_text(filename)
                            if mime == 'image/png':
                                for action in ('read','describe','ask'):
                                    page.get_by_role('button', name=w[action], exact=True).click()
                                    expect(page.locator('.m-cap-ask')).to_be_visible()
                                    self.shot(page, language, theme, 'attachment-confirm-' + action)
                                    page.get_by_role('button', name=w['cancel'], exact=True).click()
                                page.get_by_role('button', name=w['read'], exact=True).click()
                                page.locator('.m-cap-ask').get_by_role('button', name=w['go'], exact=True).click()
                            page.wait_for_function("() => document.querySelector('#cap-text').value.includes('Original attachment text')")
                            page.get_by_role('button', name=w['save'], exact=True).click()
                            expect(page.locator('.m-cap-att b')).to_have_text(filename)
                            page.get_by_role('button', name=w['add_to'], exact=True).click()
                            page.locator('.m-cap-new').click()
                            self.shot(page, language, theme, 'recap-' + mime.split('/')[-1])
                            page.get_by_role('button', name=w['add_to'], exact=True).click()
                            page.get_by_role('option').filter(has_text='Original note title').click()
                            self.shot(page, language, theme, 'recap-' + mime.split('/')[-1] + '-existing')
                            if mime != 'image/png':
                                page.get_by_role('radio', name=w['library'], exact=True).check()
                                self.shot(page, language, theme, 'recap-' + mime.split('/')[-1] + '-library')
                                page.get_by_role('radio', name=w['note'], exact=True).check()
                            page.evaluate("location.hash='#/cap'")
                            expect(page.locator('#cap-text')).to_be_visible()
                            page.get_by_role('button', name=w['remove'], exact=True).click()
                        page.locator('#cap-text').fill('https://example.test/synthetic')
                        page.get_by_role('button', name=w['save'], exact=True).click()
                        page.get_by_role('radio', name=w['library'], exact=True).check()
                        expect(page.locator('.m-cap-pv-lib')).to_be_visible()
                        self.shot(page, language, theme, 'recap-library')
                        page.get_by_role('button', name=w['suggest'], exact=True).click()
                        self.shot(page, language, theme, 'suggest-confirm')
                        page.locator('.m-cap-ask').get_by_role('button', name=w['go'], exact=True).click()
                        page.wait_for_function('() => !!window.__suggest')
                        self.shot(page, language, theme, 'suggest-pending')
                        self.assertEqual(self.attempt(page, language)['status'], 'blocked')
                        page.evaluate("window.__suggest({category:'INTERESTING',tags:'original-tags'})")
                        expect(page.get_by_role('textbox', name='Tags' if language != 'zh-Hant' else '標籤', exact=True)).to_have_value('original-tags')
                        self.shot(page, language, theme, 'suggest-result')
                        page.evaluate("""async detail => {
                          const {source}=await import('/src/mobile/state.svelte.ts');source.suggestCategory=async()=>{throw Error(detail)}
                        }""", hostile)
                        page.get_by_role('button', name=w['suggest'], exact=True).click()
                        page.locator('.m-cap-ask').get_by_role('button', name=w['go'], exact=True).click()
                        expect(page.get_by_role('alert')).to_contain_text(hostile)
                        self.assertEqual(page.locator('.m-err img').count(), 0)
                        self.shot(page, language, theme, 'suggest-error')
                        page.locator('.m-cap-category .m-picker-inline').click()
                        page.get_by_role('button', name=w['new_collection'], exact=True).click()
                        page.get_by_role('textbox', name=w['name_collection'], exact=True).fill('Original new collection')
                        self.shot(page, language, theme, 'recap-new-collection')
                        # Save failure retains the complete draft; retry is one creation and one successful save.
                        page.evaluate("location.hash='#/cap'")
                        page.locator('#cap-text').fill('Original final text français 中文')
                        page.get_by_role('button', name=w['save'], exact=True).click()
                        page.get_by_role('button', name=w['add_to'], exact=True).click()
                        page.locator('.m-cap-new').click()
                        page.evaluate("""async () => {
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          const save=source.saveMyNote.bind(source)
                          window.__originalSave=save
                          source.saveMyNote=()=>new Promise((resolve,reject)=>window.__saveFail=()=>reject(Error('synthetic write failed')))
                        }""")
                        page.get_by_role('button', name=w['save_note'], exact=True).click()
                        page.wait_for_function('() => !!window.__saveFail')
                        expect(page.locator('.m-cap-save')).to_have_attribute('aria-busy','true')
                        self.assertEqual(self.attempt(page, language)['status'], 'blocked')
                        page.evaluate('window.__saveFail()')
                        expect(page.get_by_role('alert')).to_contain_text(w['failed'])
                        self.shot(page, language, theme, 'save-failed')
                        page.evaluate("""async () => {
                          const {source}=await import('/src/mobile/state.svelte.ts');source.saveMyNote=window.__originalSave
                        }""")
                        page.get_by_role('button', name=w['save_note'], exact=True).evaluate('e=>{e.click();e.click()}')
                        expect(page.locator('#cap-done')).to_have_text(w['saved'])
                        self.assertEqual(page.evaluate('window.__saves.create'),1)
                        self.assertEqual(page.evaluate('window.__saves.save'),1)
                        expect(page.locator('.m-cap-page pre')).to_contain_text('Original final text français 中文')
                        self.shot(page, language, theme, 'save-done')
                        self.assertFalse(page.evaluate('!!window.__injected'))
                        self.assertEqual(errors, [])

    def attempt(self, page, language):
        return page.evaluate("""async language => {
          const {switchLanguage}=await import('/src/mobile/language-switch.ts')
          return switchLanguage(language==='fr'?'zh-Hant':'fr',language,async()=>{}, {setItem(){window.__switchWrites=(window.__switchWrites||0)+1}},()=>{})
        }""", language)

    def test_release_guides_results_and_escaped_errors(self):
        from playwright.sync_api import expect
        from tests.test_phone_import_browser import show, settle_import, POST
        detail = '<img src=x onerror="window.__injected=true"> {menu}'
        with mobile_browser() as (browser, base):
            for language, w in WORDS04.items():
                for theme in ('light','dark'):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        page.route('**/api/**',lambda route:route.abort())
                        page.goto(base+'/mobile.html#/import',wait_until='domcontentloaded')
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        expect(page.get_by_role('heading',name=w['imported'],exact=True)).to_be_visible()
                        for name in ('Instagram','Facebook','Threads','TikTok'):
                            block=show(page,name)
                            expect(block.get_by_role('button',name={'en':'Scan saved posts','fr':'Parcourir les favoris','zh-Hant':'掃描已收藏的貼文'}[language],exact=True)).to_be_disabled()
                            settle_import(page)
                            self.shot(page,language,theme,'import-'+name.lower())
                            for i,label in enumerate(('export','scan','file')):
                                info=block.locator('.m-import-action-caption .m-info').nth(i)
                                expect(info).to_have_text(w[label])
                                expect(info).to_have_attribute('aria-label',re.compile(re.escape(name)))
                                info.click()
                                expect(page.get_by_role('dialog').locator('h2')).to_contain_text(name)
                                if label=='export':
                                    expect(page.get_by_role('dialog').locator('li')).to_have_count(6 if name=='Instagram' else 3)
                                self.shot(page,language,theme,'import-'+name.lower()+'-'+label)
                                page.get_by_role('dialog').get_by_role('button',name=w['close'],exact=True).click()
                        page.get_by_text(w['how'],exact=True).click()
                        self.shot(page,language,theme,'import-how')
                        show(page,'Instagram')
                        page.locator('input[type=file]').last.set_input_files({'name':'broken.json','mimeType':'application/json','buffer':b'{broken'})
                        expect(page.get_by_role('alert')).to_contain_text(w['no_saved'])
                        self.shot(page,language,theme,'import-invalid')
                        page.evaluate("""async detail=>{
                          const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
                          mirrorSource.importLinks=async()=>{throw Error(detail)}
                        }""",detail)
                        payload={'name':'Original.json','mimeType':'application/json','buffer':json.dumps(POST).encode()}
                        page.locator('input[type=file]').last.set_input_files(payload)
                        expect(page.get_by_role('alert')).to_contain_text(detail)
                        self.assertEqual(page.locator('[role=alert] img').count(),0)
                        self.shot(page,language,theme,'import-unknown-error')
                        page.evaluate("""async()=>{
                          const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
                          mirrorSource.importLinks=()=>new Promise(resolve=>window.__importDone=resolve)
                        }""")
                        page.locator('input[type=file]').last.set_input_files(payload)
                        page.wait_for_function('() => !!window.__importDone')
                        self.assertEqual(self.attempt(page,language)['status'],'blocked')
                        self.shot(page,language,theme,'import-busy')
                        page.evaluate('window.__importDone({ids:[],dups:1})')
                        expect(page.locator('.m-import-expanded [role=status]')).to_contain_text('1')
                        self.shot(page,language,theme,'import-duplicates')
                        # Pure presentation uses complete count clauses; the real promotion path has its own browser suite.
                        page.evaluate("""async()=>{
                          const {mirrorSource}=await import('/src/mobile/state.svelte.ts')
                          mirrorSource.importLinks=async()=>({ids:[-123],dups:1});mirrorSource.rowsByIds=async()=>[]
                        }""")
                        page.locator('input[type=file]').last.set_input_files(payload)
                        expect(page.locator('.m-import-expanded [role=status]')).to_contain_text(w['added'])
                        self.shot(page,language,theme,'import-result')
                        self.assertFalse(page.evaluate('!!window.__injected'))
                        self.assertEqual(errors,[])

    def test_voice_idle_record_busy_queued_and_failed_durable_write(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base):
            for language,w in WORDS04.items():
                for theme in ('light','dark'):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        file=self.boot(page,base)
                        page.evaluate("""async file=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          source.canTranscribe=()=>true
                          source.transcribe=()=>new Promise(resolve=>window.__transcribe=resolve)
                          navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>window.__permission=resolve)
                          window.MediaRecorder=class {
                            state='inactive';mimeType='audio/webm'
                            start(){this.state='recording'}
                            stop(){this.state='inactive';this.ondataavailable({data:new Blob(['Original audio français 中文'],{type:'audio/webm'})});this.onstop()}
                          }
                          location.hash='#/mynotes/'+encodeURIComponent(file)
                        }""",file)
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.get_by_role('button',name=w['actions'],exact=True).click()
                        expect(page.get_by_role('button',name=w['record'],exact=True)).to_be_visible()
                        self.shot(page,language,theme,'voice-idle')
                        page.locator('.m-voice .m-info').click()
                        self.shot(page,language,theme,'voice-privacy')
                        page.locator('.m-info-dialog[open]').get_by_role('button',name=w['close'],exact=True).click()
                        page.get_by_role('button',name=w['record'],exact=True).click()
                        page.wait_for_function('() => !!window.__permission')
                        self.assertEqual(self.attempt(page,language)['status'],'blocked')
                        page.evaluate('window.__permission({getTracks:()=>[{stop(){}}]})')
                        expect(page.locator('.m-voice[data-mode=rec]')).to_be_visible()
                        expect(page.locator('.m-voice-time')).to_contain_text(w['recording'])
                        self.shot(page,language,theme,'voice-record')
                        self.assertEqual(self.attempt(page,language)['status'],'blocked')
                        page.get_by_role('button',name=w['stop'],exact=True).click()
                        page.wait_for_function('() => !!window.__transcribe')
                        expect(page.locator('.m-voice-time')).to_have_text(w['transcribing'])
                        self.shot(page,language,theme,'voice-busy')
                        self.assertEqual(self.attempt(page,language)['status'],'blocked')
                        page.evaluate("window.__transcribe('Original spoken words français 中文')")
                        page.wait_for_function("async file=>(await (await import('/src/mobile/state.svelte.ts')).source.myNote(file)).body.includes('Original spoken words')",arg=file)
                        expect(page.locator('.np-more')).to_have_count(0)
                        page.get_by_role('button',name=w['actions'],exact=True).click()
                        expect(page.locator('.m-voice[data-mode=idle]')).to_be_visible()
                        # Retain a blob in memory after a failed enqueue, and block language switching until durable retry.
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          source.transcribe=async()=>{throw Error('<img src=x> provider detail {name}')}
                          window.__transaction=IDBDatabase.prototype.transaction
                          IDBDatabase.prototype.transaction=function(name,mode,...rest){
                            if(this.name==='brainamon-voice'&&mode==='readwrite')throw Error('synthetic storage denied')
                            return window.__transaction.call(this,name,mode,...rest)
                          }
                        }""")
                        page.locator('.m-voice + input[type=file]').set_input_files({'name':'Original.webm','mimeType':'audio/webm','buffer':b'Original queued audio'})
                        expect(page.locator('.m-voice [role=alert]')).to_be_visible()
                        self.assertEqual(page.locator('.m-voice img').count(),0)
                        self.shot(page,language,theme,'voice-failed-write')
                        self.assertEqual(self.attempt(page,language)['status'],'blocked')
                        page.evaluate('() => { IDBDatabase.prototype.transaction=window.__transaction }')
                        # Existing plan-01 button copy is retained; assert the actual accessible name too.
                        retry={'en':'Retry saving recording','fr':'Réessayer de sauvegarder','zh-Hant':'重試儲存錄音'}[language]
                        page.get_by_role('button',name=retry,exact=True).click()
                        expect(page.locator('.m-voice [role=alert]')).to_have_count(0)
                        self.assertEqual(page.evaluate("async()=>{const q=await(await import('/src/mobile/voice.ts')).queued();return [q.length,await q[0].blob.text()] }"),[1,'Original queued audio'])
                        self.shot(page,language,theme,'voice-queued')
                        page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false})")
                        page.locator('.np-more .np-x').click()
                        pending={'en':'1 recording waiting for a signal.','fr':'1 enregistrement en attente de réseau.','zh-Hant':'1 段錄音等待連線。'}[language]
                        expect(page.get_by_text(pending,exact=True)).to_be_visible()
                        self.shot(page,language,theme,'voice-queue-count')
                        self.assertEqual(self.attempt(page,language)['status'],'reloaded')
                        self.assertEqual(errors,[])

    def test_denied_indexeddb_retains_memory_draft_and_refuses_switch(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base), synthetic_phone(browser,base,360,740,'light',language='fr') as (page,errors):
            page.route('**/api/**',lambda route:route.abort())
            page.add_init_script("Object.defineProperty(window,'indexedDB',{configurable:true,get(){throw Error('synthetic denied IndexedDB')}})")
            page.goto(base+'/mobile.html#/cap',wait_until='domcontentloaded')
            page.evaluate("async()=>{window.__memoryCapture=(await import('/src/mobile/capture.svelte.ts')).cap}")
            page.wait_for_function("()=>window.__memoryCapture.ready")
            page.locator('#cap-text').fill('Memory only draft français 中文')
            page.wait_for_function("()=>window.__memoryCapture.list.some(d=>d.text==='Memory only draft français 中文')")
            result=self.attempt(page,'fr')
            self.assertEqual(result,{'status':'blocked','reason':'settings.language.unsavedDraft'})
            expect(page.locator('#cap-text')).to_have_value('Memory only draft français 中文')
            self.assertEqual(page.evaluate("async()=>(await import('/src/mobile/capture.svelte.ts')).cap.list.map(x=>x.text)"),['Memory only draft français 中文'])
            self.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"),'fr')
            self.assertIsNone(page.evaluate('window.__switchWrites??null'))
            self.shot(page,'fr','light','memory-only-draft')
            self.assertEqual(errors,[])

    def test_library_pending_failed_duplicate_no_key_and_attachment_errors(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base):
            for language,w in WORDS04.items():
                for theme in ('light','dark'):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        self.boot(page,base)
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          source.ai=()=>null;source.linkPreview=async()=>null
                          source.saveLink=async()=>{throw Object.assign(Error('synthetic offline'),{status:0})}
                          location.hash='#/cap'
                        }""")
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.locator('#cap-text').fill('https://example.test/pending')
                        page.get_by_role('button',name=w['save'],exact=True).click()
                        expect(page.locator('.m-cap-suggest')).to_have_count(0)
                        self.shot(page,language,theme,'library-no-key')
                        page.get_by_role('button',name=w['save_library'],exact=True).click()
                        expect(page.locator('.m-cap-done .m-badge')).to_have_text(w['pending'])
                        self.shot(page,language,theme,'outbox-pending')
                        page.locator('.m-cap-dock.done .m-key').click()
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          source.saveLink=async()=>{throw Object.assign(Error('<img src=x> rejected {name}'),{status:400})}
                        }""")
                        page.locator('#cap-text').fill('https://example.test/rejected')
                        page.get_by_role('button',name=w['save'],exact=True).click()
                        page.get_by_role('button',name=w['save_library'],exact=True).click()
                        expect(page.get_by_role('alert')).to_contain_text('<img src=x> rejected {name}')
                        self.assertEqual(page.locator('.m-err img').count(),0)
                        self.shot(page,language,theme,'outbox-failed')
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts');source.saveLink=async()=>({id:77,new:false})
                        }""")
                        page.get_by_role('button',name=w['save_library'],exact=True).click()
                        expect(page.get_by_role('alert')).to_contain_text('77')
                        self.shot(page,language,theme,'outbox-duplicate')
                        page.evaluate("location.hash='#/cap'")
                        expect(page.locator('#cap-text')).to_have_value('https://example.test/rejected')
                        page.locator('#cap-text').fill('')
                        page.locator('input[type=file]').first.set_input_files({'name':'bad.exe','mimeType':'application/octet-stream','buffer':b'bad'})
                        expect(page.get_by_role('alert')).to_contain_text('PNG')
                        self.shot(page,language,theme,'attachment-unsupported')
                        # A PDF's automatic read fails without altering the existing draft or trusting provider detail as HTML.
                        page.evaluate("""async()=>{
                          const {source}=await import('/src/mobile/state.svelte.ts')
                          source.readFile=async()=>{throw Error('<img src=x> native/provider detail')}
                        }""")
                        page.locator('input[type=file]').first.set_input_files({'name':'Long-original-document-'+'a'*100+'.pdf','mimeType':'application/pdf','buffer':b'PDF'})
                        expect(page.get_by_role('alert')).to_contain_text('<img src=x> native/provider detail')
                        page.get_by_role('button',name=w['save'],exact=True).click()
                        expect(page.get_by_role('button',name=w['save_note'],exact=True)).to_be_disabled()
                        self.shot(page,language,theme,'recap-unread-no-key')
                        # The comment and final action remain reachable when the keyboard reduces the viewport.
                        page.set_viewport_size({'width':360,'height':520})
                        page.locator('#cap-comment').focus()
                        expect(page.locator('#cap-comment')).to_be_focused()
                        expect(page.locator('.m-cap-save')).to_be_in_viewport()
                        self.shot(page,language,theme,'recap-keyboard')
                        self.assertEqual(errors,[])

    def test_direct_pc_types_and_unread_image_preserve_ids_and_focus(self):
        from playwright.sync_api import expect
        from base64 import b64decode
        image=b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
        words={'en':('Type','Recipe','Automatic'),'fr':('Type','Recette','Auto'),'zh-Hant':('類型','食譜','自動')}
        with mobile_browser() as (browser,base):
            for language,w in WORDS04.items():
                for theme in ('light','dark'):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        self.boot(page,base)
                        page.evaluate("""async()=>{
                          const {source,phone}=await import('/src/mobile/state.svelte.ts')
                          source.kind='desktop';source.linkPreview=async()=>null;phone.reachable=true;location.hash='#/cap'
                        }""")
                        page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                        page.locator('#cap-text').fill('https://example.test/typed')
                        page.get_by_role('button',name=w['save'],exact=True).click()
                        label,recipe,automatic=words[language]
                        picker=page.locator('.m-cap-chip').filter(has=page.locator('i',has_text=re.compile('^'+label+'$'))).get_by_role('button')
                        picker.click()
                        expect(page.get_by_role('dialog').get_by_role('button',name=automatic,exact=True)).to_be_visible()
                        self.shot(page,language,theme,'recap-types')
                        page.get_by_role('dialog').get_by_role('button',name=recipe,exact=True).click()
                        expect(picker).to_be_focused()
                        expect(page.locator('.m-cap-pv-lib dd').filter(has_text=recipe)).to_be_visible()
                        page.wait_for_function("async()=>{const ds=await(await import('/src/mobile/store.ts')).drafts.all();return ds.length===1&&ds[0].type==='Recipe'}")
                        self.shot(page,language,theme,'recap-type-recipe')
                        page.evaluate("location.hash='#/cap'")
                        page.locator('input[type=file]').first.set_input_files({'name':'Original unread.png','mimeType':'image/png','buffer':image})
                        page.get_by_role('button',name=w['save'],exact=True).click()
                        expect(page.locator('.m-cap-att')).to_contain_text('Original unread.png')
                        self.shot(page,language,theme,'recap-image-unread')
                        page.set_viewport_size({'width':320,'height':740})
                        self.shot(page,language,theme,'recap-image-320')
                        self.assertEqual(errors,[])

    def test_durable_voice_and_outbox_survive_real_switch_and_retry_original_payload_once(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base), synthetic_phone(browser,base,360,740,'dark',language=None) as (page,errors):
            file=self.boot(page,base)
            page.evaluate("""async file=>{
              const {enqueue}=await import('/src/mobile/voice.ts')
              const {outbox}=await import('/src/mobile/store.ts')
              await enqueue(file,new Blob(['Original durable audio'],{type:'audio/webm'}))
              await outbox.add({url:'https://example.test/original?x=1',note:'Original note français 中文',category:'Original category',tags:'original-tags',type:'Custom type',added:123456,state:'waiting',src:'W'})
              await outbox.add({url:'https://example.test/failed',note:'Original failed entry',category:'INTERESTING',added:123457,state:'error',src:'W',error:'Historical original error'})
              location.hash='#/more'
            }""",file)
            snapshot="""async()=>{
              const {queued}=await import('/src/mobile/voice.ts'),{outbox}=await import('/src/mobile/store.ts')
              return {outbox:await outbox.all(),voice:await Promise.all((await queued()).map(async q=>({...q,blob:await q.blob.text()})))}
            }"""
            before=page.evaluate(snapshot)
            open_group(page, 'Look')
            with page.expect_navigation(wait_until='domcontentloaded'):
                page.get_by_role('group',name='Language',exact=True).get_by_role('button',name='FR',exact=True).click()
            expect(page.locator('#m-status')).to_be_visible()
            self.assertEqual(page.locator('html').get_attribute('lang'),'fr')
            self.assertEqual(page.evaluate(snapshot),before)
            seen=page.evaluate("""async()=>{
              const {Outbox}=await import('/src/mobile/outbox.svelte.ts')
              const calls=[]
              const box=new Outbox({saveLink:async url=>{calls.push(['link',url]);return{id:77,new:true}},edit:async(id,fields)=>calls.push(['edit',id,fields])},true)
              await box.load();await box.flush();await box.flush()
              return calls
            }""")
            self.assertEqual(seen,[['link','https://example.test/original?x=1'],['edit',77,dict(category='Original category',notes='Original note français 中文',tags='original-tags',type='Custom type')]])
            after=page.evaluate(snapshot)
            self.assertEqual(after['voice'],before['voice'])
            self.assertEqual(after['outbox'][0],before['outbox'][0])  # the failed historical entry is never resent
            self.assertEqual(after['outbox'][1]['id'],before['outbox'][1]['id'])
            self.assertEqual(after['outbox'][1]['state'],'sent')
            self.assertEqual(errors,[])


WORDS06 = {
    'en': dict(question='Do you use Brainamon on a PC?', skip='Skip', pc='Yes, connect my PC', phone='Not yet, start on this phone',
               help='Brainamon on your phone', help_label='About the mobile app', desktop='Get the desktop app',
               started='Get started', install='Install Brainamon', save='Save your first link', connect='Connect your PC', wiskit='Turn on Wiskit',
               count='1 of 3', done='done', ready='Brainamon is ready.', hide='Hide', coach='Share to Brainamon from any app, or tap Add.', got='Got it',
               legal=['Privacy policy','Software license','Third-party notices'], interval='Frame interval', frames='Extracted frames',
               budgets=['Auto (scale with length)','Off (transcript only)','Up to 8','Up to 15','Up to 24'],
               choices=['Keep & show in item canvas','Keep on disk only (hidden from canvas)','Delete frames after analysis'],
               steps='Backup steps', states=['done','paused','waiting'], active='in progress', use_file='Use recovery file'),
    'fr': dict(question='Utilisez-vous Brainamon sur PC\u202f?', skip='Passer', pc='Oui, connecter mon PC', phone='Pas encore, commencer ici',
               help='Brainamon sur votre téléphone', help_label='À propos de l’application mobile', desktop='Obtenir l’application PC',
               started='Premiers pas', install='Installer Brainamon', save='Enregistrer un premier lien', connect='Connecter votre PC', wiskit='Activer Wiskit',
               count='1 sur 3', done='terminé', ready='Brainamon est prêt.', hide='Masquer', coach='Partagez vers Brainamon depuis une application, ou appuyez sur Ajouter.', got='Compris',
               legal=['Politique de confidentialité','Licence du logiciel','Mentions des tiers'], interval='Intervalle des images', frames='Images extraites',
               budgets=['Auto (selon la durée)','Désactivé (transcription seule)','Jusqu’à 8','Jusqu’à 15','Jusqu’à 24'],
               choices=['Garder et afficher dans le canvas de l’élément','Garder sur disque (masqué dans le canvas)','Supprimer les images après l’analyse'],
               steps='Étapes de sauvegarde', states=['terminé','en pause','en attente'], active='en cours', use_file='Utiliser le fichier'),
    'zh-Hant': dict(question='你有在電腦上使用 Brainamon 嗎？', skip='略過', pc='是，連結我的電腦', phone='還沒，先使用這支手機',
                    help='手機上的 Brainamon', help_label='關於手機應用程式', desktop='取得電腦版應用程式',
                    started='開始使用', install='安裝 Brainamon', save='儲存第一個連結', connect='連線你的電腦', wiskit='啟用 Wiskit',
                    count='1／3', done='完成', ready='Brainamon 已可使用。', hide='隱藏', coach='從任何應用程式分享到 Brainamon，或點選新增。', got='知道了',
                    legal=['隱私權政策','軟體授權','第三方聲明'], interval='影格間隔', frames='擷取的影格',
                    budgets=['自動（依長度調整）','關閉（僅逐字稿）','最多 8 個','最多 15 個','最多 24 個'],
                    choices=['保留並顯示在項目畫布中','僅保留在磁碟上（不顯示在畫布中）','分析後刪除影格'],
                    steps='備份步驟', states=['完成','已暫停','等待中'], active='進行中', use_file='使用復原檔案'),
}


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneOnboardingSharedScenes(unittest.TestCase):
    boot = PhoneSettingsBackupRecoveryScenes.boot
    group = PhoneSettingsBackupRecoveryScenes.group

    def shot(self, page, language, theme, scene):
        # Fred accepted this exact 320px Library pill in 02; it sits behind the full-screen Welcome here.
        expected = ['ellipsized: Bibliothèque'] if language == 'fr' and scene == 'welcome-larger-text-standin' else []
        check_scene(self, page, language, theme, scene, sweep='06', expected=expected)

    def test_welcome_answers_help_coach_and_get_started_preserve_facts(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, w in WORDS06.items():
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base)
                        page.evaluate("""async theme=>{
                          const {phone,mirrorSource:m}=await import('/src/mobile/state.svelte.ts')
                          phone.loaded=true;phone.error='';phone.rows=[];m.ai=()=>null
                          document.documentElement.dataset.theme=theme
                          location.hash='#/lib'
                        }""", theme)
                        welcome = page.locator('.m-ob')
                        expect(welcome).to_be_visible()
                        expect(welcome).to_be_focused()
                        expect(page.locator('#m-ob-q')).to_have_text(w['question'])
                        expect(welcome.locator('.m-ob-opt.dk b')).to_have_text(w['pc'])
                        expect(welcome.locator('.m-ob-opt:not(.dk) b')).to_have_text(w['phone'])
                        expect(welcome.get_by_role('link', name=w['desktop'], exact=True)).to_have_attribute('href', re.compile('^https://'))
                        expect(welcome.locator('.m-info span')).to_have_text(w['help_label'])
                        self.shot(page, language, theme, 'welcome')
                        info = welcome.locator('button.m-info')
                        info.focus();info.press('Enter')
                        dialog = page.get_by_role('dialog', name=w['help'], exact=True)
                        expect(dialog).to_be_visible()
                        expect(dialog.locator('.m-info-body')).to_contain_text('Claude Code')
                        self.shot(page, language, theme, 'welcome-help')
                        page.keyboard.press('Escape')
                        expect(info).to_be_focused()
                        page.set_viewport_size(dict(width=320, height=740))
                        self.shot(page, language, theme, 'welcome-larger-text-standin')
                        self.assertLessEqual(welcome.get_by_role('link', name=w['desktop'], exact=True).bounding_box()['y'] +
                                             welcome.get_by_role('link', name=w['desktop'], exact=True).bounding_box()['height'], 740)
                        page.set_viewport_size(dict(width=360, height=740))
                        for answer in ('pc','skip','phone'):
                            if answer != 'pc':
                                page.evaluate("""async()=>{const {saveOnb}=await import('/src/mobile/onboard.svelte.ts');await saveOnb({answer:'',hidden:false,coach:false});location.hash='#/lib'}""")
                            expect(welcome).to_be_visible()
                            action = welcome.locator('.m-ob-opt.dk') if answer == 'pc' else welcome.locator('.m-ob-opt:not(.dk)') if answer == 'phone' else welcome.get_by_role('button', name=w['skip'], exact=True)
                            action.focus();action.press('Enter')
                            page.wait_for_function("""async answer=>{const {kv}=await import('/src/mobile/store.ts');return (await kv.get('onboard'))?.answer===answer}""", arg=answer)
                            self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('onboard')"), dict(answer=answer, hidden=False, coach=False))
                            expect(welcome).to_have_count(0)
                            if answer == 'pc':
                                expect(page).to_have_url(base + '/mobile.html#/backup')
                                self.shot(page, language, theme, 'welcome-pc-existing-setup')
                                page.evaluate("location.hash='#/lib'")
                            gs = page.locator('.m-gs')
                            expect(gs).to_contain_text(w['started'])
                            expect(gs.locator('[role=status]')).to_have_text(w['count'])
                            expect(gs.locator('.m-gs-row').nth(1)).to_contain_text(w['connect'] if answer == 'pc' else w['save'])
                            expect(gs).to_contain_text(w['install'])
                            expect(gs).to_contain_text(w['wiskit'])
                            expect(page.locator('.m-coach p')).to_have_text(w['coach'])
                            self.shot(page, language, theme, 'get-started-' + answer)
                        page.get_by_role('button', name=w['got'], exact=True).press('Enter')
                        page.wait_for_function("async()=> (await (await import('/src/mobile/store.ts')).kv.get('onboard')).coach")
                        expect(page.locator('.m-coach')).to_have_count(0)
                        gs.locator('button.m-gs-row').first.press('Enter')
                        expect(page).to_have_url(base + '/mobile.html#/cap')
                        page.evaluate("location.hash='#/lib'")
                        gs.locator('button.m-gs-row').last.press('Enter')
                        expect(page).to_have_url(base + '/mobile.html#/more/wiskit')
                        ai = page.locator('#m-ai')
                        expect(page.locator('h1')).to_have_text(WORDS05[language]['ai'])
                        expect(ai).to_be_visible()
                        expect(ai).to_be_focused()
                        page.locator('.m-page-keys button.m-info').press('Enter')
                        self.shot(page, language, theme, 'current-setup-help')
                        page.keyboard.press('Escape')
                        page.evaluate("""async()=>{
                          const {phone,mirrorSource:m}=await import('/src/mobile/state.svelte.ts')
                          m.ai=()=>({});phone.rows=[{id:-1,title:'Original saved title',creator:'Original creator',type:'Post',cat:'Original category',tags:'',desc:'Original content',url:'https://example.test/original',src:'web',thumb:false,ai:false,an:false,nd:0,fav:false,created:1,tv:0}]
                          location.hash='#/lib'
                        }""")
                        expect(gs.locator('[role=status]')).to_have_text(w['done'])
                        expect(gs).to_contain_text(w['ready'])
                        self.shot(page, language, theme, 'get-started-done')
                        gs.get_by_role('button', name=w['hide'], exact=True).press('Enter')
                        page.wait_for_function("async()=> (await (await import('/src/mobile/store.ts')).kv.get('onboard')).hidden")
                        self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('onboard')"), dict(answer='phone', hidden=True, coach=True))
                        self.assertEqual(errors, [])

    def test_shared_defaults_recovery_task_progress_analysis_and_legal(self):
        from playwright.sync_api import expect
        for_policy = [('privacy-policy.md','mobile-shell/store/privacy-policy.md'),('LICENSE','LICENSE'),('THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')]
        with mobile_browser() as (browser, base):
            for language, w in WORDS06.items():
                for theme in ('light','dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        self.boot(page, base)
                        page.evaluate("""async theme=>{
                          document.documentElement.dataset.theme=theme
                          const {mount,unmount}=await import('/node_modules/.vite/deps/svelte.js')
                          const {phone}=await import('/src/mobile/state.svelte.ts');phone.motionOff=false
                          const root=document.createElement('div');root.id='plan06-shared';root.className='m-box'
                          root.style='position:fixed;inset:50px 12px 85px;overflow:auto;z-index:50;margin:0;padding:12px;display:block'
                          document.querySelector('#m-app').append(root)
                          window.__shared=[];window.__calls=[]
                          window.__show=async(file,props)=>{
                            for(const c of window.__shared)await unmount(c);window.__shared=[];root.replaceChildren();root.scrollTop=0
                            const {default:Component}=await import(file)
                            window.__shared.push(mount(Component,{target:root,props}));return root.id
                          }
                        }""", theme)
                        root = page.locator('#plan06-shared')
                        page.evaluate("""async()=>window.__show('/src/components/ForgotPassphrase.svelte',{mobile:true,workingLabel:'Original caller action',workingReason:'Original caller reason <img src=x>',oncode:()=>window.__calls.push('code')})""")
                        expect(root.locator('summary').first).to_have_text('Forgot passphrase?')
                        root.locator('summary').first.press('Enter')
                        self.shot(page, language, theme, 'forgot-default-english')
                        page.evaluate("""async()=>{
                          const {phoneWords}=await import('/src/mobile/settings-words.ts')
                          await window.__show('/src/components/ForgotPassphrase.svelte',{mobile:true,words:phoneWords,workingLabel:'Original caller action',workingReason:'Original caller reason <img src=x>',onworking:()=>window.__calls.push('working'),onfile:()=>window.__calls.push('file'),oncode:()=>window.__calls.push('code')})
                        }""")
                        expect(root.locator('summary').first).to_have_text(WORDS05[language]['forgot'])
                        root.locator('summary').first.press('Enter')
                        for summary in root.locator('details details > summary').all():
                            summary.press('Enter')
                        expect(root.get_by_role('button', name='Original caller action', exact=True)).to_be_disabled()
                        expect(root).to_contain_text('Original caller reason <img src=x>')
                        expect(root.locator('img')).to_have_count(0)
                        root.get_by_role('button', name=w['use_file'], exact=True).press('Enter')
                        self.assertEqual(page.evaluate('window.__calls'), ['file'])
                        self.shot(page, language, theme, 'forgot-all-help-error')
                        page.set_viewport_size(dict(width=320,height=740))
                        self.shot(page, language, theme, 'forgot-larger-text-standin')
                        page.set_viewport_size(dict(width=360,height=740))
                        page.evaluate("""async()=>{
                          const {mount}=await import('/node_modules/.vite/deps/svelte.js')
                          const {phoneWords,phoneLocale}=await import('/src/mobile/settings-words.ts')
                          await window.__show('/src/components/ui/TaskSteps.svelte',{words:phoneWords,running:false,steps:[{label:'Original PC step <img src=x>',state:'done'},{label:'Original saved task',state:'active'},{label:'Original queued detail',state:'waiting'}]})
                          const {default:Progress}=await import('/src/components/ui/Progress.svelte')
                          const {default:DeletionEstimate}=await import('/src/components/ui/DeletionEstimate.svelte')
                          const target=document.querySelector('#plan06-shared')
                          window.__shared.push(mount(Progress,{target,props:{label:'Original caller progress',pct:50}}))
                          window.__shared.push(mount(Progress,{target,props:{label:'Original uncounted task'}}))
                          window.__shared.push(mount(DeletionEstimate,{target,props:{words:phoneWords,locale:phoneLocale(),done:1000,total:1000}}))
                        }""")
                        expect(root.get_by_role('list', name=w['steps'], exact=True)).to_be_visible()
                        self.assertEqual([s.inner_text().strip(' ·') for s in root.locator('.task-steps small').all()], w['states'])
                        expect(root).to_contain_text('Original PC step <img src=x>')
                        expect(root.locator('img')).to_have_count(0)
                        expect(root.get_by_role('progressbar',name='Original caller progress',exact=True)).to_have_attribute('aria-valuenow','50')
                        self.assertEqual(root.locator('.prog .lit').count(),6)
                        self.assertIsNone(root.get_by_role('progressbar',name='Original uncounted task',exact=True).get_attribute('aria-valuenow'))
                        expect(root.locator('.deletion-estimate')).to_contain_text({'en':'Estimated deletion:','fr':'Suppression estimée\u00a0:','zh-Hant':'預估刪除：'}[language])
                        self.shot(page, language, theme, 'task-paused-progress-deletion')
                        page.evaluate("""async()=>{
                          const {phoneWords}=await import('/src/mobile/settings-words.ts')
                          await window.__show('/src/components/ui/TaskSteps.svelte',{words:phoneWords,steps:[{label:'Original running detail',state:'active'}]})
                        }""")
                        expect(root.locator('small')).to_contain_text(w['active'])
                        self.shot(page, language, theme, 'task-running')
                        page.evaluate("""async()=>{
                          window.__options={frame_interval:3,transcribe:true,transcribe_method:'whisper-api',analysis_provider:'claude',keep_frames:true,show_frames_in_canvas:false,delete_video:false,delete_audio:false,ai_frame_budget:'15'}
                          await window.__show('/src/windows/AnalyzeOptionsForm.svelte',{o:window.__options,err:'Original PC error <img src=x onerror=alert(1)>'})
                        }""")
                        expect(root.get_by_label(w['interval'],exact=True)).to_have_value('3')
                        self.assertEqual(root.locator('#ao-send option').all_text_contents(),w['budgets'])
                        self.assertEqual(root.locator('#ao-keep option').all_text_contents(),w['choices'])
                        self.assertEqual(root.locator('#ao-pr option').evaluate_all('es=>es.map(e=>e.value)'),['claude','openai','freellmapi','none'])
                        self.assertEqual(root.locator('#ao-mod option').evaluate_all('es=>es.map(e=>e.value)'),['whisper-api'])
                        expect(root.locator('.err')).to_have_text('Original PC error <img src=x onerror=alert(1)>')
                        expect(root.locator('img')).to_have_count(0)
                        interval=root.get_by_label(w['interval'],exact=True)
                        interval.focus();interval.fill('5')
                        expect(interval).to_be_focused()
                        self.shot(page,language,theme,'analysis-error-focus')
                        for value,keep,show in [('0',True,True),('1',True,False),('2',False,False)]:
                            root.locator('#ao-keep').select_option(value)
                            page.wait_for_function('([keep,show])=>window.__options.keep_frames===keep&&window.__options.show_frames_in_canvas===show',arg=[keep,show])
                        root.locator('#ao-send').select_option('24')
                        root.locator('#ao-pr').select_option('none')
                        self.assertEqual(page.evaluate('window.__options'),dict(frame_interval=5,transcribe=True,transcribe_method='whisper-api',analysis_provider='none',keep_frames=False,show_frames_in_canvas=False,delete_video=False,delete_audio=False,ai_frame_budget='24'))
                        page.set_viewport_size(dict(width=320,height=740))
                        self.shot(page,language,theme,'analysis-larger-text-standin')
                        page.set_viewport_size(dict(width=360,height=740))
                        page.evaluate("async()=>window.__show('/src/components/LegalDocuments.svelte',{})")
                        self.assertEqual(root.locator('summary').all_text_contents(),w['legal'])
                        expect(root.get_by_role('link',name='me@fredtomas.com',exact=True)).to_have_attribute('href','mailto:me@fredtomas.com')
                        for i,(_,path) in enumerate(for_policy):
                            root.locator('summary').nth(i).press('Enter')
                            self.assertEqual(root.locator('pre').nth(i).text_content(),(ROOT/path).read_text(encoding='utf-8'))
                            if i == 0:
                                self.shot(page,language,theme,'legal-english-policy')
                            root.locator('summary').nth(i).press('Enter')
                        self.shot(page,language,theme,'legal-wrapper')
                        self.assertEqual(errors,[])


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneAiLanguageScenes(unittest.TestCase):
    """Synthetic output review samples; these do not evaluate model language obedience."""

    def test_multilingual_replies_saved_text_and_citations(self):
        from playwright.sync_api import expect

        samples = {
            'fr': dict(badge='connaissances générales', missing='Aucun élément avec ce numéro',
                       reply='## Conseils\nBougez doucement [id 1]. (general knowledge)\nVoir [note: original.md] et [id 999].\n<img src=x onerror=alert(1)>',
                       note='## Outils et ressources mentionnés\nUn guide [id 1].\n## Sources citées\n[id 1]',
                       description='Une affiche de formation. Texte original : 简体中文 / Original English.'),
            'zh-Hant': dict(badge='一般知識', missing='沒有這個編號的項目',
                            reply='## 建議\n請緩慢活動 [id 1]。（general knowledge）\n(general knowledge) 請參閱 [note: original.md] 和 [id 999]。\n<img src=x onerror=alert(1)>',
                            note='## 提到的工具與資源\n一份指南 [id 1]。\n## 來源\n[id 1]',
                            description='這是一張訓練海報。原始文字：简体中文 / Original English。'),
        }
        with mobile_browser() as (browser, base):
            for language, sample in samples.items():
                for theme in ('light', 'dark'):
                    for width, height, large in ((360, 740, False), (390, 844, True)):
                        with self.subTest(language=language, theme=theme, large=large), synthetic_phone(browser, base, width, height, theme, language=language) as (page, errors):
                            page.route('**/api/**', lambda route: route.abort())
                            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                            expect(page.locator('.m-page-keys')).to_be_visible()
                            page.evaluate("async()=>{window.__phone07=(await import('/src/mobile/state.svelte.ts')).phone}")
                            page.wait_for_function('() => window.__phone07.tried && !window.__phone07.refreshing')
                            page.evaluate(r"""async ({theme,sample}) => {
                              const {phone,source}=await import('/src/mobile/state.svelte.ts')
                              const {setSyncPaused}=await import('/src/mobile/network.svelte.ts')
                              const {saveOnb}=await import('/src/mobile/onboard.svelte.ts')
                              setSyncPaused(true);await saveOnb({answer:'phone',hidden:true,coach:true})
                              document.documentElement.dataset.theme=theme;phone.motionOff=true
                              const row={id:1,uid:'07-item',title:'Original item',cat:'SPORT',tags:'unchanged',creator:'Coach',type:'Post',url:'https://example.test/1',thumb:false,created:1,desc:sample.description,ai:true}
                              phone.rows=[row];phone.cats=[{name:'SPORT',color:'#39776b',count:1}];phone.loaded=true;phone.error='';TYPE.SPORT='#39776b'
                              source.ai=()=>({provider:'openai',model:'synthetic',label:'Synthetic model',providers:[],smart:false,synth:'synthetic'})
                              source.categoryProposal=async()=>null;source.canvasProposal=async()=>null
                              const chat={slug:'07-chat',name:'Original chat',history:[{role:'assistant',content:sample.reply}],sources:[row]}
                              source.chats=async()=>({chats:[{slug:chat.slug,name:chat.name,message_count:1,updated:'2026-11-09'}],active:chat.slug})
                              source.chat=async()=>chat
                              source.item=async()=>({...row,category:row.cat,short_desc:row.title,ai_desc:sample.description,description:'Original caption',notes:'Original note',transcript:'',files:{report:false,transcript:false,video:false,frames:0}})
                              source.itemText=async()=>sample.description
                              const noteRow={file:'original.md',title:'Original note',kind:'Synthesized',sources:[1],created:'2026-11-09',updated:'2026-11-09',snippet:sample.note}
                              source.notes=async()=>[noteRow]
                              source.note=async()=>({file:noteRow.file,meta:{topic:noteRow.title,kind:'synthesized'},body:sample.note,row:noteRow})
                              source.noteFiles=async()=>[]
                              await source.changes.saveChat({op:'chat',slug:chat.slug,name:chat.name,history:chat.history,source_ids:[1],created:'2026-11-09',was:'',options:{provider:'openai',model_id:'synthetic'}})
                              window.__source07=source
                              location.hash='#/jv'
                            }""", dict(theme=theme, sample=sample))
                            expect(page.locator('.m-a .gk')).to_have_text(sample['badge'])
                            expect(page.locator('.m-a .miss')).to_have_attribute('title', sample['missing'])
                            self.assertEqual(page.locator('.m-a img,.m-a script,.m-a [onerror]').count(), 0)
                            self.assertEqual(page.locator('.m-a .cite[data-cid="1"]').count(), 1)
                            if large:
                                page.add_style_tag(content='.m-a p,.m-a li,.m-a .gk,.m-rep p,.m-rep li{font-size:20px!important;line-height:1.6!important}')
                            suffix = '-large' if large else ''
                            check_scene(self, page, language, theme, 'reply-citations' + suffix, sweep='07')
                            page.locator('.m-a .m-foot button').click()
                            page.wait_for_function("() => window.__source07.changes.list.some(e=>e.op==='answer')")
                            stored = page.evaluate("() => ({answer:window.__source07.changes.list.find(e=>e.op==='answer').md,chat:window.__source07.changes.list.find(e=>e.op==='chat').history[0].content})")
                            self.assertEqual(stored, dict(answer=sample['reply'], chat=sample['reply']))
                            page.locator('.m-a .cite[data-cid="1"]').focus()
                            page.keyboard.press('Enter')
                            expect(page).to_have_url(base + '/mobile.html#/item/1')
                            expect(page.locator('.m-it-felt')).to_be_visible()
                            check_scene(self, page, language, theme, 'picture-description' + suffix, sweep='07')
                            page.evaluate("location.hash='#/jv'")
                            expect(page.locator('.m-a .cite[data-note="original.md"]')).to_be_visible()
                            page.locator('.m-a .cite[data-note="original.md"]').focus()
                            page.keyboard.press('Enter')
                            expect(page).to_have_url(base + '/mobile.html#/notes/original.md')
                            expect(page.locator('.m-nt-text')).to_contain_text(sample['note'].split('\n')[0].removeprefix('## '))
                            self.assertGreater(page.locator('.m-nt-text .cite[data-cid="1"]').count(), 0)
                            check_scene(self, page, language, theme, 'synthesis-localized-headings' + suffix, sweep='07')
                            self.assertEqual(errors, [])


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT / 'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires installed Playwright/Edge and web dependencies')
class PhoneLegalScenes08(unittest.TestCase):
    def test_selected_policy_original_license_notices_and_keyboard_in_both_themes(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language in ('en', 'fr', 'zh-Hant'):
                for theme in ('light', 'dark'):
                    for large in (False, True):
                        with self.subTest(language=language, theme=theme, large=large), synthetic_phone(
                                browser, base, 390 if large else 360, 844 if large else 740, theme, language=language) as (page, errors):
                            page.route('**/api/**', lambda route: route.abort())
                            page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
                            page.goto(base + '/mobile.html#/more', wait_until='domcontentloaded')
                            expect(page.locator('.m-page-keys')).to_be_visible()
                            page.evaluate("async()=>window.__phone08=(await import('/src/mobile/state.svelte.ts')).phone")
                            page.wait_for_function('()=>window.__phone08.tried&&!window.__phone08.refreshing')
                            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                            if large:
                                page.add_style_tag(content='.legal-documents{font-size:20px!important;line-height:1.6!important}')
                            PhoneSettingsBackupRecoveryScenes.group(self, page, WORDS05[language]['about'])
                            legal = page.locator('.legal-documents')
                            expect(legal.get_by_role('link', name='me@fredtomas.com', exact=True)).to_have_attribute('href','mailto:me@fredtomas.com')
                            summaries = legal.locator(':scope > details > summary')
                            expect(summaries).to_have_text(WORDS06[language]['legal'])
                            policy = legal.locator('pre').first
                            summaries.first.focus(); page.keyboard.press('Enter')
                            expect(policy).to_be_visible()
                            path = 'privacy-policy.md' if language == 'en' else f'privacy-policy.{language}.md'
                            self.assertEqual(policy.text_content(), (ROOT / 'mobile-shell/store' / path).read_text(encoding='utf-8'))
                            expect(policy).to_have_attribute('lang', 'zh-Hant-TW' if language == 'zh-Hant' else language)
                            self.assertTrue(policy.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))
                            self.assertEqual(policy.evaluate('e=>getComputedStyle(e).whiteSpace'), 'pre-wrap')
                            self.assertNotEqual(policy.evaluate('e=>getComputedStyle(e).userSelect'), 'none')
                            # The legal body is selectable text, including Markdown syntax; never HTML.
                            self.assertEqual(policy.locator('*').count(), 0)
                            suffix = '-large' if large else ''
                            policy.evaluate('e=>{e.scrollIntoView({block:"start"});const main=e.closest(".m-main");if(main)main.scrollTop=Math.max(0,main.scrollTop-60)}')
                            if language != 'en':
                                check_scene(self,page,language,theme,'selected-policy'+suffix,sweep='08')
                                original = legal.locator('details details')
                                expect(original.locator('summary')).to_have_text({'fr':'Original anglais','zh-Hant':'英文原文'}[language])
                                expect(original.locator('pre')).not_to_be_visible()
                                original.locator('summary').focus(); page.keyboard.press('Enter')
                                expect(original.locator('pre')).to_be_visible()
                                expect(original.locator('pre')).to_have_attribute('lang','en')
                                self.assertEqual(original.locator('pre').text_content(),(ROOT/'mobile-shell/store/privacy-policy.md').read_text(encoding='utf-8'))
                                check_scene(self,page,language,theme,'english-original'+suffix,sweep='08')
                                page.keyboard.press('Space')
                                expect(original.locator('pre')).not_to_be_visible()
                            else:
                                expect(legal.locator('details details')).to_have_count(0)
                                expect(legal.locator('pre')).to_have_count(3)
                            summaries.first.focus(); page.keyboard.press('Space')
                            expect(policy).not_to_be_visible()
                            for index, file in [(1,'LICENSE'),(2,'THIRD_PARTY_NOTICES.md')]:
                                summaries.nth(index).focus();page.keyboard.press('Enter')
                                body = legal.locator(':scope > details').nth(index).locator('pre')
                                expect(body).to_be_visible();expect(body).to_have_attribute('lang','en')
                                self.assertEqual(body.text_content(),(ROOT/file).read_text(encoding='utf-8'))
                                self.assertTrue(body.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))
                                page.keyboard.press('Space');expect(body).not_to_be_visible()
                            self.assertEqual(errors, [])

    def test_hostile_policy_props_are_escaped_selectable_and_do_not_change_english_default(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360,740,'light',language='fr') as (page,errors):
            page.route('**/api/**',lambda route:route.abort())
            page.goto(base+'/mobile.html#/more',wait_until='domcontentloaded')
            expect(page.locator('#m-status')).to_be_visible()
            hostile = '<img src=x onerror=alert(1)>\n<script>window.__injected08=true</script> & {name}\nhttps://example.test/<b>evil</b>'
            page.evaluate("""async text=>{
              const {mount}=await import('/node_modules/.vite/deps/svelte.js')
              const {default:Legal}=await import('/src/components/LegalDocuments.svelte')
              const target=document.createElement('div');target.id='legal-hostile08';target.className='m-box'
              target.style='position:fixed;inset:50px 12px 85px;overflow:auto;z-index:50;padding:12px';document.body.append(target)
              mount(Legal,{target,props:{policy:text,policyLang:'fr'}})
              const fallback=document.createElement('div');fallback.id='legal-default08';document.body.append(fallback)
              mount(Legal,{target:fallback})
            }""",hostile)
            root=page.locator('#legal-hostile08')
            root.locator('summary').first.press('Enter')
            expect(root.locator('pre').first).to_be_visible()
            self.assertEqual(root.locator('pre').first.text_content(),hostile)
            self.assertEqual(root.locator('img,script,b,[onerror]').count(),0)
            self.assertFalse(page.evaluate('!!window.__injected08'))
            self.assertEqual(page.locator('#legal-default08 pre').first.text_content(),(ROOT/'mobile-shell/store/privacy-policy.md').read_text(encoding='utf-8'))
            expect(page.locator('#legal-default08 pre')).to_have_count(3)
            self.assertEqual(errors,[])


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT/'web/dist/mobile.html').is_file(),
                     'requires Playwright and the current production build')
class PhoneLegalProduction08(unittest.TestCase):
    def test_emitted_dependency_closures_keep_translations_phone_only(self):
        assets=ROOT/'web/dist/assets'
        sources={path.name:path.read_text(encoding='utf-8') for path in assets.glob('*.js')}
        def closure(html):
            pending=re.findall(r'[\w-]+\.js',html);seen=set()
            while pending:
                name=pending.pop()
                if name not in sources or name in seen:continue
                seen.add(name);pending.extend(re.findall(r'[\w-]+\.js',sources[name]))
            return sorted(seen), '\n'.join(sources[name] for name in sorted(seen))
        mobile,phone=closure((ROOT/'web/dist/mobile.html').read_text(encoding='utf-8'))
        desktop,pc=closure((ROOT/'web/dist/index.html').read_text(encoding='utf-8'))
        for marker in ('Brouillon de traduction non relu','未經審閱的翻譯草稿','Original anglais','英文原文'):
            self.assertIn(marker,phone);self.assertNotIn(marker,pc)
        self.assertIn('Last updated: 2026-10-28',pc)
        main=(ROOT/'web/src/mobile/main.ts').read_text(encoding='utf-8')
        self.assertIn("Promise.all([import('./Mobile.svelte'), import('./state.svelte')])",main)
        self.assertNotIn('privacy-policy.fr', (ROOT/'web/src/components/LegalDocuments.svelte').read_text(encoding='utf-8'))
        REVIEW.mkdir(parents=True,exist_ok=True)
        (REVIEW/'08-dependency-closures.json').write_text(json.dumps(dict(phone=mobile,desktop=desktop),indent=2),encoding='utf-8')

    def test_en_first_cached_shell_reopens_offline_and_switches_to_both_policies(self):
        import tempfile
        from types import SimpleNamespace
        from playwright.sync_api import expect
        shots=_shots()
        test=self
        class Review(shots.Run):
            def first_start(self,browser,theme):pass
            def desktop(self,browser,theme):pass
            def phone(self,browser,theme):
                with synthetic_phone(browser,self.base,360,740,theme,language=None) as (page,errors):
                    ctx=page.context
                    ctx.route('**/api/**',lambda route:route.abort())
                    ctx.add_init_script(shots.INIT.replace('THEME',json.dumps(theme)).replace(
                        "localStorage.setItem('bp-lang', 'en')", "if(localStorage.getItem('bp-lang')===null)localStorage.setItem('bp-lang','en')"))
                    ctx.add_init_script("localStorage.setItem('bp-sync-paused','on')")
                    page.goto(self.base+'/mobile.html#/lib',wait_until='domcontentloaded')
                    expect(page.locator('#m-app')).to_be_visible()
                    expect(page.locator('html')).to_have_attribute('lang','en')
                    expect(page.locator('.legal-documents')).to_have_count(0)
                    page.evaluate('async()=>await navigator.serviceWorker.ready')
                    page.wait_for_function("()=>navigator.serviceWorker.controller?.scriptURL.endsWith('/sw.js')")
                    # First controlled load caches the EN shell without ever opening About/policies.
                    page.reload(wait_until='domcontentloaded');expect(page.locator('#m-app')).to_be_visible()
                    page.evaluate("""async()=>{
                      window.__assets08=performance.getEntriesByType('resource').map(e=>e.name).filter(n=>new URL(n).pathname.startsWith('/assets/'))
                      window.__cache08=await caches.open('bp-shell-v7')
                    }""")
                    page.evaluate("""()=>{
                      const check=async()=>{
                        window.__allCached08=window.__assets08.length>0&&(await Promise.all(window.__assets08.map(n=>window.__cache08.match(n)))).every(Boolean)
                        if(!window.__allCached08)requestAnimationFrame(check)
                      };void check()
                    }""")
                    page.wait_for_function('()=>window.__allCached08===true')
                    before=page.evaluate('async()=>(await window.__cache08.keys()).map(r=>new URL(r.url).pathname).sort()')
                    test.assertTrue(any(name.startswith('/assets/') for name in before))
                    expect(page.locator('.legal-documents')).to_have_count(0)
                    page.close();ctx.set_offline(True)
                    page=ctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                    assets=[]
                    page.on('response',lambda response:assets.append((response.url,response.from_service_worker)) if '/assets/' in response.url else None)
                    page.goto(self.base+'/mobile.html#/more',wait_until='domcontentloaded')
                    expect(page.locator('.m-page-keys')).to_be_visible()
                    for choice,language,html_lang,look,label in [('FR','fr','fr','Look','Language'),('繁中','zh-Hant','zh-Hant-TW','Style','Langue')]:
                        PhoneSettingsBackupRecoveryScenes.group(test,page,look)
                        group=page.get_by_role('group',name=label,exact=True)
                        page.wait_for_function('()=>window.__busy===0')
                        self.settle(page)
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            group.get_by_role('button',name=choice,exact=True).click()
                        expect(page.locator('.m-page-keys')).to_be_visible()
                        expect(page.locator('html')).to_have_attribute('lang',html_lang)
                        test.assertEqual(page.evaluate("localStorage.getItem('bp-lang')"),language)
                        PhoneSettingsBackupRecoveryScenes.group(test,page,WORDS05[language]['about'])
                        legal=page.locator('.legal-documents');legal.locator('summary').first.press('Enter')
                        expect(legal.locator('pre').first).to_be_visible()
                        test.assertEqual(legal.locator('pre').first.text_content(),(ROOT/f'mobile-shell/store/privacy-policy.{language}.md').read_text(encoding='utf-8'))
                        expect(legal.locator('pre').first).to_have_attribute('lang',html_lang)
                        original=legal.locator('details details');original.locator('summary').press('Enter')
                        test.assertEqual(original.locator('pre').text_content(),(ROOT/'mobile-shell/store/privacy-policy.md').read_text(encoding='utf-8'))
                    after=page.evaluate("async()=>(await (await caches.open('bp-shell-v7')).keys()).map(r=>new URL(r.url).pathname).sort()")
                    test.assertEqual(after,before,'Offline policies must not need any newly fetched shell asset')
                    test.assertTrue(assets);test.assertTrue(all(sw for _,sw in assets),assets)
                    test.assertEqual(errors,[])
                    (REVIEW/'08-offline-cache.json').write_text(json.dumps(dict(before=before,after=after,asset_responses=assets),indent=2),encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='brainamon-legal08-') as output:
            Review(SimpleNamespace(repo=str(ROOT),dist=str(ROOT/'web/dist'),port=0,out=output,only=None,root=None,themes='light')).go()


@unittest.skipUnless(importlib.util.find_spec('playwright') and (ROOT/'web/node_modules/vite/bin/vite.js').is_file(),
                     'requires Playwright/Edge and web dependencies')
class PhoneValidation09Scenes(unittest.TestCase):
    def test_known_error_display_preserves_raw_message_and_escapes_external_detail(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser, base):
            for language, label in [('fr', 'Erreur du canvas : Le stockage du téléphone est indisponible.'), ('zh-Hant', '畫布錯誤：手機儲存空間無法使用。')]:
                for theme in ('light', 'dark'):
                    with self.subTest(language=language, theme=theme), synthetic_phone(browser, base, 360, 740, theme, language=language) as (page, errors):
                        page.route('**/api/**', lambda route: route.abort())
                        page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
                        page.goto(base+'/mobile.html#/more', wait_until='domcontentloaded')
                        expect(page.locator('.m-page-keys')).to_be_visible()
                        page.evaluate("async()=>window.__phone09=(await import('/src/mobile/state.svelte.ts')).phone")
                        page.wait_for_function('()=>window.__phone09.tried&&!window.__phone09.refreshing')
                        page.evaluate("""async theme=>{
                          const {mirrorSource:m}=await import('/src/mobile/state.svelte.ts')
                          const {kv}=await import('/src/mobile/store.ts');await kv.setRequired('canvases',[])
                          window.__error09=Object.assign(new Error('Phone storage is unavailable.'),{displayKey:'common.error.storageUnavailable'})
                          m.canvases=async()=>{throw window.__error09}
                          document.documentElement.dataset.theme=theme;location.hash='#/canvas'
                        }""", theme)
                        expect(page.locator('.m-err')).to_have_text(label)
                        self.assertEqual(page.evaluate('window.__error09.message'), 'Phone storage is unavailable.')
                        check_scene(self, page, language, theme, 'known-error', sweep='09')
                        page.evaluate("""async()=>{
                          const {mirrorSource:m,phone}=await import('/src/mobile/state.svelte.ts')
                          m.canvases=async()=>{throw new Error('<img src=x onerror=alert(1)> Original external detail')}
                          phone.canvasRevision++
                        }""")
                        expect(page.locator('.m-err')).to_contain_text('<img src=x onerror=alert(1)> Original external detail')
                        self.assertEqual(page.locator('.m-err img').count(), 0)
                        self.assertEqual(errors, [])

    def test_missing_backup_title_localizes_without_changing_cached_or_user_names(self):
        from playwright.sync_api import expect
        with mobile_browser() as (browser,base):
            for language,label in [('fr','Canvas en attente'),('zh-Hant','畫布等待較早的備份')]:
                for theme in ('light','dark'):
                    with self.subTest(language=language,theme=theme), synthetic_phone(browser,base,360,740,theme,language=language) as (page,errors):
                        page.route('**/api/**',lambda route:route.abort())
                        page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
                        page.goto(base+'/mobile.html#/more',wait_until='domcontentloaded')
                        expect(page.locator('.m-page-keys')).to_be_visible()
                        page.evaluate("async()=>window.__phone09=(await import('/src/mobile/state.svelte.ts')).phone")
                        page.wait_for_function('()=>window.__phone09.tried&&!window.__phone09.refreshing')
                        result=page.evaluate("""async theme=>{
                          const {mirrorSource:m,phone}=await import('/src/mobile/state.svelte.ts')
                          m.unresolvedCanvases.add('waiting09')
                          window.__rows09=[{id:'waiting09',name:'Canvas waiting for earlier backup',count:0,updated:0},
                            {id:'user09',name:'Canvas waiting for earlier backup',count:1,updated:0}]
                          const {kv}=await import('/src/mobile/store.ts');await kv.setRequired('canvases',window.__rows09)
                          m.canvases=async()=>structuredClone(window.__rows09)
                          const defaults=[m.canvasTitle('waiting09'),m.canvasTitle('user09')]
                          document.documentElement.dataset.theme=theme;phone.canvasRevision++;location.hash='#/canvas'
                          return defaults
                        }""",theme)
                        self.assertEqual(result,['Canvas waiting for earlier backup',''])
                        titles=page.locator('.m-cv-list button:has(.m-cvi:not(.m-cp-new)) div>b')
                        expect(titles).to_have_text([label,'Canvas waiting for earlier backup'])
                        self.assertTrue(titles.first.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))
                        stored=page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('canvases')")
                        self.assertEqual(stored,page.evaluate('window.__rows09'))
                        check_scene(self,page,language,theme,'missing-backup',sweep='09')
                        page.set_viewport_size(dict(width=390,height=844))
                        page.add_style_tag(content='.m-cv-list b,.m-cv-list small{font-size:20px!important;line-height:1.6!important}')
                        self.assertTrue(titles.first.evaluate('e=>e.scrollWidth<=e.clientWidth+1'))
                        check_scene(self,page,language,theme,'missing-backup-large',sweep='09')
                        self.assertEqual(errors,[])
