"""Export diagnostics (Settings > App): one zip the user can attach to a support message.

Opt-in: built only when the user clicks, saved on this PC in <local>/diagnostics/ (app_paths.LOCAL:
local/ from source, %LOCALAPPDATA%\\Brainamon installed), never sent anywhere, never in data/.
Inside:
    about.txt      version, Windows / Python, installed or source, item count, the tools found
    settings.json  DB settings by name; values only for the SAFE keys, the rest as their length;
                   API keys as set / not set
    error_log.txt  the last LOG_TAIL bytes of app_paths.ERROR_LOG
Every text goes through redact(): the configured key values, API keys and tokens by shape, e-mail
addresses and the user's home folder are replaced. Reads only: the DB through the caller's reader.
"""
import json
import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

from core import app_paths
from core import config
from core.version import __version__
from library import video_analyzer
from library import ytdlp

LOG_TAIL = 256 * 1024
OUT_DIR = app_paths.LOCAL / 'diagnostics'
# DB settings whose values are app options (no paths, names or text of the user's)
SAFE = {'analyze_options', 'minimize_to_tray', 'tray_notice', 'tray_notice_seen', 'keep_window_warm', 'setup_dismissed', 'embeddings_provider',
        'ai_model_jarvis', 'ai_model_describe', 'ai_model_categorize', 'ai_model_synthesize', 'ai_model_summarize',
        'ai_model_video', 'ai_model_connections', 'claude_auto_approve', 'os_notify', 'os_notify_jobs',
        'os_notify_approval', 'os_notify_claude', 'os_notify_capture'}
KEY_ENVS = (config.ANTHROPIC, config.OPENAI, config.FREELLMAPI, config.LOCAL_OPENAI_API_KEY,
            config.GOOGLE_CLIENT_SECRET)
_SHAPES = [
    (re.compile(r'(?im)^\s*(?:cookie|set-cookie|authorization)\s*[:=].*$'), '[session header redacted]'),
    (re.compile(r'sk-[A-Za-z0-9_\-]{8,}'), '[key]'),                       # Anthropic, OpenAI
    (re.compile(r'AIza[0-9A-Za-z_\-]{20,}'), '[key]'),                     # Google API key
    (re.compile(r'ya29\.[0-9A-Za-z_\-.]+'), '[token]'),                    # Google access token
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]+'), 'Bearer [token]'),
    (re.compile(r'(?i)\b([a-z_]{0,40}(?:api[_-]?key|token|secret|password))(["\']?\s*[:=]\s*["\']?)[^\s"\',}]+'),
     r'\1\2[redacted]'),
    # bounded and starting at a word edge: an unbounded run before '@' is quadratic on a long log line
    (re.compile(r'(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}'), '[email]'),
]


def secrets() -> list:
    """The key values configured on this PC (.env and the environment), to be cut out literally."""
    vals = {config.get(k) for k in KEY_ENVS}
    vals |= {v for k, v in config.read_env_file().items() if re.search(r'KEY|SECRET|TOKEN|PASSWORD', k, re.I)}
    return sorted((v for v in vals if v and len(v) >= 8), key=len, reverse=True)


def redact(text: str, known=(), home: str = '') -> str:
    for s in known:
        text = text.replace(s, '[key]')
    for rx, rep in _SHAPES:
        text = rx.sub(rep, text)
    if home:
        for h in {home, home.replace('\\', '/')}:
            text = re.sub(re.escape(h), '%USERPROFILE%', text, flags=re.I)
    return text


def _settings(db, known, home) -> dict:
    rows = db.conn.execute('SELECT key, value FROM settings ORDER BY key').fetchall()
    out = {k: (redact(v or '', known, home) if k in SAFE else f'[{len(v or "")} characters]') for k, v in rows}
    return {'db_settings': out, 'api_keys': {k: 'set' if config.get(k) else 'not set' for k in KEY_ENVS}}


def _log_tail(path: Path) -> str:
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LOG_TAIL))
            return f.read().decode('utf-8', 'replace')
    except OSError:
        return '(no error log)'


def build(db, data_dir: Path, out_dir: Path = None, log_path: Path = None) -> Path:
    """Write brainamon-diagnostics-<time>.zip into out_dir (OUT_DIR) and return its path."""
    out_dir, log_path = Path(out_dir or OUT_DIR), Path(log_path or app_paths.ERROR_LOG)
    known, home = secrets(), str(Path.home())
    about = '\n'.join([
        f'Brainamon {__version__} ({"installed" if app_paths.FROZEN else "from source"})',
        f'Windows/OS: {platform.platform()}',
        f'Python: {sys.version.split()[0]}',
        f'Data folder: {data_dir}',
        f'Items: {db.count_items()}',
        f'ffmpeg: {"found" if video_analyzer.ffmpeg_available() else "not found"}',
        f'yt-dlp: {"found" if ytdlp.available() else "not found"}',
        f'Made: {time.strftime("%Y-%m-%d %H:%M:%S")}',
    ]) + '\n'
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'brainamon-diagnostics-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('about.txt', redact(about, known, home))
        z.writestr('settings.json', json.dumps(_settings(db, known, home), indent=2, ensure_ascii=False))
        z.writestr('error_log.txt', redact(_log_tail(log_path), known, home))
    return path
