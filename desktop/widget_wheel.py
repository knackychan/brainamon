"""Wiskit's action wheel, drop ring and speech bubbles (projects/desktop-app plans 07b, 11). tkinter only.

Wheel: a ring of round pixel-icon buttons that pops out around Wiskit on a left click, on the side
of the screen that has room. It is a borderless, topmost window whose key colour is transparent, so
everything but the buttons clicks through (clicking Wiskit again closes it). It closes on Esc, on a
choice, or when it loses focus. Nothing animates once it is open.

DropRing (plan 11): the same ring, popped out while something is dragged over Wiskit. It never takes
focus; the widget registers its window as a drop target (dropwin.py) and asks action_at(x, y) with
the cursor's screen point, which also highlights the bubble under it.

Bubble: a small box above Wiskit: a line Wiskit says for a few seconds, or a choice (a question and
one button per answer).

Dot and Card (projects/wiskit-activity): while the main window sleeps, a dot beside Wiskit pulses while
something runs and shows "!" when a request waits for a click; hovering shows the card, the bubble's look
with what runs (desktop/activity.py lines()).
"""
import math
import tkinter as tk

KEY = '#ff00ff'
INK, CREAM, ORANGE, DEEP, WHITE = '#2a1912', '#ffe7c6', '#ff7a2a', '#d4531c', '#ffffff'
FONT = ('Consolas', 9, 'bold')
DOT = 16          # the activity dot's window (px): a 10 px pulsing dot, or a 16 px "!" badge
PULSE_MS = 600    # busy: the dot swaps orange and cream this often
CARD_TONES = {'line': INK, 'bar': ORANGE, 'last': DEEP}     # the tones of desktop/activity.py lines()

R = 86            # ring radius: Wiskit's centre to a button's centre
BR = 20           # button radius
PX = 3            # icon pixel size (7 x 7 icons)
SPREAD = 160      # degrees the buttons cover, centred on the roomiest side
POP_MS, POP_FRAMES, STAGGER = 16, 10, 1

ICONS = {
    'ask': ('..xxx..', '.x...x.', '.....x.', '...xx..', '...x...', '.......', '...x...'),
    'drop': ('...x...', '...x...', '.x.x.x.', '..xxx..', 'x..x..x', 'x.....x', 'xxxxxxx'),
    'open': ('...x...', '..xxx..', '.xxxxx.', 'xxxxxxx', '.x...x.', '.x.x.x.', '.x.x.x.'),
    'write': ('.....xx', '....xxx', '...xxx.', '..xxx..', '.xxx...', '.xx....', 'xxxxxxx'),
    'record': ('...x...', '..xxx..', '..xxx..', '.xxxxx.', 'x.xxx.x', '..xxx..', '...x...'),
    'quit': ('...x...', '.x.x.x.', 'x..x..x', 'x..x..x', 'x.....x', '.x...x.', '..xxx..'),
    'inbox': ('xxxxxxx', 'x.....x', 'x.....x', 'xxx.xxx', 'x.xxx.x', 'x.....x', 'xxxxxxx'),
    'library': ('xx.xx..', 'xx.xx.x', 'xx.xx.x', 'xx.xx.x', 'xx.xx.x', 'xx.xx.x', 'xxxxxxx'),
    'video': ('.x.....', '.xxx...', '.xxxxx.', '.xxxxxx', '.xxxxx.', '.xxx...', '.x.....'),
}
ACTIONS = (('ask', 'Ask Wiskit'), ('drop', 'Drop panel'), ('write', 'Write a note'),
           ('record', 'Record a note'), ('open', 'Open Brainamon'), ('quit', 'Quit Wiskit'))
DROP_LABELS = {'inbox': 'Inbox', 'library': 'Add to library', 'video': 'Analyze video', 'ask': 'Ask Wiskit'}


def sprite_geometry(bounds: list[int], scale: int) -> tuple[int, int, int]:
    """Anchor on the menu's hover pose, clear of its animated silhouette."""
    x0, y0, x1, y1 = bounds
    radius = math.ceil(math.hypot(x1 - x0, y1 - y0) * scale / 2) + BR + 8
    return round((x0 + x1) * scale / 2), round((y0 + y1) * scale / 2), max(R, radius)


