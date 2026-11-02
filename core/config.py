"""
config.py — single source of truth for API keys.

All API keys use the logical `.env` accessor: Windows stores its bytes in current-user
DPAPI storage under LOCAL/private. Every part of the app reads keys through this
module; nothing else parses `.env` or stores keys in the DB / QSettings.

Canonical key names (also the names the Anthropic / OpenAI SDKs read natively):
    ANTHROPIC_API_KEY   — Claude (AI describe, auto-categorize, video analysis)
    OPENAI_API_KEY      — OpenAI (Whisper transcription + OpenAI analysis provider)

Usage:
    from core import config
    config.load_env()                 # call once at startup (idempotent)
    key = config.anthropic_api_key()
    config.set_keys({'ANTHROPIC_API_KEY': '...'})   # writes .env + live os.environ
"""

import json
import os
from pathlib import Path

from core import app_paths, private_storage

ENV_PATH = app_paths.env_path()   # repo .env from source; selected app home when installed

ANTHROPIC = 'ANTHROPIC_API_KEY'
OPENAI = 'OPENAI_API_KEY'
FREELLMAPI = 'FREELLMAPI_API_KEY'
FREELLMAPI_BASE_URL = 'FREELLMAPI_BASE_URL'
FREELLMAPI_DEFAULT_BASE = 'http://127.0.0.1:3001'

# Local OpenAI-compatible server (the `local_openai` Ask provider). Config only — no
# runtime install/management. Set via the ⚙️ Settings dialog (Task 04).
LOCAL_OPENAI_BASE_URL = 'LOCAL_OPENAI_BASE_URL'
LOCAL_OPENAI_API_KEY = 'LOCAL_OPENAI_API_KEY'
LOCAL_OPENAI_DEFAULT_MODEL = 'LOCAL_OPENAI_DEFAULT_MODEL'


