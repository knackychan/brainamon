"""Smart search (the Library SMART switch + Enter): hybrid ranking by meaning.

Same numbers as the Qt `_on_library_query_vec`: the query is embedded with the embeddings
provider from Settings, cosine top 150 from the in-memory `search.EmbeddingIndex`, fused with
`db.fts_ids(q, 150)` by Reciprocal Rank Fusion, 150 ids out. The index is built on first use,
held in `app.state.embed_index` and dropped when an Index job finishes (server/app.py) or after
IDLE_DROP_S unused (plan 10-footprint A2: -18 MB; the rebuild takes about 0.13 s).
"""
import asyncio
import threading
import time

from fastapi import APIRouter, Body, HTTPException, Request

from core import ai_client
from core import ai_defaults
from library import search
from server.store import reader

router = APIRouter()

LIMIT = 150
NEEDS_SETUP = ('Smart search needs an embeddings key (Settings) and an Index for search run '
               '(Process menu).')
_build_lock = threading.Lock()
IDLE_DROP_S = 600


def embed_index(app, db):
    """The cached EmbeddingIndex, built from `db` (a reader) on first use."""
    idx = getattr(app.state, 'embed_index', None)
    if idx is None:
        with _build_lock:
            idx = getattr(app.state, 'embed_index', None)
            if idx is None:
                idx = search.EmbeddingIndex.from_db(db, ai_client.EMBEDDING_MODEL)
                app.state.embed_index = idx
    app.state.embed_used = time.monotonic()
    return idx


def drop_index(app) -> None:
    app.state.embed_index = None


def drop_if_idle(app, now: float | None = None) -> bool:
    """Drop the index when it has not been used for IDLE_DROP_S. True when it was dropped."""
    if getattr(app.state, 'embed_index', None) is None:
        return False
    if (time.monotonic() if now is None else now) - getattr(app.state, 'embed_used', 0) < IDLE_DROP_S:
        return False
    drop_index(app)
    return True


async def drop_when_idle(app, every: float = 60) -> None:
    """Lifespan task on the server loop (no thread): checks once a minute."""
    while True:
        await asyncio.sleep(every)
        drop_if_idle(app)


@router.post('/api/smart')
def smart(request: Request, body: dict = Body(...)):
    q = str(body.get('q') or '').strip()
    if not q:
        raise HTTPException(400, 'Type something to search for first.')
    db = reader(request.app.state.db_path)
    key, base_url = ai_defaults.embed_credentials(db)
    idx = embed_index(request.app, db)
    if not key or len(idx) == 0:
        raise HTTPException(400, NEEDS_SETUP)
    try:
        vec = ai_client.embed_texts([q], api_key=key, base_url=base_url)[0]
    except Exception as exc:
        raise HTTPException(502, f'Smart search unavailable: {str(exc)[:200]}')
    ids = search.hybrid_rank(db.fts_ids(q, LIMIT), idx.topk(vec, LIMIT), limit=LIMIT)
    return {'ids': ids, 'mode': 'hybrid'}
