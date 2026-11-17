"""D4 Wiskit Deep research through the real authenticated ask stream; the model is a scripted stand-in."""
import os
import re
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import uvicorn
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from core import ai_client
from core import ai_defaults
from core.db import Database
from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
HEADS = re.compile(r'^\[id (\d+)\]', re.M)


class MotionWiskitBrowser(unittest.TestCase):
    def test_deep_research_steps_rows_and_citations(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            a = db.add_item({'url': 'https://example.invalid/a', 'description': 'Glass shader with transmission'})
            b = db.add_item({'url': 'https://example.invalid/b', 'description': 'Glass caustics in Cycles'})
            c = db.add_item({'url': 'https://example.invalid/c', 'description': 'Glass bottle modelling'})
            (db.items_dir / str(a)).mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (63, 88), (40, 120, 200)).save(db.items_dir / str(a) / 'thumb.jpg')
            db.update_item(a, {'thumb_path': 'thumb.jpg'})
            db.set_setting('onboarding_hidden', '1')
            db.close()
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port,
                             web_dist=ROOT / 'web/dist')
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                                   timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            gates = {k: threading.Event() for k in ('read', 'text', 'end')}
            seen = {}

            def agent(messages, provider, model, *, run_tool, on_tool, on_text, should_stop, **kw):
                if seen.get('script') == 'stop':
                    on_tool('read_items', {'ids': [a, b]})
                    deadline = time.monotonic() + 20
                    while not should_stop() and time.monotonic() < deadline:
                        time.sleep(.02)
                    raise RuntimeError('Stopped.')
                on_tool('search_library', {'query': 'glass'})
                seen['search'] = run_tool('search_library', {'query': 'glass'})
                on_tool('read_items', {'ids': [a, b, c, 999999]})
                gates['read'].wait(20)
                run_tool('read_items', {'ids': [a, b, c, 999999]})
                gates['text'].wait(20)
                on_text(f'Glass needs [id {a}] and ')
                gates['end'].wait(20)
                on_text(f'[id {b}].')
                return f'Glass needs [id {a}] and [id {b}].'

            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}), \
                        mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None)), \
                        mock.patch.object(ai_client, 'ask_agent', agent), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True)
                    try:
                        for answered, motion in enumerate(('normal', 'off', 'reduced', 'rest')):
                            with self.subTest(motion=motion):
                                for gate in gates.values():
                                    gate.clear()
                                seen.clear()
                                context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                                              reduced_motion='reduce' if motion == 'reduced' else 'no-preference')
                                page = context.new_page()
                                errors = []
                                page.on('pageerror', lambda error: errors.append(str(error)))
                                try:
                                    with page.expect_response(lambda r: r.url.endswith('/api/events') and r.status == 200):
                                        try:
                                            page.goto(f'http://127.0.0.1:{port}/#cm-auth=' + app.state.api_token)
                                        except Exception:
                                            raise AssertionError('Test bootstrap failed; credential URL omitted') from None
                                    expect(page.locator('.cell[data-id]')).to_have_count(3)
                                    answers = page.locator('.m-j')
                                    expect(answers).to_have_count(answered)
                                    expect(page.locator('.m-j .mo-res')).to_have_count(0)   # saved chats: today's markup
                                    if motion in ('off', 'rest'):
                                        page.evaluate("c => document.documentElement.classList.add(c)",
                                                      'motion-off' if motion == 'off' else 'cm-rest')
                                    deep = page.locator('#jv-tools').get_by_role('button', name='Deep', exact=True)
                                    for _ in range(50):
                                        deep.click()
                                        if deep.get_attribute('aria-pressed') == 'true':
                                            break
                                        page.wait_for_timeout(200)
                                    expect(deep).to_have_attribute('aria-pressed', 'true')
                                    page.locator('#ask').fill('Which glass items did I save?')
                                    page.locator('#ask').press('Enter')
                                    expect(answers).to_have_count(answered + 1)
                                    msg = answers.nth(answered)
                                    steps, rows = msg.locator('.mo-step'), msg.locator('.mo-src')
                                    expect(steps).to_have_count(2)
                                    expect(steps.nth(0)).to_have_attribute('data-st', 'ok')
                                    hits = len(set(HEADS.findall(seen['search'])))
                                    self.assertGreater(hits, 0)
                                    expect(steps.nth(0).locator('b')).to_have_text(str(hits))
                                    expect(steps.nth(0)).to_contain_text('search library')
                                    expect(steps.nth(0).locator('q')).to_have_text('glass')
                                    expect(steps.nth(0)).to_contain_text('hit' if hits == 1 else 'hits')
                                    expect(steps.nth(1)).to_have_attribute('data-st', 'run')
                                    expect(steps.nth(1)).to_contain_text('read sources')
                                    expect(steps.nth(1).locator('b')).to_have_text('0')
                                    expect(steps.nth(1)).to_contain_text('/ 3')
                                    expect(rows).to_have_count(3)
                                    self.assertEqual(rows.evaluate_all('els => els.map(e => +e.dataset.id)'), [a, b, c])
                                    expect(msg.locator('.mo-src.mo-read[data-st="reading"]')).to_have_count(3)
                                    self.assertEqual(rows.nth(1).evaluate("e => e.style.getPropertyValue('--mo-d')"), '90ms')
                                    expect(rows.nth(0).locator('img')).to_have_attribute('src', re.compile(rf'/thumb/{a}\?.*w=64'))
                                    expect(rows.nth(1).locator('img')).to_have_count(0)
                                    expect(rows.nth(0).locator('.mo-sid')).to_have_text(f'[id {a}]')
                                    expect(rows.nth(0).locator('.mo-stl')).to_contain_text('Glass shader')
                                    expect(rows.nth(0).locator('.mo-sbd')).to_have_text('READING')
                                    fill = rows.nth(0).evaluate("e => getComputedStyle(e, '::after').animationName")
                                    self.assertEqual(fill, 'mo-readfill' if motion == 'normal' else 'none')
                                    trace = msg.locator('.trace li').all_text_contents()
                                    self.assertFalse([t for t in trace if 'Searching the library' in t or 'in detail' in t], trace)
                                    expect(msg.locator('.mo-rsum')).to_have_count(0)

                                    gates['read'].set()
                                    expect(steps.nth(1)).to_have_attribute('data-st', 'ok')
                                    expect(msg.locator('.mo-src[data-st="read"]')).to_have_count(3, timeout=4000)
                                    expect(msg.locator('.mo-src.mo-read')).to_have_count(0)
                                    expect(steps.nth(1).locator('b')).to_have_text('3')

                                    gates['text'].set()
                                    cite = msg.locator(f'.ans .cite[data-cid="{a}"]')
                                    expect(cite).to_have_count(1)
                                    expect(cite).to_be_visible()
                                    if motion == 'normal':
                                        expect(cite).to_have_class(re.compile(r'\bmo-pop\b'))
                                        self.assertEqual(cite.evaluate('e => getComputedStyle(e).animationName'), 'mo-pop')
                                    else:
                                        expect(msg.locator('.ans .cite.mo-pop')).to_have_count(0)
                                    expect(msg.locator('.mo-rsum')).to_have_count(0)

                                    gates['end'].set()
                                    expect(msg.locator('.mo-rsum')).to_have_text('✓ 2 cited · 3 read')
                                    for iid, badge in ((a, '✓ READ'), (b, '✓ READ'), (c, 'NOT USED')):
                                        expect(msg.locator(f'.mo-src[data-id="{iid}"] .mo-sbd')).to_have_text(badge)
                                    expect(msg.locator(f'.mo-src[data-id="{c}"]')).to_have_css('opacity', '0.55')
                                    expect(steps.nth(1).locator('b')).to_have_text('3')
                                    expect(msg.locator('.mo-step[data-st="ok"]')).to_have_count(2)
                                    expect(msg.locator('.srcs')).to_be_visible()

                                    if motion == 'normal':
                                        seen['script'] = 'stop'
                                        page.locator('#ask').fill('Stop this one')
                                        page.locator('#ask').press('Enter')
                                        expect(answers).to_have_count(answered + 2)
                                        stop = answers.nth(answered + 1)
                                        expect(stop.locator('.mo-src[data-st="reading"]')).to_have_count(2)
                                        page.locator('#stop').click()
                                        expect(stop.locator('.ans .note')).to_have_text('Stopped.')
                                        expect(stop.locator('.mo-step')).to_have_attribute('data-st', 'err')
                                        expect(stop.locator('.mo-src[data-st="unused"]')).to_have_count(2)
                                        expect(stop.locator('.mo-rsum')).to_have_count(0)
                                    self.assertEqual(errors, [])
                                finally:
                                    context.close()
                    finally:
                        browser.close()
            finally:
                for gate in gates.values():
                    gate.set()
                server.should_exit = True
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