def angles(cx: float, cy: float, sw: int, sh: int, n: int = len(ACTIONS), spread: float = SPREAD, radius: int = R) -> list[float]:
    """Button angles (radians, screen coordinates: y down) fanned towards the middle of the screen,
    so a Wiskit parked in a corner opens his wheel into the room he has."""
    dx, dy = sw / 2 - cx, sh / 2 - cy
    mid = math.atan2(dy, dx) if math.hypot(dx, dy) > sw * .12 else -math.pi / 2     # near the middle: up
    original = [mid] if n == 1 else [mid + math.radians(spread) * (i / (n - 1) - .5) for i in range(n)]
    if radius == R:
        return original
    # Keep an 8px gap between buttons even when the cat needs a larger radius.
    compact = math.degrees(2 * math.asin((2 * BR + 8) / (2 * radius))) * max(0, n - 1)
    spread = min(spread, compact)
    for turn in [0] + [s * d for d in range(1, 181) for s in (-1, 1)]:
        centre = mid + math.radians(turn)
        result = [centre] if n == 1 else [centre + math.radians(spread) * (i / (n - 1) - .5) for i in range(n)]
        if all(BR + 4 <= cx + math.cos(a) * radius <= sw - BR - 4
               and BR + 4 <= cy + math.sin(a) * radius <= sh - BR - 4 for a in result):
            return result
    return original


def hit(angs: list[float], cx: float, cy: float, x: float, y: float, slack: int = 3, radius: int = R) -> int:
    """The button under (x, y) in ring coordinates (centre cx, cy), or -1."""
    for i, a in enumerate(angs):
        bx, by = cx + math.cos(a) * radius, cy + math.sin(a) * radius
        if (x - bx) ** 2 + (y - by) ** 2 <= (BR + slack) ** 2:
            return i
    return -1


LABEL_H, LABEL_GAP = 18, 6      # a label box's height; its space from the bubble


def label_width(text: str) -> int:
    return len(text) * 7 + 12


def label_boxes(angs: list[float], cx: float, cy: float, texts: list[str], size: int, radius: int = R) -> list[tuple[float, float, float, float]]:
    """(x0, y0, x1, y1) of every bubble's label (plan 11: the drop ring shows them all): inside the
    size x size ring window, clear of the other labels and of every bubble. Each label tries outwards
    from its bubble first, further out, then above or below it, then beside it."""
    centres = [(cx + math.cos(a) * radius, cy + math.sin(a) * radius) for a in angs]

    def free(box, placed) -> bool:
        x0, y0, x1, y1 = box
        if x0 < 2 or y0 < 2 or x1 > size - 2 or y1 > size - 2:
            return False
        if any(x0 < b[2] + 2 and b[0] < x1 + 2 and y0 < b[3] + 2 and b[1] < y1 + 2 for b in placed):
            return False
        return all(math.hypot(min(max(bx, x0), x1) - bx, min(max(by, y0), y1) - by) >= BR + 4 for bx, by in centres)

    boxes = []
    for (bx, by), a, text in zip(centres, angs, texts):
        w, h = label_width(text) / 2, LABEL_H / 2
        ca, sa = math.cos(a), math.sin(a)
        up, side = (-1 if sa < 0 else 1), (-1 if ca < 0 else 1)          # the outward vertical and horizontal sides
        d = BR + LABEL_GAP
        spots = [(bx + ca * (d + w + k), by + sa * (d + h + k)) for k in (0, 8, 16, 24)]
        spots += [(bx, by + up * (d + h)), (bx, by - up * (d + h)), (bx + side * (d + w), by), (bx - side * (d + w), by)]
        spots += [(bx, by + sign * (d + h + k)) for k in (8, 16, 24, 32) for sign in (-1, 1)]
        cands = [(x - w, y - h, x + w, y + h) for x, y in spots]
        box = next((c for c in cands if free(c, boxes)), None)
        if box is None:                                   # no clear spot: outwards, kept in the window
            x = min(max(spots[0][0], w + 2), size - w - 2)
            y = min(max(spots[0][1], h + 2), size - h - 2)
            box = (x - w, y - h, x + w, y + h)
        boxes.append(box)
    return boxes


def _back(t: float) -> float:
    """ease-out-back: overshoots a little, then settles (the pop)."""
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


