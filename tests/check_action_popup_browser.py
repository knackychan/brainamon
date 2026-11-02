"""Shared item-action popups against throwaway data: py tests/check_action_popup_browser.py."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)


class Review(shots.Run):
    def first_start(self, browser, theme):
        pass

    def phone(self, browser, theme):
        pass

    def desktop(self, browser, theme):
        ctx = self.context(browser, theme)
        chats = [dict(slug=f'chat-{i}', name=f'Saved chat {i}', updated='2026-10-27') for i in range(16)]
        chats[1]['name'] = 'A long chat title with enough words to wrap across several lines ' * 3
        active = chats[0]['slug']
        calls = []
        fail_delete = False

        def chat_route(route):
            nonlocal active
            path = unquote(urlparse(route.request.url).path)
            method = route.request.method
            if method != 'GET':
                calls.append((method, path, route.request.post_data_json))
            if path == '/api/chats':
                route.fulfill(json=dict(chats=chats, active=active))
            elif path == '/api/chats/active':
                active = route.request.post_data_json['slug']
                route.fulfill(json={'ok': True})
            else:
                slug = path.split('/')[3]
                chat = next(c for c in chats if c['slug'] == slug)
                if method == 'DELETE':
                    if fail_delete:
                        route.fulfill(status=500, json={'detail': 'Delete failed. Try again.'})
                    else:
                        chats.remove(chat)
                        route.fulfill(json={'chats': chats})
                elif path.endswith('/rename'):
                    chat['name'] = route.request.post_data_json['name']
                    route.fulfill(json=chat)
                elif path.endswith('/clear'):
                    route.fulfill(json={'ok': True})
                else:
                    route.fulfill(json=dict(chat, history=[{'role': 'user', 'content': 'Question'},
                                                          {'role': 'assistant', 'content': 'Saved answer'}],
                                            options={}, sources=[]))

        ctx.route('**/api/chats**', chat_route)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.url())
        page.wait_for_selector('.cell[data-id]')
        expect(page.locator('#chat-t')).to_have_text('Saved chat 0')
        page.locator('#chats-k').click()
        listing = page.locator('#chats-pop')
        popup = page.locator('.action-popup')
        rows = listing.locator('.chr-x')

        def bounds():
            box = popup.bounding_box()
            size = page.viewport_size
            assert box['x'] >= 7 and box['y'] >= 7, box
            assert box['x'] + box['width'] <= size['width'] - 7, box
            assert box['y'] + box['height'] <= size['height'] - 7, box
            assert popup.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
            return box

        trigger = rows.nth(2)
        source = trigger.bounding_box()
        trigger.click()
        expect(popup.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
        box = bounds()
        assert abs(box['x'] + box['width'] - source['x'] - source['width']) <= 1, (box, source)
        assert min(abs(box['y'] - source['y'] - source['height']),
                   abs(box['y'] + box['height'] - source['y'])) <= 9, (box, source)
        assert page.locator('#cw-scrim').evaluate('(e) => getComputedStyle(e).backdropFilter') == 'none'
        self.shot(page, f'{theme}-chat-delete-near-row')
        page.keyboard.press('Shift+Tab')
        expect(popup.get_by_role('button', name='Delete chat', exact=True)).to_be_focused()
        page.keyboard.press('Tab')
        expect(popup.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
        page.keyboard.press('Escape')
        expect(popup).to_have_count(0)
        expect(trigger).to_be_focused()
        expect(listing).to_be_visible()
        assert not calls

        trigger.click()
        page.mouse.click(8, 8)
        expect(popup).to_have_count(0)
        expect(listing).to_be_visible()
        assert not calls
        # A successful deletion keeps the list and moves keyboard focus to the next row.
        for _ in range(2):
            rows.nth(2).click()
            popup.get_by_role('button', name='Delete chat', exact=True).click()
            expect(rows).to_have_count(len(chats))
            expect(listing).to_be_visible()
            expect(rows.nth(2)).to_be_focused()
        assert len([c for c in calls if c[0] == 'DELETE']) == 2

        fail_delete = True
        rows.nth(2).click()
        popup.get_by_role('button', name='Delete chat', exact=True).click()
        expect(page.locator('#toasts')).to_contain_text('Delete failed. Try again.')
        expect(rows).to_have_count(len(chats))
        expect(listing).to_be_visible()
        fail_delete = False

        listing.get_by_role('button', name='Rename', exact=True).click()
        field = popup.locator('input')
        expect(field).to_be_focused()
        field.fill('')
        field.press('Enter')
        expect(popup).to_contain_text('Enter a name.')
        bounds()
        field.fill('Renamed chat')
        field.press('Enter')
        expect(popup).to_have_count(0)
        expect(page.locator('#chat-t')).to_have_text('Renamed chat')
        expect(listing).to_be_visible()
        listing.get_by_role('button', name='Clear', exact=True).click()
        popup.get_by_role('button', name='Clear chat', exact=True).click()
        expect(listing.get_by_role('button', name='Clear', exact=True)).to_be_disabled()
        expect(listing).to_be_visible()

        # Long content, narrow screens and resizing keep the popup on screen.
        rows.nth(1).click()
        bounds()
        self.shot(page, f'{theme}-long-chat-title')
        page.set_viewport_size({'width': 390, 'height': 480})
        expect(popup).to_be_visible()
        page.wait_for_timeout(100)
        bounds()
        self.shot(page, f'{theme}-narrow-popup')
        popup.get_by_role('button', name='Cancel', exact=True).click()
        page.set_viewport_size({'width': 1440, 'height': 900})
        # Delete the open chat and then every remaining row, including the empty state.
        while chats:
            if len(chats) == 1:
                listing.get_by_role('button', name='Delete', exact=True).click()
            else:
                rows.first.click()
            popup.get_by_role('button', name='Delete chat', exact=True).click()
            expect(rows).to_have_count(len(chats))
        expect(listing).to_contain_text('No saved chats yet.')
        expect(page.locator('#chat-t')).to_have_text('New chat')
        expect(page.locator('#chats-k')).to_be_focused()
        page.locator('#chats-k').click()
        # A different item type reaches the same component through its context menu.
        card = page.locator('.cell[data-id]').first
        card.click(button='right')
        delete = page.locator('#mnu').get_by_role('menuitem', name='Delete', exact=True)
        source = delete.bounding_box()
        delete.click()
        expect(popup).to_contain_text('leaves the library')
        box = bounds()
        assert min(abs(box['y'] - source['y'] - source['height']),
                   abs(box['y'] + box['height'] - source['y'])) <= 9, (box, source)
        self.shot(page, f'{theme}-library-delete-popup')
        popup.get_by_role('button', name='Cancel', exact=True).click()
        expect(card).to_be_visible()
        assert not errors, errors
        ctx.close()
        print(f'{theme}: placement, keyboard, cancellation, repeated deletes, errors, rename, clear, empty and library actions passed')


if __name__ == '__main__':
    args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                           out=tempfile.mkdtemp(prefix='brainamon-browser-shots-'), only=None,
                           root=None, themes='dark,light')
    Review(args).go()
