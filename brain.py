"""
brain.py - ask-your-library helper for Claude Code.

Retrieval + note persistence over the Brainamon SQLite library, reusing the
app's own search stack (db.fts_ids + search.EmbeddingIndex + search.hybrid_rank) and
note format. Qt-free, no new dependencies. Synthesis stays with Claude in conversation;
this script only fetches sources and saves the finished note.

Usage:
  py brain.py search "<query>" [--k N]
  py brain.py show <id>
  py brain.py note "<topic>" --sources 418,1330 [--created ISO]   # body on stdin
  py brain.py skills [--query "<topic>"] [--min-score 0.3] [--gate] [--json]
  py brain.py notes [--query "<topic>"] [--json]                  # where a file could go
  py brain.py file {new,append} [--note F] [--title T] [--name N] [--attach P ...]   # text on stdin
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from core import local_auth
from datetime import datetime
from pathlib import Path

from core import config
from core import db as db_module
from library import search
from knowledge import filing
from knowledge import inbox
from knowledge import knowledge
from knowledge import skills

config.load_env()   # API keys from .env (main.py does the same for the app)
# Windows consoles default to cp1252; never crash printing a non-Latin snippet.
sys.stdout.reconfigure(errors='replace')

REPO_ROOT = Path(__file__).resolve().parent
DB_PATH = REPO_ROOT / 'data' / 'content_manager.db'
DATA_DIR = DB_PATH.parent
PORT = int(os.environ.get('CM_PORT', '18765'))      # = server/settings.PORT


def _db():
    return db_module.Database(DB_PATH)


def _slugify(text: str) -> str:
    text = (text or '').strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text).strip('-')
    return text or 'untitled'


def _title(item: dict) -> str:
    t = (item.get('short_desc') or item.get('ai_desc') or item.get('description')
         or f"item-{item.get('id')}")
    return re.sub(r'\s+', ' ', t).strip()[:80]


def _best_text(item: dict) -> str:
    return (item.get('ai_desc') or item.get('transcript')
            or item.get('description') or item.get('short_desc') or '')


def _report_path(db, item_id: int):
    p = db.items_dir / str(item_id) / 'report.md'
    return p if p.exists() else None


# -- search --------------------------------------------------------------------
def _embed_query(query: str):
    """Return the query embedding vector, or None if unavailable (no key / error)."""
    try:
        from core import ai_client
        vecs = ai_client.embed_texts([query])
        return vecs[0] if vecs else None
    except Exception as e:
        print(f"(semantic search off: {e})", file=sys.stderr)
        return None


def _substring_ids(db, query: str, limit: int) -> list:
    """Last-resort recall when FTS + embeddings both return nothing."""
    like = f"%{query.lower()}%"
    rows = db.conn.cursor().execute(
        "SELECT id FROM items WHERE LOWER("
        "COALESCE(short_desc,'')||' '||COALESCE(ai_desc,'')||' '||"
        "COALESCE(description,'')||' '||COALESCE(transcript,'')||' '||"
        "COALESCE(tags,'')||' '||COALESCE(creator,'')) LIKE ? "
        "ORDER BY COALESCE(created, modified, 0) DESC LIMIT ?",
        (like, limit)
    ).fetchall()
    return [r[0] for r in rows]


def do_search(db, query: str, k: int) -> int:
    fts = db.fts_ids(query, limit=max(k * 3, 30))
    vec_hits = []
    qvec = _embed_query(query)
    if qvec is not None:
        from core import ai_client
        index = search.EmbeddingIndex(db.get_all_embeddings(ai_client.EMBEDDING_MODEL))
        vec_hits = index.topk(qvec, k=max(k * 3, 30))
    ids = search.hybrid_rank(fts, vec_hits, limit=k)
    if not ids:
        ids = _substring_ids(db, query, k)
    items = db.get_items_by_ids(ids)
    if not items:
        print(f"No matches for: {query}")
        return 0
    for n, item in enumerate(items, 1):
        rep = 'yes' if _report_path(db, item['id']) else 'no'
        snippet = re.sub(r'\s+', ' ', _best_text(item)).strip()[:200]
        print(f"{n:2}. [id {item['id']}] {_title(item)}")
        print(f"     creator: {item.get('creator') or '-'} | cat: {item.get('category') or '-'}"
              f" | report: {rep}")
        print(f"     {item.get('url') or ''}")
        if snippet:
            print(f"     {snippet}")
        print()
    return 0


# -- show ----------------------------------------------------------------------
def do_show(db, item_id: int) -> int:
    items = db.get_items_by_ids([item_id])
    if not items:
        print(f"No such item: {item_id}")
        return 1
    item = items[0]
    print(f"[id {item['id']}] {_title(item)}")
    print(f"creator : {item.get('creator') or '-'}")
    print(f"category: {item.get('category') or '-'}")
    print(f"url     : {item.get('url') or '-'}")
    print(f"tags    : {item.get('tags') or '-'}")
    print("\n## ai_desc\n" + (item.get('ai_desc') or '(none)'))
    print("\n## transcript\n" + (item.get('transcript') or '(none)'))
    report = _report_path(db, item['id'])
    tpath = db.items_dir / str(item['id']) / 'transcript.txt'
    print("\n## files on disk")
    print(f"report    : {report if report else '(none)'}")
    print(f"transcript: {tpath if tpath.exists() else '(none)'}")
    return 0


# -- note ----------------------------------------------------------------------
def do_note(db, topic: str, sources: list, created: str = None) -> int:
    body = sys.stdin.read().strip()
    if not body:
        print("No note body on stdin. Pipe the markdown in.", file=sys.stderr)
        return 1
    db.notes_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(topic)
    path = db.notes_dir / f"{slug}.md"
    n = 2
    while path.exists():
        path = db.notes_dir / f"{slug}-{n}.md"
        n += 1
    created = created or datetime.now().isoformat(timespec='seconds')
    ids = ','.join(str(i) for i in sorted(set(int(s) for s in sources)))
    front = f"---\ntopic: {topic}\ncreated: {created}\nsources: {ids}\n---\n\n"
    path.write_text(front + body + "\n", encoding='utf-8')
    db.reindex_notes()
    count = db.conn.cursor().execute("SELECT COUNT(*) FROM notes_fts").fetchone()[0]
    print(f"Wrote {path}")
    print(f"notes_fts now has {count} rows")
    return 0


# -- skills --------------------------------------------------------------------
def _skill_items(db, query: str) -> list:
    """Every item, or the items matching `query` (FTS, then the substring fallback)."""
    if not query:
        return [dict(r) for r in db.conn.cursor().execute("SELECT * FROM items").fetchall()]
    ids = db.fts_ids(query, limit=500) or _substring_ids(db, query, 500)
    return db.get_items_by_ids(ids)


def _skill_index(db):
    """The embedding index (for merge candidates), or None when nothing is embedded."""
    try:
        from core import ai_client
        rows = db.get_all_embeddings(ai_client.EMBEDDING_MODEL)
    except Exception as e:
        print(f"(merge candidates off: {e})", file=sys.stderr)
        return None
    return search.EmbeddingIndex(rows) if rows else None


def _run_gate(db, res: dict, by_id: dict) -> tuple:
    """(verdicts, 'provider/model') from one batched gate call. Provider: the Connections
    feature's (the app's cheap-gate setting), with that provider's cheap model."""
    from core import ai_client
    from core import ai_defaults
    provider, _model = ai_defaults.get(db, ai_defaults.CONNECTIONS)
    model = ai_client.cheap_model(provider)
    payload = skills.gate_payload(res, by_id, db.notes_dir)
    text = ai_client.complete_text(provider, model, prompt=skills.gate_prompt(payload),
                                   system=skills.GATE_SYSTEM,
                                   max_tokens=skills.GATE_MAX_TOKENS)
    return skills.verdicts(payload, skills.parse_gate(text)), f"{provider}/{model}"


