"""desktop/tray.py: the preference logic with a fake server (no pystray, no window).

Run from the project root:  py -m unittest tests.test_tray -v
"""
import sys
import unittest
from unittest import mock

from desktop import tray


class TrayTest(unittest.TestCase):
    def make(self):
        self.opened = []
        return tray.Tray('http://x', on_open=lambda: self.opened.append(1), on_quit=lambda: None)

    def test_show_never_turns_wiskit_on(self):
        t = self.make()
        icon = mock.Mock()
        t.icon = icon                               # already created: show only makes it visible
        with mock.patch.object(tray, 'call', return_value={'tray': True, 'widget': False, 'notice': True}) as call:
            self.assertTrue(t.show())
        call.assert_called_once_with('http://x', 'GET', '/api/app')
        self.assertEqual(t.state, {'tray': True, 'widget': False, 'notice': True})
        self.assertTrue(icon.visible)

    def test_notify_is_brief(self):
        t = self.make()
        icon = mock.Mock(visible=True)
        t.icon = icon
        t.notify('Minimized', seconds=0.05)
        icon.notify.assert_called_once_with('Minimized', tray.TITLE)
        import time
        time.sleep(0.3)
        icon.remove_notification.assert_called_once_with()

    def test_tooltip_names_the_activity_but_the_icon_is_added_as_brainamon(self):
        """projects/wiskit-activity: promote() finds the icon by the tooltip it was added with."""
        class Icon:                                  # pystray.Icon's visible / title, recording each add
            def __init__(self):
                self._visible, self.title, self.added_as = False, tray.TITLE, []

            @property
            def visible(self):
                return self._visible

            @visible.setter
            def visible(self, on):
                if on and not self._visible:
                    self.added_as.append(self.title)
                self._visible = on

            def update_menu(self):
                pass
        t = self.make()
        icon = t.icon = Icon()
        t.set_title('Brainamon - Describe 3 / 9')
        self.assertEqual(icon.title, tray.TITLE)                 # hidden: nothing changes on the icon yet
        with mock.patch.object(tray, 'call', return_value={'tray': True, 'widget': False, 'notice': False}):
            self.assertTrue(t.show())
        self.assertEqual(icon.added_as, [tray.TITLE])
        self.assertEqual(icon.title, 'Brainamon - Describe 3 / 9')
        t.set_title('Brainamon')                                 # shown: at once
        self.assertEqual(icon.title, 'Brainamon')
        t.set_title('Brainamon - Wiskit is answering')
        t.hide()
        with mock.patch.object(tray, 'call', return_value={'tray': True, 'widget': False, 'notice': False}):
            t.show()
        self.assertEqual(icon.added_as, [tray.TITLE, tray.TITLE])
        self.assertEqual(icon.title, 'Brainamon - Wiskit is answering')

    def test_turning_the_preference_off_restores_the_window(self):
        t = self.make()
        t.state = {'tray': True, 'widget': True}
        with mock.patch.object(tray, 'call', return_value={'tray': False}) as call:
            t._toggle_pref()
        call.assert_called_once_with('http://x', 'PUT', '/api/app/tray', {'on': False})
        self.assertFalse(t.state['tray'])
        self.assertEqual(self.opened, [1])

    def test_turning_it_on_keeps_the_window_where_it_is(self):
        t = self.make()
        t.state = {'tray': False, 'widget': False}
        with mock.patch.object(tray, 'call', return_value={'tray': True}):
            t._toggle_pref()
        self.assertTrue(t.state['tray'])
        self.assertEqual(self.opened, [])

    def test_icon_image_is_the_app_icon(self):
        img = tray._image()
        self.assertEqual(img.size, (32, 32))
        self.assertEqual(img.getpixel((16, 2)), (0x1F, 0x7A, 0x68, 255))   # the green tile, not the fallback
        self.assertEqual(img.getpixel((6, 16))[:3], (0xED, 0xE6, 0xD6))   # the B's stem, on whole pixels

    def test_widget_toggle_uses_the_existing_endpoint(self):
        t = self.make()
        t.state = {'tray': True, 'widget': True}
        with mock.patch.object(tray, 'call', return_value={'widget': False}) as call:
            t._toggle_widget()
        call.assert_called_once_with('http://x', 'PUT', '/api/app/widget', {'on': False}, timeout=5)
        self.assertFalse(t.state['widget'])

    def test_notice_toggle_uses_its_own_endpoint(self):
        t = self.make()
        self.assertFalse(t.state['notice'])                  # off until the server says otherwise
        with mock.patch.object(tray, 'call', return_value={'notice': True}) as call:
            t._toggle_notice()
        call.assert_called_once_with('http://x', 'PUT', '/api/app/notice', {'on': True}, timeout=5)
        self.assertTrue(t.state['notice'])
        with mock.patch.object(tray, 'call', return_value={'notice': False}) as call:
            t._toggle_notice()
        call.assert_called_once_with('http://x', 'PUT', '/api/app/notice', {'on': False}, timeout=5)
        self.assertFalse(t.state['notice'])


