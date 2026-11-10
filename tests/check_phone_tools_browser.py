"""The phone's Tools panel, option C (projects/phone-processing-flow): step rows, the confirm line by the rules of decision 2
(also for Retry, Continue and Next), a run that goes on with the panel closed (the Tools key's ring and spoken status), the
finished ledger (Failed and Skipped first, with reasons, the done ones folded), Stop / Continue / Retry / Next, kept card
marks, Undo on one item, the no-key line, the panel's lifecycle across screens and every way out of it, per-step key and
charge rules on the PC, keyboard focus, reduced motion and 130 % text, and a direct PC job shown from its events.

Isolated: Vite only (web/), the synthetic pairing of tests/test_mobile_info_browser.py, synthetic rows
(tests/test_phone_gallery_browser.py seed_items). Every https request is refused, and so is every `/api` request: the AI
calls, the PC's REST answers and its job events are stubs inside the page, and an `/api` attempt fails the check even though
it was blocked. No Drive, no PC, no data folder. Screenshots (light and dark, 360 x 780 and 320 x 568) go to
local/phone-tools/ of the checkout the check runs in.

    py tests/check_phone_tools_browser.py            # everything
    py tests/check_phone_tools_browser.py pc_flow    # one part (names are the functions below)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import expect  # noqa: E402

from tests.test_mobile_info_browser import mobile_browser, synthetic_phone  # noqa: E402
from tests.test_phone_gallery_browser import seed_items  # noqa: E402

ART = ROOT / 'local/phone-tools'
RUN = "async () => { const { runs } = await import('/src/mobile/work.svelte.ts'); return JSON.parse(JSON.stringify(runs)) }"

# Describe on the phone, held item by item: every 7th fails, every 5th has nothing to describe; each call is logged
SLOW_DESCRIBE = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  const f = window.__items
  f.gate = []; f.hold = true; f.calls = []; f.failIds = new Set(); f.nullIds = new Set()
  f.step = () => { const g = f.gate.shift(); if (g) g() }
  source.describe = async (id, undo) => {
    f.calls.push(id)
    if (f.hold) await new Promise(r => f.gate.push(r))
    if (id % 7 === 0 && !f.fixed || f.failIds.has(id)) throw new Error('OpenAI did not answer in time.')
    if (id % 5 === 0 || f.nullIds.has(id)) return null
    f.descriptions[id] = 'A described card ' + id; f.rows.set(id, { ...f.rows.get(id), ai: true })
    undo?.({ kind: 'describe', uid: 'u' + id, was: { ai_desc: '' }, now: { ai_desc: f.descriptions[id] } })
    return f.descriptions[id]
  }
  source.undoTool = async t => { f.undone = t; const id = +t.uid.slice(1), r = { ...f.rows.get(id), ai: false }; f.rows.set(id, r); return r }
}"""


class Attempts:
    """Every `/api` request a page makes is refused and counted: the checks stub them all inside the page."""

    def __init__(self, page):
        self.urls = []
        page.context.route('**/api/**', lambda route: (self.urls.append(route.request.url), route.abort()))

    def none(self, where=''):
        assert self.urls == [], (where, self.urls)


def open_page(browser, base, width, height, theme='light', hash_='#/lib', *, reduced=False):
    ctx = synthetic_phone(browser, base, width, height, theme)
    page, errors = ctx.__enter__()
    attempts = Attempts(page)
    if reduced:
        page.emulate_media(reduced_motion='reduce')
    page.goto(base + '/mobile.html' + hash_)
    # the app's own start (its first read of the copy) is over before a part stubs the source
    for _ in range(150):
        if page.evaluate("async () => (await import('/src/mobile/state.svelte.ts')).phone.tried"):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError('the app did not finish its first read')
    return ctx, page, errors, attempts


class Scenario:
    """One isolated page: closes its context and checks the page raised no error and tried no `/api` request."""

    def __init__(self, browser, base, width=360, height=780, theme='light', hash_='#/lib', **kw):
        self.args = (browser, base, width, height, theme, hash_)
        self.kw = kw

    def __enter__(self):
        if not hasattr(self, 'page'):          # (pc_page enters early to prepare the page; `with` then continues the same one)
            self.ctx, self.page, self.errors, self.attempts = open_page(*self.args, **self.kw)
        return self.page

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                assert self.errors == [], self.errors
                self.attempts.none()
        finally:
            self.ctx.__exit__(exc_type, exc, tb)
        return False


def esc(page):
    """Escape, then waits until the Tools key says the panel is closed. The dialog's close event can reach the page late in
    headless Edge (it came with the next mouse event), so the mouse is nudged while waiting."""
    page.keyboard.press('Escape')
    keys = page.locator('.m-lib-tools[aria-expanded="true"], .m-it-tools[aria-expanded="true"]')
    for _ in range(60):
        if keys.count() == 0:
            return
        page.mouse.move(1, 1)
        page.mouse.move(2, 2)
        page.wait_for_timeout(40)
    raise AssertionError('the Tools panel did not close')


def advance(page, n):
    """Lets n held items finish, one at a time: each waits until the run reached it (its gate exists)."""
    for _ in range(n):
        poll(page, '() => window.__items.gate.length > 0')
        page.evaluate('window.__items.step()')


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        page.wait_for_timeout(120)
        assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), 'wider than the screen'
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def poll(page, js, timeout=10):
    end = time.monotonic() + timeout
    while True:
        got = page.evaluate(js)
        if got:
            return got
        assert time.monotonic() < end, js
        page.wait_for_timeout(80)


def inside(page, locator, width, height):
    box = locator.bounding_box()
    assert box['x'] >= -0.5 and box['x'] + box['width'] <= width + 0.5 and box['y'] + box['height'] <= height + 0.5, box


def panel_of(page):
    return page.get_by_role('dialog', name='Tools', exact=True)


def phone_rows(page, n):
    """The Library shows n synthetic cards that all still need Describe."""
    page.evaluate("""async n => { const { phone } = await import('/src/mobile/state.svelte.ts'); const f = window.__items
      phone.cat = 'all'; phone.rows = [...f.rows.values()].filter(r => r.id > 0 && r.id !== 999).slice(0, n) }""", n)


