"""Synthetic sign-in transitions only: no personal profiles, credentials or live sites."""
import importlib.util
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HAS_PLAYWRIGHT = importlib.util.find_spec('playwright') is not None
if HAS_PLAYWRIGHT:
    with mock.patch.object(sys, 'path', [str(Path(__file__).resolve().parents[1] / 'scrapers'), *sys.path]):
        import fb_saved_playwright as fb
        import ig_saved_playwright as ig


class Page:
    def __init__(self, site, steps, user=''):
        self.site, self.steps, self.user = site, iter(steps), user
        self.url = 'about:blank'
        self.auth = False
        self.form = 0
        self.visits = []
        self.polls = 0
        self.context = SimpleNamespace(cookies=lambda url: [
            {'name': 'c_user' if site == 'facebook' else 'sessionid', 'value': 'synthetic'}
        ] if self.auth else [])

    def goto(self, url, **kwargs):
        self.visits.append(url)
        self.url = url if self.auth else f'https://www.{self.site}.com/login/'

    def locator(self, selector):
        return SimpleNamespace(count=lambda: self.form)

    def evaluate(self, script):
        return self.user

    def wait_for_timeout(self, ms):
        self.polls += 1
        if self.polls > 20:
            raise AssertionError('Login loop did not finish')
        step = next(self.steps, {})
        self.__dict__.update(step)


@unittest.skipUnless(HAS_PLAYWRIGHT, 'optional Playwright not installed')
class LoginTest(unittest.TestCase):
    def test_facebook_waits_through_login_2fa_and_captcha_then_opens_saved_once(self):
        page = Page('facebook', [
            {}, {}, {'auth': True, 'url': 'https://www.facebook.com/checkpoint/'},
            {}, {'url': 'https://www.facebook.com/two_step_verification/'},
            {'url': 'https://www.facebook.com/captcha/'},
            {'url': 'https://www.facebook.com/'},
        ])
        fb.wait_for_saved_page(page, 0)
        self.assertEqual(page.visits, [fb.SAVED_URL, fb.SAVED_URL])
        self.assertGreaterEqual(page.polls, 7)

    def test_facebook_remembered_login_needs_only_initial_navigation(self):
        page = Page('facebook', [])
        page.auth = True
        fb.wait_for_saved_page(page, 0)
        self.assertEqual(page.visits, [fb.SAVED_URL])

    def test_instagram_keeps_discovering_profile_after_delayed_login(self):
        page = Page('instagram', [
            {}, {'url': ig.HOME_URL}, {},
            {'auth': True, 'url': 'https://www.instagram.com/challenge/'}, {},
            {'url': ig.HOME_URL}, {}, {}, {'user': 'synthetic_user'},
        ])
        ig.wait_for_saved_page(page, '', 0)
        self.assertEqual(page.visits, [ig.HOME_URL, ig.saved_url_for('synthetic_user')])

    def test_instagram_manual_saved_fallback(self):
        page = Page('instagram', [
            {'auth': True, 'url': ig.HOME_URL}, {},
            {'url': ig.saved_url_for('synthetic_user')},
        ])
        ig.wait_for_saved_page(page, '', 0)
        self.assertEqual(page.visits, [ig.HOME_URL])

    def test_instagram_explicit_username_waits_for_completed_login(self):
        page = Page('instagram', [{}, {}, {'auth': True, 'url': ig.HOME_URL}])
        ig.wait_for_saved_page(page, '@synthetic_user', 0)
        self.assertEqual(page.visits, [ig.HOME_URL, ig.saved_url_for('synthetic_user')])

    def test_session_requires_site_cookie_and_no_visible_login_form(self):
        page = Page('facebook', [])
        page.url = fb.SAVED_URL
        self.assertFalse(fb.session_ready(page, 'facebook'))
        page.auth = True
        page.form = 1
        self.assertFalse(fb.session_ready(page, 'facebook'))
        page.form = 0
        self.assertTrue(fb.session_ready(page, 'facebook'))
        page.url = 'https://facebook.com.evil/saved'
        self.assertFalse(fb.session_ready(page, 'facebook'))

    def test_explicit_deadline_is_still_supported(self):
        for module, args in ((fb, (5,)), (ig, ('', 5))):
            with self.subTest(module=module.__name__), mock.patch.object(module.time, 'monotonic', side_effect=[0, 6]):
                page = Page('facebook' if module is fb else 'instagram', [])
                with self.assertRaisesRegex(RuntimeError, 'timeout'):
                    module.wait_for_saved_page(page, *args)
                self.assertEqual(len(page.visits), 1)

    def test_interactive_default_has_no_five_minute_cutoff(self):
        for module in (fb, ig):
            with mock.patch.object(sys, 'argv', ['scraper']):
                self.assertEqual(module.parse_args().login_wait_seconds, 0)

    def test_instagram_redirect_during_profile_lookup_is_retried(self):
        page = Page('instagram', [{'auth': True, 'url': ig.HOME_URL}])
        with mock.patch.object(page, 'evaluate', side_effect=[
            ig.PlaywrightError('Execution context was destroyed, most likely because of a navigation'), 'synthetic_user',
        ]):
            ig.wait_for_saved_page(page, '', 0)
        self.assertEqual(page.visits[-1], ig.saved_url_for('synthetic_user'))

    def test_challenge_after_opening_saved_is_left_alone_until_completed(self):
        for site, module, args in (('facebook', fb, (0,)), ('instagram', ig, ('synthetic_user', 0))):
            with self.subTest(site=site):
                home = f'https://www.{site}.com/'
                page = Page(site, [{'auth': True, 'url': home}, {}, {}, {'url': home}])
                goto = page.goto
                def navigate(url, **kwargs):
                    goto(url, **kwargs)
                    if len(page.visits) == 2:
                        page.url = f'https://www.{site}.com/checkpoint/'
                page.goto = navigate
                module.wait_for_saved_page(page, *args)
                self.assertEqual(len(page.visits), 3)
                self.assertGreaterEqual(page.polls, 4)

    def test_redirect_during_session_detection_waits_but_closed_browser_stops(self):
        page = Page('facebook', [])
        page.url, page.auth = fb.SAVED_URL, True
        with mock.patch.object(page, 'locator', side_effect=fb.PlaywrightError('Execution context was destroyed')):
            self.assertFalse(fb.session_ready(page, 'facebook'))
        with mock.patch.object(page, 'locator', side_effect=fb.PlaywrightError('Target page has been closed')):
            with self.assertRaisesRegex(fb.PlaywrightError, 'closed'):
                fb.session_ready(page, 'facebook')