def read_env_file() -> dict:
    """Parse `.env` into a dict. Missing file -> {}."""
    env = {}
    try:
        for line in private_storage.read(ENV_PATH).decode('utf-8').splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, value = stripped.split('=', 1)
            env[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return env


def load_env(override: bool = False) -> None:
    """Load `.env` into os.environ.

    By default a real, already-exported environment variable wins over the file
    value (standard dotenv behaviour). Pass override=True to force file values.
    Safe to call multiple times.
    """
    for key, value in read_env_file().items():
        if override or key not in os.environ:
            os.environ[key] = value


def write_env_file(updates: dict) -> None:
    """Update/insert keys in `.env`, preserving comments and ordering, and
    mirror the change into os.environ so the running app sees it immediately.

    Empty-string values are written through (lets the UI clear a key).
    """
    updates = {k: ('' if v is None else str(v)) for k, v in updates.items()}

    lines = []
    seen = set()
    try:
        existing = private_storage.read(ENV_PATH).decode('utf-8')
    except FileNotFoundError:
        existing = ''
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in line:
            lines.append(line)
            continue
        key = line.split('=', 1)[0].strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    private_storage.write(ENV_PATH, ("\n".join(lines) + ("\n" if lines else "")).encode('utf-8'))

    for key, value in updates.items():
        os.environ[key] = value


def get(key: str, default: str = '') -> str:
    """Read a key from the live environment (os.environ), falling back to default."""
    return (os.environ.get(key) or default).strip()


def set_keys(updates: dict) -> None:
    """Public alias for write_env_file — persist one or more keys to `.env`."""
    write_env_file(updates)


# ── Convenience accessors ────────────────────────────────────────────────────
def anthropic_api_key() -> str:
    return get(ANTHROPIC)


def openai_api_key() -> str:
    return get(OPENAI)


def analysis_key_for(provider: str) -> str:
    """Return the right key for a video-analysis provider ('claude'/'openai'/'freellmapi')."""
    if provider == 'openai':
        return openai_api_key()
    if provider == 'freellmapi':
        return freellmapi_api_key()
    return anthropic_api_key()


def freellmapi_api_key() -> str:
    return get(FREELLMAPI)


def freellmapi_base_url() -> str:
    """FreeLLMAPI origin (no trailing /v1). Falls back to the local default."""
    return get(FREELLMAPI_BASE_URL) or FREELLMAPI_DEFAULT_BASE


def key_for_provider(provider: str) -> str:
    """API key for a text/vision provider id ('anthropic'/'openai'/'freellmapi')."""
    if provider == 'openai':
        return openai_api_key()
    if provider == 'freellmapi':
        return freellmapi_api_key()
    return anthropic_api_key()


def local_openai_base_url() -> str:
    return get(LOCAL_OPENAI_BASE_URL)


def local_openai_api_key() -> str:
    return get(LOCAL_OPENAI_API_KEY)


def local_openai_default_model() -> str:
    return get(LOCAL_OPENAI_DEFAULT_MODEL)


# ── Google sign-in for Upload to Google Drive (server/sync.py, library/drive_client.py) ──
# Brainamon registers one Google sign-in app (an OAuth client of type "Desktop app"); every user
# signs in with their own Google account. Google treats a desktop client's secret as not secret,
# so packaging ships only these app values as defaults, with local .env overrides.
# The sign-in token lives in the local cloud folder and is never bundled.
GOOGLE_CLIENT_ID = 'BRAINAMON_GOOGLE_CLIENT_ID'
GOOGLE_CLIENT_SECRET = 'BRAINAMON_GOOGLE_CLIENT_SECRET'
def bundled_google_oauth() -> dict:
    """Public app OAuth registration, never personal keys or account tokens."""
    if not app_paths.FROZEN:
        return {}
    try:
        data = json.loads((app_paths.BUNDLE / 'google-oauth.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()) else {}


_GOOGLE_OAUTH = bundled_google_oauth()
GOOGLE_CLIENT_DEFAULT = (_GOOGLE_OAUTH.get(GOOGLE_CLIENT_ID, ''), _GOOGLE_OAUTH.get(GOOGLE_CLIENT_SECRET, ''))


def google_client() -> tuple[str, str]:
    """(client_id, client_secret) for the Google sign-in; ('', '') when none is configured."""
    cid = get(GOOGLE_CLIENT_ID) or GOOGLE_CLIENT_DEFAULT[0]
    secret = get(GOOGLE_CLIENT_SECRET) or (GOOGLE_CLIENT_DEFAULT[1] if cid == GOOGLE_CLIENT_DEFAULT[0] else '')
    return cid, secret


# The phone (a web app) signs in to the same Google project with an OAuth client of type "Web
# application"; the pairing QR hands it the client id (no secret: the phone uses the browser
# token flow). Same project as the desktop client, so both see the same app data folder.
GOOGLE_WEB_CLIENT_ID = 'BRAINAMON_GOOGLE_WEB_CLIENT_ID'
GOOGLE_WEB_CLIENT_DEFAULT = _GOOGLE_OAUTH.get(GOOGLE_WEB_CLIENT_ID, '')


def google_web_client() -> str:
    return get(GOOGLE_WEB_CLIENT_ID) or GOOGLE_WEB_CLIENT_DEFAULT


# Keys a pairing may send to the phone (Settings > Cloud > Pair phone, ticked one by one): through
# Drive, sealed with a one-time key (library/mirror.py pair_drop), never inside the pairing link
PHONE_KEYS = {'openai': OPENAI, 'anthropic': ANTHROPIC}


def phone_keys(names) -> dict:
    """{name: key} for the ticked providers that have a key."""
    return {n: get(PHONE_KEYS[n]) for n in names if n in PHONE_KEYS and get(PHONE_KEYS[n])}


# ── One-time migration from the old scattered storage ────────────────────────
def migrate_legacy_keys(db=None) -> None:
    """Move the Anthropic key out of its old location (DB `settings.api_key`) into `.env`.

    Idempotent and non-destructive: only fills a canonical key when `.env`
    doesn't already define it, so running it every startup is harmless. After
    migration protected config is the sole source; the obsolete active DB value
    is removed only after a successful protected read. Historical backups remain sensitive.
    """
    load_env()
    env = read_env_file()
    updates = {}

    # Anthropic key: from DB settings.api_key
    if not env.get(ANTHROPIC) and db is not None:
        try:
            legacy = db.get_setting('api_key', '')
        except Exception:
            legacy = ''
        if legacy:
            updates[ANTHROPIC] = legacy

    if updates:
        write_env_file(updates)
    if db is not None and read_env_file().get(ANTHROPIC):
        db.conn.execute("DELETE FROM settings WHERE key = 'api_key'")
        db.conn.commit()