# ── the main flow: confirm, run, close, ring, Stop, Continue, Retry, Next ─────────────────────────────────────────────
def phone_runs(page, width, height):
    seed_items(page)
    page.evaluate(SLOW_DESCRIBE)
    key = page.locator('.m-lib-tools')
    key.click()
    panel = panel_of(page)
    expect(panel).to_be_visible()
    # two rows, Describe suggested (80 without a summary), Auto-categorize has nothing to sort (Art)
    describe = panel.get_by_role('button', name='Describe', exact=True)
    expect(describe).to_be_enabled()
    expect(panel.get_by_role('button', name='Auto-categorize', exact=True)).to_be_disabled()
    expect(panel.locator('.m-step-rec')).to_contain_text('80 without a summary · 25 AI calls')
    expect(panel.locator('.m-step-tag')).to_have_text('Suggested')
    expect(panel.locator('.m-tl-scope')).to_have_text('Art · 80')
    expect(panel.locator('.m-tl-line')).to_have_text('Runs on this phone with its fixture key · Fixture AI. Tap a step to start it.')
    inside(page, panel, width, height)
    shoot(page, f'c3-steps-{width}')
    # more than 25 asks in the row, then the first 25
    describe.click()
    expect(describe).to_have_attribute('aria-expanded', 'true')
    expect(panel.locator('.m-tl-ask')).to_contain_text('80 items need Describe. This phone does 25 at a time: the first 25 now, 25 AI calls on its fixture key.')
    shoot(page, f'c5-confirm-{width}')
    panel.get_by_role('button', name='Cancel', exact=True).click()
    expect(panel.locator('.m-tl-ask')).to_have_count(0)
    assert page.evaluate('window.__items.calls.length') == 0
    describe.click()
    panel.get_by_role('button', name='Describe the first 25', exact=True).click()
    # a started run puts keyboard focus on its Stop key
    expect(panel.get_by_role('button', name='Stop', exact=True)).to_be_focused()
    advance(page, 4)
    poll(page, '() => window.__items.gate.length > 0')
    expect(panel.locator('.m-runbar')).to_contain_text('5 of 25')
    expect(panel.locator('.m-runbar')).to_contain_text('25 AI calls')
    expect(panel.locator('.m-tl-cur')).to_have_count(1)
    expect(panel.locator('.m-tl-li')).to_have_count(6)
    expect(panel).to_contain_text('Stop finishes this item first. Each result is saved as it lands.')
    shoot(page, f'c6-running-{width}')
    # closing the panel leaves the run going; the Tools key carries the ring, the count left and a spoken status
    esc(page)
    expect(panel).to_have_count(0)
    expect(key).to_be_focused()                                  # Escape returns to the key that opened the panel
    expect(key.locator('.m-tools-ring')).to_have_count(1)
    expect(key.locator('.m-tools-n')).to_have_text('21')
    expect(page.locator('#m-tools-status')).to_have_text('Tools: 4 of 25 done, 21 left')
    expect(key).to_have_attribute('aria-describedby', 'm-tools-status')
    shoot(page, f'ring-{width}')
    key.click()
    expect(panel).to_be_visible()
    expect(panel.locator('.m-runbar')).to_contain_text('5 of 25')   # reopened: the run is there
    # Stop: the item in hand finishes, the rest wait
    panel.get_by_role('button', name='Stop', exact=True).click()
    expect(panel).to_contain_text('Stopping after this item…')
    advance(page, 1)
    expect(panel.locator('.m-runbar')).to_contain_text('Stopped · 4 described · 1 skipped')
    expect(panel.get_by_role('button', name='Continue with 20', exact=True)).to_be_visible()
    expect(panel.get_by_role('button', name='Continue with 20', exact=True)).to_be_focused()    # a finished run puts focus on the key to press next
    expect(panel.locator('.m-tl-group').filter(has_text='Not started · 20')).to_have_count(1)
    shoot(page, f'stopped-{width}')
    # Continue is 20 calls, not more than 20: one tap, no question
    page.evaluate('window.__items.hold = false')
    panel.get_by_role('button', name='Continue with 20', exact=True).click()
    poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
    assert page.evaluate('window.__items.calls.slice(5)') == list(range(6, 26)), 'Continue runs only the waiting items, once'
    groups = panel.locator('.m-tl-group')
    expect(groups.nth(0)).to_have_text('Failed · 3')              # 7, 14, 21
    expect(groups.nth(1)).to_have_text('Skipped · 5')             # 5, 10, 15, 20, 25
    expect(panel).to_contain_text('OpenAI did not answer in time.')
    expect(panel).to_contain_text('Nothing to describe yet: open it online once or add a note.')
    fold = panel.locator('.m-tl-fold')
    expect(fold).to_have_text('Described · 17')
    expect(fold).to_have_attribute('aria-expanded', 'false')
    expect(panel.locator('.m-runbar')).to_contain_text('17 described · 5 skipped · 3 failed')
    expect(panel.get_by_role('button', name='Retry 3 failed', exact=True)).to_be_visible()
    assert page.locator('.m-cell.m-w-skip').count() >= 1 and page.locator('.m-cell.m-w-err').count() >= 1   # kept marks
    shoot(page, f'c7-finished-{width}')
    fold.click()
    expect(fold).to_have_attribute('aria-expanded', 'true')
    # Retry: only the three failed run again (they fail again); nothing else runs, nothing is lost
    before = page.evaluate('window.__items.calls.length')
    panel.get_by_role('button', name='Retry 3 failed', exact=True).click()
    poll(page, f"() => window.__items.calls.length >= {before + 3}")
    expect(panel.locator('.m-runbar')).to_contain_text('17 described · 5 skipped · 3 failed')
    assert page.evaluate(f'window.__items.calls.slice({before})') == [7, 14, 21]
    # they pass this time; the rest of the 80 is still there for Next 25
    page.evaluate('window.__items.fixed = true')
    panel.get_by_role('button', name='Retry 3 failed', exact=True).click()
    expect(panel.get_by_role('button', name='Next 25', exact=True)).to_be_visible()
    expect(panel.locator('.m-runbar')).to_contain_text('20 described · 5 skipped')
    # Next 25 is 25 calls: it asks, in the finished run's heading row; Cancel leaves the ledger as it was
    calls = page.evaluate('window.__items.calls.length')
    panel.get_by_role('button', name='Next 25', exact=True).click()
    expect(panel.locator('.m-tl-ask')).to_contain_text('Next 25. 25 AI calls on this phone’s fixture key.')
    expect(panel.get_by_role('button', name='Next 25', exact=True)).to_be_disabled()
    shoot(page, f'next-confirm-{width}')
    panel.get_by_role('button', name='Cancel', exact=True).click()
    expect(panel.locator('.m-tl-ask')).to_have_count(0)
    expect(panel.locator('.m-runbar')).to_contain_text('20 described · 5 skipped')
    assert page.evaluate('window.__items.calls.length') == calls
    panel.get_by_role('button', name='Next 25', exact=True).click()
    panel.get_by_role('button', name='Describe 25 now', exact=True).click()
    poll(page, "async () => { const r = (await (" + RUN + ")()).phone; return r?.ended && r.items[0].id === 26 }")
    assert page.evaluate(f'window.__items.calls.slice({calls})') == list(range(26, 51))
    expect(panel.get_by_role('button', name='Next 25', exact=True)).to_be_visible()      # 51..75 are still to come
    panel.get_by_role('button', name='Done', exact=True).click()
    expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_visible()
    expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_focused()     # after Done focus goes back to the first step
    expect(panel.locator('.m-step-rec')).to_contain_text('without a summary')
    esc(page)
    expect(page.locator('.m-cell.m-w-skip')).to_have_count(0)
    expect(page.locator('.m-cell.m-w-err')).to_have_count(0)


