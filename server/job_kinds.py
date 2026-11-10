"""Job kinds: what each background job loads (on the Writer), does (on the job thread) and
writes back (on the Writer). Importing this module registers them with server.jobs.

Plan 03: describe. Plan 07: thumb, categorize, analyze, index, note, download. Plan 08: note
augment / digest / connections-accept options, connections.

Job threads never open SQLite: every value a run function needs (keys, cookies settings, the
categories, the stored hashes) is resolved in `prepare` on the Writer and kept in `job.ctx`.
"""
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from core import ai_client
from core import ai_defaults
from core import app_console, site_sessions
from core import app_paths
from core import config
from core import note_format
from knowledge import connections
from knowledge import knowledge
from knowledge import my_notes
from library import search
from knowledge import synth
from knowledge import tasks
from library import linkinfo
from library import video_analyzer
from library import ytdlp
from server.jobs import JobError, JobKind, Skipped, Stopped, register

PROVIDER_NAMES = {'anthropic': 'Anthropic', 'openai': 'OpenAI', 'freellmapi': 'FreeLLMAPI',
                  'local_openai': 'local model', 'claude': 'Anthropic'}


def _key_ctx(job, provider: str, model: str) -> None:
    job.ctx.update(
        provider=provider, model=model, key=bool(config.key_for_provider(provider)),
        key_msg=f'Open Settings > API keys to enter your {PROVIDER_NAMES.get(provider, provider)} API key first.')


def _cookie_lookups(db) -> list:
    """The cookie settings snapshot for the job thread: DB settings (plan 12 Settings), then the
    Qt app's QSettings values from the registry [Q5 default a]."""
    snap = {k: db.get_setting(k, '') for k in ('yt_dlp_cookies', 'instagram_cookies', 'session_mode_general', 'session_mode_instagram')}
    return [snap.get, ytdlp.registry_get]


# ── describe ─────────────────────────────────────────────────────────────────
def _describe_prepare(db, job):
    provider, model = ai_defaults.get(db, ai_defaults.DESCRIBE)
    _key_ctx(job, provider, model)
    job.ctx['data_dir'] = str(db.data_dir)
    job.ctx['empty_msg'] = ('All of these items already have a description. '
                            'Open Process items and include completed items to describe them again.')
    rows = db.get_items_by_ids(job.ids)          # full rows: Describe uses the transcript
    return [r for r in rows if job.force or (r.get('ai_desc') or '').strip().upper() in ('', tasks.NO_CONTENT)]


def _describe_run(job, item):
    item = dict(item)
    folder = Path(job.ctx['data_dir']) / 'items' / str(item['id'])
    for field, name in (('report', 'report.md'), ('transcript', 'transcript.txt')):
        if not item.get(field):
            try:
                with (folder / name).open(encoding='utf-8', errors='replace') as f:
                    item[field] = f.read(3000)
            except OSError:
                pass
    # an ordinary website with no transcript: its visible text is the context (projects/link-preview)
    url = item.get('url') or ''
    page = ''
    if not item.get('transcript') and not linkinfo.ytdlp_first(url):
        page = linkinfo.page_text(url)
    result = tasks.describe_item(item, job.ctx['provider'], job.ctx['model'], job.ctx['data_dir'], page=page,
                                 missing_key='' if job.ctx.get('key', True) else job.ctx.get('key_msg', 'API key required.'))
    if result is None:
        raise Skipped('Nothing to describe yet: open it online once or add a note.')
    return result


def _describe_persist(db, item, result, job):
    db.update_item(item['id'], {'ai_desc': result, 'processed': True})


register(JobKind(key='describe', label='Describe', verb='Described', ai=True, text=True,
                 prepare=_describe_prepare, run_item=_describe_run, persist=_describe_persist))


# ── thumb ("Fetch link info"): thumbnail + text from yt-dlp or the link's own page ──
# The key stays 'thumb': the MCP, the widget, /api/items, /api/inbox/link and the phone mirror start it
# by that key. linkinfo.ytdlp_first picks which tool tries first; the other one fills what is still
# missing (projects/link-preview/plans/02-fetch-link-info.md).
_NO_INFO = {'filename': '', 'source': '', 'caption': '', 'title': '', 'creator': '', 'error': ''}


def _thumb_prepare(db, job):
    # no yt-dlp check here: the page reader can try every link; items that need yt-dlp fail one by one
    job.ctx['data_dir'] = str(db.data_dir)
    job.ctx['lookups'] = _cookie_lookups(db)
    job.ctx['empty_msg'] = ('All of these items already have a thumbnail. '
                            'Open Process items and include completed items to fetch their info again.')
    rows = db.get_items_by_ids(job.ids)
    return [r for r in rows if job.force or not r.get('thumb_path')]


def _ytdlp_info(job, item) -> dict:
    if not ytdlp.available():
        return dict(_NO_INFO, error=ytdlp.NOT_FOUND)
    try:
        with site_sessions.cookies(item.get('url') or '', job.ctx['lookups'], refresh=False) as cookies:
            return {**_NO_INFO, **ytdlp.fetch_thumbnail(item, job.ctx['data_dir'], cookies, should_stop=lambda: job.stopping)}
    except (OSError, RuntimeError, ValueError):
        return dict(_NO_INFO, error='Cannot unlock saved access on this PC. Re-import in Settings > Downloads; public previews can still work.')


def _web_info(job, item) -> dict:
    """The link's own page (library/linkinfo.py, the phone's rules): its picture saved as the thumbnail
    (thumb_source 'web'), its caption, title and creator."""
    url = item.get('url') or ''
    out = dict(_NO_INFO)
    info = linkinfo.read(url)
    if not info:
        out['error'] = 'The page could not be read (it may need JavaScript or a login)'
        return out
    out.update(caption=info['desc'], title=info['title'], creator=info['creator'])
    raw = linkinfo.image(linkinfo.absolute(url, info['image'])) if info['image'] else b''
    if raw:
        try:
            d = Path(job.ctx['data_dir']) / 'items' / str(item['id'])
            d.mkdir(parents=True, exist_ok=True)
            (d / 'thumb.jpg').write_bytes(linkinfo.to_jpeg(raw))
            out['filename'], out['source'] = 'thumb.jpg', 'web'
        except Exception as e:
            out['error'] = f'Could not save the page picture: {e}'
    elif not out['error']:
        out['error'] = 'The page has no picture'
    return out