def _print_verdicts(verdicts: list, used: str) -> None:
    print(f"\nGate verdicts ({used}; rejected candidates are not listed)")
    if not verdicts:
        print("  (nothing passed the gate)")
    bucket = None
    for v in verdicts:
        if v['bucket'] != bucket:
            bucket = v['bucket']
            print(f"\n  {bucket.upper()}")
        src = (v['note'] or ', '.join(f"[id {i}]" for i in v['item_ids'][:6]))
        name = f"{v['name']}: " if v['name'] else ''
        print(f"  - {name}{v['use_when'] or '(no description)'}")
        print(f"      from {src}" + (f"  (overlaps {v['overlaps']})" if v['overlaps'] else ''))


def do_skills(db, query: str, min_score: float, as_json: bool, gate: bool = False) -> int:
    items = _skill_items(db, query)
    if not items:
        print(f"No items{' for: ' + query if query else ''}")
        return 0
    index = _skill_index(db)
    ids = matrix = None
    if index is not None:
        wanted = {int(i['id']) for i in items}
        all_ids = index.ids()
        rows = [r for r, i in enumerate(all_ids) if i in wanted]
        ids = [all_ids[r] for r in rows]
        matrix = index.matrix()[rows]
    res = skills.candidates(items, ids, matrix, db.notes_dir,
                            [db.data_dir / 'skills', REPO_ROOT / '.claude' / 'skills'],
                            min_score=min_score)
    scored = res.pop('scored')
    by_id = {int(i['id']): i for i in items}
    verdicts = used = None
    if gate:
        try:
            verdicts, used = _run_gate(db, res, by_id)
        except Exception as e:
            # Candidates are never presented as skills without a verdict.
            print(f"Gate failed: {e}", file=sys.stderr)
            return 1
    if as_json:
        if verdicts is not None:
            res['verdicts'] = verdicts
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0

    def line(item_id):
        it = by_id[item_id]
        gated = scored[item_id]['gated']
        tag = f"  [gated: comment {gated}]" if gated else ''
        return f"[id {item_id}] {it.get('creator') or '-'}: {skills.item_title(it)[:80]}{tag}"

    qualify = sum(1 for s in scored.values() if s['score'] >= min_score)
    print(f"Skill candidates{' for: ' + query if query else ''} "
          f"(procedure score >= {min_score}; {qualify} of {len(items)} items qualify; "
          f"{res['covered']} already cited by a skill)\n")
    print("Merge candidates: one technique, several creators")
    if index is None:
        print("  (no embeddings: run the 'Index for search' action in the app)")
    for n, m in enumerate(res['merges'], 1):
        print(f"{n:2}. {len(m['item_ids'])} items, {m['creators']} creators, "
              f"avg score {m['score']}")
        for i in m['item_ids']:
            print(f"      {line(i)}")
    if index is not None and not res['merges']:
        print("  (none)")
    print("\nSingle items")
    for n, it in enumerate(res['items'], 1):
        print(f"{n:2}. score {it['score']}  {line(it['id'])}")
        print(f"      signals: {skills.signal_summary(it['signals'])}")
    if not res['items']:
        print("  (none)")
    print("\nNotes that read like procedures")
    for note in res['notes']:
        print(f"  - {note['file']} ({note['topic']}) score {note['score']}")
    if not res['notes']:
        print("  (none)")
    gated = res['gated']
    if gated:
        sample = ', '.join(f"[id {i}] {scored[i]['gated']}" for i in gated[:8])
        print(f"\nGated: {len(gated)} items keep their steps behind \"comment X\" "
              f"and say too little on their own (newest: {sample})")
    print(f"\nSkills checked: {', '.join(res['skills']) or '(none found)'}")
    if verdicts is not None:
        _print_verdicts(verdicts, used)
    return 0


