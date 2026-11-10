"""Import, Scrapers, Export, Video Tools (plan 12).

Imports run on the Writer (they write rows) and the new rows go to the automatic index pass.
The scraper watcher (scrape_watch.Watcher) polls the Downloads folder on its own thread and imports
each new scrape CSV through the Writer. Exports and Video Tools run as jobs (server/job_kinds.py).
The server opens no native dialog: paths come typed, picked by the desktop window (plan 13), or as
an uploaded body (browser tab).
"""
import asyncio
import os
import re
import webbrowser
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import PlainTextResponse

from core import app_console
from library import importers
from library import owner_vault
from library import scrape_watch
from library import ytdlp
from server.jobs import Busy, JobError
from server.store import reader

router = APIRouter()
IMPORT_EXTS = {'.csv', '.json'}
MAX_IMPORT = 200 * 1024 * 1024
MAX_VIDEO = 4 * 1024 * 1024 * 1024
SAFE_NAME = re.compile(r'[^A-Za-z0-9 ._\-()]+')


def _data(request: Request) -> Path:
    return request.app.state.data_dir


def _safe_name(name: str, exts) -> str:
    base = SAFE_NAME.sub('_', os.path.basename(name or '')).strip(' .') or 'upload'
    if Path(base).suffix.lower() not in exts:
        raise HTTPException(400, f'Pick a {" or ".join(sorted(exts))} file.')
    return base


def _free_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p, stem, k = folder / name, Path(name).stem, 2
    while p.exists():
        p = folder / f'{stem}-{k}{Path(name).suffix}'
        k += 1
    return p


def _start(request: Request, kind: str, opts: dict) -> dict:
    try:
        return request.app.state.jobs.start(kind, [], True, opts)
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


def run_import(app, path: Path, origin: str = '') -> dict:
    """Import one file on the Writer, then publish the change and queue the new rows for the
    index pass. From a worker thread or the threadpool, never the Writer itself."""
    counts = {'duplicates': 0, 'invalid': 0}
    added, skipped, ids = app.state.writer.call(lambda db: importers.import_file(db, path, counts=counts))
    hub = app.state.hub
    app_console.emit('log', f'Import {origin or path.name}: {added} new, {skipped} skipped')
    if ids:
        hub.publish('items_changed', {'ids': ids, 'added': True})
        app.state.jobs.reindex(ids)
    return {'added': added, 'skipped': skipped, 'ids': ids, 'file': path.name, **counts}


# ── Import ───────────────────────────────────────────────────────────────────
@router.get('/api/import/files')
def import_files(request: Request):
    """The scrape CSVs and JSON exports kept in data/scrapes/, newest first."""
    d = _data(request) / 'scrapes'
    files = [p for p in d.glob('*') if p.is_file() and p.suffix.lower() in IMPORT_EXTS] if d.is_dir() else []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{'name': p.name, 'size': p.stat().st_size, 'mtime': int(p.stat().st_mtime * 1000)} for p in files[:50]]


@router.post('/api/import')
async def import_(request: Request, name: str = ''):
    """{"path"} (a picked file), {"scrape": name} (a file of data/scrapes/), or the file itself as
    the raw body with ?name= (a browser tab), kept in data/scrapes/."""
    if name:
        raw = await request.body()
        if not raw:
            raise HTTPException(400, 'The file is empty.')
        if len(raw) > MAX_IMPORT:
            raise HTTPException(413, 'That file is too large to import.')
        path = _free_path(_data(request) / 'scrapes', _safe_name(name, IMPORT_EXTS))
        path.write_bytes(raw)
    else:
        body = await request.json()
        if body.get('scrape'):
            path = _data(request) / 'scrapes' / os.path.basename(str(body['scrape']))
        else:
            path = Path(str(body.get('path') or '').strip()).expanduser()
        if path.suffix.lower() not in IMPORT_EXTS:
            raise HTTPException(400, 'Pick a .csv or a .json file.')
        if not path.is_file():
            raise HTTPException(404, f'File not found: {path}')
    try:
        return await asyncio.to_thread(run_import, request.app, path)
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f'Import failed: {exc}')


# ── Scrapers ─────────────────────────────────────────────────────────────────
def _watch_dir(request: Request) -> Path:
    v = reader(request.app.state.db_path).get_setting('scrape_watch_dir', '')
    return Path(v) if v else scrape_watch.default_downloads_dir()


def _watch_state(request: Request) -> dict:
    w = getattr(request.app.state, 'scrape_watcher', None)
    return {'watching': bool(w and w.running), 'dir': str(w.folder if w and w.running else _watch_dir(request))}