def _thumb_run(job, item):
    tries = (_ytdlp_info, _web_info) if linkinfo.ytdlp_first(item.get('url') or '') else (_web_info,)
    best = None
    for get in tries:
        job.step(item['id'], 'Fetching thumbnail and caption…' if get is _ytdlp_info else 'Reading the page and its preview image…')
        r = get(job, item)
        # each field keeps the first answer that has it; the error is the first tool's
        best = r if best is None else {k: best[k] or r[k] for k in _NO_INFO}
        if best['filename'] and (best['caption'] or best['title']):
            break
    if not (best['filename'] or best['caption'] or best['title']):
        raise ytdlp.DownloadError(ytdlp.failure([best['error'] or 'No thumbnail produced']))
    return best


def _thumb_persist(db, item, r, job):
    """The phone's rule (server/intake.py _details): the caption fills an empty description (the link
    standing in counts as empty) and replaces it on an explicit selection; the title and the creator
    only ever fill empty fields, so what the user typed stays."""
    data = {}
    if r['filename']:
        data.update(thumb_path=r['filename'], thumb_source=r['source'])
    cur = db.get_item(item['id']) or {}
    url = (cur.get('url') or item.get('url') or '').strip()
    if r['caption'] and (job.force or (cur.get('description') or '').strip() in ('', url)):
        data['description'] = r['caption']
    if r['title'] and not (cur.get('short_desc') or '').strip():
        data['short_desc'] = r['title'][:300]
    if r['creator'] and not (cur.get('creator') or '').strip():
        data['creator'] = r['creator'][:120]
    if data:
        db.update_item(item['id'], data)
    if not r['filename']:
        raise ytdlp.DownloadError(ytdlp.failure([r['error'] or 'No thumbnail produced (the text was saved)']))


register(JobKind(key='thumb', label='Fetch link info', verb='Fetched link info for', ai=False, text=True,
                 prepare=_thumb_prepare, run_item=_thumb_run, persist=_thumb_persist))


# ── categorize (Qt _start_categorize / CategorizeWorker) ─────────────────────
def _categorize_prepare(db, job):
    provider, model = ai_defaults.get(db, ai_defaults.CATEGORIZE)
    _key_ctx(job, provider, model)
    job.ctx['categories'] = [c['name'] for c in db.get_categories()]
    job.ctx['empty_msg'] = ('No uncategorized items found. '
                            'To re-categorize specific items, open Process items and include completed items.')
    rows = db.get_items_by_ids(job.ids)
    return [r for r in rows if job.force or r.get('category') == 'INTERESTING']


def _categorize_run(job, item):
    return tasks.categorize_item(item, job.ctx['categories'], job.ctx['provider'], job.ctx['model'])


def _categorize_persist(db, item, result, job):
    category, tags = result
    db.update_item(item['id'], {'category': category, 'tags': tags})


register(JobKind(key='categorize', label='Auto-categorize', verb='Sorted', ai=True, text=True, gap=0.2,
                 prepare=_categorize_prepare, run_item=_categorize_run, persist=_categorize_persist))


# ── analyze (Qt _analyze_items / VideoAnalysisWorker) ────────────────────────
ANALYZE_DEFAULTS = {
    'frame_interval': 3.0, 'transcribe': True, 'transcribe_method': 'whisper-api',
    'analysis_provider': 'claude',
    'keep_frames': True, 'show_frames_in_canvas': True, 'delete_video': False, 'delete_audio': False,
    'ai_frame_budget': 'auto',
}
ANALYSIS_KEY_NAMES = {'claude': 'Claude (ANTHROPIC_API_KEY)', 'openai': 'OpenAI (OPENAI_API_KEY)',
                      'freellmapi': 'FreeLLMAPI (FREELLMAPI_API_KEY)'}


def _saved_analyze_options(db) -> dict:
    """The defaults Fred saved in the Analyze options window (a request from outside sends no options)."""
    try:
        v = json.loads(db.get_setting('analyze_options', '') or '{}')
    except ValueError:
        return {}
    return {k: v[k] for k in ANALYZE_DEFAULTS if k in v} if isinstance(v, dict) else {}


def _analysis_ctx(db, job) -> dict:
    """The analysis options and provider settings of an analyze run (cards or Video Tools)."""
    o = {**ANALYZE_DEFAULTS, **_saved_analyze_options(db), **(job.opts or {})}
    o['transcribe_method'] = 'whisper-api'   # the only method; a 'free' saved before its removal is ignored
    v_provider, v_model = ai_defaults.get(db, ai_defaults.VIDEO)
    default_provider = 'claude' if v_provider == 'anthropic' else v_provider
    o['analysis_provider'] = (job.opts or {}).get('analysis_provider', default_provider)
    provider = o['analysis_provider']
    key = config.analysis_key_for(provider) if provider != 'none' else ''
    job.ctx.update(
        provider=provider, model=v_model if provider == default_provider else None,
        key=provider == 'none' or bool(key), analysis_key=key, whisper_key=config.openai_api_key(),
        key_msg=(f'AI analysis uses {ANALYSIS_KEY_NAMES.get(provider, provider)}, but its key is not set. '
                 'Open Settings > API keys, or set the AI analysis provider to "none" to run '
                 'transcription only.'),
        opts=o, data_dir=str(db.data_dir))
    missing = video_analyzer.preflight(float(o['frame_interval'] or 0) > 0, bool(o['transcribe']),
                                       bool(job.ctx['whisper_key']))
    if missing:
        raise JobError(missing)
    return o


def _media_kwargs(job, step_id) -> dict:
    """analyze_media keyword arguments from the run's options."""
    c, o = job.ctx, job.ctx['opts']
    fi = float(o['frame_interval'] or 0)
    return dict(
        frame_interval=fi, transcribe=bool(o['transcribe']), transcribe_method=o['transcribe_method'],
        analysis_provider=c['provider'], analysis_model=c['model'], analysis_api_key=c['analysis_key'],
        whisper_api_key=c['whisper_key'], keep_frames=bool(o['keep_frames']) and fi > 0,
        show_frames_in_canvas=bool(o['show_frames_in_canvas']) and fi > 0,
        delete_video=bool(o['delete_video']), delete_audio=bool(o['delete_audio']),
        max_ai_frames=o['ai_frame_budget'], step=lambda m: job.step(step_id, m),
        should_stop=lambda: job.stopping)


