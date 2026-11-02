"""SQLite access for the server: one writer thread, per-thread read-only readers.

The rule (restated from root CLAUDE.md for the server): exactly one connection writes, and it
lives on the Writer thread. Every write is a callable `fn(db)` submitted to the Writer and run
there in order. Request handlers and job threads read through `reader(db_path)`, a
`db.ReadOnlyDatabase` (SQLite mode=ro) opened once per thread, because a sqlite3 connection
cannot be used from a thread other than the one that created it.
"""
import asyncio
import queue
import threading
from concurrent.futures import Future
from pathlib import Path

from core.db import Database, ReadOnlyDatabase
from core import entitlements

_local = threading.local()


def reader(db_path: Path) -> ReadOnlyDatabase:
    """The calling thread's read-only connection to `db_path` (opened on first use)."""
    conns = getattr(_local, 'conns', None)
    if conns is None:
        conns = _local.conns = {}
    key = str(db_path)
    conn = conns.get(key)
    if conn is None:
        conn = conns[key] = ReadOnlyDatabase(Path(db_path))
    return conn


class Writer:
    """Owns the only writable `db.Database`. Creating it runs the schema + `_migrate()`."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        # bumped after every write callable (it may have committed): readers key caches on it
        # (the /api/items body), since PRAGMA data_version is per connection and cannot be shared
        self.generation = 0
        self.phone_license_lock = threading.RLock()
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._loop, name='cm-writer', daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()
        if self._error is not None:
            raise self._error

    def _loop(self) -> None:
        try:
            db = Database(self.db_path)
        except BaseException as exc:  # surface the failure to start()
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            job = self._q.get()
            if job is None:
                break
            fn, fut, writes = job
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                result = fn(db)
            except BaseException as exc:
                if writes:
                    self.generation += 1
                fut.set_exception(exc)
            else:
                if writes:
                    self.generation += 1   # before the caller sees the result
                fut.set_result(result)
        db.close()

    def submit(self, fn, writes: bool = True) -> Future:
        """Queue `fn(db)` on the writer thread; returns a concurrent.futures.Future."""
        if writes and entitlements.phone_request.get():
            original = fn
            def fn(db):
                with self.phone_license_lock:
                    if not entitlements.feature_enabled('phone_sync'):
                        from fastapi import HTTPException
                        raise HTTPException(403, 'license_required')
                    return original(db)
        fut: Future = Future()
        self._q.put((fn, fut, writes))
        return fut

    def call(self, fn, timeout: float = 120):
        """Run `fn(db)` on the writer and wait. For job threads and threadpool endpoints.
        Never call it from the writer thread itself (it would wait on itself)."""
        if threading.current_thread() is self._thread:
            raise RuntimeError('Writer.call() from the writer thread')
        return self.submit(fn).result(timeout)

    def read(self, fn, timeout: float = 300):
        """Like call(), for a callable that only reads: `generation` is left alone, so the readers'
        caches stay valid. For threads that must not open SQLite themselves (server/sync.py)."""
        if threading.current_thread() is self._thread:
            raise RuntimeError('Writer.read() from the writer thread')
        return self.submit(fn, writes=False).result(timeout)

    async def run(self, fn):
        """Run `fn(db)` on the writer from async code."""
        return await asyncio.wrap_future(self.submit(fn))

    def stop(self) -> None:
        self._q.put(None)
        self._thread.join(5)
