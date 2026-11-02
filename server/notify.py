"""Windows notifications from the server (desktop/toast.py), switched in Settings > App.

Settings (DB, '1' / '0'): `os_notify` is the master switch (off by default); `os_notify_<category>` picks what
is announced, each on once the master is on. The values are cached here (read on the Writer at start, set by
PUT /api/app/notify) so a job thread or an async handler never touches SQLite to decide.

Categories: jobs (a job finished or failed), approval (Claude Code waits for a click), claude (Claude Code
did something), capture (an item or note arrived through Wiskit or the scraper). `__call__` returns at once:
the toast is raised on its own thread, and skipped while the Brainamon window is in front.
"""
import threading
from typing import Callable

from desktop import toast

MASTER_KEY = 'os_notify'
CATEGORIES = ('jobs', 'approval', 'claude', 'capture')


def _key(category: str) -> str:
    return f'os_notify_{category}'


class Notifier:
    def __init__(self, sender: Callable[[str, str], bool] = toast.show,
                 focused: Callable[[], bool] = toast.app_focused):
        self.sender, self.focused = sender, focused
        self.on = False
        self.cats = {c: True for c in CATEGORIES}

    def load(self, db) -> None:
        """On the Writer."""
        self.on = db.get_setting(MASTER_KEY, '0') == '1'
        self.cats = {c: db.get_setting(_key(c), '1') != '0' for c in CATEGORIES}

    def view(self) -> dict:
        return {'on': self.on, **self.cats}

    def save(self, db, changes: dict) -> None:
        """On the Writer: {"on"?, "jobs"?, "approval"?, "claude"?, "capture"?} booleans."""
        if 'on' in changes:
            db.set_setting(MASTER_KEY, '1' if changes['on'] else '0')
        for c in CATEGORIES:
            if c in changes:
                db.set_setting(_key(c), '1' if changes[c] else '0')
        self.load(db)

    def __call__(self, category: str, title: str, text: str, force: bool = False) -> bool:
        """force: the Settings test button (ignores the switches and the focus check)."""
        if not force and not (self.on and self.cats.get(category) and not self.focused()):
            return False
        threading.Thread(target=self.sender, args=(title, text), name='cm-toast', daemon=True).start()
        return True
