"""Desktop stays English with phone preview preferences, using a disposable built-app fixture.

Run after building web/: py -m tests.check_phone_i18n_desktop_browser
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shots', ROOT / 'tests/helpers/shots.py')
shots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shots)


class DesktopIsolation(shots.Run):
    def first_start(self, browser, theme):
        pass

    def phone(self, browser, theme):
        pass

    def desktop(self, browser, theme):
        original = shots.INIT
        try:
            for choice in ('fr', 'zh-Hant'):
                shots.INIT = original.replace("localStorage.setItem('bp-lang', 'en')",
                                              f"localStorage.setItem('bp-lang', '{choice}'); localStorage.setItem('brainamon-language', 'fr')")
                ctx = self.context(browser, theme)
                try:
                    page = ctx.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(self.url())
                    page.wait_for_selector('.cell[data-id]')
                    expect(page.locator('[data-menu="file"]')).to_have_text('File')
                    expect(page.locator('#tab-lib .wt-l')).to_have_text('Library')
                    self.assert_english_settings(page)
                    self.assert_shared_english(page, choice)
                    page.reload()
                    expect(page.locator('[data-menu="file"]')).to_have_text('File')
                    expect(page.locator('#tab-lib .wt-l')).to_have_text('Library')
                    assert page.locator('html').get_attribute('lang') == 'en'
                    assert page.evaluate("localStorage.getItem('brainamon-language')") == 'fr'
                    assert page.evaluate("localStorage.getItem('bp-lang')") == choice
                    assert not errors, errors
                finally:
                    ctx.close()
        finally:
            shots.INIT = original
        print('Desktop remains English with both phone preview preferences and the stale preference')

    def assert_shared_english(self, page, choice):
        self.close_windows(page)
        examples = ['What recipes have I saved?', 'List all my workout videos', 'What tips do I have on productivity?',
                    'Plan a weekend trip from my travel saves', 'Build me a 10-minute morning routine', 'Anything on design or drawing?']
        expect(page.locator('#sugs button')).to_have_text(examples)
        expect(page.locator('#pet')).to_have_attribute('aria-hidden', 'true')
        self.shot(page, f'06-desktop-{choice}-wiskit')
        assert self.palette(page, 'Set up Brainamon'), 'setup command must open its current window'
        expect(page.get_by_role('navigation', name='Setup checklist')).to_be_visible()
        expect(page.get_by_role('navigation', name='Setup checklist').get_by_role('button')).to_have_count(6)
        expect(page.get_by_role('progressbar', name='Setup readiness')).to_be_visible()
        expect(page.get_by_text('Let’s get you set up.', exact=True)).to_be_visible()
        self.shot(page, f'06-desktop-{choice}-setup')
        self.close_windows(page)
        assert self.palette(page, 'About Brainamon'), 'About command must open its current window'
        expect(page.locator('.legal-documents summary')).to_have_text(['Privacy policy', 'Software license', 'Third-party notices'])
        expect(page.locator('.legal-documents')).to_contain_text('Contact Frederic TOMAS:')
        self.shot(page, f'06-desktop-{choice}-legal')
        self.close_windows(page)
        page.keyboard.press('Control+Comma')
        win = page.locator('.cw.set-win')
        win.locator('#set-tbackup').click()
        forgot = win.locator('summary').filter(has_text='Forgot passphrase?')
        expect(forgot).to_be_visible()
        forgot.press('Enter')
        expect(win).to_contain_text('Choose what you still have. Opening this guide does not change your library, keys or backup.')
        self.shot(page, f'06-desktop-{choice}-backup-help')
        self.close_windows(page)
        assert self.palette(page, 'Recover a library'), 'recovery command must open its current window'
        expect(page.get_by_role('region', name='Passphrase help')).to_be_visible()
        expect(page.locator('.cw summary').filter(has_text='Forgot passphrase?')).to_be_visible()
        self.shot(page, f'06-desktop-{choice}-recovery')
        self.close_windows(page)
        assert self.palette(page, 'Video Tools'), 'Video Tools must render the shared form'
        expect(page.get_by_label('Frame interval', exact=True)).to_be_visible()
        expect(page.locator('#ao-mod option')).to_have_text(['GPT-Transcribe (OpenAI key)'])
        expect(page.locator('#ao-keep option')).to_have_text(['Keep & show in item canvas', 'Keep on disk only (hidden from canvas)', 'Delete frames after analysis'])
        expect(page.locator('#ao-send option')).to_have_text(['Auto (scale with length)', 'Off (transcript only)', 'Up to 8', 'Up to 15', 'Up to 24'])
        defaults = self.api('GET', '/api/settings/analyze')['options']
        assert float(page.locator('#ao-int').input_value()) == defaults['frame_interval']
        assert page.locator('#ao-send').input_value() == defaults['ai_frame_budget']
        assert page.locator('#ao-pr').input_value() == defaults['analysis_provider']
        assert page.locator('#ao-mod').input_value() == defaults['transcribe_method']
        self.shot(page, f'06-desktop-{choice}-analysis')
        self.close_windows(page)

    @staticmethod
    def assert_english_settings(page):
        page.keyboard.press('Control+Comma')
        win = page.locator('.cw.set-win')
        expect(win).to_be_visible()
        win.locator('#set-tgeneral').click()
        expect(win.get_by_role('group', name='Language / Langue', exact=True)).to_have_count(0)


if __name__ == '__main__':
    args = SimpleNamespace(repo=str(ROOT), dist=str(ROOT / 'web/dist'), port=0,
                           out=str(ROOT / 'local/i18n-review/06-desktop-isolation'), only=None, root=None, themes='light')
    DesktopIsolation(args).go()
