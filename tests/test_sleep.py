"""desktop/sleep.py: the sleep-mode decisions (no windows, no server).

Run from the project root:  py -m unittest tests.test_sleep -v
"""
import sys
import unittest
from unittest import mock

from desktop import sleep


@unittest.skipUnless(sys.platform == 'win32', 'Windows windows')
class WindowLookupTest(unittest.TestCase):
    def test_shell_proxy_is_not_an_app_window(self):
        u = mock.Mock()
        u.FindWindowW.return_value = 99  # The shell proxy is not enumerated by EnumWindows.
        u.EnumWindows.side_effect = lambda visit, data: visit(1, data)
        u.GetWindowTextLengthW.return_value = len(sleep.WINDOW_TITLE) + 1
        with mock.patch.object(sleep, '_user32', return_value=u):
            self.assertEqual(sleep.window_state(), 'gone')
            self.assertFalse(sleep.focus())
        u.SetForegroundWindow.assert_not_called()

    def test_hidden_app_is_found_and_restored_after_a_title_collision(self):
        u = mock.Mock()
        u.FindWindowW.return_value = 99
        def enumerate_windows(visit, data):
            for hwnd in (99, 42):
                if not visit(hwnd, data):
                    break
        u.EnumWindows.side_effect = enumerate_windows
        u.GetWindowTextLengthW.return_value = len(sleep.WINDOW_TITLE)
        u.GetWindowTextW.side_effect = lambda hwnd, text, size: setattr(text, 'value', sleep.WINDOW_TITLE)
        u.GetClassNameW.side_effect = lambda hwnd, text, size: setattr(
            text, 'value', 'Notepad' if hwnd == 99 else 'WindowsForms10.Window.8.app.0.test')
        u.IsIconic.return_value = False
        u.IsWindowVisible.side_effect = [False, True]
        with mock.patch.object(sleep, '_user32', return_value=u):
            self.assertEqual(sleep.find(sleep.WINDOW_TITLE), 42)
            self.assertTrue(sleep.focus())
        u.ShowWindowAsync.assert_called_once_with(42, 5)
        u.SetForegroundWindow.assert_called_once_with(42)

    def test_unrelated_window_with_the_same_title_is_ignored(self):
        for title, klass in ((sleep.WINDOW_TITLE, 'Windows.Internal.Shell.TabProxyWindow'),
                             (sleep.WINDOW_TITLE, 'Notepad'),
                             (sleep.WIDGET_TITLE, 'WindowsForms10.Window.8.app.0.test'),
                             ('Brainamon Drop', 'TkTopLevel')):
            with self.subTest(title=title, klass=klass):
                u = mock.Mock()
                u.EnumWindows.side_effect = lambda visit, data: visit(99, data)
                u.GetWindowTextLengthW.return_value = len(title)
                u.GetWindowTextW.side_effect = lambda hwnd, text, size: setattr(text, 'value', title)
                u.GetClassNameW.side_effect = lambda hwnd, text, size: setattr(text, 'value', klass)
                with mock.patch.object(sleep, '_user32', return_value=u):
                    self.assertEqual(sleep.window_state(title), 'gone')
                    self.assertFalse(sleep.focus(title))
                    self.assertFalse(sleep.close_window(title))
                u.SetForegroundWindow.assert_not_called()
                u.PostMessageW.assert_not_called()

    def test_widget_window_is_still_found(self):
        u = mock.Mock()
        u.EnumWindows.side_effect = lambda visit, data: visit(42, data)
        u.GetWindowTextLengthW.return_value = len(sleep.WIDGET_TITLE)
        u.GetWindowTextW.side_effect = lambda hwnd, text, size: setattr(text, 'value', sleep.WIDGET_TITLE)
        u.GetClassNameW.side_effect = lambda hwnd, text, size: setattr(text, 'value', 'TkTopLevel')
        with mock.patch.object(sleep, '_user32', return_value=u):
            self.assertEqual(sleep.find(sleep.WIDGET_TITLE), 42)


class KeeperViewTest(unittest.TestCase):
    def test_preference_off_is_the_old_behaviour(self):
        for state in ('awake', 'asleep', 'gone'):
            self.assertEqual(sleep.keeper_view(False, True, state, False), (True, False))
            self.assertEqual(sleep.keeper_view(False, False, state, False), (False, False))

    def test_preference_unknown_shows_no_icon(self):
        self.assertEqual(sleep.keeper_view(None, True, 'gone', False), (True, False))

    def test_awake_hides_wiskit_and_the_icon(self):
        self.assertEqual(sleep.keeper_view(True, True, 'awake', False), (False, False))

    def test_asleep_shows_the_icon_and_wiskit_if_he_is_on(self):
        for state in ('asleep', 'gone'):
            self.assertEqual(sleep.keeper_view(True, True, state, False), (True, True))
            self.assertEqual(sleep.keeper_view(True, False, state, False), (False, True))   # icon even without Wiskit

    def test_grace_hides_both_while_the_window_opens(self):
        self.assertEqual(sleep.keeper_view(True, True, 'gone', True), (False, False))
        self.assertEqual(sleep.keeper_view(False, True, 'gone', True), (False, False))