@unittest.skipUnless(sys.platform == 'win32', 'the notification-area settings are a Windows registry')
class PromoteTest(unittest.TestCase):
    """tray.promote against an in-memory registry shaped like HKCU\\Control Panel\\NotifyIconSettings."""
    BASE = r'Software\BrainamonTest\NotifyIconSettings'

    def setUp(self):
        self.entries = {}
        registry = mock.Mock(HKEY_CURRENT_USER='HKCU', KEY_READ=1, KEY_SET_VALUE=2, REG_DWORD=4)
        def key(value):
            result = mock.MagicMock()
            result.__enter__.return_value = value
            return result
        def opened(parent, sub, *args):
            if sub == self.BASE:
                return key('root')
            if parent == 'root' and sub in self.entries:
                return key(sub)
            raise FileNotFoundError(sub)
        def query(entry, name):
            if name not in self.entries[entry]:
                raise FileNotFoundError(name)
            return self.entries[entry][name], 1
        registry.OpenKey.side_effect = lambda parent, sub, *args: opened(parent.__enter__() if hasattr(parent, '__enter__') else parent, sub, *args)
        registry.QueryInfoKey.side_effect = lambda root: (len(self.entries), 0, 0)
        registry.EnumKey.side_effect = lambda root, index: list(self.entries)[index]
        registry.QueryValueEx.side_effect = query
        registry.SetValueEx.side_effect = lambda entry, name, reserved, kind, value: self.entries[entry].update({name: value})
        patch = mock.patch.dict(sys.modules, {'winreg': registry})
        patch.start()
        self.addCleanup(patch.stop)

    def entry(self, name, exe, tip, promoted=None):
        self.entries[name] = {'ExecutablePath': exe, 'InitialTooltip': tip}
        if promoted is not None:
            self.entries[name]['IsPromoted'] = promoted

    def promoted(self, name):
        return self.entries[name].get('IsPromoted')

    def run_promote(self, exe=r'C:\Py\pythonw.exe'):
        return tray.promote(exe, 'Brainamon', base=self.BASE, tries=1, wait=0)

    def test_promotes_our_new_entry(self):
        self.entry('1', r'C:\Py\pythonw.exe', 'Brainamon')            # tooltip case does not matter
        self.assertTrue(self.run_promote())
        self.assertEqual(self.promoted('1'), 1)

    def test_leaves_other_apps_and_other_tooltips_alone(self):
        self.entry('1', r'C:\Py\pythonw.exe', 'Some other pystray app')
        self.entry('2', r'C:\Other\app.exe', 'Brainamon')
        self.assertFalse(self.run_promote())
        self.assertIsNone(self.promoted('1'))
        self.assertIsNone(self.promoted('2'))

    def test_keeps_a_choice_the_user_made(self):
        self.entry('1', r'C:\Py\pythonw.exe', 'Brainamon', promoted=0)    # the user demoted it in Settings
        self.assertFalse(self.run_promote())
        self.assertEqual(self.promoted('1'), 0)

    def test_matches_a_known_folder_path(self):
        self.entry('1', r'{6D809377-6AF0-444B-8957-A3773F02200E}\Brainamon\Brainamon.exe', 'Brainamon')
        self.assertTrue(self.run_promote(r'C:\Program Files (x86)\Brainamon\Brainamon.exe'))
        self.assertEqual(self.promoted('1'), 1)

    def test_no_settings_key_is_not_an_error(self):
        self.assertFalse(tray.promote(r'C:\Py\pythonw.exe', 'Brainamon', base=self.BASE + r'\missing', tries=1, wait=0))


if __name__ == '__main__':
    unittest.main()
