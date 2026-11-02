"""The Knowledge workspace: find sources, saved notes, topics I follow, connections.

Reads go through store.reader; every write (note files, topics, the connections settings) runs on
the Writer and note writes are followed by db.reindex_notes() and an SSE notes_changed. The note and
source logic is knowledge.py and connections.py, shared with the Qt Knowledge tab. Synthesize,
Augment, a topic refresh and Accept are `note` jobs; a scan is a `connections` job (plan 07 / 08).
"""
import json
import os
import sqlite3
import subprocess
import time
import webbrowser

from fastapi import APIRouter, Body, HTTPException, Request

from core import ai_client
from core import ai_defaults
from knowledge import connections
from knowledge import knowledge
from server.jobs import Busy, JobError
from server.library import compact
from server.routes.library import embedded
from server.routes.smart import embed_index
from server.store import reader

router = APIRouter()


def _rd(request: Request):
    return reader(request.app.state.db_path)


def _notes_dir(request: Request):
    return request.app.state.data_dir / 'notes'


def _start(request: Request, kind: str, ids: list, opts: dict):
    try:
        return request.app.state.jobs.start(kind, ids, True, opts)
    except Busy as exc:
        raise HTTPException(409, str(exc))
    except JobError as exc:
        raise HTTPException(400, str(exc))


def _changed(request: Request, file: str = '') -> None:
    request.app.state.hub.publish('notes_changed', {'file': file})


# ── find sources ─────────────────────────────────────────────────────────────
@router.post('/api/knowledge/sources')
def sources(request: Request, body: dict = Body(...)):
    topic = str(body.get('topic') or '').strip()
    if not topic:
        raise HTTPException(400, 'Enter a topic to search.')
    limit = int(body.get('limit') or 100000)
    db = _rd(request)
    index = vec = None
    if body.get('smart', True):
        key, base = ai_defaults.embed_credentials(db)
        if key:
            idx = embed_index(request.app, db)
            if len(idx):
                try:
                    vec = ai_client.embed_texts([topic], api_key=key, base_url=base)[0]
                    index = idx
                except Exception:
                    vec = None
    rows, mode = knowledge.search_sources(db, topic, limit, index, vec)
    emb = embedded(db)
    notes = [{'file': n['filename'], 'topic': n['topic']} for n in db.search_notes(topic)]
    return {'items': [compact(r, emb) for r in rows], 'mode': mode, 'notes': notes}


@router.get('/api/knowledge/category/{name}')
def category(name: str, request: Request):
    db = _rd(request)
    emb = embedded(db)
    return {'items': [compact(r, emb) for r in db.search_items(category=name, sort='new')]}


# ── saved notes ──────────────────────────────────────────────────────────────
def _topic_note_files(db) -> set:
    return {t['note_path'] for t in db.list_topics() if t.get('note_path')}


def _row_json(r: dict) -> dict:
    return {'file': r['file'], 'title': r['title'], 'kind': r['kind'], 'sources': r['sources'],
            'created': r['date_created'].isoformat(timespec='seconds'),
            'updated': r['date_updated'].isoformat(timespec='seconds'), 'snippet': r['snippet']}


@router.get('/api/notes')
def notes(request: Request, sort: str = 'updated'):
    rows = knowledge.note_rows(_notes_dir(request), _topic_note_files(_rd(request)))
    return [_row_json(r) for r in knowledge.sort_note_rows(rows, sort if sort in knowledge.NOTE_SORTS else 'updated')]


def _note_path(request: Request, file: str):
    p = knowledge.safe_note_path(_notes_dir(request), file)
    if p is None:
        raise HTTPException(404, 'no such note')
    return p


@router.get('/api/notes/{file}')
def get_note(file: str, request: Request):
    p = _note_path(request, file)
    meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    row = knowledge.note_row(p, _topic_note_files(_rd(request)))
    return {'file': p.name, 'meta': meta, 'body': body, 'row': _row_json(row)}


def _reveal_file(path) -> None:
    """Show a note in the file manager, selected in its folder."""
    if os.name == 'nt':
        # explorer exits 1 even on success. A list arg gets quoted around the whole `/select,<path>` when the
        # path has spaces ("MY DOCS"), which explorer cannot parse (opens My Documents), so build the line by hand.
        subprocess.Popen(f'explorer /select,"{path.resolve()}"')
    else:
        webbrowser.open(path.parent.as_uri())


