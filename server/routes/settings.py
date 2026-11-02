"""App settings the V6 windows edit. Plan 07: the Analyze options defaults (DB settings key
`analyze_options`, JSON) [Q5 default a]. Plan 12: the Settings window (keys, local model,
downloads, AI models) and the menubar CK lamp."""
import asyncio
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import ai_client
from core import app_paths
from core import ai_defaults
from core import config
from core import site_sessions
from library import scrape_watch
from library import video_analyzer
from library import ytdlp
from server.job_kinds import ANALYZE_DEFAULTS
from server.store import reader

router = APIRouter()


@router.get('/api/settings/scraper-runtime')
async def scraper_runtime_state():
    from library import scraper_runtime
    return await asyncio.to_thread(scraper_runtime.status, recheck=True)


@router.post('/api/settings/scraper-runtime')
def scraper_runtime_action(request: Request, body: dict = Body(...)):
    from library import scraper_runtime
    if request.app.state.jobs.current and request.app.state.jobs.current.kind == 'scrape':
        raise HTTPException(409, 'Stop the scraper and wait for cleanup before changing browser tools.')
    try:
        if body.get('action') == 'select':
            result = scraper_runtime.select_location(body.get('kind'), body.get('folder'))
            request.app.state.hub.publish('settings_changed', {'tools': True})
            return result
        return scraper_runtime.action(body.get('action'))
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc))

PROVIDERS = ['claude', 'openai', 'freellmapi', 'none']
TRANSCRIBE = ['whisper-api']
FRAME_BUDGETS = ['auto', '0', '8', '15', '24']


def _saved(db) -> dict:
    try:
        v = json.loads(db.get_setting('analyze_options', '') or '{}')
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


@router.get('/api/settings/analyze')
def get_analyze(request: Request):
    db = reader(request.app.state.db_path)
    saved = _saved(db)
    v_provider, _ = ai_defaults.get(db, ai_defaults.VIDEO)
    default_provider = 'claude' if v_provider == 'anthropic' else v_provider
    opts = {**ANALYZE_DEFAULTS, **saved}
    opts['transcribe_method'] = 'whisper-api'   # a 'free' saved before the local engine was removed
    # Wiskit overrides the last-used provider; a run may explicitly override it again.
    if default_provider in PROVIDERS:
        opts['analysis_provider'] = default_provider
    return {'options': opts, 'providers': PROVIDERS, 'transcribe_methods': TRANSCRIBE,
            'frame_budgets': FRAME_BUDGETS}


@router.put('/api/settings/analyze')
async def put_analyze(request: Request, data: dict = Body(...)):
    o = {**ANALYZE_DEFAULTS}
    for k in ANALYZE_DEFAULTS:
        if k in data:
            o[k] = data[k]
    try:
        o['frame_interval'] = max(0.0, min(60.0, float(o['frame_interval'])))
    except (TypeError, ValueError):
        raise HTTPException(400, 'Frame interval must be a number of seconds.')
    if o['analysis_provider'] not in PROVIDERS or o['transcribe_method'] not in TRANSCRIBE \
            or str(o['ai_frame_budget']) not in FRAME_BUDGETS:
        raise HTTPException(400, 'Unknown option value.')
    for k in ('transcribe', 'keep_frames', 'show_frames_in_canvas', 'delete_video', 'delete_audio'):
        o[k] = bool(o[k])
    o['ai_frame_budget'] = str(o['ai_frame_budget'])
    await request.app.state.writer.run(lambda db: db.set_setting('analyze_options', json.dumps(o)))
    return {'options': o}


# ── plan 12: the Settings window (API keys, Local model, Downloads, AI models) ──
# API keys stay in .env through config.py and never leave the server: the window gets "set" /
# "not set" and can replace a key. Cookie paths and the scrape folder are DB settings; on the
# first V6 start each missing one is copied once from the Qt app's registry values.
SECRET_KEYS = {'anthropic': config.ANTHROPIC, 'openai': config.OPENAI, 'freellmapi': config.FREELLMAPI,
               'local': config.LOCAL_OPENAI_API_KEY}