class _Ring:
    """The buttons around a screen point, in a borderless topmost window whose key colour is
    transparent; pops out, then holds still. actions: [(name, label)], name a key of ICONS."""
    slack = 3
    all_labels = False      # every label once the pop is done (the drop ring), not only the hovered one's

    def __init__(self, root: tk.Tk, cx: int, cy: int, actions, radius: int = R):
        self.actions = list(actions)
        self.radius = radius
        self.size = 2 * (radius + BR + 34)
        half = self.size // 2
        self.cx, self.cy = half, half
        self.ox, self.oy = cx - half, cy - half          # the window's screen position
        self.angles = angles(cx, cy, root.winfo_screenwidth(), root.winfo_screenheight(), len(self.actions), radius=radius)
        self.hot = -1
        self.t = 0
        self.alive = True

        w = self.win = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.configure(bg=KEY)
        w.wm_attributes('-transparentcolor', KEY)
        w.geometry(f'{self.size}x{self.size}+{self.ox}+{self.oy}')
        self.cv = tk.Canvas(w, width=self.size, height=self.size, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack()

    @property
    def _frames(self) -> int:
        return POP_FRAMES + STAGGER * len(self.actions)

    # ── drawing ──
    def _pos(self, i: int, k: float) -> tuple[float, float]:
        a = self.angles[i]
        return self.cx + math.cos(a) * self.radius * k, self.cy + math.sin(a) * self.radius * k

    def _draw(self):
        cv = self.cv
        cv.delete('all')
        for i, (name, label) in enumerate(self.actions):
            t = max(0.0, min(1.0, (self.t - i * STAGGER) / POP_FRAMES))
            if t <= 0:
                continue
            k = _back(t)
            x, y = self._pos(i, k)
            r = BR * min(1.0, .4 + .6 * k)
            hot = i == self.hot
            cv.create_oval(x - r, y - r + 3, x + r, y + r + 3, fill=DEEP, outline=INK, width=2)     # pixel drop shadow
            lift = -2 if hot else 0
            cv.create_oval(x - r, y - r + lift, x + r, y + r + lift, fill=ORANGE if hot else CREAM, outline=INK, width=2)
            if t >= 1:
                ox, oy = round(x - 3.5 * PX), round(y - 3.5 * PX + lift)
                for row, line in enumerate(ICONS[name]):
                    for col, c in enumerate(line):
                        if c == 'x':
                            cv.create_rectangle(ox + col * PX, oy + row * PX, ox + col * PX + PX - 1, oy + row * PX + PX - 1,
                                                fill=WHITE if hot else INK, width=0)
        if self.all_labels and self.t >= self._frames:
            boxes = label_boxes(self.angles, self.cx, self.cy, [label for _, label in self.actions], self.size, self.radius)
            for i, (x0, y0, x1, y1) in enumerate(boxes):
                hot = i == self.hot
                cv.create_rectangle(x0, y0, x1, y1, fill=ORANGE if hot else INK, outline=INK)
                cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=self.actions[i][1], fill=WHITE if hot else CREAM, font=FONT)
        elif self.hot >= 0 and self.t >= self._frames:
            x, y = self._pos(self.hot, 1)
            a = self.angles[self.hot]
            lx, ly = x + math.cos(a) * (BR + 18), y + math.sin(a) * (BR + 12)
            text = self.actions[self.hot][1]
            tw = len(text) * 7 + 12
            lx = min(max(lx, tw / 2 + 2), self.size - tw / 2 - 2)
            cv.create_rectangle(lx - tw / 2, ly - 9, lx + tw / 2, ly + 9, fill=INK, outline=INK)
            cv.create_text(lx, ly, text=text, fill=CREAM, font=FONT)

    def _pop(self):
        if not self.alive:
            return
        self._draw()
        if self.t < self._frames:
            self.t += 1
            self.win.after(POP_MS, self._pop)

    # ── input ──
    def _hit(self, x: int, y: int) -> int:
        return hit(self.angles, self.cx, self.cy, x, y, self.slack, self.radius)

    def _hover(self, i: int):
        if i != self.hot:
            self.hot = i
            self.cv.configure(cursor='hand2' if i >= 0 else '')
            self._draw()