def _analyze_prepare(db, job):
    if not ytdlp.available():
        raise JobError(ytdlp.NOT_FOUND)
    _analysis_ctx(db, job)
    job.ctx.update(lookups=_cookie_lookups(db),
                   empty_msg='Nothing to analyze: no reel or video among these items still needs it.')
    rows = db.get_items_by_ids(job.ids)
    return [r for r in rows if r.get('type') in ('Reel', 'Video') and (job.force or not r.get('analysis_done'))]


def _analyze_run(job, item):
    c, iid = job.ctx, item['id']
    job.step(iid, 'Locating / downloading video...')
    try:
        video = video_analyzer.find_or_download(
            iid, item.get('url', ''), c['data_dir'],
            cookies_resolver=lambda u: site_sessions.cookies(u, c['lookups']),
            should_stop=lambda: job.stopping)
        report_path, transcript, ai_analysis, _ = video_analyzer.analyze_media(
            video, Path(c['data_dir']) / 'items' / str(iid),
            item_id=iid, url=item.get('url', ''), post_text=item.get('description') or '',
            **_media_kwargs(job, iid))
    except video_analyzer.AnalysisStopped as exc:
        raise Stopped(str(exc)) from exc
    return report_path, transcript, ai_analysis


def _analyze_persist(db, item, result, job):
    report_path, transcript, ai_analysis = result
    db.update_item(item['id'], tasks.analysis_update(db.get_item(item['id']), report_path, transcript, ai_analysis))


register(JobKind(key='analyze', label='Analyze videos', verb='Analyzed', ai=True, text=True, gap=0,
                 join=True, prepare=_analyze_prepare, run_item=_analyze_run, persist=_analyze_persist))


# ── index for search (Qt _start_embed_index / EmbedWorker, 64 texts per call) ──
def _index_prepare(db, job):
    key, base_url = ai_defaults.embed_credentials(db)
    model = ai_client.EMBEDDING_MODEL
    job.ctx.update(api_key=key, base_url=base_url, provider='embeddings', model=model, key=bool(key),
                   key_msg=('Semantic search needs an embeddings API key. Open Settings to set the key '
                            'for your Embeddings provider (FreeLLMAPI or OpenAI).'),
                   empty_msg='All of these items are already indexed for semantic search.')
    stored = db.get_embedding_hashes(model)
    out = []
    for it in db.get_items_by_ids(job.ids):
        text = search.build_embed_text(it)
        if not text.strip():
            continue
        h = search.text_hash(model, text)
        if stored.get(it['id']) == h and not job.force:
            continue
        out.append({'id': it['id'], 'text': text, 'hash': h, 'short_desc': it.get('short_desc'),
                    'ai_desc': it.get('ai_desc'), 'description': it.get('description'), 'url': it.get('url')})
    return out


def _index_batch(job, chunk):
    vectors = ai_client.embed_texts([j['text'] for j in chunk], api_key=job.ctx['api_key'],
                                    base_url=job.ctx['base_url'])
    return [{'dim': len(v), 'hash': j['hash'], 'blob': search.vec_to_blob(v)} for j, v in zip(chunk, vectors)]


def _index_persist(db, item, r, job):
    db.upsert_embedding(item['id'], ai_client.EMBEDDING_MODEL, r['dim'], r['hash'], r['blob'])


register(JobKind(key='index', label='Index for search', verb='Indexed', ai=True, text=False, gap=0,
                 prepare=_index_prepare, run_item=lambda job, item: None, persist=_index_persist,
                 batch=64, run_batch=_index_batch))


# ── note: synthesize the items into data/notes/<slug>.md (SynthesizeWorker) ──
# opts: topic; mode 'new' (default) or 'augment' (fold into opts['note'], or a topic's first
# digest when opts['topic_id'] is set and the note does not exist yet); merge 'integrate' or
# 'append'; card_key (a Connections card: removed once its note is written); feature
# 'connections' (the Connections provider / model instead of Synthesize).
def _note_prepare(db, job):
    o = job.opts or {}
    feature = ai_defaults.CONNECTIONS if o.get('feature') == 'connections' else ai_defaults.SYNTHESIZE
    provider, model = ai_defaults.get(db, feature)
    _key_ctx(job, provider, model)
    topic = str(o.get('topic') or '').strip()
    if not topic:
        raise JobError('Give the note a topic first.')
    job.ctx.update(topic=topic, note='', notes_dir=str(db.notes_dir), augment=False,
                   fold_mode='append' if o.get('merge') == 'append' else 'reorganize',
                   empty_msg=('None of the selected sources have any text to synthesize yet '
                              '(no report, AI description, transcript, caption or note).'))
    rows = db.get_items_by_ids(job.ids)
    for r in rows:                         # the report is a file beside the item: the prompt's Report part
        p = db.items_dir / str(r['id']) / 'report.md'
        r['report'] = p.read_text(encoding='utf-8', errors='replace') if p.is_file() else ''
    rows = [r for r in rows if synth.has_text(r)]
    if o.get('mode') == 'augment':
        path = knowledge.safe_note_path(db.notes_dir, str(o.get('note') or ''))
        if path is not None:
            meta, body = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
        elif o.get('topic_id'):
            path = knowledge.new_digest_path(db.notes_dir, topic)
            meta = {'topic': topic, 'created': datetime.now().isoformat(timespec='seconds'), 'sources': ''}
            body = ''
        else:
            raise JobError('Open a note first (Saved notes on the rail).')
        have = knowledge.parse_source_ids(meta.get('sources', ''))
        rows = [r for r in rows if r['id'] not in have]
        job.ctx.update(augment=True, note_path=str(path), meta=meta, note=body,
                       topic=meta.get('topic') or topic,
                       empty_msg='All ticked sources are already in this note.')
    return rows


def _note_batch(job, chunk):
    job.emit('synth', {'job': job.id, 'line': f'Folding {len(chunk)} source(s) into the note…'})
    job.ctx['note'] = synth.fold(job.ctx['provider'], job.ctx['model'], job.ctx['topic'], job.ctx['note'], chunk,
                                 mode=job.ctx['fold_mode'],
                                 log=lambda m: job.emit('synth', {'job': job.id, 'line': m.strip()}))
    return [None] * len(chunk)


