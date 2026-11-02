"""owner_pages.py - the pages of a Brainamon-owned vault (spec 2026-10-28, decision 3). Pure text.

<vault>/Brainamon/
  Knowledge Map.md              the home page
  Items/<slug>-<id>.md          one page per titled item (item_title); untitled items are listed by URL
  Topics/<slug>-t<n>.md         AI topics with a summary (library/map_engine.py)
  Tags/<slug>.md, Categories/<slug>.md    hubs, grouped by fold()
  Reports/<id>.md, Notes/<file>.md        copied files; Attachments/<id>.jpg only with Include pictures

build_owner_payload reads the DB where the caller allows it (the Writer) and asks owner_vault.Names
for every page name, so names are chosen once and kept. render() turns the payload into
{relative path: {'data': bytes} or {'src': path}, 'source', 'key'} without reading any file.
Every generated page carries `source: brainamon`; copies carry nothing (owner_vault.COPIED).
"""
import re
from datetime import datetime
from pathlib import Path

from library.obsidian_export import RELATED_K, RELATED_MIN_SCORE, _canonical_tags, _epoch_to_iso, _link_text, _slugify, _yaml_value

FOLDER = 'Brainamon'
SOURCE_LINE = 'source: brainamon'
TAG_LIMIT = 40                  # tag hubs listed on the Knowledge Map
_LINK = re.compile(r'^https?://\S+$', re.IGNORECASE)


def fold(name: str) -> str:
    """The hub key: lowercased, spaces, hyphens and underscores folded to one space."""
    return re.sub(r'[\s_-]+', ' ', (name or '').strip().lower())


def item_title(row: dict) -> str:
    """The first real title: short_desc, else the first line of ai_desc, else description unless its trimmed
    text is the item's URL or another http(s) address. '' means no page yet."""
    url = (row.get('url') or '').strip()
    for field in ('short_desc', 'ai_desc', 'description'):
        text = (row.get(field) or '').strip()
        if not text:
            continue
        if field == 'description' and (text == url or _LINK.match(text)):
            continue
        first = text.splitlines()[0].strip()
        if first:
            return first
    return ''


def build_owner_payload(db, names, embed_index=None, tag_map=None, cache=None, include_pictures=False) -> dict:
    """{items, tags, categories, topics, notes, generated, has_map}. `names`: owner_vault.Names over the
    manifest. `tag_map`: {raw tag: canonical or None} from obsidian_run.stored_tag_map, or None for the
    frequency filter. `cache`: map_engine.load(...), or None."""
    rows = db.search_items()
    items, by_id, tag_counts = [], {}, {}
    for r in rows:
        tags = [t.strip() for t in (r.get('tags') or '').split(',') if t.strip()]
        for t in tags:
            tag_counts[t.lower()] = tag_counts.get(t.lower(), 0) + 1
        title = item_title(r)
        thumb_src = None
        if include_pictures:
            cand = db.items_dir / str(r['id']) / 'thumb.jpg'
            if cand.exists():
                thumb_src = str(cand)
        report_src = None
        if r.get('analysis_done') and r.get('analysis_path') and Path(r['analysis_path']).exists():
            report_src = str(r['analysis_path'])
        it = {'id': r['id'], 'title': title, 'name': names.item(r['id'], title) if title else '',
              'url': r.get('url') or '', 'creator': r.get('creator') or '', 'type': r.get('type') or '',
              'category': r.get('category') or '', 'category_name': '', 'tags': tags,
              'created_iso': _epoch_to_iso(r.get('created') or r.get('modified')),
              'body': r.get('ai_desc') or r.get('description') or '',
              'thumb_src': thumb_src, 'report_src': report_src,
              'related': [], 'tag_refs': [], 'topic_refs': []}
        items.append(it)
        by_id[it['id']] = it

    tags_hub, cats_hub = {}, {}

    def add(hub, source, label, item):
        key = fold(label)
        e = hub.get(key)
        if e is None:
            e = hub[key] = {'name': names.hub(source, key, label), 'label': label, 'members': []}
        e['members'].append(item['id'])
        return e

    for it in items:
        for label in _canonical_tags(it['tags'], tag_map, tag_counts):
            e = add(tags_hub, 'tag', label, it)
            it['tag_refs'].append((e['name'], label))
        if it['category']:
            it['category_name'] = add(cats_hub, 'category', it['category'], it)['name']

    topics = {}
    for tid, t in ((cache or {}).get('clusters') or {}).items():
        if not t.get('synthesis') or not t.get('name'):
            continue                                    # waiting for its summary: no page, no link
        name = names.topic(tid, t['name'])
        members = [i for i in t['member_ids'] if i in by_id]
        topics[tid] = {'name': name, 'label': t['title'], 'synthesis': t['synthesis'], 'members': members,
                       'stale': bool(t.get('stale'))}
        for i in members:
            by_id[i]['topic_refs'].append((name, t['title']))

    if embed_index is not None and len(embed_index) > 0:
        for it in items:
            if not it['name']:
                continue
            for other_id, score in embed_index.similar_to(it['id'], k=RELATED_K):
                if score < RELATED_MIN_SCORE:
                    continue
                other = by_id.get(other_id)
                if other is not None and other['name']:
                    it['related'].append((other['name'], other['title']))

    notes = [str(p) for p in sorted(db.notes_dir.glob('*.md'))] if db.notes_dir.exists() else []
    return {'items': items, 'tags': tags_hub, 'categories': cats_hub, 'topics': topics, 'notes': notes,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'has_map': bool(((cache or {}).get('clusters') or {}))}