class Wheel(_Ring):
    def __init__(self, root: tk.Tk, cx: int, cy: int, on_pick, on_close, radius: int = R):
        super().__init__(root, cx, cy, ACTIONS, radius)
        self.on_pick, self.on_close = on_pick, on_close
        w = self.win
        self.cv.bind('<Motion>', self._motion)
        self.cv.bind('<Leave>', lambda e: self._hover(-1))
        self.cv.bind('<ButtonRelease-1>', self._click)
        w.bind('<Escape>', lambda e: self.close())
        w.bind('<FocusOut>', lambda e: self.close() if e.widget is w else None)
        w.focus_force()
        self._pop()

    def _motion(self, e):
        self._hover(self._hit(e.x, e.y))

    def _click(self, e):
        i = self._hit(e.x, e.y)
        if i >= 0:
            self.close()
            self.on_pick(self.actions[i][0])

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.win.destroy()
        self.on_close()


class DropRing(_Ring):
    """The drop bubbles (plan 11). The widget registers `hwnds` with dropwin and revokes them before
    close(); action_at(x, y) takes screen points from the drag."""
    slack = 8           # generous while dragging
    all_labels = True

    def __init__(self, root: tk.Tk, cx: int, cy: int, actions, radius: int = R):
        super().__init__(root, cx, cy, actions, radius)
        self.win.update_idletasks()
        self.hwnds = [int(self.win.wm_frame(), 16), self.cv.winfo_id()]
        self._pop()

    def action_at(self, sx: int, sy: int) -> str | None:
        """The action under a screen point (None: none); highlights it."""
        if not self.alive:
            return None
        i = self._hit(sx - self.ox, sy - self.oy)
        self._hover(i)
        return self.actions[i][0] if i >= 0 else None

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.win.destroy()