def phone_item(page, width):
    seed_items(page)
    page.evaluate(SLOW_DESCRIBE)
    page.evaluate('window.__items.hold = false')
    page.evaluate("location.hash = '#/item/31'")
    key = page.locator('.m-it-tools')
    key.click()
    panel = panel_of(page)
    expect(panel.locator('.m-tl-scope')).to_have_text('This item')
    expect(panel.locator('.m-step-rec')).to_contain_text('A short summary from the caption and thumbnail · 1 AI call')
    shoot(page, f'c1-item-{width}')
    panel.get_by_role('button', name='Describe', exact=True).click()
    expect(panel.locator('.m-tl-pv')).to_contain_text('New AI description')
    expect(panel.locator('.m-tl-pv')).to_contain_text('A described card 31')
    expect(panel.locator('.m-step-fin')).to_contain_text('Saved on this phone.')       # the synthetic pairing is solo
    shoot(page, f'c2-item-done-{width}')
    panel.get_by_role('button', name='Undo', exact=True).click()
    expect(panel.locator('.m-tl-pv')).to_contain_text('Description restored')
    expect(panel.get_by_role('button', name='Undo', exact=True)).to_have_count(0)
    assert page.evaluate('window.__items.undone')['uid'] == 'u31'
    esc(page)
    expect(panel).to_have_count(0)


# ── decision 2: when it asks (20 / 21 / 25 / 26, Run again, a double tap) ─────────────────────────────────────────────
def boundaries(browser, base):
    for n, asks, first in ((20, False, 20), (21, True, 21), (25, True, 25), (26, True, 25)):
        with Scenario(browser, base) as page:
            seed_items(page)
            page.evaluate(SLOW_DESCRIBE)
            page.evaluate('window.__items.hold = false; window.__items.nullIds = new Set(); window.__items.fixed = true')
            page.evaluate("() => { window.__items.nullIds = { has: () => false }; }")
            phone_rows(page, n)
            page.locator('.m-lib-tools').click()
            panel = panel_of(page)
            panel.get_by_role('button', name='Describe', exact=True).click()
            if asks:
                expect(panel.locator('.m-tl-ask')).to_be_visible()
                assert page.evaluate('window.__items.calls.length') == 0, n
                # a double tap on the confirm key starts one run, not two
                panel.get_by_role('button', name=f'Describe {first} now' if n <= 25 else f'Describe the first {first}', exact=True).dblclick()
            poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
            calls = page.evaluate('window.__items.calls')
            assert len(calls) == first, (n, len(calls))
            assert len(set(calls)) == first, 'an item was sent twice'
    # Run again on one item always asks, and replaces
    with Scenario(browser, base) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.evaluate('window.__items.hold = false; window.__items.fixed = true; window.__items.nullIds = { has: () => false }')
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); const f = window.__items; f.rows.set(1, { ...f.rows.get(1), ai: true }); phone.cat = 'all'; phone.rows = [f.rows.get(1)] }")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_disabled()      # nothing needs it
        panel.get_by_text('More', exact=True).click()
        panel.get_by_role('button', name='Include completed items (run again)', exact=True).click()
        again = panel.get_by_role('button', name='Describe again', exact=True)
        again.click()
        expect(panel.locator('.m-tl-ask')).to_contain_text('Run again on 1 item. Replace existing AI descriptions. 1 AI call on this phone’s fixture key')
        assert page.evaluate('window.__items.calls.length') == 0
        panel.get_by_role('button', name='Describe 1 now', exact=True).click()
        poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
        assert page.evaluate('window.__items.calls') == [1]
    # a follow-up with Run again asks even when it is small, and names its action
    with Scenario(browser, base) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.evaluate('window.__items.hold = false; window.__items.failIds = new Set([2]); window.__items.nullIds = { has: () => false }')
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); const f = window.__items; for (const id of [1, 2, 3]) f.rows.set(id, { ...f.rows.get(id), ai: true }); phone.cat = 'all'; phone.rows = [1, 2, 3].map(id => f.rows.get(id)) }")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_text('More', exact=True).click()
        panel.get_by_role('button', name='Include completed items (run again)', exact=True).click()
        panel.get_by_role('button', name='Describe again', exact=True).click()
        panel.get_by_role('button', name='Describe 3 now', exact=True).click()
        poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
        calls = page.evaluate('window.__items.calls.length')
        panel.get_by_role('button', name='Retry 1 failed', exact=True).click()
        expect(panel.locator('.m-tl-ask')).to_contain_text('Retry 1 failed. Run again on 1 item.')
        assert page.evaluate('window.__items.calls.length') == calls, 'a follow-up of a Run again must ask first'
        panel.get_by_role('button', name='Cancel', exact=True).click()
        expect(panel.locator('.m-runbar')).to_contain_text('2 described · 1 failed')


