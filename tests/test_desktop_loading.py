"""The loading page and app share one framed desktop window."""
import json
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from server import desktop


class DesktopLoadingTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(desktop.local_auth, 'browser_url', side_effect=lambda url: url + '#cm-auth=synthetic')
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(desktop.time, 'time_ns', return_value=123)
        patch.start()
        self.addCleanup(patch.stop)

    def test_native_history_guard_preserves_app_navigation_and_clipboard(self):
        for block_history, startup in ((True, 'data:text/html;base64,startup'),
                                       (True, 'about:blank'), (False, None)):
            with self.subTest(block_history=block_history, startup=startup):
                window = mock.MagicMock()
                window.native.Invoke.side_effect = lambda callback: callback()
                core = window.native.browser.webview.CoreWebView2
                window.native.BeginInvoke.side_effect = lambda callback: callback()
                for event in (window.events.loaded, core.PermissionRequested, core.NavigationStarting,
                              core.NavigationCompleted):
                    event.__iadd__.return_value = event
                func = mock.MagicMock()
                func.__getitem__.return_value = lambda callback: callback
                modules = {
                    'System': SimpleNamespace(Func=func, Type=object),
                    'Microsoft.Web.WebView2.Core': SimpleNamespace(
                        CoreWebView2NavigationKind=SimpleNamespace(BackOrForward='history'),
                        CoreWebView2PermissionKind=SimpleNamespace(ClipboardRead='clipboard'),
                        CoreWebView2PermissionState=SimpleNamespace(Allow='allow')),
                }
                with mock.patch.object(sys, 'platform', 'win32'), mock.patch.dict(sys.modules, modules):
                    app_url = f'http://{desktop.settings.HOST}:18765/'
                    desktop._configure_webview(window, block_history=block_history,
                                               app_url=app_url if block_history else None)
                    loaded = window.events.loaded.__iadd__.call_args.args[0]
                    loaded()
                    loaded()  # later page loads must not register duplicate handlers
                core.PermissionRequested.__iadd__.assert_called_once()
                permission = core.PermissionRequested.__iadd__.call_args.args[0]
                for uri, expected in ((f'http://{desktop.settings.HOST}:18765/', 'allow'),
                                      ('https://example.com/', 'default')):
                    args = SimpleNamespace(PermissionKind='clipboard', Uri=uri, State='default')
                    permission(None, args)
                    self.assertEqual(args.State, expected)
                if block_history:
                    core.NavigationStarting.__iadd__.assert_called_once()
                    navigate = core.NavigationStarting.__iadd__.call_args.args[0]
                    for kind in ('history', 'new-document', 'reload'):
                        args = SimpleNamespace(NavigationKind=kind, Cancel=False)
                        navigate(None, args)
                        self.assertEqual(args.Cancel, kind == 'history')
                    core.NavigationCompleted.__iadd__.assert_called_once()
                    completed = core.NavigationCompleted.__iadd__.call_args.args[0]

                    def visit(source, success=True):
                        completed(SimpleNamespace(Source=source), SimpleNamespace(IsSuccess=success))

                    visit('data:text/html;base64,startup')
                    visit('about:blank')
                    visit(app_url, success=False)
                    visit('about:blank')
                    window.load_url.assert_not_called()  # never interfere with startup / backend errors
                    visit('https://example.com/')
                    visit('about:blank')
                    window.load_url.assert_not_called()
                    visit(app_url + '?boot=123#cm-auth=synthetic')
                    visit('https://example.com/')
                    window.load_url.assert_not_called()  # unrelated navigation does not trigger recovery
                    visit('data:text/html;base64,startup', success=False)
                    window.load_url.assert_not_called()
                    visit(startup)
                    window.load_url.assert_called_once_with(app_url + '?reload=123#cm-auth=synthetic')
                    visit(app_url)
                    visit('about:blank')
                    visit('data:text/html;base64,startup')
                    self.assertEqual(window.load_url.call_count, 1)  # no recovery loop
                    window.create_confirmation_dialog.assert_not_called()
                else:
                    core.NavigationStarting.__iadd__.assert_not_called()
                    core.NavigationCompleted.__iadd__.assert_not_called()

    def test_reload_failure_is_logged_and_shown_natively(self):
        window = mock.Mock()
        with mock.patch.object(desktop.local_auth, 'browser_url', side_effect=OSError('unavailable')), \
                mock.patch.object(desktop, '_log_crash') as log:
            desktop._reload_app(window, 'http://127.0.0.1:18765/')
        log.assert_called_once()
        window.load_url.assert_not_called()
        self.assertEqual(window.create_confirmation_dialog.call_args.args[0], 'Could not reload app')

    def test_minimized_loading_window_applies_tray_preference_when_backend_is_ready(self):
        for tray, warm in ((False, False), (True, False), (True, True)):
            with self.subTest(tray=tray, warm=warm):
                window = mock.MagicMock()
                window.events.shown.is_set.return_value = True
                window.native.WindowState = 'minimized'
                window.native.Invoke.side_effect = lambda callback: callback()
                func = mock.MagicMock()
                func.__getitem__.return_value = lambda callback: callback
                modules = {'System': SimpleNamespace(Func=func, Type=object),
                           'System.Windows.Forms': SimpleNamespace(
                               FormWindowState=SimpleNamespace(Minimized='minimized'))}
                with mock.patch.dict(sys.modules, modules), \
                        mock.patch.object(desktop, 'LEAVING', desktop.threading.Event()), \
                        mock.patch.object(desktop.sleep, 'window_state', return_value='asleep'), \
                        mock.patch.object(desktop.sleep, 'find', return_value=1), \
                        mock.patch.object(desktop.tray, 'call', return_value={'tray': tray, 'warm': warm}), \
                        mock.patch.object(desktop, '_raise') as raise_window, \
                        mock.patch.object(desktop, '_destroy_all') as close:
                    desktop._sleep(window, 'http://127.0.0.1:18765')
                raise_window.assert_not_called()
                self.assertEqual(close.call_count, int(tray and not warm))
                self.assertEqual(window.native.Hide.call_count, int(tray and warm))

    def test_loading_window_restored_before_backend_ready_is_left_open(self):
        window = mock.MagicMock()
        window.events.shown.is_set.return_value = True
        with mock.patch.object(desktop.sleep, 'window_state', return_value='awake'), \
                mock.patch.object(desktop.tray, 'call') as prefs, \
                mock.patch.object(desktop, '_raise') as raise_window, \
                mock.patch.object(desktop, '_destroy_all') as close:
            desktop._sleep(window, 'http://127.0.0.1:18765')
        prefs.assert_not_called()
        raise_window.assert_not_called()
        close.assert_not_called()

    def test_window_opened_minimized_before_first_show_is_still_raised(self):
        window = mock.MagicMock()
        window.events.shown.is_set.return_value = False
        with mock.patch.object(desktop.sleep, 'window_state', return_value='asleep'), \
                mock.patch.object(desktop.tray, 'call') as prefs, \
                mock.patch.object(desktop, '_raise') as raise_window:
            desktop._sleep(window, 'http://127.0.0.1:18765')
        raise_window.assert_called_once_with(window)
        prefs.assert_not_called()

    def test_first_user_minimize_is_not_undone(self):
        window = mock.MagicMock()
        minimized = window.events.minimized
        with mock.patch.object(desktop.sleep, 'window_state', return_value='awake'), \
                mock.patch.object(desktop.tray, 'call', return_value={'tray': False, 'warm': False}) as prefs, \
                mock.patch.object(desktop, '_raise') as raise_window:
            desktop._sleep(window, 'http://127.0.0.1:18765')
            minimized.__iadd__.call_args.args[0]()
        prefs.assert_called_once()
        raise_window.assert_not_called()

    def test_loading_page_becomes_app_in_the_same_window(self):
        window = mock.Mock()
        with mock.patch.object(sys, 'argv', ['launch.pyw']), \
                mock.patch.object(desktop.config, 'load_env'), \
                mock.patch.object(desktop, '_focus_existing', return_value=False), \
                mock.patch.object(desktop, '_running', return_value=True), \
                mock.patch.object(desktop, '_suspend_when_minimized'), \
                mock.patch.object(desktop, '_configure_webview') as configure, \
                mock.patch.object(desktop, '_show_front'), \
                mock.patch.object(desktop, '_close_when_server_gone'), \
                mock.patch.object(desktop, '_sleep'), \
                mock.patch.object(desktop.app_paths, 'cache_dir', return_value='cache'), \
                mock.patch.object(desktop.webview, 'windows', [window]), \
                mock.patch.object(desktop.webview, 'create_window', return_value=window) as create, \
                mock.patch.object(desktop.webview, 'start', side_effect=lambda boot, **kwargs: boot()) as start:
            self.assertEqual(desktop.main(), 0)
        _, options = create.call_args
        configure.assert_called_once_with(window, block_history=True,
                                          app_url=f'http://{desktop.settings.HOST}:{desktop.settings.PORT}/')
        self.assertIn('window.CM_BOOT={"t0": ', options['html'])
        self.assertIn('Starting backend', options['html'])      # boot.js, inlined
        self.assertNotIn('frameless', options)
        self.assertNotIn('menu', start.call_args.kwargs)
        self.assertNotIn('on_top', options)
        window.load_url.assert_called_once()
        self.assertRegex(window.load_url.call_args.args[0].split('#')[0],
                         rf'^http://{desktop.settings.HOST}:{desktop.settings.PORT}/\?boot=\d+-\d+$')
        t0, t1 = map(int, window.load_url.call_args.args[0].split('#')[0].split('=')[1].split('-'))
        self.assertLessEqual(t0, t1)                            # the bar's clock carries over, never back
        window.load_html.assert_not_called()

    def _fail_start(self, start_server):
        window = mock.Mock()
        clock = iter(range(1_000_000, 10**9, 5))                # each time.time() call: 5 s later
        with mock.patch.object(sys, 'argv', ['launch.pyw']),                 mock.patch.object(desktop.config, 'load_env'),                 mock.patch.object(desktop, '_focus_existing', return_value=False),                 mock.patch.object(desktop, '_running', return_value=False),                 mock.patch.object(desktop, '_start_server', side_effect=start_server),                 mock.patch.object(desktop, '_log_crash') as log,                 mock.patch.object(desktop, '_suspend_when_minimized'), mock.patch.object(desktop, '_configure_webview'),                 mock.patch.object(desktop, '_show_front'),                 mock.patch.object(desktop.time, 'time', side_effect=lambda: next(clock)),                 mock.patch.object(desktop.time, 'sleep'),                 mock.patch.object(desktop.app_paths, 'cache_dir', return_value='cache'),                 mock.patch.object(desktop.autostart, 'spawn'),                 mock.patch.object(desktop.webview, 'windows', [window]),                 mock.patch.object(desktop.webview, 'create_window', return_value=window),                 mock.patch.object(desktop.webview, 'start', side_effect=lambda boot, **kwargs: boot()):
            self.assertEqual(desktop.main(), 0)
        window.load_url.assert_not_called()
        window.load_html.assert_called_once()
        page = window.load_html.call_args.args[0]
        self.assertIn('"error": "Could not start the backend', page)
        self.assertIn(json.dumps(str(desktop.app_paths.ERROR_LOG))[1:-1], page)
        return log

    def test_backend_that_never_answers_shows_an_error_not_a_bar(self):
        self._fail_start(lambda port: None).assert_not_called()

    def test_backend_that_crashes_is_logged_and_shown(self):
        log = self._fail_start(RuntimeError('broken create_app'))
        self.assertEqual(str(log.call_args.args[0]), 'broken create_app')

    def test_cold_start_shows_window_before_starting_backend(self):
        window = mock.Mock()
        created = []
        responses = iter((False, True, True))

        def running(_port):
            self.assertTrue(created)
            return next(responses)

        with mock.patch.object(sys, 'argv', ['launch.pyw']), \
                mock.patch.object(desktop.config, 'load_env'), \
                mock.patch.object(desktop, '_focus_existing', return_value=False), \
                mock.patch.object(desktop, '_running', side_effect=running), \
                mock.patch.object(desktop, '_suspend_when_minimized'), mock.patch.object(desktop, '_configure_webview'), \
                mock.patch.object(desktop, '_show_front'), \
                mock.patch.object(desktop, '_close_when_server_gone'), \
                mock.patch.object(desktop, '_sleep'), \
                mock.patch.object(desktop.app_paths, 'cache_dir', return_value='cache'), \
                mock.patch.object(desktop.webview, 'windows', [window]), \
                mock.patch.object(desktop.webview, 'create_window', side_effect=lambda *a, **k: created.append(True) or window), \
                mock.patch.object(desktop.autostart, 'spawn') as spawn, \
                mock.patch.object(desktop.webview, 'start', side_effect=lambda boot, **kwargs: boot()):
            self.assertEqual(desktop.main(), 0)
        spawn.assert_called_once_with('--widget', '--grace', '--owned')
        window.load_url.assert_called_once()


    def test_restart_waits_for_the_previous_server_window_and_keeper(self):
        gone = iter([True, True, False])        # server answers twice, then stops
        with mock.patch.object(desktop, '_running', side_effect=lambda port: next(gone, False)),                 mock.patch.object(desktop.sleep, 'find', return_value=0), mock.patch.object(desktop.time, 'sleep'):
            self.assertTrue(desktop._wait_for_previous(18765))
        with mock.patch.object(desktop, '_running', return_value=False),                 mock.patch.object(desktop.sleep, 'find', side_effect=lambda title: title == desktop.sleep.WIDGET_TITLE),                 mock.patch.object(desktop.time, 'sleep'):
            self.assertFalse(desktop._wait_for_previous(18765, timeout=0.01))


if __name__ == '__main__':
    unittest.main()
