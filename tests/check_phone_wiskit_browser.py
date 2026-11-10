"""The phone's Wiskit sheet (projects/phone-wiskit-chat, version C "thumb composer") in the phone page at 360 x 780,
light and dark: C1 (a solo phone without an AI key: the centred "needs a key" screen, the composer greyed, Add a key
opens More > Wiskit), C2 (a key: "Ask your library.", one example, the status line, Quick / Deep), C3 (a conversation
streamed by a fake ask: Enter sends, Enter during IME composition does not, Stop while answering, the Latest key when
scrolled up, the chat's name after the tag), the Chats page, the bottom inset (simulated by a style tag) and the
keyboard rule (html.kb). Vite alone; a synthetic solo pairing; every https and /api request aborted; no Drive, no AI
call, no data folder. Screenshots: local/phone-wiskit/.
Run: py tests/check_phone_wiskit_browser.py
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'local/phone-wiskit'
VIEW = {'width': 360, 'height': 780}
INSET = 44
RAW = bytes([17]) * 32
KEY = base64.urlsafe_b64encode(RAW).decode().rstrip('=')
FP = hashlib.sha256(b'brainamon-mirror-1 id' + RAW).hexdigest()[:12]
PAIR = dict(v=2, k=KEY, f=FP, c='', e='', ai={}, at=0, solo=True)
SETTLED = "async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return phone.tried && !phone.refreshing }"
EXAMPLE = re.search(r"ASK_EXAMPLES = \['([^']+)'", (ROOT / 'web/src/lib/ask-examples.ts').read_text(encoding='utf-8')).group(1)
MODEL = json.loads((ROOT / 'knowledge/prompts/phone_ai.json').read_text(encoding='utf-8'))['ask']['models']['openai'][0]['label']
FAKE_ASK = """async () => {
  const { source } = await import('/src/mobile/state.svelte.ts')
  window.__asks = []
  source.stopAsk = async () => {}
  source.ask = (q, chat, on, signal, mode) => new Promise((ok, bad) => {
    window.__asks.push({ q, mode })
    on({ ev: 'start', run: 'synthetic-run' })
    on({ ev: 'context', line: 'Reading the library…', ids: [] })
    const lines = Array.from({ length: 80 }, (_, i) => `Line ${i + 1} of a long synthetic answer that keeps going so the page has to scroll.`)
    let n = 0
    window.__more = count => { for (let i = 0; i < count && n < lines.length; i++, n++) on({ ev: 'chunk', text: lines[n] + '\\n\\n' }) }
    window.__finish = () => { on({ ev: 'done', text: lines.slice(0, n).join('\\n\\n') || 'Done.', cited: [], notes: [], sources: [], chat: { slug: 'synthetic-chat', name: 'Synthetic chat' } }); ok() }
    signal.addEventListener('abort', () => bad(new DOMException('aborted', 'AbortError')))
  })
}"""
SCROLL = "() => { const b = document.querySelector('.m-sheet-body'); return { top: b.scrollTop, left: b.scrollHeight - b.scrollTop - b.clientHeight } }"


def inset(page):
    page.add_style_tag(content=f'.m-sheet-layer.m-bare{{padding-bottom:{INSET}px}}')


def pad(page):
    return page.locator('.m-sheet-layer.m-bare').evaluate('e => getComputedStyle(e).paddingBottom')


def composer_clear(page):
    """The composer's box ends above the simulated inset (8 px of padding, then the inset)."""
    box = page.locator('.m-jv-comp').bounding_box()
    assert box['y'] + box['height'] <= VIEW['height'] - INSET - 8 + 0.5, box
    assert box['x'] >= 10 - 0.5 and box['x'] + box['width'] <= VIEW['width'] - 10 + 0.5, box