# ── R6: the panel's lifecycle ────────────────────────────────────────────────────────────────────────────────────────
def removed_followup(browser, base):
    with Scenario(browser, base) as page:
        seed_items(page)
        phone_rows(page, 1)
        page.evaluate(SLOW_DESCRIBE)
        page.evaluate("() => { window.__items.hold = false; window.__items.failIds.add(1) }")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); phone.rows = phone.rows.filter(r => r.id !== 1); window.__items.rows.delete(1) }")
        panel.get_by_role('button', name='Retry 1 failed', exact=True).click()
        expect(panel.locator('.m-runbar')).to_contain_text('1 skipped')
        expect(panel.get_by_role('button', name='Retry 1 failed', exact=True)).to_have_count(0)
        assert page.evaluate('window.__items.calls') == [1]


def lifecycle(browser, base):
    # a batch started in the Library keeps its scope on an item screen; finishing hidden keeps the summary; Done goes back
    with Scenario(browser, base) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        panel.get_by_role('button', name='Describe the first 25', exact=True).click()
        advance(page, 2)
        esc(page)
        page.evaluate("location.hash = '#/item/31'")
        item_key = page.locator('.m-it-tools')
        expect(item_key.locator('.m-tools-ring')).to_have_count(1)         # the ring follows to the next screen
        item_key.click()
        expect(panel.locator('.m-tl-scope')).to_have_text('Art · 80')       # not "This item"
        expect(panel.locator('.m-runbar')).to_contain_text('of 25')
        esc(page)
        page.evaluate('window.__items.hold = false; window.__items.gate.splice(0).forEach(g => g())')
        poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
        item_key.click()
        expect(panel.locator('.m-tl-scope')).to_have_text('Art · 80')       # finished while hidden: the summary waits to be reviewed
        expect(panel.locator('.m-runbar')).to_contain_text('described')
        expect(panel.get_by_role('button', name='Retry 3 failed', exact=True)).to_be_visible() if page.evaluate('window.__items.calls.some(i => i % 7 === 0)') else None
        panel.get_by_role('button', name='Done', exact=True).click()
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_visible()
        expect(panel.locator('.m-tl-scope')).to_have_text('This item')
        esc(page)
    # one item's Undo keeps its target when the panel is reopened from the Library
    with Scenario(browser, base) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.evaluate('window.__items.hold = false')
        page.evaluate("location.hash = '#/item/31'")
        page.locator('.m-it-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        expect(panel.get_by_role('button', name='Undo', exact=True)).to_be_visible()
        page.evaluate("location.hash = '#/lib'")                           # a route change unmounts the open panel: a finished run goes with it
        expect(panel).to_have_count(0)
        expect(page.locator('#m-tools-status')).to_have_text('')
    # the Tools key stays while a run exists even when the filter shows nothing
    with Scenario(browser, base) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        panel.get_by_role('button', name='Describe the first 25', exact=True).click()
        advance(page, 1)
        esc(page)
        page.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); phone.q = 'zzz-nothing'; phone.searchIds = new Set(); phone.rank = null }")
        expect(page.locator('.m-lib-tools')).to_have_count(1)
        page.locator('.m-lib-tools').click()
        expect(panel).to_be_visible()
        expect(panel.locator('.m-runbar')).to_contain_text('of 25')
        esc(page)
    # every way out of a finished panel clears the run and its kept marks
    for way in ('escape', 'outside', 'route'):         # (the Tools key is under the modal panel: a tap on it is a tap outside)
        with Scenario(browser, base) as page:
            seed_items(page)
            page.evaluate(SLOW_DESCRIBE)
            page.evaluate('window.__items.hold = false; window.__items.failIds = new Set([2])')
            phone_rows(page, 6)
            key = page.locator('.m-lib-tools')
            key.click()
            panel = panel_of(page)
            panel.get_by_role('button', name='Describe', exact=True).click()
            expect(panel.get_by_role('button', name='Retry 1 failed', exact=True)).to_be_visible()
            assert page.locator('.m-cell.m-w-err').count() == 1, way
            if way == 'escape':
                esc(page)
            elif way == 'outside':
                page.mouse.click(2, 2)
            else:
                page.evaluate("location.hash = '#/more'")
            expect(panel).to_have_count(0)
            run = page.evaluate(RUN)
            assert run['phone'] is None, (way, run)
            page.evaluate("location.hash = '#/lib'")
            expect(page.locator('.m-cell.m-w-err')).to_have_count(0)


# ── no key ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def phone_no_key(page, width):
    seed_items(page)
    page.evaluate("""async () => { const { source } = await import('/src/mobile/state.svelte.ts')
      source.ai = () => null
      source.noKeyText = () => 'Wiskit needs an AI key on this phone: add your Anthropic or OpenAI key under Settings > Wiskit on this phone.' }""")
    page.locator('.m-lib-tools').click()
    panel = panel_of(page)
    expect(panel.get_by_role('alert')).to_contain_text('No AI key. Wiskit needs an AI key on this phone')
    expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_disabled()
    expect(panel.locator('.m-step-rec')).to_have_count(0)
    shoot(page, f'c8-no-key-{width}')
    esc(page)


