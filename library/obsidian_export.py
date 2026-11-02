"""
obsidian_export.py — the classic Export to Obsidian: a one-way publish of the Brainamon library into
<vault>/Content Manager/ of a vault the user already uses (spec 2026-10-28 decision 11: kept, manual, for
vaults without a .brainamon/manifest.json; refused in owner mode; retired when guest mode writes land).
The Brainamon-owned vault layout (Brainamon/ with a manifest) is library/owner_pages.py + owner_vault.py,
rendered by server/map_service.py. Qt-free so the filesystem half can run on a worker thread. DB reads
happen only in build_obsidian_payload (the Writer).

Layout written under <vault>/Content Manager/:
  items/<slug>-<id>.md     one note per item
  reports/<id>.md          copied analysis reports
  attachments/<id>.jpg     thumbnails
  notes/<name>.md          copies of data/notes/*.md
  topics/, categories/     tag topics, the AI topics of the knowledge map (library/map_engine.py), categories
  README.md                generated-folder notice
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

MANAGED_SUBDIRS = ('items', 'reports', 'attachments', 'notes', 'topics', 'categories')

RELATED_K = 6              # max Related links per item
RELATED_MIN_SCORE = 0.35   # cosine floor; below this, neighbors are noise
TAG_MIN_COUNT = 3          # fallback tag filter when no tag map exists (plan 02 not run)


def _slugify(text: str) -> str:
    text = (text or '').strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text).strip('-')
    return text or 'untitled'


def _epoch_to_iso(value) -> str:
    """Items store created/modified as epoch seconds. Return 'YYYY-MM-DD' or ''."""
    if not value:
        return ''
    try:
        return datetime.fromtimestamp(int(value)).strftime('%Y-%m-%d')
    except Exception:
        return ''


def _yaml_value(v) -> str:
    """Quote a scalar if it contains YAML-significant characters.

    Frontmatter scalars must stay on one line, so newlines/tabs (which can leak in
    from scraped fields like creator) are collapsed to single spaces first."""
    s = re.sub(r'\s+', ' ', str(v)).strip()
    if s == '':
        return '""'
    if re.search(r'[:#\[\]{}",\']', s) or s[0] in '!&*?|>%@`':
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s


def _link_text(s: str) -> str:
    """Sanitize text used as a wikilink alias: [[target|alias]] breaks on [ ] |."""
    return re.sub(r'[\[\]|]', '', re.sub(r'\s+', ' ', s or '')).strip()[:80] or 'untitled'


def _canonical_tags(raw_tags, tag_map, tag_counts) -> list:
    """Map raw tags to canonical topic names.

    tag_map (plan 02, {lowercase_raw: canonical_or_None}): value None or missing key
    means dropped. Without a map: keep the tag only if used by >= TAG_MIN_COUNT items.
    Returns deduped canonical names, first-seen order (dedupe key is the slug so
    'Martial Arts' and 'martial-arts' merge)."""
    out, seen = [], set()
    for t in raw_tags:
        key = t.strip().lower()
        if not key:
            continue
        if tag_map is not None:
            name = tag_map.get(key)
            if not name:
                continue
        else:
            if tag_counts.get(key, 0) < TAG_MIN_COUNT:
                continue
            name = key
        s = _slugify(name)
        if s and s not in seen:
            seen.add(s)
            out.append(name)
    return out


def _item_markdown(item: dict) -> str:
    fm = ['---', f"id: {item['id']}", f"url: {_yaml_value(item.get('url', ''))}"]
    if item.get('creator'):
        fm.append(f"creator: {_yaml_value(item['creator'])}")
    fm.append(f"type: {_yaml_value(item.get('type', '') or 'Item')}")
    if item.get('category'):
        fm.append(f"category: {_yaml_value(item['category'])}")
    tags = item.get('tags') or []
    if tags:
        fm.append('tags: [' + ', '.join(_yaml_value(t) for t in tags) + ']')
    if item.get('created_iso'):
        fm.append(f"created: {item['created_iso']}")
    fm.append('source: content-manager')
    fm.append('---')

    parts = ['\n'.join(fm), '']
    if item.get('thumb_name'):
        parts.append(f"![[attachments/{item['thumb_name']}]]")
        parts.append('')
    parts.append((item.get('body') or '').strip() or '—')

    topic_links = [f"[[topics/{t['slug']}|{_link_text(t['name'])}]]"
                   for t in item.get('topics', [])]
    if item.get('category'):
        topic_links.append(
            f"[[categories/{_slugify(item['category'])}|{_link_text(item['category'])}]]")
    if topic_links:
        parts.append('')
        parts.append('## Topics')
        parts.append(' '.join(topic_links))

    if item.get('related'):
        parts.append('')
        parts.append('## Related')
        for r in item['related']:
            parts.append(f"- [[items/{r['stem']}|{_link_text(r['title'])}]]")

    if item.get('report_name'):
        stem = Path(item['report_name']).stem
        parts.append('')
        parts.append(f"[[reports/{stem}|Analysis report]]")
    return '\n'.join(parts).rstrip() + '\n'


def _topic_markdown(slug: str, topic: dict) -> str:
    fm = ['---',
          f"kind: {'ai-topic' if topic.get('kind') == 'ai' else 'tag-topic'}",
          f"items: {len(topic['members'])}",
          'source: content-manager',
          '---']
    parts = ['\n'.join(fm), '', f"# {_link_text(topic['name'])}"]
    if topic.get('body'):
        parts.append('')
        parts.append(topic['body'].strip())
    parts.append('')
    parts.append(f"## Items ({len(topic['members'])})")
    for stem in sorted(topic['members'],
                       key=lambda s: topic['member_titles'].get(s, '').lower()):
        parts.append(f"- [[items/{stem}|{_link_text(topic['member_titles'].get(stem, stem))}]]")
    return '\n'.join(parts).rstrip() + '\n'


def _category_markdown(slug: str, cat: dict, topics: dict) -> str:
    fm = ['---', 'kind: category', f"items: {len(cat['members'])}",
          'source: content-manager', '---']
    parts = ['\n'.join(fm), '', f"# {_link_text(cat['name'])}"]
    tslugs = [s for s in cat.get('topic_slugs', []) if s in topics]
    tslugs.sort(key=lambda s: -len(topics[s]['members']))
    if tslugs:
        parts.append('')
        parts.append('## Topics')
        for s in tslugs:
            parts.append(f"- [[topics/{s}|{_link_text(topics[s]['name'])}]] "
                         f"({len(topics[s]['members'])} items)")
    parts.append('')
    parts.append(f"## Items ({len(cat['members'])})")
    for stem in sorted(cat['members'],
                       key=lambda s: cat['member_titles'].get(s, '').lower()):
        parts.append(f"- [[items/{stem}|{_link_text(cat['member_titles'].get(stem, stem))}]]")
    return '\n'.join(parts).rstrip() + '\n'


def _knowledge_map_markdown(payload: dict) -> str:
    m = payload['map']
    topics = payload['topics']
    categories = payload['categories']
    parts = ['# Knowledge Map', '',
             f"Generated by Brainamon on {m['generated']}. "
             f"{m['item_count']} items.", '',
             '## Categories']
    for s in m['category_slugs']:
        parts.append(f"- [[categories/{s}|{_link_text(categories[s]['name'])}]] "
                     f"({len(categories[s]['members'])} items)")
    ai_slugs = [s for s in m['topic_slugs'] if topics[s].get('kind') == 'ai']
    tag_slugs = [s for s in m['topic_slugs'] if topics[s].get('kind') != 'ai'][:40]
    if ai_slugs:
        parts.append('')
        parts.append('## Synthesized topics')
        for s in ai_slugs:
            parts.append(f"- [[topics/{s}|{_link_text(topics[s]['name'])}]] "
                         f"({len(topics[s]['members'])} items)")
    if tag_slugs:
        parts.append('')
        parts.append('## Topics')
        for s in tag_slugs:
            parts.append(f"- [[topics/{s}|{_link_text(topics[s]['name'])}]] "
                         f"({len(topics[s]['members'])} items)")
    return '\n'.join(parts).rstrip() + '\n'


def build_obsidian_payload(db, embed_index=None, tag_map=None, ai_topics=None) -> dict:
    """Read the library (main thread) and resolve source paths into plain dicts.

    embed_index: search.EmbeddingIndex or None -> Related links.
    tag_map:     {lowercase_raw_tag: canonical_or_None} from DB settings
                 'obsidian_tag_map' (plan 02), or None -> frequency filter.
    ai_topics:   [{'key','title','synthesis','member_ids'}] from the graph cache
                 (plan 03), or None.
    Returns {'items','notes','topics','categories','map'} with no file bytes read.
    """
    items = []
    by_id = {}
    tag_counts = {}
    for r in db.search_items():
        item_id = r['id']

        thumb_src = None
        thumb_name = None
        tp = r.get('thumb_path') or ''
        if tp:
            cand = db.thumbs_dir / tp
            if cand.exists():
                thumb_src = str(cand)
        if not thumb_src:
            cand = db.items_dir / str(item_id) / 'thumb.jpg'
            if cand.exists():
                thumb_src = str(cand)
        if thumb_src:
            thumb_name = f"{item_id}.jpg"

        report_src = None
        report_name = None
        if r.get('analysis_done') and r.get('analysis_path'):
            rp = Path(r['analysis_path'])
            if rp.exists():
                report_src = str(rp)
                report_name = f"{item_id}.md"

        tags = [t.strip() for t in (r.get('tags') or '').split(',') if t.strip()]
        for t in tags:
            k = t.lower()
            tag_counts[k] = tag_counts.get(k, 0) + 1
        title = r.get('short_desc') or r.get('ai_desc') or r.get('description') or f"item-{item_id}"
        slug = _slugify(title[:60])
        stem = f"{slug}-{item_id}"

        items.append({
            'id': item_id,
            'url': r.get('url', ''),
            'creator': r.get('creator', ''),
            'type': r.get('type', ''),
            'category': r.get('category', ''),
            'tags': tags,
            'created_iso': _epoch_to_iso(r.get('created') or r.get('modified')),
            'body': r.get('ai_desc') or r.get('description') or '',
            'title': title,
            'stem': stem,
            'filename': f"{stem}.md",
            'thumb_src': thumb_src,
            'thumb_name': thumb_name,
            'report_src': report_src,
            'report_name': report_name,
            'topics': [],      # [{'slug','name'}] filled below
            'related': [],     # [{'stem','title'}] filled below
        })
        by_id[item_id] = items[-1]

    topics = {}      # slug -> {'name','kind','members','member_titles','body','topic_slugs'}
    categories = {}  # same shape, kind 'category'

    def _add_member(registry, slug, name, item, kind='tag'):
        entry = registry.get(slug)
        if entry is None:
            entry = registry[slug] = {'name': name, 'kind': kind, 'members': [],
                                      'member_titles': {}, 'body': None,
                                      'topic_slugs': []}
        if item['stem'] not in entry['member_titles']:
            entry['members'].append(item['stem'])
            entry['member_titles'][item['stem']] = item['title']
        return entry

    for item in items:
        for name in _canonical_tags(item['tags'], tag_map, tag_counts):
            slug = _slugify(name)
            _add_member(topics, slug, name, item)
            item['topics'].append({'slug': slug, 'name': name})
        if item['category']:
            cslug = _slugify(item['category'])
            centry = _add_member(categories, cslug, item['category'], item,
                                 kind='category')
            for t in item['topics']:
                if t['slug'] not in centry['topic_slugs']:
                    centry['topic_slugs'].append(t['slug'])

    for cluster in (ai_topics or []):
        name = (cluster.get('title') or '').strip() or f"topic {cluster.get('key', '')[:8]}"
        slug = 'ai-' + _slugify(name)
        for member_id in cluster.get('member_ids', []):
            item = by_id.get(member_id)
            if item is None:
                continue   # item deleted since the synthesis run
            entry = _add_member(topics, slug, name, item, kind='ai')
            entry['body'] = cluster.get('synthesis') or None
            if not any(t['slug'] == slug for t in item['topics']):
                item['topics'].append({'slug': slug, 'name': name})

    if embed_index is not None and len(embed_index) > 0:
        for item in items:
            for other_id, score in embed_index.similar_to(item['id'], k=RELATED_K):
                if score < RELATED_MIN_SCORE:
                    continue
                other = by_id.get(other_id)
                if other is not None:
                    item['related'].append({'stem': other['stem'],
                                            'title': other['title']})

    notes = []
    if getattr(db, 'notes_dir', None) and db.notes_dir.exists():
        notes = [str(p) for p in sorted(db.notes_dir.glob('*.md'))]

    return {
        'items': items,
        'notes': notes,
        'topics': topics,
        'categories': categories,
        'map': {
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'item_count': len(items),
            'category_slugs': sorted(
                categories, key=lambda s: (-len(categories[s]['members']), s)),
            'topic_slugs': sorted(
                topics, key=lambda s: (-len(topics[s]['members']), s)),
        },
    }


README_TEXT = (
    "# Brainamon export\n\n"
    "This folder is generated by Brainamon's classic Export to Obsidian and is OVERWRITTEN on every export.\n"
    "The items/, reports/, attachments/, notes/, topics/, and categories/ subfolders\n"
    "are wiped and regenerated each run, and Knowledge Map.md is rewritten. Do not\n"
    "edit files here by hand - changes will be lost. Edit your content in Brainamon\n"
    "and re-export. For a vault that Brainamon keeps up to date on its own and that\n"
    "respects your edits, set up a Brainamon vault in Settings > Obsidian.\n\n"
    "Start browsing from [[Knowledge Map]].\n"
)


def _put_text(path: Path, text: str, written: set) -> None:
    """Write `text` unless the file already holds exactly those bytes (vault sync watches this folder)."""
    written.add(path)
    data = text.encode('utf-8')
    try:
        if path.read_bytes() == data:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _put_copy(src, dst: Path, written: set) -> None:
    written.add(dst)
    try:
        data = Path(src).read_bytes()
        if dst.exists() and dst.read_bytes() == data:
            return
    except OSError:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _sweep(base: Path, written: set) -> None:
    """Remove managed files this run did not write (an item deleted since the last export)."""
    for sub in MANAGED_SUBDIRS:
        for p in (base / sub).rglob('*'):
            if p.is_file() and p not in written:
                p.unlink()


def write_obsidian_vault(payload: dict, vault_dir, progress=None):
    """Write the payload into <vault_dir>/Content Manager/. Filesystem only - no DB.
    Returns (items_written, errors) where errors is a list of (label, message)."""
    base = Path(vault_dir) / 'Content Manager'
    base.mkdir(parents=True, exist_ok=True)
    written = set()
    for sub in MANAGED_SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    _put_text(base / 'README.md', README_TEXT, written)

    items = payload.get('items', [])
    notes = payload.get('notes', [])
    topics = payload.get('topics', {})
    categories = payload.get('categories', {})
    total = (len(items) + len(notes) + len(topics) + len(categories)
             + (1 if payload.get('map') else 0))
    done = 0
    count = 0
    errors = []

    for item in items:
        try:
            if item.get('thumb_src') and item.get('thumb_name'):
                try:
                    _put_copy(item['thumb_src'], base / 'attachments' / item['thumb_name'], written)
                except Exception as e:
                    errors.append((f"thumb {item['id']}", str(e)))
            if item.get('report_src') and item.get('report_name'):
                try:
                    _put_copy(item['report_src'], base / 'reports' / item['report_name'], written)
                except Exception as e:
                    errors.append((f"report {item['id']}", str(e)))
            _put_text(base / 'items' / item['filename'], _item_markdown(item), written)
            count += 1
        except Exception as e:
            errors.append((f"item {item.get('id')}", str(e)))
        done += 1
        if progress:
            progress(done, total)

    for note_path in notes:
        try:
            p = Path(note_path)
            _put_copy(p, base / 'notes' / p.name, written)
        except Exception as e:
            errors.append((f"note {Path(note_path).name}", str(e)))
        done += 1
        if progress:
            progress(done, total)

    for slug, topic in topics.items():
        try:
            _put_text(base / 'topics' / f"{slug}.md", _topic_markdown(slug, topic), written)
        except Exception as e:
            errors.append((f"topic {slug}", str(e)))
        done += 1
        if progress:
            progress(done, total)

    for slug, cat in categories.items():
        try:
            _put_text(base / 'categories' / f"{slug}.md", _category_markdown(slug, cat, topics), written)
        except Exception as e:
            errors.append((f"category {slug}", str(e)))
        done += 1
        if progress:
            progress(done, total)

    if payload.get('map'):
        try:
            _put_text(base / 'Knowledge Map.md', _knowledge_map_markdown(payload), written)
        except Exception as e:
            errors.append(('knowledge-map', str(e)))
        done += 1
        if progress:
            progress(done, total)

    _sweep(base, written)
    return count, errors
