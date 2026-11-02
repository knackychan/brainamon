"""Collections (db categories): create, rename / recolour, delete. Names are upper-case, as the Qt
CategoryDialog saves them. INTERESTING is the default collection for new items: it can be
recoloured, not renamed or deleted. Every write goes through the Writer."""
import re

from fastapi import APIRouter, Body, HTTPException, Request

from server.routes.library import categories as list_categories
from server.store import reader

router = APIRouter()

DEFAULT = 'INTERESTING'
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _clean(data: dict) -> tuple[str, str, bool]:
    name = str(data.get('name') or '').strip().upper()
    color = str(data.get('color') or '').strip()
    if not name:
        raise HTTPException(400, 'Enter a name.')
    if not HEX.match(color):
        raise HTTPException(400, 'Pick a colour.')
    return name, color, bool(data.get('hidden'))


def _names(request: Request) -> set:
    return {c['name'] for c in reader(request.app.state.db_path).get_categories()}


@router.post('/api/categories')
async def create(request: Request, data: dict = Body(...)):
    name, color, hidden = _clean(data)
    if name in _names(request):
        raise HTTPException(409, f'{name} already exists.')
    await request.app.state.writer.run(lambda db: db.add_category(name, color, hidden))
    return list_categories(request)


@router.patch('/api/categories/{old}')
async def update(old: str, request: Request, data: dict = Body(...)):
    name, color, hidden = _clean(data)
    names = _names(request)
    if old not in names:
        raise HTTPException(404, 'no such collection')
    if old == DEFAULT and name != DEFAULT:
        raise HTTPException(400, 'Interesting is the default collection: it can be recoloured, not renamed.')
    if name != old and name in names:
        raise HTTPException(409, f'{name} already exists.')
    await request.app.state.writer.run(lambda db: db.update_category(old, name, color, hidden))
    if name != old:
        request.app.state.hub.publish('items_changed', {'ids': _ids_in(request, name)})
    return list_categories(request)


@router.delete('/api/categories/{name}')
async def delete(name: str, request: Request):
    if name == DEFAULT:
        raise HTTPException(400, 'Interesting is the default collection: it cannot be deleted.')
    if name not in _names(request):
        raise HTTPException(404, 'no such collection')
    ids = _ids_in(request, name)
    await request.app.state.writer.run(lambda db: db.delete_category(name, DEFAULT))
    if ids:
        request.app.state.hub.publish('items_changed', {'ids': ids})
    return list_categories(request)


def _ids_in(request: Request, cat: str) -> list:
    return [r['id'] for r in reader(request.app.state.db_path).search_items(category=cat)]