PLAIN_KEYS = {'freellmapi_base': config.FREELLMAPI_BASE_URL, 'local_base': config.LOCAL_OPENAI_BASE_URL,
              'local_model': config.LOCAL_OPENAI_DEFAULT_MODEL}
DOWNLOAD_KEYS = ('yt_dlp_cookies', 'instagram_cookies', 'scrape_watch_dir')
EMBED_PROVIDERS = [(ai_client.ASK_PROVIDER_FREELLMAPI, 'FreeLLMAPI (free)'), (ai_client.ASK_PROVIDER_OPENAI, 'OpenAI')]
_MISSING = '\0'


def migrate_registry(db) -> None:
    """Copy each download setting the DB does not have yet from the Qt app's QSettings
    (HKCU\\Software\\ContentManager\\Main, read-only). Runs on the Writer at start-up."""
    existing = db.count_items() > 0 or db.get_setting('setup_dismissed', '') == '1' or any(db.get_setting(k, '') for k in DOWNLOAD_KEYS)
    for k in DOWNLOAD_KEYS:
        if db.get_setting(k, _MISSING) == _MISSING:
            v = ytdlp.registry_get(k) if existing else ''
            if v:
                db.set_setting(k, v)
        slot = 'instagram' if k == 'instagram_cookies' else 'general'
        if k != 'scrape_watch_dir' and db.get_setting('session_mode_' + slot, _MISSING) == _MISSING:
            db.set_setting('session_mode_' + slot, 'legacy' if existing else 'none')


def _has_key(provider: str) -> bool:
    return bool(config.key_for_provider(provider))


def settings_view(db) -> dict:
    provider, model = ai_defaults.get(db, ai_defaults.DESCRIBE)
    found = ai_defaults.found_models(db)
    return {
        'keys': {name: bool(config.get(env)) for name, env in SECRET_KEYS.items()},
        'plain': {name: config.get(env) for name, env in PLAIN_KEYS.items()},
        'freellmapi_default_base': config.FREELLMAPI_DEFAULT_BASE,
        'downloads': {k: db.get_setting(k, '') for k in DOWNLOAD_KEYS},
        'default_watch_dir': str(scrape_watch.default_downloads_dir()),
        'models': {
            'jarvis': {'provider': provider, 'model': model},
            'saved': db.get_setting(ai_defaults.WISKIT_KEY, None) is not None or bool(db.get_setting('ai_model_describe', '')),
            'providers': [{**p, 'has_key': _has_key(p['id'])} for p in ai_client.feature_provider_options()],
            'models': {p['id']: ai_client.feature_models(p['id'], found.get(p['id']))
                       for p in ai_client.feature_provider_options()},
            'found_at': ai_defaults.found_at(db),
            'embed_provider': ai_defaults.embed_provider(db),
            'embed_providers': [{'id': i, 'label': label} for i, label in EMBED_PROVIDERS],
        },
    }


@router.get('/api/settings')
def get_settings(request: Request):
    return settings_view(reader(request.app.state.db_path))


