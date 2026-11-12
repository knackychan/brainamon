"""Saved intents (S3): long cloud work the sync thread runs, one list in the protected cloud folder.

An HTTP handler validates, writes an intent and returns; `cm-sync` runs it at a safe point (between upload requests)
and records its stage after every step, so a quit or a crash resumes at the same stage. The file holds no passphrase:
a payload carries only what was sealed locally (wrapped keys, record names, key texts, which the cloud folder already
protects in `rotation.json` and `mirror.key`).
"""
import json
import secrets
import threading
import time

from core import app_console, private_storage
from server.cloud_errors import Busy

REMOVE, ENROLL, SWITCH, ONE_SHOT, RESET = 'remove_phones', 'enroll', 'switch_account', 'one_shot_publish', 'reset_backup'
UPDATE = 'update_folder'        # S9: queued -> downloading -> downloaded (waits for Restart now) -> swap (at the start) -> claim
DISCONNECT = 'disconnect'
KINDS = (REMOVE, ENROLL, SWITCH, ONE_SHOT, RESET, UPDATE, DISCONNECT)
FIRST_STAGE = {REMOVE: 'requested', ENROLL: 'queued', SWITCH: 'queued', ONE_SHOT: 'queued', RESET: 'queued', UPDATE: 'queued', DISCONNECT: 'queued'}
WAITING = {UPDATE: ('downloaded', 'swap')}     # stages that wait for the user (Restart now), not for the sync thread
BUSY_TEXT = {
    REMOVE: 'Phones are already being removed. Check the progress in Backup & phones.',
    ENROLL: 'The passphrase is already being saved.',
    SWITCH: 'The Google account is already being switched.',
    ONE_SHOT: 'A backup is already waiting to run.',
    RESET: 'The backup is already being reset.',
    UPDATE: 'This folder is already being updated.',
    DISCONNECT: 'Google Drive is already being disconnected.',
}


class Intents:
    """`owner` names the library (its data folder) the tasks belong to. A cloud folder can be opened by another data folder
    (a second copy, a test run): that one neither sees nor runs these tasks, and keeps them when it writes its own."""

    def __init__(self, path, owner=''):
        self.path = path
        self.owner = owner
        self._lock = threading.RLock()
        self._items = None          # this process is the only writer: the list is read from disk once
        self.on_change = lambda: None

    def _everything(self) -> list:
        if self._items is None:
            self._items = self._load()
        return self._items

    def _read(self) -> list:
        return [dict(i, payload=dict(i.get('payload') or {})) for i in self._everything() if i.get('owner', '') == self.owner]

    def _load(self) -> list:
        try:
            value = json.loads(private_storage.read(self.path))
        except FileNotFoundError:
            return []
        except (ValueError, OSError) as e:      # a damaged list never blocks the app; it reads as empty
            app_console.emit('log', 'Drive mirror: the saved task list could not be read', level='warning', error=e)
            return []
        return [i for i in value if isinstance(i, dict) and i.get('kind') in KINDS] if isinstance(value, list) else []

    def _write(self, mine: list) -> None:
        items = [i for i in self._everything() if i.get('owner', '') != self.owner] + [dict(i) for i in mine]
        if items:
            private_storage.write(self.path, json.dumps(items).encode())
        else:
            try:
                private_storage.remove(self.path)
            except FileNotFoundError:
                pass
        self._items = items
        try:
            self.on_change()
        except Exception:
            app_console.emit('log', 'Saved cloud task status could not be published.', level='warning')

    def all(self) -> list:
        with self._lock:
            return sorted(self._read(), key=lambda i: (0 if i['kind'] == DISCONNECT else
                          1 if i['kind'] in (RESET, SWITCH) and i['stage'] == 'queued' else 2,
                          -i['created'] if i['kind'] in (RESET, SWITCH) and i['stage'] == 'queued' else i['created']))

    def find(self, kind: str):
        return next((i for i in self.all() if i['kind'] == kind), None)

    def add(self, kind: str, payload: dict | None = None, *, error: str = '', code: str = '') -> dict:
        """A second intent of the same kind is a double click: refused, nothing written (A19)."""
        with self._lock:
            items = [i for i in self._read() if not (i['kind'] == kind and i.get('error'))]      # a failed one is replaced by the retry
            if any(i['kind'] == kind for i in items):
                raise Busy(BUSY_TEXT[kind])
            item = {'id': secrets.token_hex(8), 'owner': self.owner, 'kind': kind, 'stage': FIRST_STAGE[kind], 'created': int(time.time() * 1000),
                    'payload': payload or {}, 'error': error, 'code': code}
            self._write(items + [item])
            return item

    def update(self, kind: str, **fields):
        """Change fields of the pending intent of `kind` (`payload` merges); None when there is none."""
        with self._lock:
            items = self._read()
            for item in items:
                if item['kind'] == kind:
                    payload = fields.pop('payload', None)
                    item.update(fields)
                    if payload:
                        item['payload'] = {**item.get('payload', {}), **payload}
                    self._write(items)
                    return item
            return None

    def finish(self, kind: str) -> None:
        with self._lock:
            items = self._read()
            rest = [i for i in items if i['kind'] != kind]
            if len(rest) != len(items):
                self._write(rest)

    def preempting(self) -> bool:
        """True when an intent waits for the slot between upload requests: the export in progress ends so it can run. A
        removal waits there until the key is switched; a failed intent waits for its retry, not for the slot."""
        for item in self.all():
            if item.get('error') or item['kind'] == ONE_SHOT:
                continue
            if item['kind'] == REMOVE:
                if item['stage'] in ('requested', 'prepared'):
                    return True
            elif item['stage'] == FIRST_STAGE[item['kind']]:
                return True
        return False
