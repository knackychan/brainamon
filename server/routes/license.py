"""Explicit legacy receipt exchange/storage; feature access does not depend on a receipt."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import license, license_activation

router = APIRouter()


class Activation(BaseModel):
    key: str = Field(max_length=license.MAX_KEY_LENGTH, strict=True)


@router.get('/api/license')
def get_license():
    return license.load().view()


@router.put('/api/license')
def activate(request: Request, body: Activation):
    key = body.key
    if license_activation.is_gumroad_key(key):
        try:
            key = license_activation.exchange(key)          # network, outside the license lock
        except license_activation.ActivationError as e:
            raise HTTPException(e.status, str(e))
    try:
        with request.app.state.sync.license_lock:
            result = license.save(key).view()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(500, 'Could not save the license. Check access to the app settings folder and retry.')
    request.app.state.sync.license_changed()
    return result


@router.delete('/api/license')
def remove(request: Request):
    try:
        with request.app.state.sync.license_lock:
            license.remove()
    except OSError:
        raise HTTPException(500, 'Could not remove the license. Check access to the app settings folder and retry.')
    request.app.state.sync.license_changed()
    return license.load().view()