class StatusTest(unittest.TestCase):
    def test_fixed_statuses_are_visible_but_page_output_and_secrets_are_not(self):
        from server import job_kinds
        proc = mock.Mock(stdout=iter([
            '[status] login\n', '[status] instagram-saved\n', '[status] collecting\n',
            '[status] unsave-failed\n', '[status] unsave-failed synthetic-secret\n',
            '[status] login synthetic-secret\n', '[action] synthetic-secret\n',
            'Traceback: synthetic-secret\n', '[done] Scraped 3 posts\n', '[done] Unsaved 2 of 3 posts\n',
        ]))
        proc.wait.return_value = 0
        say = mock.Mock()
        with mock.patch('subprocess.Popen', return_value=proc), \
                mock.patch.object(job_kinds.ytdlp, 'monitor', return_value=nullcontext()):
            job_kinds._scrape_process(SimpleNamespace(stopping=False),
                                     ['python', '--session-state', 'synthetic.json'], {}, say, 'Instagram')
        output = '\n'.join(call.args[0] for call in say.call_args_list)
        self.assertIn('2FA or CAPTCHA', output)
        self.assertIn('profile > Saved > All posts', output)
        self.assertIn('Collecting', output)
        self.assertIn('Scraped 3 posts', output)
        self.assertIn('Unsaved 2 of 3 posts', output)
        warnings = [call.args[0] for call in say.call_args_list if call.args[1:] == ('r',)]
        self.assertEqual(len(warnings), 1)
        self.assertIn('Could not confirm removal', warnings[0])
        self.assertNotIn('synthetic-secret', output)


@unittest.skipUnless(HAS_PLAYWRIGHT and sys.platform == 'win32', 'requires optional Playwright and Windows Edge')
class BrowserLoginTest(unittest.TestCase):
    def test_real_dom_detection_and_profile_lookup_with_intercepted_pages(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                context = browser.new_context()
                context.route('**/*', lambda route: route.fulfill(
                    content_type='text/html', body='<input type="password"><nav></nav>'))
                page = context.new_page()
                page.goto(ig.HOME_URL)
                context.add_cookies([{'name': 'sessionid', 'value': 'synthetic', 'url': ig.HOME_URL}])
                page.locator('input').fill('synthetic-password')
                for _ in range(3):
                    self.assertFalse(fb.session_ready(page, 'instagram'))
                self.assertEqual(page.locator('input').input_value(), 'synthetic-password')
                page.evaluate('document.querySelector("input").remove()')
                self.assertTrue(fb.session_ready(page, 'instagram'))
                self.assertEqual(page.evaluate(ig.FIND_USER_JS), '')
                page.evaluate('document.querySelector("nav").innerHTML = \'<a href="/synthetic_user/">Profile</a>\'')
                self.assertEqual(page.evaluate(ig.FIND_USER_JS), 'synthetic_user')
                page.evaluate('document.querySelector("nav").innerHTML = \'<a href="/synthetic_user/saved/all-posts/">Saved</a>\'')
                self.assertEqual(page.evaluate(ig.FIND_USER_JS), 'synthetic_user')
                page.goto('https://www.instagram.com/challenge/')
                page.evaluate('document.querySelector("input").remove()')
                self.assertFalse(fb.session_ready(page, 'instagram'))
            finally:
                browser.close()