class OwnerQuitTest(unittest.TestCase):
    def test_closing_the_window_ends_the_app_when_nothing_else_shows(self):
        self.assertTrue(sleep.owner_should_quit(True, False, 'gone', False, False))

    def test_window_closed_before_keeper_started_exits_after_grace(self):
        self.assertFalse(sleep.owner_should_quit(True, True, 'gone', False, False))
        self.assertTrue(sleep.owner_should_quit(True, False, 'gone', False, False))

    def test_stays_up_otherwise(self):
        self.assertFalse(sleep.owner_should_quit(False, False, 'gone', False, False))  # Start with Windows
        self.assertFalse(sleep.owner_should_quit(True, True, 'gone', False, False))    # still in startup grace
        self.assertFalse(sleep.owner_should_quit(True, False, 'asleep', False, False)) # only minimized
        self.assertFalse(sleep.owner_should_quit(True, False, 'gone', True, False))    # asleep in the tray
        self.assertFalse(sleep.owner_should_quit(True, False, 'gone', None, False))    # preference not read yet
        self.assertFalse(sleep.owner_should_quit(True, False, 'gone', False, True))    # Wiskit still on


class WindowDecisionTest(unittest.TestCase):
    def test_minimize(self):
        self.assertEqual(sleep.on_minimize(False, False), 'normal')
        self.assertEqual(sleep.on_minimize(False, True), 'normal')
        self.assertEqual(sleep.on_minimize(True, False), 'close')
        self.assertEqual(sleep.on_minimize(True, True), 'hide')

    def test_x_button_sleeps_like_minimize(self):
        self.assertEqual(sleep.on_close(False, False), 'close')
        self.assertEqual(sleep.on_close(False, True), 'close')
        self.assertEqual(sleep.on_close(True, False), 'close')
        self.assertEqual(sleep.on_close(True, True), 'hide')

    def test_lazy_panel_only_when_sleeping_cold(self):
        self.assertTrue(sleep.lazy_panel(True, False))
        self.assertFalse(sleep.lazy_panel(True, True))
        self.assertFalse(sleep.lazy_panel(False, False))
        self.assertFalse(sleep.lazy_panel(None, False))

    def test_hidden_panel_goes_with_the_window(self):
        self.assertTrue(sleep.close_hidden_panel(0.0, True))          # the window just closed: no WebView2 left
        self.assertFalse(sleep.close_hidden_panel(5.0, False))        # prewarmed on hover, still useful
        self.assertTrue(sleep.close_hidden_panel(sleep.PANEL_IDLE_S, False))


class AnnounceTest(unittest.TestCase):
    def test_only_when_the_window_leaves_the_screen(self):
        self.assertTrue(sleep.announce('awake', True, True))
        self.assertFalse(sleep.announce('gone', True, True))       # keeper started with no window
        self.assertFalse(sleep.announce('awake', False, True))     # icon going away

    def test_nothing_when_the_notice_is_off(self):
        self.assertFalse(sleep.announce('awake', True, False))

    def test_the_first_time_is_told_whatever_the_setting_says(self):
        self.assertTrue(sleep.announce('awake', True, False, True))
        self.assertFalse(sleep.announce('gone', True, False, True))        # still not when the keeper starts alone
        self.assertIn('Settings', sleep.tray_note(True, True))
        self.assertNotIn('Settings', sleep.tray_note(True))

    def test_message_names_wiskit_only_when_he_is_on(self):
        self.assertIn('or Wiskit', sleep.tray_note(True))
        self.assertNotIn('Wiskit', sleep.tray_note(False))


class TitlesTest(unittest.TestCase):
    def test_titles_are_shared(self):
        try:
            from desktop import panel_ghost
            from server import desktop
        except ImportError as e:                  # pywebview: Windows only
            if sys.platform == 'win32':
                raise
            self.skipTest(f'Windows desktop modules: {e}')
        self.assertEqual(desktop.TITLE, sleep.WINDOW_TITLE)
        self.assertNotEqual(panel_ghost.PANEL_TITLE.casefold(), sleep.WINDOW_TITLE.casefold())
        self.assertNotEqual(sleep.WIDGET_TITLE.casefold(), sleep.WINDOW_TITLE.casefold())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows windows')
    def test_missing_window_is_gone(self):
        self.assertEqual(sleep.window_state('Brainamon test window that does not exist'), 'gone')
        self.assertFalse(sleep.close_window('Brainamon test window that does not exist'))


if __name__ == '__main__':
    unittest.main()
