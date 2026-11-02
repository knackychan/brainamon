"""Item files, read-only: /files/items/{id}/{path} serves only frames/*.jpg, report.md,
transcript.txt and thumb.jpg inside data/items/<id>/. Anything else is 404."""
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()

ALLOWED = re.compile(r'^(frames/[A-Za-z0-9_.\-]+\.jpg|report\.md|transcript\.txt|thumb\.jpg)$')
TYPES = {'.jpg': 'image/jpeg', '.md': 'text/markdown; charset=utf-8', '.txt': 'text/plain; charset=utf-8'}


@router.get('/files/items/{item_id}/{path:path}')
def item_file(item_id: int, path: str, request: Request):
    if not ALLOWED.match(path) or '..' in path:
        raise HTTPException(404, 'not found')
    base = (request.app.state.data_dir / 'items' / str(item_id)).resolve()
    p = (base / path).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404, 'not found')
    return FileResponse(p, media_type=TYPES[p.suffix.lower()], headers={'Cache-Control': 'no-cache'})
