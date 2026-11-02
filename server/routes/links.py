"""POST /api/link/preview {"url"} -> {title, creator, desc, image, asked, url, found}: what a link's own
page says (library/linkinfo.py, the phone's rules), for the preview card in Add to Brainamon
(projects/link-preview/plans/04-preview-api.md). A read: nothing is saved, the DB is not opened; the
fetch runs in the thread pool."""
from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool

from knowledge import inbox
from library import linkinfo

router = APIRouter()


@router.post('/api/link/preview')
async def preview(data: dict = Body(...)):
    asked = str(data.get('url') or '').strip()
    url = inbox.link(asked)
    if not url:
        raise HTTPException(400, 'A web link is required.')
    info = await run_in_threadpool(linkinfo.read, url)
    if not info:
        return {**linkinfo.NONE, 'asked': asked, 'url': url, 'found': False}
    return {**info, 'image': linkinfo.absolute(url, info['image']), 'asked': asked, 'url': url, 'found': True}