# ── the PC (R2, R3, R4, R7) ──────────────────────────────────────────────────────────────────────────────────────────
PC = """async () => {
  const { source, phone } = await import('/src/mobile/state.svelte.ts')
  const { api } = await import('/src/lib/api.ts')
  const { DesktopSource } = await import('/src/mobile/source/desktop.ts')
  const f = window.__items
  const pc = window.__pc = { events: new EventTarget(), posts: [], puts: [], gets: [], next: 40, jobs: {}, hold: {}, preview: {}, previewHold: null, postHold: null,
    settings: { frame_interval: 3, transcribe: true, analysis_provider: 'claude', ai_frame_budget: 'auto', keep_frames: true, show_frames_in_canvas: true, delete_video: false, delete_audio: false },
    current: null }
  source.kind = 'desktop'
  phone.cat = 'all'
  phone.rows = [...f.rows.values()].filter(r => r.id > 0 && r.id !== 999).slice(0, 80).map(r => ({ ...r, nd: 15 }))
  for (const r of phone.rows) f.rows.set(r.id, r)
  new DesktopSource().watchJob(pc.events)
  pc.send = (type, data) => pc.events.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
  pc.items = []
  const J = (id, kind, state, o = {}) => ({ id, kind, label: kind[0].toUpperCase() + kind.slice(1), state, total: 0, done: 0, skipped: 0, err: 0, ...o })
  pc.J = J
  api.get = async url => {
    pc.gets.push(url)
    if (url === '/api/jobs/progress') return { job: pc.job || null, items: pc.items }
    if (url === '/api/jobs') return { current: pc.current, last: pc.last || null }
    if (url === '/api/settings/analyze') return { options: JSON.parse(JSON.stringify(pc.settings)) }
    if (url === '/api/app/setup') return { tools: { 'yt-dlp': true, ffmpeg: true }, cookies: false }
    throw new Error('refused: ' + url)
  }
  api.put = async (url, body) => { pc.puts.push({ url, body }); if (pc.putHold) await pc.putHold.p; if (url === '/api/settings/analyze') pc.settings = { ...pc.settings, ...body }; return {} }
  api.post = async (url, body) => {
    pc.posts.push({ url, body })
    if (url === '/api/jobs/preview') {
      if (pc.previewHold) await pc.previewHold.p
      const r = pc.preview[body.kind]
      const v = typeof r === 'function' ? r(body) : r
      if (v instanceof Error) throw v
      return v ?? { count: body.ids.length, provider: 'openai', model: 'gpt-6-luna', key: true }
    }
    if (url === '/api/jobs') {
      if (pc.postHold) await pc.postHold.p
      if (pc.join) return pc.current                     // a second Analyze joins the running one: the same job answers
      const id = ++pc.next
      pc.job = J(id, body.kind, 'running', { total: body.ids.length })
      pc.current = pc.job
      pc.items = body.ids.map(i => ({ id: i, state: 'queued', title: 'PC title ' + i }))
      return pc.job
    }
    if (url === '/api/jobs/stop') { if (pc.stopError) throw new Error(pc.stopError); return {} }
    throw new Error('refused: ' + url)
  }
  pc.defer = () => { let resolve; const p = new Promise(r => { resolve = r }); return { p, resolve } }
}"""


def pc_state(page):
    # previews: not the panel's own look at the PC's model (one item, forced), which it makes when it opens
    return page.evaluate("() => { const pc = window.__pc; return { posts: pc.posts.filter(p => p.url === '/api/jobs'), previews: pc.posts.filter(p => p.url === '/api/jobs/preview' && !(p.body.force && p.body.ids.length === 1)), stops: pc.posts.filter(p => p.url === '/api/jobs/stop'), puts: pc.puts } }")


def pc_page(browser, base, width=360, height=780, **kw):
    sc = Scenario(browser, base, width, height, **kw)
    page = sc.__enter__()
    seed_items(page, 'desktop')
    page.evaluate(PC)
    # the source's kind never changes in the app, so a screen drawn before the test set it is drawn again
    page.evaluate("location.hash = '#/more'")
    page.wait_for_timeout(150)
    page.evaluate("location.hash = '#/lib'")
    expect(page.locator('.m-lib-tools')).to_be_visible()
    return sc, page


def other_steps(panel):
    """Opens 'Other PC steps' unless the suggestion already opened it."""
    if not panel.get_by_role('button', name='Index for search', exact=True).is_visible():
        panel.get_by_text('Other PC steps · 3', exact=True).click()
    expect(panel.get_by_role('button', name='Index for search', exact=True)).to_be_visible()


def width_of(page):
    return page.viewport_size['width']


def end_pc_job(page, state='finished', errors=None, **counts):
    """The PC's job ends: its last snapshot as an event and as the answers to GET /api/jobs[/progress]; `errors` maps an
    item id to the message of its failure."""
    page.evaluate("""([state, errors, counts]) => { const pc = window.__pc
      pc.items = pc.items.map(i => (errors[i.id] ? { ...i, state: 'error', error: errors[i.id] }
        : i.state === 'queued' || i.state === 'working' ? { ...i, state: state === 'finished' ? 'done' : 'queued' } : i))
      pc.job = { ...pc.job, state, ...counts }; pc.current = null; pc.last = pc.job
      pc.send('job', { current: null, last: pc.job }) }""", [state, {str(k): v for k, v in (errors or {}).items()}, counts])