@router.put('/api/settings')
async def put_settings(request: Request, data: dict = Body(...)):
    keys = data.get('keys') or {}
    plain = data.get('plain') or {}
    updates = {}
    for name, value in keys.items():           # a key is replaced only when a new value is given
        if name in SECRET_KEYS and isinstance(value, str) and value.strip():
            updates[SECRET_KEYS[name]] = value.strip()
    for name in data.get('clear_keys') or []:
        if name in SECRET_KEYS:
            updates[SECRET_KEYS[name]] = ''
    for name, value in plain.items():
        if name in PLAIN_KEYS and isinstance(value, str):
            updates[PLAIN_KEYS[name]] = value.strip()
    downloads = {k: str(v).strip() for k, v in (data.get('downloads') or {}).items() if k in DOWNLOAD_KEYS}
    models = data.get('models') or {}
    if not isinstance(models, dict):
        raise HTTPException(400, 'Models must be an object.')
    if 'features' in models:
        raise HTTPException(400, 'Use the Wiskit model chooser instead of per-feature settings.')
    choice = models.get('jarvis')
    found = ai_defaults.found_models(reader(request.app.state.db_path))
    valid = {p['id']: {m['id'] for m in ai_client.feature_models(p['id'], found.get(p['id']))}
             for p in ai_client.feature_provider_options()}
    if 'jarvis' in models:
        if not isinstance(choice, dict) or not isinstance(choice.get('provider'), str) \
                or not isinstance(choice.get('model'), str) \
                or choice['model'] not in valid.get(choice['provider'], set()):
            raise HTTPException(400, 'Unknown Wiskit model.')
    embed = models.get('embed_provider')
    if embed is not None and embed not in dict(EMBED_PROVIDERS):
        raise HTTPException(400, 'Unknown embeddings provider.')
    if updates:
        config.set_keys(updates)

    def write(db):
        for k, v in downloads.items():
            db.set_setting(k, v)
            if k in ('yt_dlp_cookies', 'instagram_cookies'):
                slot = 'instagram' if k == 'instagram_cookies' else 'general'
                db.set_setting('session_mode_' + slot, 'legacy' if v else 'disabled')
        if choice is not None:
            ai_defaults.set(db, ai_defaults.DESCRIBE, choice['provider'], choice['model'])
        if embed is not None:
            ai_defaults.set_embed_provider(db, embed)
        return settings_view(db)
    view = await request.app.state.writer.run(write)
    request.app.state.hub.publish('settings_changed', {'cookies': cookies_state(view['downloads'])})
    return view


@router.post('/api/settings/models/refresh')
async def refresh_models(request: Request):
    """Ask Anthropic and OpenAI which models the saved keys can use and keep the lists
    (projects/model-lists/PLAN.md). A provider with no key is skipped; a failed one keeps its
    previous list and says why. The calls run in the thread pool, the save on the Writer."""
    results, fetched = {}, {}
    for provider in ai_client.DISCOVER_PROVIDERS:
        key = config.key_for_provider(provider)
        if not key:
            results[provider] = {'ok': False, 'count': 0, 'error': 'No API key saved.'}
            continue
        try:
            fetched[provider] = await run_in_threadpool(ai_client.discover_cloud_models, provider, key)
        except Exception as exc:
            results[provider] = {'ok': False, 'count': 0, 'error': str(exc)[:200]}
            continue
        results[provider] = {'ok': True, 'count': len(fetched[provider]), 'error': ''}
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def write(db):
        for provider, models in fetched.items():
            ai_defaults.set_found_models(db, provider, models, at)
        return settings_view(db)
    view = await request.app.state.writer.run(write)
    return {'results': results, 'models': view['models']}


def cookies_state(downloads: dict) -> dict:
    """Saved access is amber until a scoped live test; file presence is never authentication."""
    states = [site_sessions.summary(slot, [downloads.get]) for slot in ('general', 'instagram')]
    saved = any(s['mode'] in ('protected', 'unavailable') or s['status'].startswith('Legacy file mode') for s in states)
    return {'lamp': 'a' if saved else 'off', 'detail': '; '.join(s['slot'] + ': ' + s['status'] for s in states)}


@router.get('/api/settings/cookies-state')
def get_cookies_state(request: Request):
    db = reader(request.app.state.db_path)
    return cookies_state({k: db.get_setting(k, '') for k in (*DOWNLOAD_KEYS, 'session_mode_general', 'session_mode_instagram')})


@router.get('/api/settings/site-sessions')
def get_site_sessions(request: Request):
    db = reader(request.app.state.db_path)
    return {'supported': site_sessions.supported(),
            'sessions': [site_sessions.summary(slot, [db.get_setting]) for slot in site_sessions.SLOTS]}