# -- notes / file (projects/wiskit-files plan 03) -------------------------------
def _topic_files(db) -> set:
    return {t['note_path'] for t in db.list_topics() if t.get('note_path')}


def do_notes(db, query: str, as_json: bool) -> int:
    """Notes a file could go into: keyword-ranked for --query, else every note newest first.
    Topic digests are flagged: Refresh digest rewrites them, never file into one."""
    topics = _topic_files(db)
    if query:
        rows = [{'file': n['filename'], 'title': n['topic'], 'snippet': ' '.join((n.get('body') or '').split())[:160]}
                for n in db.search_notes(query, 15)]
    else:
        rows = [{'file': r['file'], 'title': r['title'], 'snippet': r['snippet'][:160]}
                for r in knowledge.sort_note_rows(knowledge.note_rows(db.notes_dir, topics), 'updated')]
    for r in rows:
        r['topic_digest'] = r['file'] in topics
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print('No notes match.')
        return 0
    for r in rows:
        flag = '  [topic digest: do not file here]' if r['topic_digest'] else ''
        print(f"{r['file']}  {r['title']}{flag}\n    {r['snippet']}")
    return 0


def _post(path: str, body: dict):
    """POST to the running app, so its Writer does the write. None when the app is not running;
    RuntimeError with the app's message when it refuses."""
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{PORT}{path}', data=json.dumps(body).encode('utf-8'),
                                     headers=local_auth.headers(PORT, {'X-CM': '1', 'Content-Type': 'application/json'}), method='POST')
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(detail).get('detail', detail)
        except ValueError:
            pass
        raise RuntimeError(f'The app refused it ({e.code}): {detail}') from None
    except (urllib.error.URLError, FileNotFoundError):
        return None