def pc_flow(browser, base):
    # each step is previewed and charged by itself: no Describe key does not stop Index, Fetch or Analyze
    sc, page = pc_page(browser, base)
    with sc:
        page.evaluate("""() => { const pc = window.__pc
          pc.preview.describe = { count: 80, provider: 'openai', model: 'gpt-6-luna', key: false }
          pc.preview.index = { count: 1280, provider: 'embeddings', model: 'e', key: true } }""")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        expect(panel.locator('.m-tl-line').first).to_have_text('Runs on your PC · OpenAI gpt-6-luna. Tap a step to start it.')
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_enabled()      # no key gate from the Describe preview
        other_steps(panel)
        for name in ('Fetch link info', 'Analyze videos', 'Index for search'):
            expect(panel.get_by_role('button', name=name, exact=True)).to_be_enabled()
        shoot(page, f'c4-pc-steps-{width_of(page)}')
        panel.get_by_role('button', name='Describe', exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('API key required: on the PC open Settings > API keys.')
        assert pc_state(page)['posts'] == []
        # Fetch link info needs no key at all and never asks
        panel.get_by_role('button', name='Fetch link info', exact=True).click()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs')")
        assert pc_state(page)['posts'][0]['body']['kind'] == 'thumb'
        end_pc_job(page, done=80)
        poll(page, "async () => (await (" + RUN + ")()).pc?.ended")
        panel.get_by_role('button', name='Done', exact=True).click()
        # Index sends 64 texts per call: 1280 texts is 20 calls and starts at once; 1281 is 21 and asks
        other_steps(panel)
        panel.get_by_role('button', name='Index for search', exact=True).click()
        poll(page, "() => window.__pc.posts.filter(p => p.url === '/api/jobs').length === 2")
        assert pc_state(page)['posts'][1]['body']['kind'] == 'index' and pc_state(page)['posts'][1]['body']['force'] is False
        end_pc_job(page, done=80)
        poll(page, "async () => (await (" + RUN + ")()).pc?.ended")
        panel.get_by_role('button', name='Done', exact=True).click()
        page.evaluate("() => { window.__pc.preview.index = { count: 1281, provider: 'embeddings', model: 'e', key: true } }")
        other_steps(panel)
        panel.get_by_role('button', name='Index for search', exact=True).click()
        expect(panel.locator('.m-tl-ask')).to_contain_text('21 embedding calls on the PC’s embeddings key')
        assert len(pc_state(page)['posts']) == 2
        panel.get_by_role('button', name='Cancel', exact=True).click()
        # the embeddings key missing says so (its own message) and starts nothing
        page.evaluate("() => { window.__pc.preview.index = { count: 5, provider: 'embeddings', model: 'e', key: false } }")
        panel.get_by_role('button', name='Index for search', exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('Embeddings key required')
        assert len(pc_state(page)['posts']) == 2
        esc(page)


def pc_analyze(browser, base):
    sc, page = pc_page(browser, base)
    with sc:
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        other_steps(panel)
        panel.get_by_role('button', name='Analyze videos', exact=True).click()
        # the options open before anything is previewed, and the question is always asked
        expect(panel.get_by_label('Frame interval', exact=False)).to_have_value('3')
        assert not pc_state(page)['previews'], 'the options must open before the preview'
        shoot(page, f'c4-analyze-{width_of(page)}')
        # a transcription key missing on the PC: the PC's answer is shown, the options stay, nothing starts
        page.evaluate("() => { window.__pc.preview.analyze = body => (body.opts.transcribe ? new Error('Transcription needs an OpenAI API key.') : { count: body.ids.length, key: true }) }")
        go = panel.get_by_role('button', name='Start 80 on the PC', exact=True)
        go.click()
        expect(panel.get_by_role('alert')).to_contain_text('Transcription needs an OpenAI API key.')
        expect(panel.get_by_label('Frame interval', exact=False)).to_be_visible()
        assert pc_state(page)['posts'] == []
        # frames only with the report off needs no AI key: the chosen options are what the PC previews and runs; the choice is saved
        panel.get_by_label('Transcribe audio', exact=False).uncheck()
        panel.get_by_label('Frame interval', exact=False).fill('5')
        panel.get_by_label('AI report', exact=False).select_option('none')
        go.click()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs')")
        st = pc_state(page)
        chosen = {'frame_interval': 5, 'transcribe': False, 'analysis_provider': 'none'}
        assert all(st['previews'][-1]['body']['opts'][k] == v for k, v in chosen.items()), st['previews'][-1]
        assert all(st['posts'][0]['body']['opts'][k] == v for k, v in chosen.items()) and st['posts'][0]['body']['force'] is False, st['posts']
        assert [p['url'] for p in st['puts']] == ['/api/settings/analyze']
        # one video fails; Retry keeps those options, asks (Analyze always does) and saves nothing new
        page.evaluate("""() => { const pc = window.__pc, job = pc.job.id
          pc.send('job', { current: pc.job, last: null })
          pc.send('job_item', { job, id: 3, state: 'error', error: 'No video found.' })
          for (const i of pc.items) if (i.id !== 3) pc.send('job_item', { job, id: i.id, state: 'done' }) }""")
        end_pc_job(page, errors={3: 'No video found.'}, done=79, err=1)
        poll(page, "async () => (await (" + RUN + ")()).pc?.ended")
        page.wait_for_timeout(700)
        panel.get_by_role('button', name='Retry 1 failed', exact=True).click()
        expect(panel.locator('.m-tl-ask')).to_contain_text('Retry 1 failed. 1 video. Same options as this run.')
        expect(panel.get_by_label('Frame interval', exact=False)).to_have_count(0)
        # the saved default changes meanwhile: the retry must not pick it up
        page.evaluate("() => { window.__pc.settings = { ...window.__pc.settings, frame_interval: 9, analysis_provider: 'claude' } }")
        shoot(page, f'c4-analyze-retry-{width_of(page)}')
        panel.get_by_role('button', name='Start 1 on the PC', exact=True).click()
        poll(page, "() => window.__pc.posts.filter(p => p.url === '/api/jobs').length === 2")
        st = pc_state(page)
        assert st['posts'][1]['body'] == {'kind': 'analyze', 'ids': [3], 'force': False, 'opts': st['posts'][0]['body']['opts']}, st['posts'][1]
        assert st['posts'][1]['body']['opts']['frame_interval'] == 5 and len(st['puts']) == 1
        esc(page)
    # joining a running Analyze: the options are the running job's, and the Stop label says it ends the whole job
    sc, page = pc_page(browser, base)
    with sc:
        page.evaluate("""() => { const pc = window.__pc; pc.current = pc.J(77, 'analyze', 'running', { label: 'Analyze videos', total: 4, done: 1 }); pc.job = pc.current; pc.join = true
          pc.items = [1, 2, 3, 4].map(i => ({ id: i, state: i === 1 ? 'done' : 'queued', title: 'PC title ' + i })); pc.send('job', { current: pc.current, last: null }) }""")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        expect(panel.get_by_role('status').first).to_contain_text('The PC is busy: Analyze videos, 1 of 4.')
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_disabled()
        other_steps(panel)
        expect(panel.get_by_role('button', name='Fetch link info', exact=True)).to_be_disabled()
        panel.get_by_role('button', name='Analyze videos', exact=True).click()
        expect(panel.locator('.m-step .m-tl-ask')).to_contain_text('They join the running analysis and use its options, which are shared with that job.')
        expect(panel.get_by_label('Frame interval', exact=False)).to_have_count(0)
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs')")
        assert pc_state(page)['posts'][0]['body']['opts'] == {} and pc_state(page)['puts'] == []
        poll(page, "async () => (await (" + RUN + ")()).pc?.joined === true")
        expect(panel.get_by_role('button', name='Stop PC job', exact=True)).to_be_visible()
        expect(panel).to_contain_text('joined to a running analysis. Stop ends the whole PC job.')
        page.wait_for_timeout(700)
        panel.get_by_role('button', name='Stop PC job', exact=True).click()
        assert [s['body'] for s in pc_state(page)['stops']] == [{'id': 77}]
        esc(page)


def pc_guards(browser, base):
    # The settings save may already be sent, but closing before it answers must still prevent the job POST.
    sc, page = pc_page(browser, base)
    with sc:
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        other_steps(panel)
        panel.get_by_role('button', name='Analyze videos', exact=True).click()
        expect(panel.get_by_label('Frame interval', exact=False)).to_be_visible()
        page.evaluate("() => { const pc = window.__pc; pc.putHold = pc.defer() }")
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
        poll(page, "() => window.__pc.puts.length === 1")
        esc(page)
        page.evaluate("() => window.__pc.putHold.resolve()")
        page.wait_for_timeout(300)
        assert pc_state(page)['posts'] == []
    # Analyze's final preview is cancellable before saving options or sending a job.
    sc, page = pc_page(browser, base)
    with sc:
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        other_steps(panel)
        panel.get_by_role('button', name='Analyze videos', exact=True).click()
        expect(panel.get_by_label('Frame interval', exact=False)).to_be_visible()
        page.evaluate("() => { const pc = window.__pc; pc.previewHold = pc.defer() }")
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs/preview' && p.body.kind === 'analyze')")
        esc(page)
        page.evaluate("() => window.__pc.previewHold.resolve()")
        page.wait_for_timeout(300)
        st = pc_state(page)
        assert st['posts'] == [] and st['puts'] == [], st
    # Done discards a pending follow-up preview and an already visible confirmation.
    for pending in (True, False):
        sc, page = pc_page(browser, base)
        with sc:
            page.locator('.m-lib-tools').click()
            panel = panel_of(page)
            panel.get_by_role('button', name='Describe', exact=True).click()
            panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
            poll(page, "async () => (await (" + RUN + ")()).pc?.loaded")
            end_pc_job(page, errors={i: 'Synthetic' for i in range(1, 81)}, err=80)
            poll(page, "async () => (await (" + RUN + ")()).pc?.ended")
            if pending:
                page.evaluate("() => { const pc = window.__pc; pc.previewHold = pc.defer() }")
            panel.get_by_role('button', name='Retry 80 failed', exact=True).click()
            if not pending:
                expect(panel.locator('.m-tl-ask')).to_contain_text('Retry 80 failed')
            panel.get_by_role('button', name='Done', exact=True).click()
            if pending:
                page.evaluate("() => { window.__pc.previewHold.resolve(); window.__pc.previewHold = null }")
            page.wait_for_timeout(300)
            panel.get_by_role('button', name='Describe', exact=True).click()
            expect(panel.locator('.m-tl-ask')).to_contain_text('80 AI calls')
            panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
            poll(page, "() => window.__pc.posts.filter(p => p.url === '/api/jobs').length === 2")
    # closing while the preview is in flight: nothing starts afterwards
    sc, page = pc_page(browser, base)
    with sc:
        page.evaluate("() => { const pc = window.__pc; pc.previewHold = pc.defer() }")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        describe = panel.get_by_role('button', name='Describe', exact=True)
        describe.click()
        expect(describe).to_be_disabled()                                  # one preview at a time
        esc(page)
        expect(panel).to_have_count(0)
        page.evaluate("() => window.__pc.previewHold.resolve()")
        page.wait_for_timeout(300)
        st = pc_state(page)
        assert len(st['previews']) == 1 and st['posts'] == [], st            # the preview came back after the panel closed: no job
    # a double tap on a step makes one preview; a double tap on the confirm key makes one job
    sc, page = pc_page(browser, base)
    with sc:
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).dblclick()
        expect(panel.locator('.m-tl-ask')).to_be_visible()
        assert len(pc_state(page)['previews']) == 1
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).dblclick()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs')")
        page.wait_for_timeout(200)
        assert len(pc_state(page)['posts']) == 1
    # closing after the start was sent: the job still starts and the run is there when the panel opens again
    sc, page = pc_page(browser, base)
    with sc:
        page.evaluate("() => { const pc = window.__pc; pc.postHold = pc.defer() }")
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
        poll(page, "() => window.__pc.posts.some(p => p.url === '/api/jobs')")
        esc(page)
        expect(panel).to_have_count(0)
        page.evaluate("() => window.__pc.postHold.resolve()")
        poll(page, "async () => (await (" + RUN + ")()).pc?.job === 41")
        expect(page.locator('#m-tools-status')).to_have_text('Tools: 0 of 80 done, 80 left')
        page.locator('.m-lib-tools').click()
        expect(panel.locator('.m-runbar')).to_contain_text('on your PC')
        expect(page.locator('#m-tools-status')).to_have_text('')           # the panel is open: the closed key says nothing
        esc(page)