@router.post('/api/settings/site-sessions/import')
async def import_site_session(request: Request, slot: str = 'general', site: str = '', save: bool = False, digest: str = ''):
    if slot not in ('general', 'instagram') or slot == 'instagram' and site != 'instagram':
        raise HTTPException(400, 'Choose the general or Instagram cookie slot and a matching site.')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > site_sessions.MAX_BYTES:
            raise HTTPException(413, 'Cookie files must be no larger than 1 MiB.')
        raw.extend(chunk)
    try:
        if request.headers.get('content-type', '').startswith('application/json'):
            body = json.loads(raw)
            path = Path(body['path'])
            with path.open('rb') as f:
                raw = f.read(site_sessions.MAX_BYTES + 1)
        normalized, info = site_sessions.parse_cookies(bytes(raw), site)
        if save:
            if info['digest'] != digest:
                raise ValueError('The file changed. Review its domains again before saving.')
            await run_in_threadpool(site_sessions.save, slot, normalized)
            request.app.state.hub.publish('settings_changed', {'cookies': {'lamp': 'a', 'detail': 'Saved; not tested'}})
        return {**info, 'status': 'Saved; not tested' if save else 'Review domains before saving'}
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, 'Invalid file: check the Netscape header, seven-column records, selected site and review digest. The previous saved session is kept.') from None
    except (OSError, RuntimeError):
        raise HTTPException(400, 'Could not save protected cookies on this PC. Check Windows storage permissions. Protected storage is unavailable on other platforms. The previous saved session is kept.') from None


@router.post('/api/settings/site-sessions/forget')
async def forget_site_session(request: Request, body: dict = Body(...)):
    import asyncio
    slot = body.get('slot')
    if slot not in site_sessions.SLOTS:
        raise HTTPException(400, 'Choose a saved session.')
    # Disabling comes first, so queued/new operations cannot resurrect legacy access.
    slots = [slot]
    if slot in ('general', 'instagram'):
        sites = ['instagram'] if slot == 'instagram' else ['facebook', 'reddit']
        slots += ['browser-' + s for s in sites]
    try:
        await run_in_threadpool(site_sessions.forget, slots)
        jobs = request.app.state.jobs
        if jobs.current and jobs.current.kind in ('thumb', 'download', 'analyze', 'scrape'):
            jobs.stop()
            thread = jobs._thread
            if thread:
                await run_in_threadpool(thread.join, 20)
            if jobs.current:
                raise HTTPException(409, 'Saved access is disabled. The active job is still cleaning up; wait and retry Forget.')
        for _ in range(200):
            if not site_sessions.busy():
                break
            await asyncio.sleep(.1)
        if site_sessions.busy():
            raise HTTPException(409, 'Saved access is disabled. A link test is still cleaning up; wait and retry Forget.')
        await run_in_threadpool(site_sessions.cleanup_stale)
        await request.app.state.writer.run(lambda db: [db.set_setting('session_mode_' + s, 'disabled') for s in slots])
        request.app.state.hub.publish('settings_changed', {'cookies': {'lamp': 'off', 'detail': 'Saved access forgotten; legacy fallback disabled'}})
        return get_site_sessions(request)
    except (OSError, RuntimeError):
        raise HTTPException(409, 'Could not finish session cleanup. Stop browser tools and retry Forget.') from None