# ── markdown ─────────────────────────────────────────────────────────────────
def item_page(it: dict) -> str:
    fm = ['---', f"id: {it['id']}", f"aliases: [{_yaml_value(it['title'])}]", f"url: {_yaml_value(it['url'])}"]
    if it['creator']:
        fm.append(f"creator: {_yaml_value(it['creator'])}")
    fm.append(f"type: {_yaml_value(it['type'] or 'Item')}")
    if it['category']:
        fm.append(f"category: {_yaml_value(it['category'])}")
    canon = [label for _n, label in it['tag_refs']]
    if canon:
        fm.append('tags: [' + ', '.join(_yaml_value(t) for t in canon) + ']')
    if it['created_iso']:
        fm.append(f"created: {it['created_iso']}")
    fm += [SOURCE_LINE, '---']
    parts = ['\n'.join(fm), '', f"# {_link_text(it['title'])}", '']
    if it['thumb_src']:
        parts += [f"![[{FOLDER}/Attachments/{it['id']}.jpg]]", '']
    parts.append((it['body'] or '').strip() or '-')
    links = [f"[[{FOLDER}/Topics/{n}|{_link_text(t)}]]" for n, t in it['topic_refs']]
    links += [f"[[{FOLDER}/Tags/{n}|{_link_text(t)}]]" for n, t in it['tag_refs']]
    if it['category'] and it['category_name']:
        links.append(f"[[{FOLDER}/Categories/{it['category_name']}|{_link_text(it['category'])}]]")
    if links:
        parts += ['', '## Topics', ' '.join(links)]
    if it['related']:
        parts += ['', '## Related'] + [f"- [[{FOLDER}/Items/{n}|{_link_text(t)}]]" for n, t in it['related']]
    if it['report_src']:
        parts += ['', f"[[{FOLDER}/Reports/{it['id']}|Analysis report]]"]
    return '\n'.join(parts).rstrip() + '\n'


def _member_lines(ids, by_id: dict) -> list:
    """Titled items link to their page; untitled ones are listed as their URL, never linked."""
    rows = sorted((by_id[i] for i in ids if i in by_id), key=lambda r: ((r['title'] or r['url']).lower(), r['id']))
    return [f"- [[{FOLDER}/Items/{r['name']}|{_link_text(r['title'])}]]" if r['name'] else f"- {r['url']}" for r in rows]


