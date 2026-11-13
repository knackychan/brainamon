"""Automatic removal against synthetic site DOM only; no account requests."""
import sys
import unittest
from pathlib import Path
from unittest import mock

from playwright.sync_api import sync_playwright

with mock.patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'scrapers'), *sys.path]):
    import fb_saved_playwright as fb
    import ig_saved_playwright as ig


class DesktopUnsaveBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def page(self, html):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content(html)
        page.evaluate('''() => {
          const timer = window.setTimeout;
          window.setTimeout = (fn, ms) => timer(fn, Math.min(ms, 5));
          window.clicked = [];
        }''')
        return page

    def test_facebook_nested_card_native_button_and_new_menu_label(self):
        for label in ('Unsave', 'Remove from saved'):
            for removed in (True, False):
                with self.subTest(label=label, removed=removed):
                    page = self.page('''<main>
                      <article id="target"><div><a href="https://www.facebook.com/reel/123456/">Post</a>
                        <a href="https://www.facebook.com/reel/123456/">Same post</a><span>Add to collection</span></div>
                        <button aria-label="More options">More</button></article>
                      <article><a href="https://www.facebook.com/reel/999999/">Other post</a>
                        <span>Add to collection</span><button aria-label="More options">More</button></article>
                      <div role="menu" hidden><button role="menuitem" onclick="clicked.push('hidden')">Unsave</button></div>
                    </main>''')
                    page.evaluate('''({label, removed}) => {
                      const row = document.querySelector('#target');
                      row.querySelector('button').onclick = () => {
                        const menu = document.createElement('div'); menu.role = 'menu';
                        const item = document.createElement('button'); item.role = 'menuitem'; item.textContent = label;
                        item.onclick = () => { clicked.push('123456'); if (removed) row.remove(); menu.remove(); };
                        menu.append(item); document.body.append(menu);
                      };
                    }''', {'label': label, 'removed': removed})
                    self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456']), {'123456': removed})
                    self.assertEqual(page.evaluate('clicked'), ['123456'])
                    self.assertEqual(page.locator('a[href*="999999"]').count(), 1)

    def test_instagram_ignores_hidden_bookmarks_and_reads_button_labels(self):
        for markup in ('<svg aria-label="Remove" width="20" height="20"></svg>', 'Remove'):
            for removed in (True, False):
                with self.subTest(markup=markup, removed=removed):
                    page = self.page(f'''<main>
                      <button hidden onclick="clicked.push('hidden')"><svg aria-label="Remove"></svg></button>
                      <article><button id="bookmark" aria-label="Remove">{markup}</button></article>
                    </main>''')
                    page.evaluate('''removed => {
                      document.querySelector('#bookmark').onclick = e => {
                        clicked.push('bookmark');
                        if (removed) {
                          e.currentTarget.setAttribute('aria-label', 'Save');
                          e.currentTarget.querySelector('svg')?.setAttribute('aria-label', 'Save');
                        }
                      };
                    }''', removed)
                    self.assertEqual(page.evaluate(ig.UNSAVE_JS), 'ok' if removed else 'nochange')
                    self.assertEqual(page.evaluate('clicked'), ['bookmark'])

    def test_instagram_waits_for_post_and_does_not_resave_an_unsaved_post(self):
        page = self.page('<main></main>')
        page.evaluate('''() => setTimeout(() => {
          document.querySelector('main').innerHTML = '<article><button aria-label="Save" onclick="clicked.push(1)">Save</button></article>';
        }, 1)''')
        self.assertEqual(page.evaluate(ig.UNSAVE_JS), 'already')
        self.assertEqual(page.evaluate('clicked'), [])

    def test_instagram_leaves_suggested_posts_saved(self):
        page = self.page('''<div role="main">
          <article><button aria-label="Save" onclick="clicked.push('post')">Save</button></article>
          <article><button aria-label="Remove" onclick="clicked.push('suggestion')">Remove</button></article>
        </div>''')
        self.assertEqual(page.evaluate(ig.UNSAVE_JS), 'already')
        self.assertEqual(page.evaluate('clicked'), [])

    def test_instagram_svg_bookmark_in_dialog(self):
        page = self.page('''<div role="dialog"><svg width="24" height="24" aria-label="Remove"
          onclick="clicked.push('bookmark'); this.setAttribute('aria-label', 'Save')"></svg></div>''')
        self.assertEqual(page.evaluate(ig.UNSAVE_JS), 'ok')
        self.assertEqual(page.evaluate('clicked'), ['bookmark'])

    def test_facebook_menu_items_without_menu_wrapper(self):
        page = self.page('''<main><article id="target">
          <a href="https://www.facebook.com/reel/123456/">Post</a><span>Add to collection</span>
          <button aria-label="More options">More</button></article></main>
          <button role="menuitem" onclick="clicked.push('unrelated')">Unsave</button>''')
        page.evaluate('''() => {
          document.querySelector('article button').onclick = () => {
            const item = document.createElement('button'); item.role = 'menuitem'; item.textContent = 'Unsave';
            item.onclick = () => { clicked.push('target'); document.querySelector('#target').remove(); item.remove(); };
            document.body.append(item);
          };
        }''')
        self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456']), {'123456': True})
        self.assertEqual(page.evaluate('clicked'), ['target'])

    def test_facebook_more_dialog_button_with_post_label(self):
        page = self.page('''<article id="target"><a href="https://www.facebook.com/reel/123456/">Post</a>
          <span>Add to collection</span><div role="button" aria-label="More, unrelated">Other</div>
          <div role="button" aria-haspopup="dialog" aria-label="More, sample saved post">More</div></article>''')
        page.evaluate('''() => {
          document.querySelector('[aria-haspopup="dialog"]').onclick = () => {
            const item = document.createElement('div'); item.role = 'menuitem'; item.textContent = 'Unsave';
            item.onclick = () => { clicked.push('target'); document.querySelector('#target').remove(); item.remove(); };
            document.body.append(item);
          };
        }''')
        self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456']), {'123456': True})
        self.assertEqual(page.evaluate('clicked'), ['target'])

    def test_facebook_finds_each_row_again_after_list_redraw(self):
        page = self.page('<main></main>')
        page.evaluate('''() => {
          let ids = ['123456', '999999'];
          function render() {
            document.querySelector('main').innerHTML = ids.map(id => `<article>
              <a href="https://www.facebook.com/reel/${id}/">Post</a><span>Add to collection</span>
              <button aria-label="More options" data-id="${id}">More</button></article>`).join('');
            document.querySelectorAll('article button').forEach(button => button.onclick = () => {
              const item = document.createElement('button'); item.role = 'menuitem'; item.textContent = 'Unsave';
              item.onclick = () => { clicked.push(button.dataset.id); ids = ids.filter(id => id !== button.dataset.id); item.remove(); render(); };
              document.body.append(item);
            });
          }
          render();
        }''')
        self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456', '999999']),
                         {'123456': True, '999999': True})
        self.assertEqual(page.evaluate('clicked'), ['123456', '999999'])

    def test_facebook_redraw_of_still_saved_row_is_not_removal(self):
        page = self.page('''<main><article>
          <a href="https://www.facebook.com/reel/123456/">Post</a><span>Add to collection</span>
          <button aria-label="More options">More</button></article></main>''')
        page.evaluate('''() => {
          document.querySelector('article button').onclick = () => {
            const item = document.createElement('button'); item.role = 'menuitem'; item.textContent = 'Unsave';
            item.onclick = () => { const row = document.querySelector('article'); row.replaceWith(row.cloneNode(true)); item.remove(); };
            document.body.append(item);
          };
        }''')
        self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456']), {'123456': False})

    def test_facebook_does_not_remove_a_recycled_row(self):
        page = self.page('''<article><a href="https://www.facebook.com/reel/123456/">Post</a>
          <span>Add to collection</span><button aria-label="More options">More</button></article>''')
        page.evaluate('''() => {
          document.querySelector('article button').onclick = () => {
            document.querySelector('article a').href = 'https://www.facebook.com/reel/999999/';
            const item = document.createElement('button'); item.role = 'menuitem'; item.textContent = 'Unsave';
            item.onclick = () => clicked.push('wrong post'); document.body.append(item);
          };
        }''')
        self.assertEqual(page.evaluate(fb.UNSAVE_VISIBLE_JS, ['123456']), {'123456': False})
        self.assertEqual(page.evaluate('clicked'), [])

    def test_instagram_open_dialog_takes_priority_over_background_main(self):
        page = self.page('''<main><article>
          <button aria-label="Remove" onclick="clicked.push('background')">Remove</button>
        </article></main><div role="dialog"><article>
          <svg width="24" height="24" aria-label="Remove"
            onclick="clicked.push('target'); this.setAttribute('aria-label', 'Save')"></svg>
        </article></div>''')
        self.assertEqual(page.evaluate(ig.UNSAVE_JS), 'ok')
        self.assertEqual(page.evaluate('clicked'), ['target'])


if __name__ == '__main__':
    unittest.main()