def _note_finish(db, job):
    note = (job.ctx.get('note') or '').strip()
    if not note or not job.ok_ids:
        return
    o = job.opts or {}
    if job.ctx['augment']:
        path = Path(job.ctx['note_path'])
        knowledge.write_back_note(path, note, job.ctx['meta'], job.ok_ids, job.ctx['topic'])
        if o.get('topic_id'):
            db.update_topic(int(o['topic_id']), note_path=path.name, last_run=int(time.time() * 1000))
        toast = f'Augmented data/notes/{path.name} with {len(job.ok_ids)} source(s)'
    else:
        path, _meta = knowledge.save_new_note(db.notes_dir, job.ctx['topic'], job.ok_ids, note)
        toast = f'Wrote data/notes/{path.name}'
    db.reindex_notes()
    events = [('notes_changed', {'file': path.name, 'job': True})]
    if o.get('card_key'):
        cards = [c for c in _json_setting(db, connections.CARDS_KEY, []) if c.get('key') != o['card_key']]
        db.set_setting(connections.CARDS_KEY, json.dumps(cards))
        events.append(('connections_changed', {}))
    job.ctx['note_file'] = path.name
    job.ctx['finish_toast'] = toast
    job.ctx['finish_events'] = events


register(JobKind(key='note', label='Synthesize a note', verb='Read', ai=True, text=False, gap=0,
                 prepare=_note_prepare, run_item=lambda job, item: None, persist=lambda db, i, r, j: None,
                 batch=synth.BATCH_SIZE, run_batch=_note_batch, finish=_note_finish))


# ── connections: one scan = one job item (ConnectionsPanel._scan + ConnectionsWorker) ──
def _json_setting(db, key, default):
    try:
        raw = db.get_setting(key, '')
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def _cx_prepare(db, job):
    provider, _model = ai_defaults.get(db, ai_defaults.CONNECTIONS)
    _key_ctx(job, provider, ai_client.cheap_model(provider))   # the gate stays cheap per provider
    index = search.EmbeddingIndex.from_db(db, ai_client.EMBEDDING_MODEL)
    if len(index) == 0:
        raise JobError('Connections need the search index: run Index for search (Process menu) first.')
    items = db.get_items_by_ids(index.ids())
    dismissed = connections.prune_dismissed(_json_setting(db, connections.DISMISSED_KEY, []))
    job.ctx.update(index=index, items_by_id={it['id']: it for it in items}, notes_dir=str(db.notes_dir),
                   dismissed={d['key'] for d in dismissed})
    return [{'id': 0, 'description': f'Scan {len(index)} indexed items for connections'}]


def _cx_run(job, item):
    c = job.ctx
    job.step(0, f"Clustering {len(c['index'])} items…")
    pending, payload = connections.candidates(c['index'], c['items_by_id'], c['notes_dir'], c['dismissed'])
    nb, nd = len(pending['bridges']), len(pending['drifts'])
    app_console.emit('log', f'Connections: {nb} bridge candidate(s) and {nd} drift cluster(s)')
    if not nb and not nd:
        return []
    job.step(0, f"Curating {nb} bridge + {nd} drift candidate(s) at the gate ({c['provider']}/{c['model']})…")
    try:
        text = ai_client.complete_text(c['provider'], c['model'], prompt=connections.gate_prompt(payload),
                                       system=connections.GATE_SYSTEM, max_tokens=connections.GATE_MAX_TOKENS)
        res = connections.parse_gate(text)
    except Exception as exc:
        app_console.emit('error', 'Connections gate failed', level='error', error=exc)
        res = None                 # bridges are dropped (never shown ungated); drifts keep tag labels
    return connections.cards_from_gate(pending, res)


def _cx_persist(db, item, cards, job):
    merged, n = connections.merge_cards(_json_setting(db, connections.CARDS_KEY, []), cards)
    db.set_setting(connections.CARDS_KEY, json.dumps(merged))
    db.set_setting(connections.LAST_SCAN_KEY, str(int(time.time() * 1000)))
    job.ctx['finish_toast'] = f'{n} new insight(s).' if n else 'No new connections passed the gate.'
    job.ctx['finish_events'] = [('connections_changed', {})]


register(JobKind(key='connections', label='Find connections', verb='Scanned', ai=True, text=False, gap=0,
                 prepare=_cx_prepare, run_item=_cx_run, persist=_cx_persist))


# ── download: one item's video (or thumbnail only) with streamed yt-dlp lines ──
def _download_prepare(db, job):
    if not ytdlp.available():
        raise JobError(ytdlp.NOT_FOUND)
    rows = [r for r in db.get_items_by_ids(job.ids[:1]) if (r.get('url') or '').strip()]
    if job.ids and not rows:
        raise JobError('This item has no URL.')
    job.ctx.update(data_dir=str(db.data_dir), lookups=_cookie_lookups(db),
                   thumbnail_only=bool((job.opts or {}).get('thumbnail_only')))
    return rows


def _download_run(job, item):
    c, iid, url = job.ctx, item['id'], item['url'].strip()
    out_dir = Path(c['data_dir']) / 'items' / str(iid) / 'video'
    out_dir.mkdir(parents=True, exist_ok=True)
    before = set(out_dir.iterdir())
    try:
        with site_sessions.cookies(url, c['lookups']) as cookies:
            args = ytdlp.download_args(ytdlp.find_ytdlp() or 'yt-dlp', url, out_dir, c['thumbnail_only'], cookies)
            ok, rc, hint = ytdlp.run_streaming(
                args, url, out_dir, on_line=lambda line: job.emit('ytdlp', {'job': job.id, 'id': iid, 'line': line}),
                should_stop=lambda: job.stopping)
            if not ok:
                raise ytdlp.DownloadError(ytdlp.failure([hint or f'yt-dlp exited with code {rc}']))
            if not c['thumbnail_only'] and not any(p.suffix.lower() in video_analyzer.VIDEO_EXTS and p.stat().st_size for p in out_dir.iterdir()):
                raise ytdlp.DownloadError({'code': 'unavailable', 'action': 'source', 'error': 'No complete video was produced. A preview picture does not establish a successful video download.'})
    except BaseException:
        for path in set(out_dir.iterdir()) - before:
            if path.is_file():
                path.unlink(missing_ok=True)
        raise
    thumb = ytdlp.largest_image(out_dir)
    if thumb:
        shutil.copy(thumb, Path(c['data_dir']) / 'items' / str(iid) / 'thumb.jpg')
    elif c['thumbnail_only']:
        raise RuntimeError('yt-dlp ran but produced no thumbnail for this URL.')
    return {'thumb': bool(thumb), 'out_dir': str(out_dir)}


