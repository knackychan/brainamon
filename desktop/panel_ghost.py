"""The drop panel's dock ghost (projects/desktop-app/NOTE-webview-process-count.md).

The panel is its own WebView2 process and starts cold in about a second. It is normally there already,
hidden (the widget prewarms it and a close only hides it, Fred's choice over the note above: about
255 MB kept for an instant open), so this only shows when the panel still has to start: a hollow
outline where the panel will dock, corner brackets, a scan line and loading dots, drawn with tkinter
in the widget process the moment the click lands. It closes itself when the panel's window is
visible, or after GHOST_MAX_MS if the panel never came.

PANEL_TITLE / PANEL_W / PANEL_H / panel_rect are the one definition of the panel's window; server/desktop.py
(the panel process) and desktop/widget.py import them from here. tkinter is imported only by Ghost, so
the panel process pays nothing for this module.
"""
import sys
import time

from desktop import sleep

PANEL_TITLE = sleep.WINDOW_TITLE + ' Drop'
PANEL_W, PANEL_H = 420, 560
MARGIN_X, MARGIN_Y = 24, 200        # from the screen's right edge, and above the taskbar + Wiskit

GHOST_MAX_MS = 8000                 # the panel did not come: give up the outline
STEP_MS = 40                        # one frame: poll the panel's window, move the scan line
SCAN_PX = 8                         # scan line travel per frame (about 200 px/s)
DOTS_EVERY = 6                      # frames per loading-dot step (about 4 steps/s)
BRACKET = 18

KEY = '#ff00ff'                     # transparent (same key colour as the widget)
INK, ORANGE, DEEP = '#2a1912', '#ff7a2a', '#d4531c'
FONT = ('Consolas', 9, 'bold')


def panel_rect(sw: int, sh: int) -> tuple[int, int, int, int]:
    """Where the panel docks: bottom right of a sw x sh primary screen, above Wiskit. (x, y, w, h)."""
    return sw - PANEL_W - MARGIN_X, max(0, sh - PANEL_H - MARGIN_Y), PANEL_W, PANEL_H


def panel_visible() -> bool:
    """True when the panel's window exists and is shown (a WebView2 window is created before it shows)."""
    if sys.platform != 'win32':
        return False
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = sleep.find(PANEL_TITLE)
    return bool(hwnd and user32.IsWindowVisible(hwnd))


class Ghost:
    """The outline. ready() is asked every frame (panel_visible by default; tests inject one)."""

    def __init__(self, root, ready=panel_visible, max_ms: int = GHOST_MAX_MS):
        import tkinter as tk
        self.root, self.ready = root, ready
        self.deadline = time.monotonic() + max_ms / 1000
        self.n, self.timer = 0, None
        x, y, w, h = panel_rect(root.winfo_screenwidth(), root.winfo_screenheight())
        self.w, self.h = w, h
        win = self.win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=KEY)
        win.wm_attributes('-transparentcolor', KEY)
        win.geometry(f'{w}x{h}+{x}+{y}')
        c = self.canvas = tk.Canvas(win, width=w, height=h, bg=KEY, bd=0, highlightthickness=0)
        c.pack()
        c.create_rectangle(2, 2, w - 2, h - 2, outline=DEEP, width=2)
        b = BRACKET
        for (px, py, dx, dy) in ((2, 2, 1, 1), (w - 2, 2, -1, 1), (2, h - 2, 1, -1), (w - 2, h - 2, -1, -1)):
            c.create_line(px, py + dy * b, px, py, px + dx * b, py, fill=ORANGE, width=3)
        self.scan = c.create_line(4, 4, w - 4, 4, fill=ORANGE, width=2)
        # the label sits on a solid pill: text anti-aliased straight onto the key colour leaves a magenta fringe
        pill = c.create_rectangle(0, 0, 0, 0, fill=INK, outline=DEEP, width=2)
        self.text = c.create_text(w // 2 - 36, h // 2, text='loading...', fill=ORANGE, font=FONT, anchor='w')
        x0, y0, x1, y1 = c.bbox(self.text)
        c.coords(pill, x0 - 12, y0 - 8, x1 + 12, y1 + 8)
        c.itemconfigure(self.text, text='loading')
        self._step()

    def _step(self):
        self.timer = None
        if self.win is None:
            return
        if self.ready() or time.monotonic() > self.deadline:
            self.close()
            return
        self.n += 1
        y = 4 + (self.n * SCAN_PX) % (self.h - 8)
        self.canvas.coords(self.scan, 4, y, self.w - 4, y)
        self.canvas.itemconfigure(self.text, text='loading' + '.' * (1 + (self.n // DOTS_EVERY) % 3))
        self.timer = self.win.after(STEP_MS, self._step)

    def close(self):
        if self.win is None:
            return
        win, self.win = self.win, None
        try:
            if self.timer:
                win.after_cancel(self.timer)
            win.destroy()
        except Exception:          # tk.TclError when the root is already gone
            pass