@router.get('/api/scrapers')
def scrapers(request: Request):
    return {'platforms': [{'key': k, 'label': v[0], 'target': v[2]} for k, v in scrape_watch.PLATFORMS.items()],
            'playwright': [{'key': k, 'label': v[0]} for k, v in scrape_watch.PLAYWRIGHT.items()
                           if scrape_watch.playwright_script(k).exists()],
            **_watch_state(request)}


@router.get('/api/scrapers/{key}.js')
def scraper_script(key: str, stop_at: str = '', unsave: bool = False):
    if key not in scrape_watch.PLATFORMS:
        raise HTTPException(404, 'no such scraper')
    try:
        text = scrape_watch.script_for(key, unsave=unsave, stop_at=stop_at.strip())
    except OSError:
        raise HTTPException(404, f'Scraper not found: scrapers/{scrape_watch.PLATFORMS[key][1]}')
    return PlainTextResponse(text, media_type='text/javascript; charset=utf-8')


@router.post('/api/scrapers/{key}/open')
def scraper_open(key: str):
    """Open the scraper's target page in the default browser (an allow-list: PLATFORMS)."""
    if key not in scrape_watch.PLATFORMS:
        raise HTTPException(404, 'no such scraper')
    webbrowser.open(scrape_watch.PLATFORMS[key][2])
    return {'ok': True}


@router.post('/api/scrapers/watch')
def scraper_watch(request: Request, body: dict = Body(...)):
    app = request.app
    w = getattr(app.state, 'scrape_watcher', None)
    if not body.get('on'):
        if w:
            w.stop()
        app.state.scrape_watcher = None
        return _watch_state(request)
    if w and w.running:
        return _watch_state(request)
    folder = _watch_dir(request)
    if not folder.is_dir():
        raise HTTPException(400, f'The watch folder does not exist: {folder}. Change it in Settings > Downloads.')
    hub, backup = app.state.hub, _data(request) / 'scrapes'

    def on_csv(p: Path):
        say = lambda line, c='': hub.publish('scrape', {'line': line, 'c': c})   # noqa: E731
        say(f'New CSV: {p.name}', 'g')
        try:
            scrape_watch.backup(p, backup)
        except OSError as exc:
            say(f'Could not back up {p.name}: {exc}', 'r')
        try:
            r = run_import(app, p, p.name)
            say(f'{p.name}: imported {r["added"]} new, skipped {r["skipped"]}.', 'g')
            hub.publish('toast', {'text': f'Scraper imported {r["added"]} new item(s)', 'level': ''})
            if r['added']:
                app.state.notify('capture', 'Scraper imported', f'{r["added"]} new item(s) from {p.name}')
        except Exception as exc:                 # noqa: BLE001  (shown in the window, logged)
            say(f'Import failed for {p.name}: {exc}', 'r')
            app_console.emit('error', 'Scrape import failed', level='error', error=exc)

    app.state.scrape_watcher = scrape_watch.Watcher(folder, on_csv)
    app.state.scrape_watcher.start()
    return _watch_state(request)


@router.post('/api/scrapers/playwright')
def scraper_playwright(request: Request, body: dict = Body(...)):
    key = str(body.get('platform') or 'facebook')
    if key not in scrape_watch.PLAYWRIGHT:
        raise HTTPException(404, 'no such Playwright scraper')
    if key == 'threads' and body.get('unsave'):
        raise HTTPException(400, 'Unsave is not available for Threads. Turn it off before starting.')
    if body.get('unsave') and body.get('unsave_confirmed') is not True:
        raise HTTPException(400, 'Confirm that Unsave changes your account before starting.')
    scraper_watch(request, {'on': True})          # the CSV it writes is imported by the watcher
    return _start(request, 'scrape', {'stop_at': str(body.get('stop_at') or ''), 'unsave': bool(body.get('unsave')),
                                      'remember': body.get('remember') is True, 'unsave_confirmed': body.get('unsave_confirmed') is True, 'platform': key, 'username': str(body.get('username') or '')})


@router.post('/api/import/youtube-playlist')
def import_youtube_playlist(request: Request, body: dict = Body(...)):
    return _start(request, 'youtube_playlist', {'url': body.get('url')})


# ── Export ───────────────────────────────────────────────────────────────────
def _vault(request: Request) -> str:
    db = reader(request.app.state.db_path)
    return db.get_setting('obsidian_vault', '') or ytdlp.registry_get('obsidian_vault') \
        or str(_data(request) / 'Fredorama')


def _owner(request: Request) -> bool:
    return reader(request.app.state.db_path).get_setting('obsidian_mode', '') == 'owner'