def _download_persist(db, item, r, job):
    if r['thumb']:
        db.update_item(item['id'], {'thumb_path': 'thumb.jpg', 'thumb_source': 'yt-dlp', 'processed': 1})


register(JobKind(key='download', label='Download', verb='Downloaded', ai=False, text=False, gap=0,
                 prepare=_download_prepare, run_item=_download_run, persist=_download_persist))


# ── My Notes: Summarize (one note) and the screenshot digest (one item per screenshot) ──
def _personal_note(db, job):
    p = knowledge.safe_note_path(db.notes_dir, str((job.opts or {}).get('file') or ''))
    if p is None:
        raise JobError('That note is gone.')
    meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    return p, meta, body


def _summarize_prepare(db, job):
    provider, model = ai_defaults.get(db, ai_defaults.SUMMARIZE)
    _key_ctx(job, provider, model)
    p, meta, body = _personal_note(db, job)
    if not body.strip():
        raise JobError('Nothing to summarize: write something first.')
    job.ctx.update(path=str(p), title=meta.get('topic') or p.stem, body=body)
    return [{'id': 0, 'description': f'Summarize {p.name}'}]


def _summarize_run(job, item):
    return tasks.summarize_note(job.ctx['title'], note_format.plain(job.ctx['body']).strip(), job.ctx['provider'], job.ctx['model'])


def _summarize_persist(db, item, md, job):
    p = Path(job.ctx['path'])
    meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))   # the latest autosave
    my_notes.save_note(p, meta.get('topic') or p.stem, meta.get('category') or '', my_notes.replace_summary(body, md))
    db.reindex_notes()
    job.ctx['finish_toast'] = 'AI summary appended and saved.'
    job.ctx['finish_events'] = [('notes_changed', {'file': p.name, 'personal': True, 'job': True})]


register(JobKind(key='summarize', label='Summarize', verb='Summarized', ai=True, text=False, gap=0,
                 prepare=_summarize_prepare, run_item=_summarize_run, persist=_summarize_persist))


def _digest_prepare(db, job):
    provider, model = ai_defaults.get(db, ai_defaults.DESCRIBE)
    _key_ctx(job, provider, model)
    p, _meta, _body = _personal_note(db, job)
    images = (job.opts or {}).get('images') or []
    job.ctx.update(path=str(p), parts={})
    # negative ids: these are screenshots, not library items
    return [{'id': -(i + 1), 'description': im['name'], 'name': im['name'], 'type': im['type'], 'data': im['data']}
            for i, im in enumerate(images)]


def _digest_run(job, item):
    return tasks.transcribe_screenshot(item['type'], item['data'], job.ctx['provider'], job.ctx['model'])


def _digest_persist(db, item, text, job):
    job.ctx['parts'][item['id']] = text


def _digest_finish(db, job):
    parts = []
    for it in job.items:
        if it['id'] in job.ctx['parts']:
            parts.append((it['name'], job.ctx['parts'][it['id']]))
        else:
            parts.append((it['name'], f"[transcription failed: {job.status.get(it['id'], {}).get('error', '')}]"))
    if not job.ctx['parts']:
        job.ctx['finish_toast'] = f'All {len(job.items)} screenshot(s) failed to transcribe.'
        return
    p = Path(job.ctx['path'])
    meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
    my_notes.save_note(p, meta.get('topic') or p.stem, meta.get('category') or '',
                       my_notes.append_digest(body, my_notes.combine_digest(parts)))
    db.reindex_notes()
    job.ctx['finish_toast'] = 'Screenshot digest appended and saved.'
    job.ctx['finish_events'] = [('notes_changed', {'file': p.name, 'personal': True, 'job': True})]


register(JobKind(key='digest', label='Digest screenshots', verb='Transcribed', ai=True, text=False, gap=0,
                 prepare=_digest_prepare, run_item=_digest_run, persist=_digest_persist, finish=_digest_finish))


# ── reformat & classify (one personal note; proposes only — the preview window applies) ──
def _reformat_prepare(db, job):
    provider, model = ai_defaults.get(db, ai_defaults.SUMMARIZE)
    _key_ctx(job, provider, model)
    p, meta, body = _personal_note(db, job)
    if not body.strip():
        raise JobError('Nothing to reformat: write something first.')
    if len(body) > 20000:
        raise JobError(f'That note is too long to reformat ({len(body)} characters, at most 20000).')
    job.ctx.update(path=str(p), file=p.name, title=meta.get('topic') or p.stem,
                   category=meta.get('category') or my_notes.DEFAULT_CATEGORY, body=body,
                   categories=my_notes.all_categories(db, db.notes_dir),
                   instruction=str((job.opts or {}).get('instruction') or '')[:500], stamps=meta.get(note_format.KEY, ''))
    return [{'id': 0, 'description': f'Reformat {p.name}'}]


def _reformat_run(job, item):
    return tasks.reformat_note(job.ctx['title'], job.ctx['body'].strip(), job.ctx['category'],
                               job.ctx['categories'], job.ctx['provider'], job.ctx['model'],
                               job.ctx.get('instruction', ''), job.ctx.get('stamps', ''))


def _reformat_persist(db, item, proposal, job):
    # no write: the proposal goes to My Notes for a preview; Apply (Fred's click) saves it
    job.ctx['finish_toast'] = 'Reformat proposal ready — preview it in My Notes.'
    job.ctx['finish_events'] = [('reformat_preview', {
        'file': job.ctx['file'], 'old_title': job.ctx['title'], 'old_category': job.ctx['category'],
        'title': proposal['title'], 'category': proposal['category'],
        'topics': proposal['topics'], 'body': proposal['body'],
        'stamps': proposal.get('stamps'), 'instruction': job.ctx.get('instruction', '')})]


