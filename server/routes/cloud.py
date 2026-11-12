"""Settings > Cloud: Upload to Google Drive (projects/mobile-app/PLAN.md Phase 3).

Everything here goes through app.state.sync (server/sync.py). With Upload to Google Drive off,
GET reads local state only, and the sizes come from files under data/. Explicit
pairing/cleanup actions can contact Drive, as can the separate license-control worker.

Pair phone (Phase 4): POST /api/cloud/pair answers the pairing link and its QR. The link opens the
phone page with everything after `#pair=` (a fragment: the browser never sends it anywhere):
base64url JSON {v: 2, k: mirror key, c: Google web client id, e: Google account, f: key fingerprint,
p: the Google Cloud project number of the PC's sign-in app,
t + tx: when AI keys are ticked, the one-time key and expiry of the sealed file in Drive that holds
them (library/mirror.py pair_drop; the link never carries an API key), d: Drive base URL only when
not Google's (development)}.
POST /api/cloud/unpair makes a new mirror key, which locks every paired phone out.
"""
import base64
import json
import re

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core import app_console, config, entitlements
from library import drive_client, mirror, recovery
from server.recovery import Busy
from server.store import reader
from server.sync import S_CANVASES, S_VIDEOS, read_options

S_PHONE_URL = 'cloud_phone_url'
GOOGLE_DRIVE = 'https://www.googleapis.com'

router = APIRouter()


def refuse(request: Request, exc: BaseException, status: int = 409, fallback: str = '', storage: str = '') -> JSONResponse:
    """The one answer for a Drive failure (I7): `detail` stays the sentence every client already shows, and the
    classified `code` and next `action` ride beside it."""
    c = request.app.state.sync.classified(exc, fallback=fallback, storage=storage)
    return JSONResponse(status_code=status, content={'detail': c['message'], **c})


def require_license():
    if not entitlements.feature_enabled('phone_sync'):
        raise HTTPException(403, 'license_required')


def expected_account(body):
    if 'expected_account' not in body:
        return None
    account = body['expected_account']
    if not isinstance(account, str) or not account.strip() or len(account) > 320:
        raise HTTPException(400, 'Invalid confirmation account.')
    return account.strip()


def _phone_url(request: Request, db=None) -> str:
    db = db or reader(request.app.state.db_path)
    return db.get_setting(S_PHONE_URL, '') or f'http://localhost:{request.app.state.port}/mobile.html'


def _view(request: Request) -> dict:
    sync = request.app.state.sync
    db = reader(request.app.state.db_path)
    o = read_options(db)
    return {**sync.status(), 'options': {'videos': o.videos, 'canvases': o.canvases},
            'phone_url': _phone_url(request, db), 'web_client': bool(config.google_web_client()),
            'phone_keys': sorted(config.phone_keys(config.PHONE_KEYS))}


@router.get('/api/cloud')
def cloud(request: Request):
    return _view(request)


@router.get('/api/cloud/sizes')
def sizes(request: Request):
    db = reader(request.app.state.db_path)
    rows = [{'id': r[0], 'favourite': bool(r[1])} for r in db.conn.execute('SELECT id, favourite FROM items')]
    return dict(mirror.estimate(request.app.state.data_dir, rows), items=len(rows),
                files=sum(name != mirror.MANIFEST for name in db.get_sync_state()))


@router.post('/api/cloud/connect')
def connect(request: Request):
    """Upload to Google Drive: sign in when needed (the browser opens), then upload."""
    try:
        request.app.state.sync.connect()
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/switch')
def switch(request: Request, body: dict = Body(default={})):
    """Change account: sign out (the mirror and the key stay), then sign in with the account chooser. With `delete_old`
    (true or false) it is the Switch account task: this PC backs up in the other account, and the old copy is deleted only
    when asked and only after the new backup is complete."""
    try:
        flag = body.get('delete_old')
        request.app.state.sync.switch(None if flag is None else bool(flag), expected_account=expected_account(body))
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/reset')
def reset(request: Request, body: dict = Body(default={})):
    """Reset backup: a new key and a new first backup; the old backup is deleted once the new one is complete."""
    try:
        request.app.state.sync.reset_backup(replace_existing=body.get('replace_existing') is True, expected_account=expected_account(body))
    except (recovery.RecoveryError, drive_client.DriveError) as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/reauth')
def reauth(request: Request):
    """Sign in again after Google stopped accepting this PC's sign-in: the browser opens for the same account, and the
    new sign-in is kept only if Google confirms that account (S1). Nothing is deleted or cleared."""
    try:
        request.app.state.sync.sign_in_again()
    except (recovery.RecoveryError, drive_client.DriveError) as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/stop')
