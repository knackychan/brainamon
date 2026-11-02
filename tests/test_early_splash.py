"""Early feedback must not import the app, affect helper modes, or outlive the window."""
import runpy
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from desktop import early_splash, sleep


class EarlySplashTest(unittest.TestCase):
    def test_helper_modes_never_start_a_splash(self):
        for args in (['--background'], ['--widget', '--grace', '--owned'], ['--panel'],
                     ['--mcp'], ['--uninstall-data'], ['--smoke'], ['--mobile'],
                     ['--dependency-report'], ['--restart-after', '123']):
            with self.subTest(args=args), mock.patch.object(early_splash, '_current', None), \
                    mock.patch.object(early_splash, 'Splash') as surface:
                early_splash.start(args)
                surface.assert_not_called()

    def test_start_is_once_and_carries_its_clock(self):
        with mock.patch.object(early_splash, '_current', None), \
                mock.patch.object(sys, 'platform', 'win32'), \
                mock.patch.object(early_splash, 'Splash') as surface, \
                mock.patch.object(early_splash.atexit, 'register'):
            surface.return_value.t0 = 123
            early_splash.start(['v6'])
            early_splash.start([])
            surface.assert_called_once()
            surface.return_value.thread.start.assert_called_once()
            self.assertEqual(early_splash.started_at(), 123)
            early_splash.close()
            surface.return_value.close.assert_called_once()

    def test_handoff_waits_for_loaded_or_user_hiding_the_main_window(self):
        with mock.patch.object(early_splash, '_current') as surface:
            window = mock.MagicMock()
            for event in (window.events.loaded, window.events.closed, window.events.minimized):
                event.__iadd__.return_value = event
            early_splash.handoff(window)
            surface.close.assert_not_called()
            for event in (window.events.loaded, window.events.closed, window.events.minimized):
                event.__iadd__.call_args.args[0]()
            self.assertEqual(surface.close.call_count, 3)

    def test_close_stops_and_joins_its_worker(self):
        surface = early_splash.Splash()
        surface.thread = threading.Thread(target=lambda: surface.stopped.wait(5))
        surface.thread.start()
        surface.close()
        self.assertFalse(surface.thread.is_alive())
        surface.close()  # exit cleanup may follow an earlier handoff

    def test_unavailable_gui_does_not_block_startup(self):
        surface = early_splash.Splash()
        tk = mock.Mock()
        tk.Tk.side_effect = RuntimeError('no GUI')
        with mock.patch.dict(sys.modules, {'tkinter': tk}), mock.patch.object(sys, 'stderr'):
            surface.thread.start()
            surface.thread.join(2)
        self.assertFalse(surface.thread.is_alive())
        self.assertFalse(surface.painted.is_set())

    def test_launcher_starts_splash_before_desktop_imports(self):
        class Started(Exception):
            pass

        with mock.patch.object(sys, 'argv', ['launch.pyw']), \
                mock.patch.object(sleep, 'focus', return_value=False), \
                mock.patch.object(early_splash, 'start', side_effect=Started) as start, \
                mock.patch.object(runpy, 'run_module') as desktop:
            with self.assertRaises(Started):
                runpy.run_path(str(Path(__file__).resolve().parents[1] / 'launch.pyw'))
            start.assert_called_once_with([])
            desktop.assert_not_called()

    def test_launcher_restores_existing_window_before_splash(self):
        for args in ([], ['v6']):
            with self.subTest(args=args), mock.patch.object(sys, 'argv', ['launch.pyw', *args]), \
                    mock.patch.object(sleep, 'focus', return_value=True), \
                    mock.patch.object(early_splash, 'start') as start:
                with self.assertRaises(SystemExit) as exit_:
                    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'launch.pyw'))
                self.assertEqual(exit_.exception.code, 0)
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