register(JobKind(key='reformat', label='Reformat & classify', verb='Reformatted', ai=True, text=False, gap=0,
                 prepare=_reformat_prepare, run_item=_reformat_run, persist=_reformat_persist))


# ── plan 12: the exports, the Playwright scrapers (Facebook, Instagram, Reddit), Video Tools ───────
# One pseudo item per step (negative ids: these are not library items). Steps report through
# job.step, results through finish_toast and an `export_done` event (path + text, so the page
# can offer Open folder). The DB reads they need happen in prepare / persist, on the Writer.
def log_error(tag: str, label: str, msg: str) -> None:
    try:
        with open(app_paths.ERROR_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{tag}] {label}: {msg}\n')
    except OSError:
        pass


def outside_data(db, path: Path, what: str) -> Path:
    """Exports never write inside data/ (the library's own folder)."""
    p = Path(path).expanduser().resolve()
    data = Path(db.data_dir).resolve()
    if p == data or data in p.parents:
        raise JobError(f'Pick a {what} outside the data folder: data/ holds the library itself.')
    return p


def _export_done(job, kind: str, path: str, text: str) -> None:
    job.ctx['finish_toast'] = text.splitlines()[0]
    job.ctx['reveal'] = path
    job.ctx['finish_events'] = [('export_done', {'kind': kind, 'path': path, 'text': text})]


def _csv_prepare(db, job):
    raw = str((job.opts or {}).get('path') or '').strip()
    if not raw:
        raise JobError('Enter the file to write.')
    p = outside_data(db, Path(raw), 'file')
    if p.suffix.lower() != '.csv':
        p = p.with_name(p.name + '.csv')
    if not p.parent.is_dir():
        raise JobError(f'The folder does not exist: {p.parent}')
    job.ctx.update(path=str(p), rows=db.search_items(include_thumbs=False))
    return [{'id': -1, 'description': f'Item CSV export: {p}'}]


def _csv_run(job, item):
    from library import importers
    return importers.write_csv(job.ctx['rows'], job.ctx['path'])


def _csv_persist(db, item, n, job):
    _export_done(job, 'csv', job.ctx['path'], f'Exported {n} items to {job.ctx["path"]}\n'
                 'Re-import with File > Import CSV or JSON. Files and other library data are not included.')


register(JobKind(key='export_csv', label='Export item CSV', verb='Exported', ai=False, text=False, gap=0,
                 prepare=_csv_prepare, run_item=_csv_run, persist=_csv_persist))


def _obs_prepare(db, job):
    """The classic export (decision 11): kept for vaults without a manifest; refused in owner mode, where
    Settings > Obsidian keeps the vault up to date. Topics come from the knowledge map (Refresh map)."""
    from library import map_engine, obsidian_run, owner_vault
    o = job.opts or {}
    raw = str(o.get('vault') or '').strip()
    vault = Path(raw).expanduser()
    if not raw or not vault.is_dir():
        raise JobError('Pick an existing vault folder.')
    if db.get_setting('obsidian_mode', '') == 'owner':
        raise JobError('Your Obsidian vault is a Brainamon vault: Settings > Obsidian keeps it up to date, and Refresh map '
                       'there updates the AI topics.')
    if owner_vault.read_manifest(vault) is not None:
        raise JobError('That folder is a Brainamon vault. Use Settings > Obsidian for it.')
    idx = search.EmbeddingIndex.from_db(db, ai_client.EMBEDDING_MODEL)
    cache_path = map_engine.cache_path(db.data_dir)
    db.set_setting('obsidian_vault', str(vault))
    tag_map, topics = obsidian_run.export_inputs(db, cache_path)
    job.ctx.update(vault=str(vault), idx=idx, tag_map=tag_map, topics=topics)
    return [{'id': -2, 'step': 'payload', 'description': 'Build the vault pages'},
            {'id': -3, 'step': 'write', 'description': f'Write {vault / "Content Manager"}'}]


def _obs_run(job, item):
    from library import obsidian_export
    from server.map_service import VAULT_LOCK
    c, step = job.ctx, item['step']
    if step != 'write':
        return None
    while not VAULT_LOCK.acquire(timeout=0.5):              # a user action: waits for the vault, Stop cancels
        if job.stopping:
            raise Stopped()
        job.step(-3, 'Waiting for the vault')
    try:
        return obsidian_export.write_obsidian_vault(
            c['payload'], c['vault'], progress=lambda d, t: job.step(-3, f'{d} of {t} pages'))
    finally:
        VAULT_LOCK.release()


def _obs_persist(db, item, result, job):
    from library import obsidian_export
    c, step = job.ctx, item['step']
    if step == 'payload':
        idx = c['idx']
        c['payload'] = obsidian_export.build_obsidian_payload(
            db, embed_index=idx if len(idx) else None, tag_map=c['tag_map'], ai_topics=c['topics'])
    elif step == 'write':
        count, errors = result
        for label, msg in errors:
            log_error('obsidian-export', label, msg)
        base = Path(c['vault']) / 'Content Manager'
        text = f'Exported {count} item(s) and {len(c["payload"]["notes"])} note(s) to {base}'
        if errors:
            text += f'\n{len(errors)} file(s) had issues (logged to error_log.txt).'
        _export_done(job, 'obsidian', str(base), text)


register(JobKind(key='export_obsidian', label='Export to Obsidian', verb='Exported', ai=False, text=False, gap=0,
                 prepare=_obs_prepare, run_item=_obs_run, persist=_obs_persist))