def stop(request: Request):
    try:
        request.app.state.sync.turn_off()
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/publish')
def publish(request: Request):
    """Back up once, or Try again: with backup off a one-time task runs and backup stays as it was (D4)."""
    try:
        request.app.state.sync.publish_once()
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/pause')
async def pause(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid pause request.')
    if not isinstance(body, dict) or set(body) - {'source'} or 'source' in body and body['source'] != 'recovery':
        raise HTTPException(400, 'Invalid pause request.')
    try:
        token = await run_in_threadpool(request.app.state.sync.turn_off, body.get('source', 'user'))
    except drive_client.DriveError as e:
        return refuse(request, e)
    view = await run_in_threadpool(_view, request)
    return {**view, 'pause_token': token} if body.get('source') == 'recovery' else view


@router.post('/api/cloud/resume')
async def resume(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Invalid resume request.')
    if (not isinstance(body, dict) or set(body) - {'pause_token'} or
            'pause_token' in body and (not isinstance(body['pause_token'], str) or not re.fullmatch(r'[0-9a-f]{32}', body['pause_token']))):
        raise HTTPException(400, 'Invalid pause token.')
    try:
        await run_in_threadpool(request.app.state.sync.resume, body.get('pause_token'))
    except drive_client.DriveError as e:
        return refuse(request, e)
    return await run_in_threadpool(_view, request)


@router.post('/api/cloud/cancel-sign-in')
def cancel_sign_in(request: Request):
    """Cancel sign-in: stop waiting for the browser; Upload to Google Drive can start a new one."""
    request.app.state.sync.cancel_sign_in()
    return _view(request)


@router.post('/api/cloud/sign-out')
def sign_out(request: Request, body: dict = Body(default={})):
    try:
        request.app.state.sync.request_disconnect(delete_mirror=body.get('delete_mirror') is True, delete_existing=body.get('delete_existing') is True,
                                                  expected_account=expected_account(body))
    except (Busy, recovery.RecoveryError) as e:
        return refuse(request, e)
    except drive_client.DriveError as e:
        return refuse(request, e, fallback=f'Could not delete the mirror: {e}')
    return _view(request)


DEV_AI = ''        # set by server/dev_drive.py --fake-ai (development only)


@router.post('/api/cloud/pair')
def pair(request: Request, body: dict = Body(default={})):
    """The pairing link and QR for the phone. A POST (X-CM, server/guard.py): it carries the
    mirror key. Ticked AI keys go to Drive sealed with a one-time key (sync.send_keys); the link
    carries that key, never the API keys."""
    require_license()
    import segno
    sync = request.app.state.sync
    try:
        key = sync.mirror_key()
        public = sync.license_public_key()
    except (mirror.MirrorKeyError, drive_client.DriveError) as e:
        return refuse(request, e, fallback=str(e))
    want = [k for k in (body.get('keys') or []) if k in config.PHONE_KEYS]
    data = {'v': 2, 'k': key.text(), 'c': config.google_web_client(), 'e': sync.account(), 'f': key.fingerprint,
            'l': public}
    project = config.google_client()[0].split('-', 1)[0]      # an OAuth client id starts with its Cloud project's number
    if project.isdigit():
        data['p'] = project         # the phone compares it with its own sign-in app's: the hidden folder belongs to the project
    ai = config.phone_keys(want)
    base = drive_client.API.rsplit('/drive/v3', 1)[0]
    if base != GOOGLE_DRIVE:
        data['d'] = base
    if DEV_AI:                      # server/dev_drive.py --fake-ai: stand-in providers and keys
        data['x'] = {p: f'{DEV_AI}/{p}' for p in config.PHONE_KEYS}
        ai = {p: 'dev-fake' for p in want}
    if ai:
        try:
            data.update(sync.send_keys(ai))
        except drive_client.DriveError as e:
            return refuse(request, e, fallback=f'The AI keys could not be sent: {e}')
    require_license()
    sync._start_control()
    code = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).rstrip(b'=').decode()
    url = f'{_phone_url(request)}#pair={code}'
    qr = segno.make(url, error='l', micro=False)
    return {'url': url, 'code': code, 'svg': qr.svg_inline(scale=4, border=2, omitsize=True, dark='#18191c', light='#ffffff'),
            'fingerprint': key.fingerprint, 'keys': sorted(ai), 'expires': data.get('tx', 0), 'version': qr.version}


@router.post('/api/cloud/unpair')
def unpair(request: Request, body: dict = Body(default={})):
    """A new mirror key: every paired phone is locked out (the next upload replaces the mirror)."""
    try:
        password = body.get('recovery_passphrase', '')
        if not isinstance(password, str) or len(password) > 1024:
            raise recovery.RecoveryError('Invalid recovery passphrase.')
        new_password = body.get('new_passphrase', '')
        if not isinstance(new_password, str) or len(new_password) > 1024:
            raise recovery.RecoveryError('Invalid new recovery passphrase.')
        fp = request.app.state.sync.unpair(password, new_password, expected_account=expected_account(body))
    except (recovery.RecoveryError, Busy) as e:
        return refuse(request, e)
    except (OSError, drive_client.DriveError) as e:
        # a refusal, not a server fault: offline, an expired sign-in and a busy worker each say so (F8)
        return refuse(request, e, fallback=f'Could not write the new key: {e}')
    try:
        request.app.state.sync.ensure_running()
    except (OSError, RuntimeError, drive_client.DriveError) as e:
        # The removal is already saved; boot resumes it. Do not report its accepted key change as a refusal.
        app_console.emit('log', 'Drive mirror: saved phone removal could not start', level='warning', error=e)
        request.app.state.sync._set(state='error', error='The phone removal was saved. Restart Brainamon to continue removing the phones.')
    return {**_view(request), 'fingerprint': fp}


@router.post('/api/cloud/vault/connect')
def vault_connect(request: Request):
    """Sync my Obsidian vault: sign in when needed (the browser opens), then start the vault rounds."""
    require_license()
    try:
        request.app.state.sync.connect('vault')
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/vault/stop')
def vault_stop(request: Request):
    """Stop syncing the vault; the phone mirror goes on."""
    try:
        request.app.state.sync.turn_vault_off()
    except drive_client.DriveError as e:
        return refuse(request, e)
    return _view(request)


@router.post('/api/cloud/vault/now')
def vault_now(request: Request):
    require_license()
    sync = request.app.state.sync
    if not sync.vault_running:
        raise HTTPException(409, 'The vault sync is off.')
    sync.vault_now()
    return _view(request)


@router.post('/api/cloud/vault/confirm')
def vault_confirm(request: Request):
    """"Apply anyway" after the vault sync stopped at the deletion brake. A POST (X-CM, server/guard.py)."""
    require_license()
    request.app.state.sync.confirm_vault()
    return _view(request)


@router.post('/api/cloud/vault/drop')
async def vault_drop(request: Request, body: dict = Body(...)):
    """Drop a phone from vault sync (spec 1b decision 5): its file list leaves Drive and the next round forgets
    its base and remembered membership. The phone retains its local base and can sync again. A POST (X-CM, server/guard.py)."""
    require_license()
    device = str(body.get('device') or '').strip()
    if not device or device == 'pc':
        raise HTTPException(400, 'Name the phone to drop.')
    sync = request.app.state.sync
    try:
        n = await run_in_threadpool(sync.drop_device, device)
    except (drive_client.DriveError, mirror.MirrorKeyError, OSError) as e:
        return refuse(request, e, fallback=str(e))
    if sync.vault_running:
        sync.vault_now()
    return {**_view(request), 'dropped': n}


@router.put('/api/cloud/options')
async def options(request: Request, body: dict = Body(...)):
    if body.get('vault'):
        require_license()
    videos = body.get('videos')
    canvases = body.get('canvases')
    phone_url = body.get('phone_url')
    vault = body.get('vault')
    if videos is not None and videos not in mirror.VIDEO_MODES:
        raise HTTPException(400, 'Videos: off, fav or all.')
    if phone_url is not None and phone_url and not str(phone_url).startswith(('https://', 'http://localhost', 'http://127.0.0.1')):
        raise HTTPException(400, 'The phone page needs an https:// address (or localhost while developing).')

    def put(db):
        if videos is not None:
            db.set_setting(S_VIDEOS, videos)
        if canvases is not None:
            db.set_setting(S_CANVASES, 'on' if canvases else 'off')
        if phone_url is not None:
            db.set_setting(S_PHONE_URL, str(phone_url).strip())
    sync = request.app.state.sync
    if vault is not None:
        sync._set(vault_devices=None)
    if vault:
        def enable():
            # Turning vault sync on must not race reconnect (server/recovery.py gate).
            with sync.recovery.gate():
                extra = {}
                if videos is not None:
                    extra[S_VIDEOS] = videos
                if canvases is not None:
                    extra[S_CANVASES] = 'on' if canvases else 'off'
                if phone_url is not None:
                    extra[S_PHONE_URL] = str(phone_url).strip()
                signed_in = sync.signed_in()
                sync.turn_vault_on(start=signed_in, extra_settings=extra)
                if signed_in:
                    sync.vault_now()
        try:
            await run_in_threadpool(enable)
        except drive_client.DriveError as e:
            return refuse(request, e)
        sync.poke()
        return _view(request)
    await request.app.state.writer.run(put)
    sync.poke()
    if vault is not None and not vault:
        try:
            await run_in_threadpool(sync.turn_vault_off)
        except drive_client.DriveError as e:
            return refuse(request, e)
        await run_in_threadpool(sync.reset_vault_history)
    return _view(request)