@router.post('/api/settings/site-sessions/test')
def test_site_session(request: Request, body: dict = Body(...)):
    from urllib.parse import urlsplit
    url = body.get('url')
    if not isinstance(url, str) or len(url) > 4096:
        raise HTTPException(400, 'Choose one supported site link.')
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or not site_sessions.site_for(url):
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Use a single HTTPS Facebook, Instagram, Reddit or YouTube link.') from None
    executable = ytdlp.find_ytdlp()
    if not executable:
        raise HTTPException(409, ytdlp.NOT_FOUND)
    db = reader(request.app.state.db_path)
    snap = {k: db.get_setting(k, '') for k in (*DOWNLOAD_KEYS, 'session_mode_general', 'session_mode_instagram')}
    try:
        with site_sessions.cookies(url, [snap.get, ytdlp.registry_get]) as path:
            args = [executable, '--ignore-config', *ytdlp.runtime_args(), '--no-playlist', '--skip-download', '--simulate', '--no-warnings', '--dump-single-json']
            if path:
                args += ['--cookies', str(path)]
            proc = subprocess.Popen([*args, '--', url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=app_paths.NO_WINDOW)
            with ytdlp.monitor(proc, lambda: site_sessions.revoked(path), timeout=60):
                _stdout, stderr = proc.communicate()
                out = subprocess.CompletedProcess(args, proc.returncode, '', stderr)
            if out.returncode:
                raise ytdlp.DownloadError(ytdlp.failure((out.stderr or '').splitlines()))
        info = {'status': 'Last test succeeded for this link', 'code': '', 'action': ''}
    except ytdlp.DownloadError as exc:
        info = {'status': str(exc), 'code': exc.code, 'action': exc.action}
    except subprocess.TimeoutExpired:
        info = {'status': 'The test timed out. Check your connection and retry.', 'code': 'network', 'action': 'retry'}
    except (OSError, RuntimeError, ValueError):
        info = {'status': 'Cannot unlock on this PC. Re-import saved access or sign in again.', 'code': 'authentication', 'action': 'sessions'}
    return {**info, 'site': site_sessions.site_for(url), 'link': ytdlp.safe_url(url),
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}


@router.post('/api/settings/site-sessions/reuse')
def reuse_browser_session(request: Request, body: dict = Body(...)):
    try:
        result = site_sessions.reuse_browser(body.get('site'), body.get('save') is True, body.get('digest', ''))
        if body.get('save') is True:
            request.app.state.hub.publish('settings_changed', {'cookies': {'lamp': 'a', 'detail': 'Saved; not tested'}})
        return result
    except (OSError, RuntimeError, ValueError, TypeError):
        raise HTTPException(400, 'Cannot reuse this browser login. Remember a valid login first, then review its site cookies again.') from None


# ── Settings > Tools: ffmpeg, ffprobe and yt-dlp are not bundled; they come from PATH or the folder
# the user picked. The folder lives in <LOCAL>/tools.json (core/app_paths.py), not the DB: it must be on
# PATH at import, before any database is open.
TOOL_NAMES = ('ffmpeg', 'ffprobe', 'yt-dlp', 'deno')


def youtube_tools():
    """Probe the selected distribution with synthetic local metadata. No URL is fetched."""
    import tempfile
    import re
    result = {'deno': False, 'ejs': 'unknown', 'functional': False}
    deno = app_paths.find_tool('deno')
    try:
        if deno:
            out = subprocess.run([deno, '--version'], capture_output=True, text=True, timeout=10, creationflags=app_paths.NO_WINDOW)
            match = re.search(r'deno (\d+)\.(\d+)\.(\d+)', out.stdout)
            result['deno'] = bool(out.returncode == 0 and match and tuple(map(int, match.groups())) >= (2, 3, 0))
        executable = ytdlp.find_ytdlp()
        if executable:
            with tempfile.TemporaryDirectory(prefix='brainamon-tool-probe-') as folder:
                path = Path(folder) / 'probe.json'
                path.write_text(json.dumps({'id': 'local-probe', 'title': 'local-probe', 'extractor': 'generic',
                                           'url': 'https://example.invalid/probe.mp4', 'ext': 'mp4'}), encoding='utf-8')
                out = subprocess.run([executable, '--ignore-config', *ytdlp.runtime_args(), '--verbose', '--simulate', '--skip-download',
                                      '--no-check-formats', '--no-playlist', '--load-info-json', str(path)],
                                     capture_output=True, text=True, timeout=20, creationflags=app_paths.NO_WINDOW)
            result['functional'] = out.returncode == 0
            if '[debug] Optional libraries:' in out.stderr:
                result['ejs'] = 'detected' if re.search(r'yt[-_]dlp[-_]ejs[- ]', out.stderr) else 'not detected'
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


def tool_probe(name, path):
    """Local executable/version check; only Deno has a minimum version policy."""
    import re
    result = {'version': '', 'state': 'missing' if not path else 'failed'}
    if not path:
        return result
    try:
        out = subprocess.run([path, '-version' if name in ('ffmpeg', 'ffprobe') else '--version'],
                             capture_output=True, text=True, timeout=10, creationflags=app_paths.NO_WINDOW)
        pattern = r'(\d+\.\d+\.\d+)' if name == 'deno' else (r'version (\S+)' if name in ('ffmpeg', 'ffprobe') else r'(\d{4}\.\d{2}\.\d{2})')
        match = re.search(pattern, out.stdout or '')
        if out.returncode == 0 and match:
            result.update(version=match[1], state='ready')
            if name == 'deno' and tuple(map(int, match[1].split('.'))) < (2, 3, 0):
                result['state'] = 'older'
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


def tools_view() -> dict:
    """Where each tool resolves right now (None = not found) and the saved tools folder."""
    app_paths.merge_registry_path()        # something installed since the app started
    found = {'ffmpeg': app_paths.find_tool('ffmpeg'), 'ffprobe': app_paths.find_tool('ffprobe'), 'yt-dlp': ytdlp.find_ytdlp(), 'deno': app_paths.find_tool('deno')}
    youtube = youtube_tools()
    tools = [{'name': n, 'found': bool(found[n]), 'path': found[n] or '', **tool_probe(n, found[n])} for n in TOOL_NAMES]
    for tool in tools:
        if tool['name'] == 'yt-dlp' and tool['found'] and not youtube['functional']:
            tool['state'] = 'failed'
    return {'tools_dir': app_paths.tools_dir(), 'tool_folders': app_paths.tool_folders(), 'tools': tools,
            'all_found': all(found.values()), 'youtube': youtube}


@router.get('/api/settings/tools')
async def get_tools():
    # Executable probes must not occupy the bounded pool used by ordinary settings and file reads.
    return await asyncio.to_thread(tools_view)


@router.put('/api/settings/tools')
def put_tools(request: Request, data: dict = Body(...)):
    """{"tools_dir": folder}: save the folder and put it first on PATH now. '' clears it (PATH of this
    run is left as it is until the next start)."""
    if 'tool' in data:
        name, folder = data.get('tool'), data.get('folder')
        if name not in TOOL_NAMES or not isinstance(folder, str):
            raise HTTPException(400, 'Choose a known tool and its folder.')
        folder = folder.strip()
        if folder and (not Path(folder).is_absolute() or not Path(folder).is_dir() or not shutil.which(name, path=folder)):
            raise HTTPException(400, f'Choose the folder containing {name}.')
        app_paths.set_tool_folder(name, folder)
        request.app.state.hub.publish('settings_changed', {'tools': True})
        return tools_view()
    raw = data.get('tools_dir')
    if not isinstance(raw, str):
        raise HTTPException(400, 'tools_dir must be a folder path.')
    raw = raw.strip()
    if raw and not (Path(raw).is_absolute() and Path(raw).is_dir()):
        raise HTTPException(400, 'Pick an existing folder.')
    app_paths.set_tools_dir(raw)
    request.app.state.hub.publish('settings_changed', {'tools': True})
    return tools_view()


# Use yt-dlp's FFmpeg package so its dependencies do not install a second FFmpeg distribution.
_INSTALL_IDS = ('yt-dlp.yt-dlp', 'yt-dlp.FFmpeg', 'DenoLand.Deno')
INSTALL_COMMAND = '\n'.join(f'winget install --id {pid} -e --source winget --force' for pid in _INSTALL_IDS)
_install = {'state': 'idle', 'step': '', 'error': ''}      # idle | running | done | error
_install_lock = threading.Lock()


def _needed_tools(view):
    ready = {t['name']: t['state'] == 'ready' for t in view['tools']}
    youtube = view['youtube']
    return [pid for pid, works in zip(_INSTALL_IDS, (
        ready['yt-dlp'] and youtube['functional'] and youtube['ejs'] == 'detected',
        ready['ffmpeg'] and ready['ffprobe'], ready['deno'] and youtube['deno'],
    )) if not works]


def _winget_links() -> str:
    base = os.environ.get('LOCALAPPDATA', '')
    link = Path(base) / 'Microsoft' / 'WinGet' / 'Links' if base else None
    return str(link) if link and link.is_dir() else ''


def _run_install() -> None:
    try:
        _install['step'] = 'Checking video tools'
        view = tools_view()
        if not _needed_tools(view):
            _install.update(state='done', step='', error='')
            return
        winget = shutil.which('winget')
        if not winget:
            raise RuntimeError('winget was not found. Install Microsoft App Installer, then try again, or use the manual downloads in Advanced details.')
        for pid in _INSTALL_IDS:
            if pid not in _needed_tools(view):
                continue
            _install['step'] = pid
            r = subprocess.run([winget, 'install', '--id', pid, '-e', '--source', 'winget', '--force',
                                '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity'],
                               capture_output=True, text=True, timeout=900, creationflags=app_paths.NO_WINDOW)
            # WinGet can report "no applicable upgrade"; only the subsequent probes establish success.
            if (r.returncode & 0xffffffff) not in (0, 0x8a15002b):
                tail = (r.stdout or r.stderr or '').strip().splitlines()
                raise RuntimeError(f'Windows could not set up {pid}: {tail[-1] if tail else "exit " + str(r.returncode)}. Try the administrator terminal below.')
            app_paths.apply_tools_dir(_winget_links())
            _install['step'] = 'Checking installed tools'
            view = tools_view()
        if _needed_tools(view):
            raise RuntimeError('Setup finished, but some tools still need attention. Check Advanced details. If you selected a tool folder, update that copy or choose the newly installed copy; your folder choices were kept.')
        _install.update(state='done', step='', error='')
    except subprocess.TimeoutExpired:
        _install.update(state='error', step='', error='Setup took too long. Try the administrator terminal below, then Check and set up again.')
    except Exception as e:
        _install.update(state='error', step='', error=str(e))


@router.get('/api/settings/tools/install')
def get_tools_install():
    return {**_install, 'command': INSTALL_COMMAND, 'winget': bool(shutil.which('winget'))}


@router.post('/api/settings/tools/install')
def post_tools_install():
    """Check, install/repair, then verify on a thread; poll GET for progress."""
    if os.name != 'nt':
        raise HTTPException(400, 'The install button works on Windows only. Install FFmpeg and yt-dlp with your package manager.')
    with _install_lock:
        if _install['state'] == 'running':
            raise HTTPException(409, 'The install is already running.')
        _install.update(state='running', step='Checking video tools', error='')
    threading.Thread(target=_run_install, name='cm-tools-install', daemon=True).start()
    return get_tools_install()


@router.post('/api/settings/tools/install/terminal')
def tools_install_terminal():
    """Only an explicit recovery click opens a visible elevated terminal with fixed commands."""
    if os.name != 'nt':
        raise HTTPException(400, 'The administrator terminal is available on Windows only.')
    with _install_lock:
        if _install['state'] == 'running':
            raise HTTPException(409, 'Wait for automatic setup to finish first.')
        import ctypes
        from ctypes import wintypes
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
        shell_execute.restype = ctypes.c_void_p
        command = INSTALL_COMMAND.replace('\n', ' & ')
        terminal = str(Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe')
        result = shell_execute(None, 'runas', terminal, f'/d /k {command}', None, 1)
        if not result or result <= 32:
            raise HTTPException(409, 'The administrator terminal was not opened. Approve the Windows permission prompt, or copy the commands from Advanced details.')
    return {'opened': True}
