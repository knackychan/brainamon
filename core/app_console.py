"""
app_console.py - lightweight event bus for the in-app diagnostics console.

The bus is intentionally small: workers can emit API/log/error events from any
thread, and the V6 server's SSE hub subscribes with add_listener().
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from time import perf_counter
from typing import Any

MAX_ENTRIES = 1000
MAX_STRING = 4000
MAX_ITEMS = 30
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "session_token",
}


def _is_sensitive_key(key: str) -> bool:
    key_l = key.lower()
    return (
        key_l in _SENSITIVE_KEYS
        or key_l.endswith("_api_key")
        or key_l.endswith("_secret")
        or key_l.endswith("_password")
    )


_entries: list[dict] = []
_lock = RLock()
_logging_handler = None
_listeners: list = []   # subscribers (the V6 server's SSE hub); called from any thread


def add_listener(fn) -> None:
    """Call fn(entry) for every new entry. Used by server/app.py."""
    with _lock:
        _listeners.append(fn)


def remove_listener(fn) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


def entries() -> list[dict]:
    with _lock:
        return list(_entries)


def _redact(value: Any, depth: int = 0, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return "<redacted>"
    if depth > 6:
        return "<max depth>"
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_ITEMS:
                out["..."] = f"{len(value) - MAX_ITEMS} more keys"
                break
            out[str(k)] = _redact(v, depth + 1, str(k))
        return out
    if isinstance(value, (list, tuple)):
        out = [_redact(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            out.append(f"... {len(value) - MAX_ITEMS} more items")
        return out
    if isinstance(value, bytes):
        return f"<bytes {len(value)}>"
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            return value[:MAX_STRING] + f"... <truncated {len(value) - MAX_STRING} chars>"
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def emit(kind: str, title: str, *, level: str = "info", payload: Any = None,
         error: BaseException | str | None = None, details: Any = None) -> dict:
    entry = {
        "id": uuid.uuid4().hex[:8],
        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": level,
        "kind": kind,
        "title": title,
    }
    if payload is not None:
        entry["payload"] = _redact(payload)
    if details is not None:
        entry["details"] = _redact(details)
    if error is not None:
        entry["error"] = str(error)
        if isinstance(error, BaseException):
            entry["traceback"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
    with _lock:
        _entries.append(entry)
        del _entries[:-MAX_ENTRIES]
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(entry)
        except Exception:
            pass
    return entry


@contextmanager
def api_call(title: str, payload: Any = None):
    call_id = uuid.uuid4().hex[:8]
    start = perf_counter()
    emit("api", f"{title} started", payload={"call_id": call_id, "request": payload})
    try:
        yield call_id
    except Exception as exc:
        elapsed = round((perf_counter() - start) * 1000)
        emit(
            "api",
            f"{title} failed",
            level="error",
            payload={"call_id": call_id, "duration_ms": elapsed},
            error=exc,
        )
        raise
    else:
        elapsed = round((perf_counter() - start) * 1000)
        emit(
            "api",
            f"{title} completed",
            payload={"call_id": call_id, "duration_ms": elapsed},
        )


class ConsoleLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            emit(
                "log",
                record.getMessage(),
                level=record.levelname.lower(),
                details={
                    "logger": record.name,
                    "file": record.pathname,
                    "line": record.lineno,
                },
            )
        except Exception:
            pass


def install_logging_handler(level: int = logging.INFO) -> None:
    global _logging_handler
    if _logging_handler is not None:
        return
    _logging_handler = ConsoleLogHandler()
    _logging_handler.setLevel(level)
    logging.getLogger().addHandler(_logging_handler)
    logging.getLogger().setLevel(min(logging.getLogger().level or level, level))
