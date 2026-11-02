"""Small startup surface before WebView2/.NET imports; no server or app-data access."""
import atexit
import sys
import threading
import time

_current = None


def progress(elapsed_ms: float) -> float:
    """Match boot.js goal(0): keep moving within the first ~10%, never complete."""
    elapsed_ms = max(0, elapsed_ms)
    return 12 * 0.85 * elapsed_ms / (elapsed_ms + 2500)


class Splash:
    def __init__(self):
        self.t0 = int(time.time() * 1000)
        self.stopped = threading.Event()
        self.painted = threading.Event()
        self.thread = threading.Thread(target=self._run, name='startup-splash', daemon=True)

    def close(self, *_):
        self.stopped.set()
        if threading.current_thread() is not self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)

    def _run(self):
        # Keep every Tk object on its owning thread, including interpreter cleanup.
        root = canvas = None
        try:
            import tkinter as tk
            if self.stopped.is_set():
                return
            root = tk.Tk()
            root.withdraw()
            root.title('Brainamon starting')
            root.overrideredirect(True)
            root.configure(bg='#17181b')
            w, h = 440, 180
            x = (root.winfo_screenwidth() - w) // 2
            y = (root.winfo_screenheight() - h) // 2
            root.geometry(f'{w}x{h}+{x}+{y}')
            canvas = tk.Canvas(root, width=w, height=h, bg='#17181b', bd=0, highlightthickness=0)
            canvas.pack()
            canvas.create_text(w // 2, 48, text='Brainamon', fill='#e8e8e1', font=('Segoe UI', 22, 'bold'))
            canvas.create_rectangle(40, 94, 350, 98, fill='#383b42', outline='')
            bar = canvas.create_rectangle(40, 94, 40, 98, fill='#ff5a1f', outline='')
            percent = canvas.create_text(400, 96, text='0%', anchor='e', fill='#e8e8e1', font=('Consolas', 11))
            canvas.create_text(w // 2, 132, text='Starting Brainamon...', fill='#b4b5ae', font=('Segoe UI', 11))
            root.deiconify()
            deadline = time.monotonic() + 90
            while not self.stopped.is_set() and time.monotonic() < deadline:
                value = progress(time.time() * 1000 - self.t0)
                canvas.coords(bar, 40, 94, 40 + 310 * value / 100, 98)
                canvas.itemconfigure(percent, text=f'{int(value)}%')
                root.update()
                self.painted.set()
                self.stopped.wait(1 / 30)
        except Exception as exc:
            if sys.stderr is not None:
                print(f'Early splash unavailable: {exc}', file=sys.stderr)
        finally:
            if root is not None:
                root.destroy()
            canvas = root = None
            # Tk has reference cycles; do not leave them for a later WebView thread's GC.
            import gc
            gc.collect()


def start(args) -> None:
    global _current
    if sys.platform != 'win32' or any(arg != 'v6' for arg in args) or _current is not None:
        return
    _current = Splash()
    atexit.register(close)
    _current.thread.start()
    # Yield to the first paint before competing imports; a broken splash never blocks startup.
    _current.painted.wait(0.5)


def started_at() -> int:
    return _current.t0 if _current is not None else int(time.time() * 1000)


def close(*_) -> None:
    if _current is not None:
        _current.close()


def handoff(window) -> None:
    if _current is not None:
        window.events.loaded += close
        window.events.closed += close
        window.events.minimized += close
