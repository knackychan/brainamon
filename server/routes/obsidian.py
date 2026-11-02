"""Settings > Obsidian (docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md, decisions 1, 2,
4, 8, 10): the owner vault's setup and actions, the knowledge map's numbers. Every vault write goes through
app.state.maps (server/map_service.py) under the vault lock, on the threadpool; settings through the Writer;
reads through store.reader. obsidian_vault + obsidian_mode name the vault Brainamon renders into, never the
user's notes vault (roadmap item 3 gets its own setting)."""
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import ai_client
from library import map_engine, owner_vault
from server import map_service
from server.store import reader

router = APIRouter()


def _view(request: Request) -> dict:
    from server.routes.io import _obsidian_installed
    db = reader(request.app.state.db_path)
    maps = request.app.state.maps
    data_dir = Path(request.app.state.data_dir)
    vault = db.get_setting('obsidian_vault', '') or ''
    mode = db.get_setting('obsidian_mode', '') or ''
    p = Path(vault) if vault else None
    default = owner_vault.default_location()
    # an earlier Brainamon vault (any library) at the default place: the first screen offers Reconnect
    earlier = mode != 'owner' and owner_vault.read_manifest(default) is not None
    cache = map_engine.load(map_engine.cache_path(data_dir))
    total = db.count_items()
    indexed = db.count_embeddings(ai_client.EMBEDDING_MODEL)
    return {
        'vault': vault, 'mode': mode,
        'exists': bool(p and p.is_dir()), 'is_vault': bool(p and (p / '.obsidian').is_dir()),
        'legacy': bool(p and mode != 'owner' and p.resolve() == (data_dir / 'Fredorama').resolve()),
        'default_location': str(default), 'earlier_vault': earlier,
        'pictures': db.get_setting('obsidian_pictures', '') == 'on',
        'first_open': db.get_setting('obsidian_first_open', '') or '',
        'vault_sync_on': db.get_setting('cloud_vault', '') == 'on',
        'installed': _obsidian_installed(),
        'map': {**map_engine.stats(cache),
                'model_changed': bool(cache['clusters']) and cache.get('model') != ai_client.EMBEDDING_MODEL,
                'coverage': {'indexed': indexed, 'total': total, 'low': total > 0 and indexed < 0.8 * total}},
        'status': maps.status(),
    }


def _fail(exc: Exception):
    if isinstance(exc, owner_vault.VaultError):
        text = str(exc)
        code = 409 if text == map_service.PHONES_UNCHECKED or text.startswith(map_service.PHONE_OLD) or 'Cancelled' in text else 400
        raise HTTPException(code, str(exc))
    raise exc


@router.get('/api/obsidian')
def obsidian(request: Request):
    return _view(request)


@router.get('/api/obsidian/vaults')
def vaults():
    """Obsidian's own vault list, read-only; [] when its file is missing or unreadable (the folder dialog stays)."""
    return {'vaults': owner_vault.obsidian_vaults()}


@router.put('/api/obsidian/vault')
async def set_vault(request: Request, body: dict = Body(...)):
    """Owner mode on a folder. create: Create a new vault (the folder and an empty .obsidian/ are made, the
    first-open step starts). Without create: a vault made in Obsidian or by Brainamon before (.obsidian/
    untouched). A folder with 1 to 5 other entries answers needs_confirm until confirm is sent (Use it
    anyway); another library's Brainamon vault answers needs_takeover (count = leftovers) until takeover is
    sent, with remove to delete the leftovers."""
    path = str(body.get('path') or '').strip()
    try:
        r = await run_in_threadpool(request.app.state.maps.set_owner_vault, path,
                                    bool(body.get('confirm')), bool(body.get('create')), bool(body.get('takeover')),
                                    bool(body.get('remove')))
    except map_service.NeedsConfirm as exc:
        return {'needs_confirm': True, 'count': exc.count, 'message': str(exc)}
    except map_service.NeedsTakeover as exc:
        return {'needs_takeover': True, 'count': exc.count, 'message': str(exc)}
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    request.app.state.hub.publish('settings_changed', {'obsidian': True})
    return {'ok': True, **r, **_view(request)}


@router.post('/api/obsidian/move')
async def move(request: Request, body: dict = Body(...)):
    """Move to a new vault (decision 10). The old vault is never deleted."""
    try:
        n = await run_in_threadpool(request.app.state.maps.move, str(body.get('path') or '').strip())
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    request.app.state.hub.publish('settings_changed', {'obsidian': True})
    return {'ok': True, 'copied': n, **_view(request)}


@router.post('/api/obsidian/cancel')
def cancel(request: Request):
    """The waiting user action (Move, Reset, Reclaim, Take over, setup) gives up on the vault lock."""
    request.app.state.maps.cancel.set()
    return {'ok': True}


@router.post('/api/obsidian/reset')
async def reset(request: Request, body: dict = Body(...)):
    try:
        await run_in_threadpool(request.app.state.maps.reset, str(body.get('path') or ''))
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    return {'ok': True, **_view(request)}


@router.post('/api/obsidian/reclaim')
async def reclaim(request: Request):
    try:
        n = await run_in_threadpool(request.app.state.maps.reclaim)
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    return {'ok': True, 'reclaimed': n, **_view(request)}


@router.post('/api/obsidian/takeover')
async def takeover(request: Request):
    try:
        await run_in_threadpool(request.app.state.maps.take_over)
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    return {'ok': True, **_view(request)}


@router.post('/api/obsidian/leftovers/remove')
async def remove_leftovers(request: Request):
    """Remove leftovers: pages an earlier library made, kept at take-over, deleted when still unchanged."""
    try:
        n = await run_in_threadpool(request.app.state.maps.remove_leftovers)
    except Exception as exc:                      # noqa: BLE001
        _fail(exc)
    return {'ok': True, 'removed': n, **_view(request)}


@router.put('/api/obsidian/options')
async def options(request: Request, body: dict = Body(...)):
    if 'pictures' in body:
        on = bool(body['pictures'])
        await request.app.state.writer.run(lambda db: db.set_setting('obsidian_pictures', 'on' if on else 'off'))
        request.app.state.maps.poke(now=True)
    return _view(request)


@router.post('/api/obsidian/first-open/done')
async def first_open_done(request: Request):
    await request.app.state.writer.run(lambda db: db.set_setting('obsidian_first_open', ''))
    return _view(request)