def pc_job(browser, base, width, height):
    sc, page = pc_page(browser, base, width, height)
    with sc:
        key = page.locator('.m-lib-tools')
        key.click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        expect(panel.locator('.m-tl-ask')).to_contain_text('80 AI calls on the PC’s OpenAI key. Provider charges may apply. The PC works through them; you can close this.')
        panel.get_by_role('button', name='Start 80 on the PC', exact=True).click()
        poll(page, "async () => (await (" + RUN + ")()).pc?.job === 41")
        job = 41
        page.evaluate(f"""() => {{ const pc = window.__pc
          pc.send('job', {{ current: pc.job, last: null }})
          for (const id of [1, 2, 3]) {{ pc.send('job_item', {{ job: {job}, id, state: 'working' }}); pc.send('job_item', {{ job: {job}, id, state: 'done' }}) }}
          pc.send('job_item', {{ job: {job}, id: 4, state: 'skipped', step: 'Nothing to describe yet: open it online once or add a note.' }})
          pc.send('job_item', {{ job: {job}, id: 5, state: 'error', error: 'OpenAI did not answer in time (on the PC).' }})
          pc.send('job_item', {{ job: {job}, id: 6, state: 'working' }}) }}""")
        expect(panel.locator('.m-runbar')).to_contain_text('6 of 80')
        expect(panel.locator('.m-runbar')).to_contain_text('on your PC · 80 AI calls')
        expect(panel.locator('.m-tl-li').first).to_contain_text('PC title')
        expect(panel.get_by_role('progressbar')).to_have_attribute('aria-valuemax', '80')
        shoot(page, f'c9-pc-running-{width}')
        # a refused Stop leaves Stop usable and says why; the next one names the job
        page.wait_for_timeout(700)                                    # (a tap within 0.6 s of a start is taken for a double tap)
        page.evaluate("() => { window.__pc.stopError = 'The PC is not reachable.' }")
        panel.get_by_role('button', name='Stop', exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('The PC is not reachable.')
        expect(panel.get_by_role('button', name='Stop', exact=True)).to_be_enabled()
        page.evaluate("() => { window.__pc.stopError = '' }")
        panel.get_by_role('button', name='Stop', exact=True).click()
        assert [s['body'] for s in pc_state(page)['stops']] == [{'id': 41}, {'id': 41}]
        page.evaluate(f"""() => {{ const pc = window.__pc
          pc.items = pc.items.map(i => ({{ ...i, state: i.id <= 3 ? 'done' : i.id === 4 ? 'skipped' : i.id === 5 ? 'error' : 'queued', error: i.id === 5 ? 'OpenAI did not answer in time (on the PC).' : undefined, step: i.id === 4 ? 'Nothing to describe yet: open it online once or add a note.' : undefined }}))
          pc.job = {{ ...pc.job, state: 'stopped', done: 3, skipped: 1, err: 1 }}; pc.current = null; pc.last = pc.job
          pc.send('job', {{ current: null, last: pc.job }}) }}""")
        expect(panel.locator('.m-runbar')).to_contain_text('Stopped · 3 described · 1 skipped · 1 failed')
        expect(panel.get_by_role('button', name='Retry 1 failed', exact=True)).to_be_visible()
        expect(panel).to_contain_text('OpenAI did not answer in time (on the PC).')
        expect(panel.locator('.m-tl-group').nth(2)).to_have_text('Not started · 75')
        shoot(page, f'pc-stopped-{width}')
        # Retry: one item, one tap (not more than 20 calls); the same ledger goes on
        panel.get_by_role('button', name='Retry 1 failed', exact=True).click()
        poll(page, "() => window.__pc.posts.filter(p => p.url === '/api/jobs').length === 2")
        assert pc_state(page)['posts'][1]['body'] == {'kind': 'describe', 'ids': [5], 'force': False, 'opts': {}}
        expect(panel.locator('.m-tl-led').first).to_be_visible()
        page.evaluate("""() => { const pc = window.__pc
          pc.items = pc.items.map(i => (i.id === 5 ? { ...i, state: 'done', error: undefined } : i)); pc.job = { ...pc.job, state: 'finished', done: 1, err: 0 }; pc.current = null; pc.last = pc.job
          pc.send('job', { current: null, last: pc.job }) }""")
        poll(page, "async () => (await (" + RUN + ")()).pc?.ended")
        expect(panel.locator('.m-runbar')).to_contain_text('4 described · 1 skipped')                # the earlier results stay in the ledger
        panel.get_by_role('button', name='Done', exact=True).click()
        # a job started elsewhere: "The PC is busy", the rows wait
        page.evaluate("""() => { const pc = window.__pc
          pc.send('job', { current: pc.J(90, 'thumb', 'running', { label: 'Fetch link info', total: 80, done: 30 }), last: null }) }""")
        expect(panel.get_by_role('status').first).to_contain_text('The PC is busy: Fetch link info, 30 of 80. One job at a time; Describe can start when it ends.')
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_disabled()
        shoot(page, f'c10-pc-busy-{width}')
        page.evaluate("() => window.__pc.send('job', { current: null, last: { id: 90, kind: 'thumb', state: 'finished', done: 80, skipped: 0, err: 0 } })")
        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_enabled()
        esc(page)


# ── keyboard focus, reduced motion, 130 % text ───────────────────────────────────────────────────────────────────────
def motion_and_text(browser, base):
    with Scenario(browser, base, reduced=True) as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        panel.get_by_role('button', name='Describe the first 25', exact=True).click()
        advance(page, 1)
        poll(page, '() => window.__items.gate.length > 0')
        names = page.evaluate("""() => ({ spin: getComputedStyle(document.querySelector('.m-tl-spin')).animationName,
          stripe: getComputedStyle(document.querySelector('.m-meter-run')).animationName })""")
        assert names == {'spin': 'none', 'stripe': 'none'}, names
        esc(page)
    with Scenario(browser, base, 320, 568, 'dark') as page:
        seed_items(page)
        page.evaluate(SLOW_DESCRIBE)
        page.evaluate('window.__items.hold = false; window.__items.fixed = true; window.__items.failIds = new Set([2, 4])')
        phone_rows(page, 30)
        page.locator('.m-lib-tools').click()
        panel = panel_of(page)
        panel.get_by_role('button', name='Describe', exact=True).click()
        panel.get_by_role('button', name='Describe the first 25', exact=True).click() if panel.get_by_role('button', name='Describe the first 25', exact=True).count() else None
        poll(page, "async () => (await (" + RUN + ")()).phone?.ended")
        # 130 % text stands in as a zoom of the panel's content (desktop Edge ignores text-size-adjust)
        page.add_style_tag(content='dialog.m-process-pop .m-tl{zoom:1.3}')
        page.wait_for_timeout(150)
        box = panel.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 320.5, box
        assert page.evaluate("() => { const d = document.querySelector('dialog.m-process-pop'); return d.scrollWidth <= d.clientWidth + 1 }")
        bar = panel.locator('.m-runbar')
        bar.scroll_into_view_if_needed()
        for locator in (panel.get_by_role('button', name='Retry 2 failed', exact=True), panel.get_by_role('button', name='Done', exact=True)):
            b = locator.bounding_box()
            pb = panel.bounding_box()
            assert b and b['x'] >= pb['x'] - 1 and b['x'] + b['width'] <= pb['x'] + pb['width'] + 1, (locator, b, pb)
        page.screenshot(path=str(ART / 'large-text-320-dark.png'))
        esc(page)


def main():
    ART.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    run = lambda name: not only or name in only  # noqa: E731
    with mobile_browser() as (browser, base):
        for width, height in ((360, 780), (320, 568)):
            if run('phone'):
                with Scenario(browser, base, width, height) as page:
                    phone_runs(page, width, height)
                with Scenario(browser, base, width, height) as page:
                    phone_item(page, width)
                with Scenario(browser, base, width, height) as page:
                    phone_no_key(page, width)
            if run('pc_job'):
                pc_job(browser, base, width, height)
        if run('boundaries'):
            boundaries(browser, base)
        if run('lifecycle'):
            lifecycle(browser, base)
        if run('removed_followup'):
            removed_followup(browser, base)
        if run('pc_flow'):
            pc_flow(browser, base)
        if run('pc_analyze'):
            pc_analyze(browser, base)
        if run('pc_guards'):
            pc_guards(browser, base)
        if run('motion_and_text'):
            motion_and_text(browser, base)
    print(f'PASS: Tools panel option C (steps, confirm rules, ring and status, Stop/Continue/Retry/Next, undo, lifecycle, no key, PC steps and job, focus, motion, text size); no /api request left the page; screenshots in {ART}')


if __name__ == '__main__':
    main()