def place_above(win: tk.Toplevel, anchor, below: int = 110) -> None:
    """Centre a box above Wiskit (anchor() -> his centre x, top y) and keep it on the screen; with no room
    above, `below` pixels under his top."""
    win.update_idletasks()
    cx, top = anchor()
    bw, bh = win.winfo_reqwidth(), win.winfo_reqheight()
    x = min(max(4, cx - bw // 2), win.winfo_screenwidth() - bw - 4)
    y = top - bh - 6
    if y < 4:
        y = top + below
    win.geometry(f'+{x}+{y}')


class Bubble:
    """A box above Wiskit. say(): a line for a few seconds. choose(): a question with one button per
    answer. on_open(): runs as a bubble opens (the widget closes the activity card, which sits there too)."""

    def __init__(self, root: tk.Tk, anchor, on_open=None):
        self.root, self.anchor = root, anchor          # anchor() -> (centre x, top y) of Wiskit
        self.on_open = on_open
        self.win = None
        self._timer = None

    def _open(self, width: int):
        self.close()
        if self.on_open:
            self.on_open()
        w = self.win = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.configure(bg=INK)
        self.box = tk.Frame(w, bg=CREAM, padx=10, pady=8)
        self.box.pack(padx=2, pady=2)
        self.width = width
        return self.box

    def _place(self):
        place_above(self.win, self.anchor)

    def _title(self, box, text: str):
        top = tk.Frame(box, bg=CREAM)
        top.pack(fill='x')
        tk.Label(top, text=text, bg=CREAM, fg=INK, font=FONT).pack(side='left')
        x = tk.Label(top, text='x', bg=CREAM, fg=INK, font=FONT, cursor='hand2', padx=4)
        x.pack(side='right')
        x.bind('<Button-1>', lambda e: self.close())

    def say(self, text: str, ms: int = 3500):
        box = self._open(260)
        tk.Label(box, text=text, bg=CREAM, fg=INK, font=FONT, wraplength=260, justify='left').pack(anchor='w')
        self._place()
        self._timer = self.win.after(ms, self.close)

    def choose(self, title: str, line: str, choices):
        """A question, what it is about, one button per (label, callback). A click closes the bubble,
        then runs the callback; Esc or x closes it and runs nothing."""
        box = self._open(300)
        self._title(box, title)
        if line:
            tk.Label(box, text=line, bg=CREAM, fg=DEEP, font=FONT, wraplength=300, justify='left').pack(anchor='w', pady=(4, 0))
        row = tk.Frame(box, bg=CREAM)
        row.pack(fill='x', pady=(8, 0))
        for label, cb in choices:
            b = tk.Label(row, text=label, bg=ORANGE, fg=WHITE, font=FONT, padx=7, pady=4, cursor='hand2')
            b.pack(side='left', padx=(0, 6))
            b.bind('<Button-1>', lambda e, cb=cb: (self.close(), cb()))
        self.win.bind('<Escape>', lambda e: self.close())
        self._place()
        self.win.focus_force()

    def close(self):
        if self._timer:                 # a say() timer left running would close the next bubble (a choice) early
            self.root.after_cancel(self._timer)
            self._timer = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None


def dot_xy(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """The activity dot's top-left corner for Wiskit's window at (x, y), w x h: its bottom-right corner,
    clear of every pose (the widest, processing, ends at x 84 of the 96-pixel cell), just above the ground."""
    return x + w - DOT - 6, y + h - DOT - 10


class Dot:
    """Beside Wiskit while the window sleeps (projects/wiskit-activity). set(mode, x, y): 'busy' pulses a
    small orange dot, 'waiting' shows a steady deep-orange badge with "!", '' removes the window. A click
    runs on_click(); the pointer coming onto it and leaving runs on_hover(True) / on_hover(False)."""

    def __init__(self, root: tk.Tk, on_click, on_hover):
        self.root, self.on_click, self.on_hover = root, on_click, on_hover
        self.win = self.canvas = None
        self.mode, self.lit, self._timer = '', True, None

    def set(self, mode: str, x: int, y: int):
        if mode != self.mode:
            self._stop()
            self.mode = mode
            if not mode:
                self._close()
                return
            self._open()
            self.lit = True
            self._draw()
        if self.win is not None:
            self.win.geometry(f'{DOT}x{DOT}+{x}+{y}')

    def move(self, x: int, y: int):
        """Wiskit is dragged: the dot goes with him."""
        if self.win is not None:
            self.win.geometry(f'+{x}+{y}')

    def _open(self):
        if self.win is not None:
            return
        w = self.win = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.configure(bg=KEY)
        w.wm_attributes('-transparentcolor', KEY)
        c = self.canvas = tk.Canvas(w, width=DOT, height=DOT, bg=KEY, highlightthickness=0, bd=0, cursor='hand2')
        c.pack()
        c.bind('<Button-1>', lambda e: self.on_click())
        c.bind('<Enter>', lambda e: self.on_hover(True))
        c.bind('<Leave>', lambda e: self.on_hover(False))

    def _draw(self):
        self._timer = None
        c = self.canvas
        c.delete('all')
        if self.mode == 'waiting':
            c.create_oval(1, 1, DOT - 1, DOT - 1, fill=DEEP, outline=INK, width=2)
            c.create_text(DOT // 2, DOT // 2, text='!', fill=WHITE, font=FONT)
            return
        c.create_oval(3, 3, DOT - 3, DOT - 3, fill=ORANGE if self.lit else CREAM, outline=INK, width=2)
        self.lit = not self.lit
        self._timer = self.root.after(PULSE_MS, self._draw)

    def _stop(self):
        if self._timer:
            self.root.after_cancel(self._timer)
            self._timer = None

    def _close(self):
        self._stop()
        if self.win is not None:
            try:
                if self.root.winfo_containing(*self.root.winfo_pointerxy()) is self.canvas:
                    self.on_hover(False)       # a destroyed window sends no <Leave>
            except (KeyError, tk.TclError):
                pass
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = self.canvas = None


class Card:
    """The activity card above Wiskit (projects/wiskit-activity), the bubble's look: what runs while the
    window sleeps. show(lines) opens it or refreshes it in place; no buttons and no timer: the pointer
    leaving Wiskit and the dot closes it."""

    def __init__(self, root: tk.Tk, anchor):
        self.root, self.anchor = root, anchor          # anchor() -> (centre x, top y) of Wiskit
        self.win = self.box = None

    def show(self, lines):
        """lines: desktop/activity.py lines(), [(tone, text)] with tone 'line' | 'bar' | 'last'."""
        if self.win is None:
            w = self.win = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes('-topmost', True)
            w.configure(bg=INK)
            self.box = tk.Frame(w, bg=CREAM, padx=10, pady=8)
            self.box.pack(padx=2, pady=2)
        for child in self.box.winfo_children():
            child.destroy()
        for tone, text in lines:
            tk.Label(self.box, text=text, bg=CREAM, fg=CARD_TONES[tone], font=FONT, justify='left').pack(anchor='w')
        # no room above: under Wiskit's window, never over him (the pointer would leave him and close it)
        place_above(self.win, self.anchor, below=self.root.winfo_height() + 6)

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = self.box = None
