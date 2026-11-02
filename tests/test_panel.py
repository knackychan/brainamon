"""The drop panel's lifecycle (server/desktop.py --panel, plan 11): always there (Fred's choice over
NOTE-webview-process-count): the widget starts it hidden, closing hides it and rests its WebView2, a
panel_attach event wakes and shows it with the ids. The widget's dock ghost (desktop/panel_ghost.py)
holds the panel's place when it still has to start cold.
A fake window, no WebView2.
Run:  py -m unittest tests.test_panel -v
"""
import sys
import time
import unittest
from unittest import mock

try:
    from desktop import panel_ghost
    from desktop import widget
    from server import desktop
except ImportError as e:                          # Windows only (pywebview, tkinter)
    if sys.platform == 'win32':
        raise
    raise unittest.SkipTest(f'Windows desktop modules: {e}')


class FakeWindow:
    def __init__(self):
        self.calls = []

    def hide(self):
        self.calls.append('hide')

    def show(self):
        self.calls.append('show')

    def destroy(self):
        self.calls.append('destroy')

    def evaluate_js(self, js):
        self.calls.append(js)


class PanelApiTest(unittest.TestCase):
    def setUp(self):
        self.w = FakeWindow()
        for name, fn in (('_front', lambda title: None),
                         ('_webview_rest', lambda window, rest: window.calls.append('rest' if rest else 'wake'))):
            p = mock.patch.object(desktop, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def api(self, hidden=False):
        api = desktop.PanelApi(hidden)
        api._window = self.w
        return api

    def test_close_hides_and_rests_reopen_wakes_and_shows(self):
        api = self.api()
        api.close()
        api.reopen(['a1'])
        self.assertEqual(self.w.calls, ['hide', 'rest', 'wake', 'show', 'window.panelAttach?.(["a1"])'])

    def test_stays_warm(self):
        """Always there (Fred): no idle exit, the panel lives as long as its server."""
        self.api().close()
        time.sleep(0.05)
        self.assertNotIn('destroy', self.w.calls)
        self.assertFalse(hasattr(desktop, 'PANEL_IDLE_S'))

    def test_prewarmed_panel_wakes_on_first_open(self):
        self.api(hidden=True).reopen([])
        self.assertEqual(self.w.calls, ['wake', 'show', 'window.panelAttach?.([])'])

    def test_reopen_of_a_shown_panel_only_fronts(self):
        self.api().reopen([])
        self.assertEqual(self.w.calls, ['show', 'window.panelAttach?.([])'])

    def test_watch_reopens_on_panel_attach_only(self):
        seen = []
        lines = [b'event: job\n', b'data: {"current": null}\n', b'\n',
                 b'event: panel_attach\n', b'data: {"ids": ["x", "video:y"]}\n', b'\n', b'data: {}\n']
        desktop._panel_watch(lines, seen.append)
        self.assertEqual(seen, [['x', 'video:y']])


class GhostTest(unittest.TestCase):
    def test_one_definition_of_the_panel_window(self):
        self.assertEqual((desktop.PANEL_TITLE, desktop.PANEL_W, desktop.PANEL_H),
                         (panel_ghost.PANEL_TITLE, panel_ghost.PANEL_W, panel_ghost.PANEL_H))
        self.assertEqual(widget.PANEL_TITLE, panel_ghost.PANEL_TITLE)

    def test_panel_rect_docks_bottom_right(self):
        x, y, w, h = panel_ghost.panel_rect(1920, 1080)
        self.assertEqual((w, h), (panel_ghost.PANEL_W, panel_ghost.PANEL_H))
        self.assertEqual(x + w + panel_ghost.MARGIN_X, 1920)
        self.assertEqual(y + h + panel_ghost.MARGIN_Y, 1080)
        self.assertEqual(panel_ghost.panel_rect(800, 600)[1], 0)      # a short screen: clamped to the top

    def _root(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'no display: {e}')
        root.withdraw()
        self.addCleanup(root.destroy)
        return root

    def test_ghost_closes_when_the_panel_shows(self):
        root = self._root()
        shown = []
        g = panel_ghost.Ghost(root, ready=lambda: bool(shown), max_ms=60000)
        self.assertIsNotNone(g.win)
        g._step()                              # still starting: the outline stays, the scan line moved
        self.assertIsNotNone(g.win)
        self.assertEqual(g.canvas.coords(g.scan)[1], 4 + 2 * panel_ghost.SCAN_PX)
        shown.append(1)
        g._step()
        self.assertIsNone(g.win)
        g.close()                              # idempotent

    def test_ghost_gives_up_after_max_ms(self):
        root = self._root()
        g = panel_ghost.Ghost(root, ready=lambda: False, max_ms=0)
        g._step()
        self.assertIsNone(g.win)


if __name__ == '__main__':
    unittest.main()