@router.get('/api/export/defaults')
def export_defaults(request: Request):
    vault = _vault(request)
    home = Path.home()
    return {'home': str(home), 'csv_path': str(home / 'brainamon-items.csv'), 'vault': vault,
            'vault_ok': Path(vault).is_dir(), 'is_vault': (Path(vault) / '.obsidian').is_dir(), 'owner': _owner(request)}


@router.get('/api/export/obsidian/coverage')
def obsidian_coverage(request: Request):
    from core import ai_client
    db = reader(request.app.state.db_path)
    total = db.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    indexed = db.count_embeddings(ai_client.EMBEDDING_MODEL)
    return {'indexed': indexed, 'total': total, 'low': total > 0 and indexed < 0.8 * total}


@router.post('/api/export/csv')
def export_csv(request: Request, body: dict = Body(...)):
    return _start(request, 'export_csv', {'path': body.get('path')})


@router.post('/api/export/obsidian')
def export_obsidian(request: Request, body: dict = Body(...)):
    return _start(request, 'export_obsidian', {'vault': body.get('vault'), 'refresh_topics': bool(body.get('refresh_topics'))})


# ── See my knowledge graph: Obsidian opens on the exported vault ─────────────
def _obsidian_installed() -> bool:
    """Windows registers obsidian:// when Obsidian is installed; elsewhere assume it is."""
    if os.name != 'nt':
        return True
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'obsidian'))
        return True
    except OSError:
        return False


def _open_uri(uri: str) -> None:
    if os.name == 'nt':
        os.startfile(uri)                    # noqa: S606  (an obsidian:// link this app built)
    else:
        webbrowser.open(uri)


@router.post('/api/obsidian/graph')
def obsidian_graph(request: Request):
    """Open Obsidian on the vault: Brainamon/Knowledge Map.md for a Brainamon vault, the classic export's
    Content Manager/README.md otherwise. Obsidian has no link for the graph itself: the page says Ctrl+G.
    A folder Obsidian has never opened answers "Vault not found" to a path link, so for a vault missing
    from Obsidian's own list this only starts Obsidian (opened: false) and the page says what to do once."""
    vault = Path(_vault(request))
    if not (vault / '.obsidian').is_dir():
        raise HTTPException(400, f'No Obsidian vault at {vault} yet. Set one up in Settings > Obsidian, or run Export to Obsidian and open that folder as a vault in Obsidian once.')
    if not _obsidian_installed():
        raise HTTPException(400, 'Obsidian is not installed on this PC. Get it from obsidian.md, then open the vault in it once.')
    known = {os.path.normcase(os.path.normpath(v['path'])) for v in owner_vault.obsidian_vaults()}
    if os.path.normcase(os.path.normpath(str(vault))) not in known:
        _open_uri('obsidian://open')
        return {'ok': True, 'opened': False, 'vault': str(vault), 'uri': 'obsidian://open'}
    page = vault / 'Brainamon' / 'Knowledge Map.md' if _owner(request) else vault / 'Content Manager' / 'README.md'
    uri = 'obsidian://open?path=' + quote(str(page if page.is_file() else vault), safe='')
    _open_uri(uri)
    return {'ok': True, 'opened': True, 'vault': str(vault), 'uri': uri}


@router.post('/api/reveal')
def reveal(request: Request, body: dict = Body(...)):
    """Open a folder an export or Video Tools just wrote (only those) in the file manager."""
    p = str(body.get('path') or '')
    if p not in request.app.state.revealable:
        raise HTTPException(404, 'Nothing to open.')
    target = Path(p) if Path(p).is_dir() else Path(p).parent
    if os.name == 'nt':
        os.startfile(str(target))            # noqa: S606  (a folder this app just wrote)
    else:
        webbrowser.open(target.as_uri())
    return {'ok': True}


# ── Video Tools ──────────────────────────────────────────────────────────────
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}


@router.put('/api/video-tools/upload')
async def vt_upload(request: Request, name: str):
    """A browser tab sends the video itself; it is kept in data/video_tools/uploads/."""
    fname = _safe_name(name, VIDEO_EXTS)
    path = _free_path(_data(request) / 'video_tools' / 'uploads', fname)
    size = 0
    with open(path, 'wb') as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_VIDEO:
                f.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, 'That video is too large.')
            f.write(chunk)
    if not size:
        path.unlink(missing_ok=True)
        raise HTTPException(400, 'The file is empty.')
    return {'path': str(path), 'name': path.name}


@router.post('/api/video-tools/analyze')
def vt_analyze(request: Request, body: dict = Body(...)):
    return _start(request, 'video_tools', {'path': body.get('path'), 'opts': dict(body.get('opts') or {})})