def _map_prepare(db, job):
    """Refresh map (decision 6): tag cleanup for unmapped tags, Rebuild when ticked or needed, then one
    summary per new or stale topic. Everything paid is confirmed first (POST /api/jobs/preview)."""
    from library import knowledge_graph, map_engine, obsidian_run
    o = job.opts or {}
    provider, model = ai_defaults.get(db, ai_defaults.SYNTHESIZE)
    _key_ctx(job, provider, model)
    job.ctx['key_msg'] = (f'The knowledge map uses your Wiskit model ({provider} / {model}). Open Settings > API keys '
                          'to enter that key.')
    emodel = ai_client.EMBEDDING_MODEL
    rows = db.search_items(include_thumbs=True)
    fps = map_engine.fingerprints(emodel, rows)
    idx = search.EmbeddingIndex.from_db(db, emodel)
    cache_path = map_engine.cache_path(db.data_dir)
    cache = map_engine.load(cache_path)
    map_engine.recompute_stale(cache, fps)
    rebuild = bool(o.get('rebuild')) or map_engine.needs_rebuild(cache, emodel)
    stored = obsidian_run.stored_tag_map(db)
    unmapped = obsidian_run.unmapped_tags(rows, stored)
    job.ctx.update(unmapped=unmapped, emodel=emodel, cache_path=str(cache_path), rebuild=rebuild,
                   by_id={r['id']: r for r in rows})
    items, plan = [], {'tags': len(unmapped), 'rebuild': 0, 'summaries': 0}
    if unmapped:
        items.append({'id': -1, 'step': 'tags', 'description': f'Clean up {len(unmapped)} tags'})
    if rebuild:
        if len(idx) < knowledge_graph.MIN_CLUSTER_SIZE * 2:
            raise JobError('Index more items for search first: the map needs at least 6 embedded items.')
        clusters = knowledge_graph.cluster_items(idx.ids(), idx.matrix())
        if not clusters:
            raise JobError('Not enough embedded items for a topic map yet. Index more items, then try again.')
        job.ctx['clusters'] = clusters
        plan['rebuild'] = len(clusters)
        items.append({'id': -2, 'step': 'rebuild', 'description': f'Rebuild: {len(clusters)} topics'})
        cache = map_engine.rebuild(cache, clusters, fps, emodel)      # the same ids the persist step will give
    jobs = map_engine.summary_jobs(cache, job.ctx['by_id'], fps, obsidian_run.excerpts_for)
    plan['summaries'] = len(jobs)
    items += [{'id': -(10 + i), 'step': 'topic', 'topic': j, 'description': f'Summary {i + 1} of {len(jobs)}'}
              for i, j in enumerate(jobs)]
    job.ctx['plan'] = plan
    job.ctx['empty_msg'] = 'The map is up to date: no tags to clean and no new or stale topics.'
    return items


def _map_run(job, item):
    from library import obsidian_run
    c, step = job.ctx, item['step']
    if step == 'tags':
        return obsidian_run.normalize_tags(c['unmapped'], c['provider'], c['model'], log=lambda m: job.step(-1, m))
    if step == 'topic':
        job.step(item['id'], f"Summarizing {len(item['topic']['member_ids'])} items with {c['model']}")
        return obsidian_run.synthesize_topic(item['topic'], c['provider'], c['model'])
    return None                                      # rebuild: the clustering was done in prepare


def _map_persist(db, item, result, job):
    """Every write merges into the latest state under the map lock (decision 6); nothing saves a snapshot
    taken earlier."""
    from library import map_engine, obsidian_run
    from server.map_service import MAP_LOCK
    c, step = job.ctx, item['step']
    if step == 'tags':
        stored = obsidian_run.stored_tag_map(db)
        stored.update(result)
        db.set_setting(obsidian_run.TAG_MAP_KEY, json.dumps(stored, ensure_ascii=False))
        return
    fps = map_engine.fingerprints(c['emodel'], db.search_items(include_thumbs=True))    # the text now
    with MAP_LOCK:
        cache = map_engine.load(c['cache_path'])
        map_engine.recompute_stale(cache, fps)
        if step == 'rebuild':
            cache = map_engine.rebuild(cache, c['clusters'], fps, c['emodel'])
        elif step == 'topic':
            if not map_engine.merge_summary(cache, item['topic'], result[0], result[1], fps):
                job.step(item['id'], 'Topic retired meanwhile: summary dropped')
                return
        map_engine.save(c['cache_path'], cache)
    # the activity log's result line (Settings > Knowledge map, the progress window)
    job.step(item['id'], f"{len(c['clusters'])} topics" if step == 'rebuild' else result[0])


register(JobKind(key='refresh_map', label='Refresh map', verb='Refreshed', ai=True, text=False, gap=0,
                 prepare=_map_prepare, run_item=_map_run, persist=_map_persist))


def _youtube_prepare(db, job):
    from library import youtube_playlist
    try:
        url = youtube_playlist.playlist_url(job.opts.get('url'))
    except ValueError as exc:
        raise JobError(str(exc)) from None
    executable = ytdlp.find_ytdlp()
    if not executable:
        raise JobError('Playlist imports need yt-dlp. Open Settings > Tools to install or locate it.')
    job.ctx.update(url=url, executable=executable, lookups=_cookie_lookups(db), data_dir=str(db.data_dir))
    return [{'id': -1, 'description': 'Import YouTube playlist'}]


def _youtube_run(job, item):
    from library import youtube_playlist
    job.emit('scrape', {'line': 'Reading YouTube playlist. No videos are downloaded.', 'c': 'a'})
    try:
        rows = youtube_playlist.read(job.ctx['url'], job.ctx['executable'], job.ctx['lookups'],
                                    should_stop=lambda: job.stopping,
                                    progress=lambda n: job.step(-1, f'Read {n} video links'))
    except Exception:
        if job.stopping:
            raise Stopped('Stopped.') from None
        raise
    return rows


def _youtube_persist(db, item, rows, job):
    from uuid import uuid4
    from library import importers
    if job.stopping:
        raise Stopped('Stopped.')
    folder = Path(db.data_dir) / 'scrapes'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'youtube_playlist_{uuid4().hex}.csv'
    importers.write_csv(rows, path)
    added, skipped, ids = importers.import_csv(db, path)
    job.ctx['added_ids'] = ids
    text = f'YouTube playlist: imported {added} new videos; skipped {skipped} duplicates.'
    job.ctx['finish_toast'] = text
    job.emit('scrape', {'line': text, 'c': 'g'})
    job.emit('items_changed', {'ids': ids, 'added': True})


register(JobKind(key='youtube_playlist', label='YouTube playlist import', verb='Imported', ai=False, text=False, gap=0,
                 prepare=_youtube_prepare, run_item=_youtube_run, persist=_youtube_persist))