@router.post('/api/notes/{file}/reveal')
def reveal_note(file: str, request: Request):
    _reveal_file(_note_path(request, file))
    return {'ok': True}


@router.put('/api/notes/{file}')
async def save_note(file: str, request: Request, body: dict = Body(...)):
    p = _note_path(request, file)
    md = str(body.get('body') or '')

    def write(db):
        meta, _old = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        meta.update({k: str(v) for k, v in (body.get('meta') or {}).items() if k in ('topic', 'kind', 'category')})
        meta['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        knowledge.write_front(p, meta, md)
        db.reindex_notes()
        return _row_json(knowledge.note_row(p, _topic_note_files(db)))
    row = await request.app.state.writer.run(write)
    _changed(request, p.name)
    return row


@router.post('/api/notes/{file}/rename')
async def rename_note(file: str, request: Request, body: dict = Body(...)):
    p = _note_path(request, file)
    title = str(body.get('title') or '').strip()
    if not title:
        raise HTTPException(400, 'Enter a name.')

    def write(db):
        new = knowledge.rename_note(p.parent, p, title)
        for t in db.list_topics():                 # a digest keeps pointing at its note
            if t.get('note_path') == p.name and new.name != p.name:
                db.update_topic(t['id'], note_path=new.name)
        db.reindex_notes()
        return _row_json(knowledge.note_row(new, _topic_note_files(db)))
    row = await request.app.state.writer.run(write)
    _changed(request, row['file'])
    return row


@router.delete('/api/notes/{file}')
async def delete_note(file: str, request: Request):
    p = _note_path(request, file)

    def write(db):
        knowledge.delete_note(p)
        db.reindex_notes()
    await request.app.state.writer.run(write)
    _changed(request, p.name)
    return {'ok': True}


# ── topics I follow ──────────────────────────────────────────────────────────
def _topic_ranking(request: Request, db, topics: list, retry: int = None) -> tuple:
    """(index, {topic id: query vector}, {topic id: why keyword-only}) for topic candidates.

    Hybrid (knowledge.topic_candidates) needs an embeddings key and stored vectors; otherwise
    every topic is keyword-only and says why. Query vectors are cached per (base_url, query) on
    app.state; a failed embed is remembered there and retried only by a refresh of that topic
    (`retry`), so listing topics does not re-hit a failing endpoint on every call."""
    key, base = ai_defaults.embed_credentials(db)
    if not key:
        return None, {}, {t['id']: 'no OpenAI key for embeddings' for t in topics}
    idx = embed_index(request.app, db)
    if not len(idx):
        return None, {}, {t['id']: 'search index empty, run Index for search' for t in topics}
    st = request.app.state
    if getattr(st, 'topic_vecs', None) is None:
        st.topic_vecs, st.topic_embed_errors = {}, {}
    vecs, why = {}, {}
    for t in topics:
        k = (base, t['query'].strip())
        if k not in st.topic_vecs and (k not in st.topic_embed_errors or t['id'] == retry):
            try:
                st.topic_vecs[k] = ai_client.embed_texts([k[1]], api_key=key, base_url=base)[0]
                st.topic_embed_errors.pop(k, None)
            except Exception as exc:
                st.topic_embed_errors[k] = str(exc)[:200]
        if k in st.topic_vecs:
            vecs[t['id']] = st.topic_vecs[k]
        else:
            why[t['id']] = f"embedding failed: {st.topic_embed_errors.get(k, '')}"
    return idx, vecs, why


def _topic_new_ids(db, nd, t: dict, ranking: tuple) -> list:
    idx, vecs, _why = ranking
    vec = vecs.get(t['id'])
    return knowledge.topic_new_ids(db, nd, t, index=idx if vec is not None else None, query_vec=vec)


def _topics(request: Request) -> list:
    db, nd = _rd(request), _notes_dir(request)
    topics = db.list_topics()
    ranking = _topic_ranking(request, db, topics)
    out = []
    for t in topics:
        try:
            n = len(_topic_new_ids(db, nd, t, ranking))
        except Exception:
            n = 0
        why = ranking[2].get(t['id'], '')
        out.append({'id': t['id'], 'name': t['name'], 'query': t['query'],
                    'note_path': t.get('note_path') if knowledge.topic_note_path(nd, t) else None,
                    'last_run': t.get('last_run'), 'new': n,
                    'mode': 'fts' if why else 'hybrid', 'mode_reason': why})
    return out


@router.get('/api/topics')
def topics(request: Request):
    return _topics(request)


@router.post('/api/topics')
async def add_topic(request: Request, body: dict = Body(...)):
    name = str(body.get('name') or '').strip()
    query = str(body.get('query') or '').strip() or name
    if not name:
        raise HTTPException(400, 'Enter a topic.')
    try:
        await request.app.state.writer.run(lambda db: db.add_topic(name, query))
    except sqlite3.IntegrityError:
        raise HTTPException(409, f'A topic named "{name}" already exists.')
    return _topics(request)


@router.delete('/api/topics/{topic_id}')
async def delete_topic(topic_id: int, request: Request):
    await request.app.state.writer.run(lambda db: db.delete_topic(topic_id))
    return _topics(request)


@router.post('/api/topics/{topic_id}/refresh')
def refresh_topic(topic_id: int, request: Request):
    db = _rd(request)
    t = next((x for x in db.list_topics() if x['id'] == topic_id), None)
    if t is None:
        raise HTTPException(404, 'no such topic')
    ids = _topic_new_ids(db, _notes_dir(request), t, _topic_ranking(request, db, [t], retry=topic_id))
    if not ids:
        raise HTTPException(400, f'"{t["name"]}" is up to date: no new items.')
    note = t.get('note_path') if knowledge.topic_note_path(_notes_dir(request), t) else ''
    return _start(request, 'note', ids, {'topic': t['name'], 'mode': 'augment', 'merge': 'integrate',
                                         'note': note or '', 'topic_id': topic_id})


# ── connections ──────────────────────────────────────────────────────────────
def _cards(db) -> list:
    try:
        return json.loads(db.get_setting(connections.CARDS_KEY, '') or '[]')
    except ValueError:
        return []


def _cx_state(request: Request) -> dict:
    db = _rd(request)
    return {'cards': _cards(db), 'last_scan': int(db.get_setting(connections.LAST_SCAN_KEY, '0') or '0')}


@router.get('/api/connections')
def get_connections(request: Request):
    return _cx_state(request)


@router.post('/api/connections/scan')
def scan(request: Request):
    return _start(request, 'connections', [0], {})


@router.post('/api/connections/reset')
def reset(request: Request):
    """Unstick: stop a running scan or card synthesis (saved notes are untouched)."""
    jm = request.app.state.jobs
    if jm.current is not None and (jm.current.kind == 'connections' or (jm.current.opts or {}).get('card_key')):
        jm.stop()
    return _cx_state(request)


def _card(request: Request, key: str) -> dict:
    c = next((c for c in _cards(_rd(request)) if c.get('key') == key), None)
    if c is None:
        raise HTTPException(404, 'no such card')
    return c


@router.post('/api/connections/{key}/accept')
def accept(key: str, request: Request):
    c = _card(request, key)
    return _start(request, 'note', c['item_ids'], {'topic': connections.card_topic(c), 'card_key': key,
                                                   'feature': 'connections'})


@router.post('/api/connections/{key}/dismiss')
async def dismiss(key: str, request: Request):
    def write(db):
        try:
            dismissed = connections.prune_dismissed(json.loads(db.get_setting(connections.DISMISSED_KEY, '') or '[]'))
        except ValueError:
            dismissed = []
        dismissed.append({'key': key, 'ts': int(time.time() * 1000)})
        db.set_setting(connections.DISMISSED_KEY, json.dumps(dismissed))
        db.set_setting(connections.CARDS_KEY, json.dumps([c for c in _cards(db) if c.get('key') != key]))
    await request.app.state.writer.run(write)
    return _cx_state(request)


@router.post('/api/connections/{key}/sources')
async def card_sources(key: str, request: Request, body: dict = Body(...)):
    ids = [int(i) for i in body.get('ids') or []]
    if not ids:
        raise HTTPException(400, 'Keep at least one source.')
    _card(request, key)

    def write(db):
        items = {it['id']: it for it in db.get_items_by_ids(ids)}
        cards = _cards(db)
        for c in cards:
            if c.get('key') == key:
                c['item_ids'] = [i for i in ids if i in items]
                c['items'] = [{'id': i, 'title': connections.item_title(items[i])} for i in c['item_ids'][:6]]
        db.set_setting(connections.CARDS_KEY, json.dumps(cards))
    await request.app.state.writer.run(write)
    return _cx_state(request)