def do_file(action: str, note: str, title: str, name: str, attach: list) -> int:
    text = sys.stdin.read().strip()
    if not text:
        print("No text on stdin. Pipe the markdown in.", file=sys.stderr)
        return 1
    if action == 'append' and not note:
        print("append needs --note <file.md> (find it with: py brain.py notes --query ...)", file=sys.stderr)
        return 1
    missing = [p for p in attach if not Path(p).is_file()]
    if missing:
        print(f"Not a file: {', '.join(missing)}", file=sys.stderr)
        return 1
    copies = [inbox.save_file(DATA_DIR, Path(p).name, Path(p).read_bytes()).name for p in attach]
    if copies:
        text += '\n\n' + '\n'.join(f'Source file: `data/inbox/{c}`' for c in copies)
    name = name or (Path(attach[0]).name if attach else 'Claude Code')
    try:
        r = _post('/api/filing/file', {'action': action, 'name': name, 'text': text, 'file': note, 'title': title})
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    via = 'through the running app'
    if r is None:                     # the app is not running: no other writer is open
        db = _db()
        try:
            if note in _topic_files(db):
                print('Refresh digest rewrites topic notes. Pick another note.', file=sys.stderr)
                return 1
            p = filing.file_text(db, action, name, text, note, title)
        except (LookupError, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
        finally:
            db.close()
        meta, _body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        r, via = {'file': p.name, 'title': meta.get('topic') or p.stem}, 'directly (the app is not running)'
    print(f"Filed into data/notes/{r['file']} ({r['title']}) {via}")
    return 0


def _parse_sources(s: str) -> list:
    return [tok for tok in re.split(r'[,\s]+', s.strip()) if tok]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ask-your-library helper")
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('search', help='rank library items for a query')
    sp.add_argument('query')
    sp.add_argument('--k', type=int, default=15)

    sh = sub.add_parser('show', help='full record for one item id')
    sh.add_argument('id', type=int)

    nt = sub.add_parser('note', help='write data/notes/<slug>.md (body on stdin)')
    nt.add_argument('topic')
    nt.add_argument('--sources', required=True)
    nt.add_argument('--created', default=None)

    sk = sub.add_parser('skills', help='list skill candidates (no AI calls, read-only)')
    sk.add_argument('--query', default='', help='only items matching this topic')
    sk.add_argument('--min-score', type=float, default=skills._MIN_SCORE)
    sk.add_argument('--gate', action='store_true',
                    help='one AI call sorts candidates into skill / agent / rule / note')
    sk.add_argument('--json', action='store_true', help='machine-readable output')

    ns = sub.add_parser('notes', help='notes a file could be filed into (read-only)')
    ns.add_argument('--query', default='')
    ns.add_argument('--json', action='store_true')

    fl = sub.add_parser('file', help='file text (stdin) into a new note or an existing one')
    fl.add_argument('action', choices=['new', 'append'])
    fl.add_argument('--note', default='', help='the note file for append (see: notes)')
    fl.add_argument('--title', default='', help='the title of a new note')
    fl.add_argument('--name', default='', help='what the text came from (the section heading)')
    fl.add_argument('--attach', nargs='*', default=[], help='original files to keep in data/inbox')

    args = ap.parse_args(argv)
    if args.cmd == 'file':            # writes through the app when it runs: no DB opened here first
        return do_file(args.action, args.note, args.title, args.name, args.attach)
    # skills and notes only read: a mode=ro connection, no schema or migration code.
    db = db_module.ReadOnlyDatabase(DB_PATH) if args.cmd in ('skills', 'notes') else _db()
    if args.cmd == 'search':
        return do_search(db, args.query, args.k)
    if args.cmd == 'show':
        return do_show(db, args.id)
    if args.cmd == 'note':
        return do_note(db, args.topic, _parse_sources(args.sources), args.created)
    if args.cmd == 'skills':
        return do_skills(db, args.query, args.min_score, args.json, args.gate)
    if args.cmd == 'notes':
        try:
            return do_notes(db, args.query, args.json)
        finally:
            db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
