"""The phone, automated desktop and console scrapers read the same synthetic Facebook captions."""
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from scrapers.fb_saved_playwright import EXTRACT_VISIBLE_JS

ROOT = Path(__file__).resolve().parents[1]


class FacebookCaptionsBrowserTest(unittest.TestCase):
    def test_story_controls_are_not_captions_in_any_reader(self):
        phone = (ROOT / 'scrapers/sites/facebook.js').read_text(encoding='utf-8')
        manual = (ROOT / 'scrapers/facebook_scraper.js').read_text(encoding='utf-8').removesuffix('run();\n')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                for kind in ('Reel', 'Video'):
                    caption = 'Chickpea cookies with chocolate chips'
                    for content, expected in ((f'<p>{caption}</p>', caption),
                                              (f'<img alt="{caption}">', caption), ('', '')):
                        with self.subTest(kind=kind, content=content):
                            page.set_content(f'''<article>
                              <div>Sam Example, view story</div>
                              <a style="display:block" href="https://www.facebook.com/reel/1234567890/">{kind} · Sam Example</a>
                              {content}<button>Add to collection</button>
                              <button aria-label="More options">More</button>
                            </article>''')
                            desktop = page.evaluate(EXTRACT_VISIBLE_JS, {'seenIds': [], 'captureThumbs': False})
                            mobile = page.evaluate('() => {' + phone + '; return SITE.read(document); }')
                            console = page.evaluate('() => {' + manual + ''';
                              return extractDescription(document.querySelector('a'), document.querySelector('article'), 'Sam Example');
                            }''')
                            self.assertEqual(len(desktop), 1)
                            self.assertEqual(len(mobile), 1)
                            self.assertEqual(desktop[0]['creator'], 'Sam Example')
                            self.assertEqual(mobile[0]['creator'], 'Sam Example')
                            self.assertEqual([desktop[0]['description'], mobile[0]['caption'], console], [expected] * 3)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
