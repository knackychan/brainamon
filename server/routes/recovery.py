"""Local-authenticated recovery endpoints. Secrets are POST bodies, never URLs/status."""
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from library import drive_client, mirror, recovery as R
from server.recovery import Busy
from server.routes.cloud import refuse

router = APIRouter()


@router.get('/api/cloud/recovery')
def status(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return request.app.state.sync.recovery.status()
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(409, 'Recovery settings cannot be unlocked on this PC. Keep the files and restore with your kit or passphrase.') from None


@router.post('/api/cloud/recovery/{action}')
async def action(request: Request, response: Response, action: str):
    response.headers['Cache-Control'] = 'no-store'
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 65536:
            raise HTTPException(413, 'Recovery request is too large.')
    try:
        body = R.parse(bytes(raw) or b'{}')
        # The request may contain a kit as a JSON string; its own parser also enforces 32 KiB.
        sync = request.app.state.sync
        service = sync.recovery
        if action == 'cancel':
            service.cancel.set()
            return service.status()
        sync.require_open()
        def text(key):
            value = body.get(key, '')
            if not isinstance(value, str):
                raise R.RecoveryError('Recovery fields must contain text.')
            return value
        def run():
            if action == 'sign-in':
                sync.connect('recovery')
                from server.routes.cloud import _view
                return _view(request)
            if action == 'preflight':
                return service.preflight()
            if action == 'reconcile':
                return service.reconcile()
            if action == 'discover':
                return {'libraries': service.discover()}
            if action == 'enroll':
                return service.enroll(text('password'), text('confirmation'))
            if action == 'kit':
                return service.export_kit()
            if action == 'save-kit':
                return service.save_kit(text('path'))
            if action == 'verify':
                return service.verify_kit(text('material'))
            if action == 'preview':
                return service.preview(material=text('material'), file_id=text('file_id'), password=text('password'))
            if action == 'restore':
                return service.start_restore(text('destination'))
            if action == 'activate':
                if body.get('confirm') is not True:
                    raise R.RecoveryError('Confirm switching to the restored library.')
                return service.activate()
            if action == 'take-over':
                if body.get('confirm') is not True:
                    raise R.RecoveryError('Confirm this PC will be the only uploader. Update and stop all other PCs first.')
                return service.take_over(text('password'), text('confirmation'))
            if action == 'reconnect':
                # No phone-sync license: keeping a library and backing it up stay licence-free.
                if body.get('confirm') is not True:
                    raise R.RecoveryError('Confirm reconnecting this library. Stop and update every other PC first.')
                return service.reconnect(text('password'), text('confirmation'))
            # Update this folder (S9): the same key, the newer library another PC uploaded; Drive is only read until the claim
            if action == 'update-preview':
                return service.update_preview()
            if action == 'update-start':
                if body.get('confirm') is not True:
                    raise R.RecoveryError('Confirm updating this folder.')
                return service.start_update()
            if action == 'update-cancel':
                return service.cancel_update()
            if action == 'update-activate':
                return service.update_activate()
            raise HTTPException(404, 'Unknown recovery action.')
        return await run_in_threadpool(run)
    except (R.RecoveryError, Busy) as e:
        return refuse(request, e)
    except drive_client.DriveError as e:
        if str(e) == 'license_required':
            raise HTTPException(403, 'license_required') from None
        # a code, a sentence from the fixed table and the next action (I7); a raw Drive error keeps the old sentence
        return refuse(request, e, fallback='Google Drive work could not finish. Reconnect or retry; existing data was preserved.')
    except (OSError, RuntimeError, mirror.MirrorKeyError) as e:
        return refuse(request, e, storage='Recovery could not access protected local storage. Keep the current files and retry with your recovery material.')