def shoot(page, name):
    for theme in ('light', 'dark'):
        page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
        page.wait_for_timeout(150)
        assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), (name, theme)
        page.screenshot(path=str(ART / f'{name}-{theme}.png'))
    page.evaluate("document.documentElement.dataset.theme = 'light'")


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-wiskit-') as td, open(Path(td) / 'vite.log', 'w') as log:
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

                def phone_page(with_key: bool):
                    ctx = browser.new_context(viewport=VIEW, is_mobile=True, has_touch=True, locale='en-US')
                    ctx.route('https://**/*', lambda r: r.abort())
                    ctx.route('**/api/**', lambda r: r.abort())
                    ctx.route(base + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                    ctx.route(base + '/wiskit/**', lambda r: r.fulfill(path=str(ROOT / 'web/public/wiskit' / urlparse(r.request.url).path.removeprefix('/wiskit/'))))
                    pair = dict(PAIR, ai={'openai': 'synthetic-openai-key'} if with_key else {})
                    ctx.add_init_script("Math.random = () => 0; localStorage.setItem('bp-lang','en'); localStorage.setItem('bp-wifi','off'); localStorage.setItem('bp-motion','off');"
                                        " if (!sessionStorage.getItem('fixture')) { sessionStorage.setItem('fixture','1'); localStorage.setItem('bp-pair', "
                                        + json.dumps(json.dumps(pair)) + ") }")
                    page = ctx.new_page()
                    page.set_default_timeout(15000)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/mobile.html#/jv')
                    page.wait_for_function(SETTLED)
                    page.locator('.m-sheet-layer.m-vt-jv').wait_for(state='visible')
                    inset(page)
                    return ctx, page

                # C1: a solo phone without a key
                ctx, page = phone_page(False)
                assert page.locator('.m-sheet-head').count() == 0
                expect(page.get_by_role('button', name='Close Wiskit', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Chats', exact=True)).to_have_attribute('aria-pressed', 'false')
                expect(page.locator('.m-ws')).to_have_text('Wiskit')
                need = page.locator('.m-jv-need')
                expect(need.locator('h4')).to_have_text('Wiskit needs an AI key')
                expect(need.locator('p')).to_have_text('Add your Anthropic or OpenAI key once. It stays on this phone, and Wiskit answers even with the PC off.')
                expect(need.get_by_role('button', name='Add a key', exact=True)).to_be_visible()
                assert need.get_by_role('button', name='Add a key', exact=True).bounding_box()['height'] >= 44
                expect(page.locator('.m-jv-try')).to_have_count(0)
                field = page.get_by_role('textbox', name='Question', exact=True)
                expect(field).to_be_disabled()
                expect(field).to_have_attribute('placeholder', 'Add a key to ask…')
                expect(page.get_by_role('button', name='Send', exact=True)).to_be_disabled()
                for word in ('Quick', 'Deep'):
                    expect(page.get_by_role('group', name='Mode').get_by_role('button', name=word, exact=True)).to_be_disabled()
                assert page.locator('.m-jv-stat').count() == 0 and page.locator('.m-jv-row .m-jv-cat').count() == 0
                assert pad(page) == f'{INSET}px', pad(page)
                composer_clear(page)
                shoot(page, 'c1')
                need.get_by_role('button', name='Add a key', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/more')
                expect(page.locator('#m-ai')).to_be_visible()
                # Settings' round Back returns to Wiskit after Add a key (once); an ordinary visit to Settings, or one
                # after leaving it, still goes to the Library (plan 02 Task 6; the round Back: projects/phone-settings)
                back = page.locator('.m-page-keys').get_by_role('button', name='Back', exact=True)
                back.click()
                expect(page).to_have_url(base + '/mobile.html#/jv')
                page.locator('.m-sheet-layer.m-vt-jv').wait_for(state='visible')
                need.get_by_role('button', name='Add a key', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/more')
                page.evaluate("location.hash = '#/lib'")
                expect(page).to_have_url(base + '/mobile.html#/lib')
                page.evaluate("location.hash = '#/more'")
                expect(page).to_have_url(base + '/mobile.html#/more')
                back.click()
                expect(page).to_have_url(base + '/mobile.html#/lib')
                ctx.close()

                # C2: a key, an empty chat
                ctx, page = phone_page(True)
                hello = page.locator('.m-jv-hello')
                expect(hello.locator('b')).to_have_text('Ask your library.')
                expect(hello.locator('small')).to_have_text('Answers cite the cards they come from.')
                expect(page.locator('.m-jv-try span')).to_have_text(EXAMPLE)
                expect(page.locator('.m-jv-try i')).to_have_text('Try')
                expect(page.locator('.m-jv-need')).to_have_count(0)
                expect(page.locator('.m-jv-stat')).to_have_text(f'{MODEL} · this phone')
                assert page.locator('.m-jv-row .m-jv-cat canvas').count() == 1
                expect(page.get_by_role('button', name='More info: About Wiskit', exact=True)).to_be_visible()
                field = page.get_by_role('textbox', name='Question', exact=True)
                expect(field).to_be_enabled()
                expect(field).to_have_attribute('placeholder', 'Ask your library…')
                send = page.get_by_role('button', name='Send', exact=True)
                expect(send).to_be_disabled()
                assert send.bounding_box()['height'] >= 44
                mode = page.get_by_role('group', name='Mode')
                mode.get_by_role('button', name='Deep', exact=True).click()
                expect(field).to_have_attribute('placeholder', 'Ask Wiskit to research…')
                expect(mode.get_by_role('button', name='Deep', exact=True)).to_have_attribute('aria-pressed', 'true')
                assert page.evaluate("localStorage.getItem('bp-deep')") == '1'
                mode.get_by_role('button', name='Quick', exact=True).click()
                expect(field).to_have_attribute('placeholder', 'Ask your library…')
                composer_clear(page)
                shoot(page, 'c2')
                # the keyboard: the page loses more than a fifth of its height; html.kb drops the inset padding
                page.set_viewport_size({'width': 360, 'height': 400})
                expect(page.locator('html')).to_have_class(re.compile(r'\bkb\b'))      # not wait_for_function: the page's CSP blocks its polling
                assert pad(page) == '0px', pad(page)
                page.set_viewport_size(VIEW)
                expect(page.locator('html')).not_to_have_class(re.compile(r'\bkb\b'))
                assert pad(page) == f'{INSET}px', pad(page)
                # the field grows to four lines, then scrolls inside
                field.fill('one\ntwo\nthree\nfour\nfive\nsix')
                h = field.bounding_box()['height']
                assert 100 <= h <= 105, h
                expect(send).to_be_enabled()
                field.fill('')
                expect(send).to_be_disabled()

                # C3: a conversation through the fake ask
                page.evaluate(FAKE_ASK)
                field.fill('What recipes have I saved?')
                field.press('Enter')
                expect(page.locator('.m-q')).to_have_text('What recipes have I saved?')
                stop = page.get_by_role('button', name='Stop', exact=True)
                expect(stop).to_be_visible()
                expect(send).to_have_count(0)
                expect(field).to_be_enabled()
                expect(field).to_have_value('')
                assert page.evaluate('window.__asks') == [{'q': 'What recipes have I saved?', 'mode': 'quick'}]
                assert page.evaluate("""async () => {
                  const { switchLanguage } = await import('/src/mobile/language-switch.ts')
                  return (await switchLanguage('fr', 'en', async () => {}, { setItem() { throw Error('must not write') } }, () => {})).status
                }""") == 'blocked'
                expect(page.locator('.m-jv-hello')).to_have_count(0)
                page.evaluate('__more(80)')
                page.wait_for_timeout(200)
                assert page.evaluate(SCROLL)['left'] < 2, page.evaluate(SCROLL)        # followed to the end
                expect(page.locator('.m-jv-latest')).to_have_count(0)
                page.locator('.m-sheet-body').evaluate('e => e.scrollTo({ top: 0 })')
                latest = page.get_by_role('button', name='Latest', exact=True)
                expect(latest).to_be_visible()
                comp = page.locator('.m-jv-comp').bounding_box()
                assert latest.bounding_box()['y'] + latest.bounding_box()['height'] <= comp['y'] + 0.5, (latest.bounding_box(), comp)
                page.evaluate('__finish()')
                expect(send).to_be_visible()
                page.wait_for_function("""async () => {
                  const { switchLanguage } = await import('/src/mobile/language-switch.ts')
                  return (await switchLanguage('fr', 'en', async () => {}, { setItem() {} }, () => {})).status === 'reloaded'
                }""")
                expect(stop).to_have_count(0)
                assert page.evaluate(SCROLL)['top'] < 2, page.evaluate(SCROLL)         # stayed put while the answer ended
                latest.click()
                page.wait_for_timeout(200)
                assert page.evaluate(SCROLL)['left'] < 2, page.evaluate(SCROLL)
                expect(latest).to_have_count(0)
                expect(page.locator('.m-sheet-name')).to_have_text('Synthetic chat')
                expect(page.locator('.m-a').first).to_contain_text('Line 80 of a long synthetic answer')
                keys = page.locator('.m-sheet-keys').bounding_box()
                body = page.locator('.m-sheet-body').bounding_box()
                assert body['y'] >= keys['y'] + keys['height'] + 8 - .5, (body, keys)
                expect(page.get_by_role('button', name='Save as note', exact=True)).to_be_visible()
                composer_clear(page)
                shoot(page, 'c3')
                # Enter during IME composition keeps the text; a plain Enter sends; Stop ends the answer
                field.fill('Second question')
                field.evaluate("e => e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }))")
                page.wait_for_timeout(100)
                expect(field).to_have_value('Second question')
                assert len(page.evaluate('window.__asks')) == 1
                field.evaluate("e => e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true, cancelable: true }))")
                page.wait_for_timeout(100)
                assert len(page.evaluate('window.__asks')) == 1
                field.press('Enter')
                expect(stop).to_be_visible()
                assert len(page.evaluate('window.__asks')) == 2
                field.fill('typed while answering')
                field.press('Enter')
                expect(field).to_have_value('typed while answering')                   # refused, kept
                assert len(page.evaluate('window.__asks')) == 2
                stop.click()
                expect(send).to_be_visible()
                expect(page.locator('.m-a').last).to_contain_text('Stopped.')
                # the Chats page
                page.get_by_role('button', name='Chats', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/jv/chats')
                expect(page.get_by_role('button', name='Chats', exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.m-chats button').first).to_have_text('+ New chat')
                expect(page.locator('.m-jv-comp')).to_have_count(0)
                expect(page.locator('.m-sheet-name')).to_have_count(0)
                page.get_by_role('button', name='Back', exact=True).click()
                expect(page).to_have_url(base + '/mobile.html#/jv')
                expect(page.locator('.m-jv-comp')).to_be_visible()
                ctx.close()
                browser.close()
            assert not errors, errors
            print(f'PASS: C1 no key (Add a key opens More > Wiskit, More Back returns once, ordinary More keeps the Library), C2 one example and status, keyboard rule, four-line field, '
                  f'C3 Enter / IME / Stop / Latest / chat name, Chats page, composer above the {INSET} px inset; screenshots in {ART}')
        finally:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == '__main__':
    main()