def _scrape_prepare(db, job):
    from library import scrape_watch
    o = job.opts or {}
    key = str(o.get('platform') or 'facebook')
    if key not in scrape_watch.PLAYWRIGHT:
        raise JobError(f'No Playwright scraper for {key}.')
    if key == 'threads' and o.get('unsave'):
        raise JobError('Unsave is not available for Threads. Turn it off before starting.')
    script = scrape_watch.playwright_script(key)
    if not script.exists():
        raise JobError(f'Playwright scraper not found: {script}')
    watch = db.get_setting('scrape_watch_dir', '') or str(scrape_watch.default_downloads_dir())
    Path(watch).mkdir(parents=True, exist_ok=True)
    from library import scraper_runtime
    if scraper_runtime.status()['state'] != 'ready':
        raise JobError('Browser tools are not ready. Open Help or Settings > Tools to install/check them.')
    if o.get('unsave') and o.get('unsave_confirmed') is not True:
        raise JobError('Confirm that Unsave changes your account before starting.')
    job.ctx.update(watch=watch, platform=key, lookups=_cookie_lookups(db))
    job.ctx['label'] = scrape_watch.PLAYWRIGHT[key][0]
    return [{'id': -1, 'description': f'{job.ctx["label"]} (Playwright)'}]


def _scrape_run(job, item):
    from library import scrape_watch

    def say(line, c=''):
        job.emit('scrape', {'line': line, 'c': c})

    name = job.ctx['label']
    say(f'{name} (Playwright): browser automation started.', 'a')
    say(f'A Chromium window opens. Log in there if {name} asks, then wait.')
    from contextlib import ExitStack
    from library import scraper_runtime
    key = job.ctx['platform']
    with scraper_runtime.use() as (python, env), ExitStack() as stack:
        state = stack.enter_context(site_sessions.browser_state(key, bool(job.opts.get('remember'))))
        cookies = stack.enter_context(site_sessions.cookies(f'https://www.{key}.com/', job.ctx['lookups'], refresh=False))
        if cookies:
            raw, info = site_sessions.parse_cookies(cookies.read_bytes())
            if any(site_sessions.matches(domain, root) for domain in info['domains'] for root in site_sessions.SITES[key]):
                raw, _ = site_sessions.parse_cookies(raw, key)
                cookies.write_bytes(raw)
            else:
                cookies = None  # A different site's download login must not block browser sign-in.
        args = scrape_watch.playwright_args(Path(job.ctx['watch']), str(job.opts.get('stop_at') or ''),
                                             bool(job.opts.get('unsave')), str(cookies or ''),
                                             key, str(job.opts.get('username') or ''), python=python)
        args += ['--isolated', '--session-state', str(state)]
        if job.opts.get('remember'):
            args += ['--remember']
        return _scrape_process(job, args, env, say, name)


def _scrape_process(job, args, env, say, name):
    import subprocess
    from library import scrape_watch
    if job.stopping:
        raise Stopped('Stopped.')
    proc = subprocess.Popen(args, env=env, cwd=str(scrape_watch.ROOT_DIR), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    credential = Path(args[args.index('--session-state') + 1])
    statuses = {
        '[status] login': 'Finish signing in, including 2FA or CAPTCHA, in the browser. The helper waits without refreshing. Use Stop Playwright to cancel.',
        '[status] saved': 'Signed in. Opening Saved; if it does not open, choose Saved in the browser.',
        '[status] instagram-saved': 'Signed in. Looking for your Instagram profile. If Saved does not open, choose your profile > Saved > All posts in the browser.',
        '[status] collecting': 'Saved page reached. Collecting your saved items.',
    }
    with ytdlp.monitor(proc, lambda: job.stopping or site_sessions.revoked(credential), timeout=7200):
        for line in proc.stdout:
            # Page logs and tracebacks can contain secrets; publish only fixed statuses and counts.
            import re
            status = statuses.get(line.strip())
            if status:
                say(status)
            count = re.fullmatch(r'\[done\] (Scraped|Unsaved) ([0-9]+)(?: of ([0-9]+))? (items|posts)\s*', line)
            if count:
                say(count.group(0).strip())
        rc = proc.wait()
    if job.stopping:
        raise RuntimeError('Stopped.')
    if rc != 0:
        raise RuntimeError(f'The Playwright {name} scraper exited with code {rc}.')
    say(f'Playwright {name} scraper finished. The watcher imports its CSV.', 'g')
    return rc


register(JobKind(key='scrape', label='Playwright scraper', verb='Finished', ai=False, text=False, gap=0,
                 prepare=_scrape_prepare, run_item=_scrape_run, persist=lambda db, item, r, job: None))


VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}


def _vt_prepare(db, job):
    p = Path(str((job.opts or {}).get('path') or '').strip())
    if not p.is_file():
        raise JobError(f'File not found: {p}')
    if p.suffix.lower() not in VIDEO_EXTS:
        raise JobError('Pick a video file (mp4, mov, mkv, webm, avi, m4v).')
    job.opts = dict((job.opts or {}).get('opts') or {})       # the analysis options
    o = _analysis_ctx(db, job)
    if not float(o['frame_interval'] or 0) and not o['transcribe']:
        raise JobError('Nothing to analyze: set a frame interval or turn transcription on.')
    job.ctx['out_base'] = str(Path(db.data_dir) / 'video_tools')
    return [{'id': -1, 'description': p.name, 'local_path': str(p), 'stem': p.stem}]


def _vt_run(job, item):
    out = Path(job.ctx['out_base']) / 'items' / item['stem']
    job.step(-1, f'Analyzing: {item["local_path"]}')
    try:
        report_path, transcript, ai_analysis, _ = video_analyzer.analyze_media(
            Path(item['local_path']), out, item_id=item['stem'], url='', post_text='', **_media_kwargs(job, -1))
    except video_analyzer.AnalysisStopped as exc:
        raise Stopped(str(exc)) from exc
    return str(report_path), bool(transcript), ai_analysis or ''


def _vt_persist(db, item, r, job):
    report, transcript, ai = r
    job.ctx['finish_toast'] = f'Video Tools: wrote data/video_tools/items/{item["stem"]}/report.md'
    job.ctx['reveal'] = str(Path(report).parent)
    job.ctx['finish_events'] = [('video_tools', {'report': report, 'folder': str(Path(report).parent),
                                                  'transcript': transcript, 'analysis': ai})]


register(JobKind(key='video_tools', label='Video Tools', verb='Analyzed', ai=True, text=False, gap=0,
                 prepare=_vt_prepare, run_item=_vt_run, persist=_vt_persist))
