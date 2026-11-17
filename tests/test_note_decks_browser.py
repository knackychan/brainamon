"""Workspace search/actions and flexible note rails, using only a synthetic library."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import uvicorn
from playwright.sync_api import expect, sync_playwright

from core import ai_defaults
from core.db import Database
from knowledge import my_notes
from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class NoteDecksBrowserTest(unittest.TestCase):
    def test_search_actions_and_rail_heights(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            db = Database(root / 'data/content_manager.db')
            db.set_setting('setup_dismissed', '1')
            db.set_setting('onboarding_hidden', '1')
            db.add_item({'url': 'https://example.invalid/river', 'description': 'River source for a journal'})
            db.add_item({'url': 'https://example.invalid/other', 'description': 'Unrelated source'})
            for i in range(45):
                my_notes.create_note(db.notes_dir, f'Journal {i:02}', 'General')
            note = my_notes.create_note(db.notes_dir, 'Field journal', 'Work')
            my_notes.save_note(note, 'Field journal', 'Work', 'x' * 500 + '\n\nRiver compass.')
            db.reindex_notes()
            db.close()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            app = create_app(data_dir=root / 'data', cloud_dir=root / 'cloud', port=port, web_dist=ROOT / 'web/dist')
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', timeout_graceful_shutdown=1))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(server.started)
                with mock.patch.object(ai_defaults, 'embed_credentials', return_value=('', '')):
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(channel='msedge', headless=True)
                        page = browser.new_page(viewport={'width': 1920, 'height': 1400})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{port}/#cm-auth=' + app.state.api_token)
                        page.locator('#tab-notes').click()
                        notes = page.locator('#ws-notes .workspace-deck')
                        expect(page.locator('#mods-notes .trow')).to_have_count(46)
                        expect(notes.get_by_role('button', name='Summarize note', exact=True)).to_be_disabled()
                        page.keyboard.press('/')
                        expect(page.locator('#notes-q')).to_be_focused()
                        page.locator('#notes-q').fill('RIVER COMPASS')
                        expect(page.locator('#mods-notes .trow')).to_have_count(1)
                        page.locator('#mods-notes .trow').click()
                        expect(notes.get_by_role('button', name='Summarize note', exact=True)).to_be_enabled()
                        expect(notes.get_by_role('button', name='Reformat note', exact=True)).to_be_enabled()
                        page.context.route('**/api/my-notes/*/summarize', lambda route: route.fulfill(json={}))
                        with page.expect_request('**/api/my-notes/*/summarize'):
                            notes.get_by_role('button', name='Summarize note', exact=True).click()
                        page.context.route('**/api/my-notes/*/reformat', lambda route: route.fulfill(json={}))
                        with page.expect_request('**/api/my-notes/*/reformat'):
                            notes.get_by_role('button', name='Reformat note', exact=True).click()
                        with page.expect_file_chooser():
                            notes.get_by_role('button', name='Digest screenshot', exact=True).click()
                        notes.get_by_role('button', name='Clear notes search').click()
                        expect(page.locator('#mods-notes .trow')).to_have_count(46)
                        notes.get_by_role('button', name='New note', exact=True).click()
                        expect(page.get_by_role('dialog', name='New note')).to_be_visible()
                        page.keyboard.press('Escape')
                        page.locator('#tab-know').click()
                        knowledge = page.locator('#ws-know .workspace-deck')
                        expect(knowledge.get_by_role('button', name='Synthesize sources')).to_be_disabled()
                        expect(knowledge.get_by_role('button', name='Augment note', exact=True)).to_be_disabled()
                        page.keyboard.press('/')
                        expect(page.locator('#knowledge-q')).to_be_focused()
                        page.locator('#knowledge-q').fill('River')
                        page.locator('#knowledge-q').press('Enter')
                        expect(page.locator('#ws-know .srow')).to_have_count(1)
                        expect(page.locator('#kq')).to_have_value('River')
                        expect(page.locator('#mods-know .knowledge-list .bdg.nw')).to_have_count(1)
                        expect(knowledge.get_by_role('button', name='Synthesize sources')).to_be_enabled()
                        page.locator('#mods-know .knowledge-list .trow').filter(has_text='Field journal').click()
                        expect(knowledge.get_by_role('button', name='Augment note', exact=True)).to_be_enabled()
                        page.context.route('**/api/jobs/preview', lambda route: route.fulfill(json={'count': 1}))
                        page.context.route('**/api/jobs', lambda route: route.fulfill(json={}) if route.request.method == 'POST' else route.continue_())
                        for name, mode in [('Synthesize sources', None), ('Augment note', 'augment')]:
                            with page.expect_request(lambda r: r.url.endswith('/api/jobs') and r.method == 'POST') as sent:
                                knowledge.get_by_role('button', name=name, exact=True).click()
                            payload = sent.value.post_data_json
                            self.assertEqual(payload['kind'], 'note')
                            self.assertEqual(payload['opts'].get('mode'), mode)
                            if page.locator('#cw-scrim').count():
                                page.keyboard.press('Escape')
                        page.context.route('**/api/connections/scan', lambda route: route.fulfill(json={}))
                        with page.expect_request('**/api/connections/scan'):
                            knowledge.get_by_role('button', name='Find connections', exact=True).click()
                        knowledge.get_by_role('button', name='Clear knowledge search').click()
                        expect(page.locator('#ws-know .srow')).to_have_count(0)
                        expect(knowledge.get_by_role('button', name='Synthesize sources')).to_be_disabled()
                        # A cleared search must not be repopulated by its outstanding request.
                        pending = []
                        page.context.route('**/api/knowledge/sources', lambda route: pending.append(route))
                        page.locator('#knowledge-q').fill('Delayed')
                        page.locator('#knowledge-q').press('Enter')
                        page.wait_for_timeout(100)
                        self.assertTrue(pending)
                        knowledge.get_by_role('button', name='Clear knowledge search').click()
                        pending[0].fulfill(json={'items': [], 'notes': [{'file': note.name}], 'mode': 'keyword'})
                        page.wait_for_timeout(100)
                        expect(page.locator('#knowledge-q')).to_have_value('')
                        expect(page.locator('#mods-know .knowledge-list .bdg.nw')).to_have_count(0)
                        for workspace in ('know', 'notes'):
                            page.locator('#tab-' + workspace).click()
                            for width, height in ((1920, 1400), (1440, 900), (1000, 800)):
                                page.set_viewport_size({'width': width, 'height': height})
                                page.wait_for_timeout(100)
                                deck = page.locator(f'#ws-{workspace} .workspace-deck')
                                expect(deck).to_be_visible()
                                self.assertTrue(deck.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'))
                                self.assertGreater(deck.locator('input').bounding_box()['width'], 90)
                                if width == 1920:
                                    selector = '#mods-know .knowledge-list .tlist' if workspace == 'know' else '#mods-notes .tlist'
                                    self.assertGreater(page.locator(selector).bounding_box()['height'], 350)
                                    output = ROOT / 'build/notes-knowledge-decks'
                                    output.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(output / f'{workspace}.png'))
                                if width == 1440:
                                    page.evaluate("document.documentElement.dataset.theme = 'dark'")
                                    page.screenshot(path=str(ROOT / 'build/notes-knowledge-decks' / f'{workspace}-dark.png'))
                        self.assertEqual(errors, [])
                        browser.close()
            finally:
                server.should_exit = True
                thread.join(10)