def hub_page(kind: str, hub: dict, by_id: dict) -> str:
    """kind: 'tag', 'category' or 'ai-topic' (then hub has synthesis and stale)."""
    fm = ['---', f'kind: {kind}', f"items: {len(hub['members'])}"]
    if kind == 'ai-topic':
        fm.append(f"stale: {'true' if hub.get('stale') else 'false'}")
    fm += [SOURCE_LINE, '---']
    parts = ['\n'.join(fm), '', f"# {_link_text(hub['label'])}"]
    if hub.get('synthesis'):
        parts += ['', hub['synthesis'].strip()]
    parts += ['', f"## Items ({len(hub['members'])})"] + _member_lines(hub['members'], by_id)
    return '\n'.join(parts).rstrip() + '\n'


def map_page(payload: dict) -> str:
    by_size = lambda hubs: sorted(hubs, key=lambda h: (-len(h['members']), h['name']))   # noqa: E731
    cats, topics = by_size(payload['categories'].values()), by_size(payload['topics'].values())
    tags = by_size(payload['tags'].values())[:TAG_LIMIT]
    parts = ['---', 'kind: map', SOURCE_LINE, '---', '', '# Knowledge Map', '',
             f"Generated by Brainamon on {payload['generated']}. {len(payload['items'])} items. "
             f"Brainamon writes only the {FOLDER} folder; your own notes elsewhere in this vault are never touched.",
             '', '## Categories']
    parts += [f"- [[{FOLDER}/Categories/{h['name']}|{_link_text(h['label'])}]] ({len(h['members'])} items)" for h in cats]
    parts += ['', '## AI topics']
    if topics:
        parts += [f"- [[{FOLDER}/Topics/{h['name']}|{_link_text(h['label'])}]] ({len(h['members'])} items"
                  f"{', summary out of date' if h['stale'] else ''})" for h in topics]
    else:
        parts.append('AI topics appear here after the first Refresh map (Settings > Obsidian).')
    parts += ['', '## Tags'] + [f"- [[{FOLDER}/Tags/{h['name']}|{_link_text(h['label'])}]] ({len(h['members'])} items)" for h in tags]
    return '\n'.join(parts).rstrip() + '\n'


def render(payload: dict) -> dict:
    """{relative path: {'data': bytes} | {'src': source path}, plus 'source' and 'key'} for this render."""
    by_id = {it['id']: it for it in payload['items']}
    files = {}

    def page(rel, text, source, key):
        files[rel] = {'data': text.encode('utf-8'), 'source': source, 'key': str(key)}

    def copy(rel, src, source, key):
        files[rel] = {'src': str(src), 'source': source, 'key': str(key)}

    for it in payload['items']:
        if it['name']:
            page(f"{FOLDER}/Items/{it['name']}.md", item_page(it), 'item', it['id'])
        if it['thumb_src']:
            copy(f"{FOLDER}/Attachments/{it['id']}.jpg", it['thumb_src'], 'attachment', it['id'])
        if it['report_src']:
            copy(f"{FOLDER}/Reports/{it['id']}.md", it['report_src'], 'report', it['id'])
    for key, h in payload['tags'].items():
        page(f"{FOLDER}/Tags/{h['name']}.md", hub_page('tag', h, by_id), 'tag', key)
    for key, h in payload['categories'].items():
        page(f"{FOLDER}/Categories/{h['name']}.md", hub_page('category', h, by_id), 'category', key)
    for tid, h in payload['topics'].items():
        page(f"{FOLDER}/Topics/{h['name']}.md", hub_page('ai-topic', h, by_id), 'topic', tid)
    for p in payload['notes']:
        copy(f"{FOLDER}/Notes/{Path(p).name}", p, 'note', Path(p).name)
    page(f"{FOLDER}/Knowledge Map.md", map_page(payload), 'map', 'map')
    return files
