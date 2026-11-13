"""
db.py — SQLite database layer for Brainamon.
"""

import sqlite3, json, re, time, uuid
from pathlib import Path
from typing import Optional
from core.urls import facebook_post_key, http_url

# Conversational filler dropped from FTS queries so a natural-language question
# ("what do we have for knee injuries?") matches on its content words only.
_FTS_STOPWORDS = frozenset("""
a an the and or of to for in on at by with from into about as is are was were be been
i me my we our us you your he she they them his her their it its this that these those there here
do does did have has had can could would should will shall may might must
what which who whom whose how why when where
give find show tell help please want need looking seeking related any some all
content stuff things up
le la les de des du un une et ou pour avec sur dans est que qui quoi comment
""".split())


def fts_terms(query: str) -> list:
    """The content words of free text: split on non-word characters, lowercased,
    stopwords and 1-char words dropped, deduped in order. Falls back to every word
    when the text is all filler (e.g. "test it")."""
    words = re.findall(r'\w+', (query or '').lower())
    keep = [w for w in words if w not in _FTS_STOPWORDS and len(w) > 1]
    if not keep:
        keep = [w for w in words if len(w) > 1] or words
    return list(dict.fromkeys(keep))


def fts_match_query(query: str, match_all: bool = False) -> str:
    """Build a safe FTS5 MATCH expression from free text.

    Uses fts_terms (so '?', ',', '-' and quotes can never cause an FTS5 syntax
    error) and prefix-matches each word. match_all=False ORs the words (bm25 ranks
    items matching more words higher) - right for ranked retrieval over questions.
    match_all=True ANDs them - right for narrowing filters (Library search box, topic
    digests). Empty string when the query has no usable words."""
    return (' AND ' if match_all else ' OR ').join(f'"{w}"*' for w in fts_terms(query))


class Database:

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.db_path.parent          # data/
        self.items_dir = self.data_dir / 'items'
        self.items_dir.mkdir(exist_ok=True)
        # Legacy flat dirs — kept for the migration step; callers should use item_dir()
        self.thumbs_dir = self.data_dir / 'thumbs'
        self.reels_dir  = self.data_dir / 'reels'
        self.analysis_dir = self.data_dir / 'analysis'
        self.notes_dir = self.data_dir / 'notes'   # Knowledge-wiki synthesis notes (created on demand)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self._migrate()

    def item_dir(self, item_id: int) -> Path:
        """Return data/items/<id>/ and create it if needed."""
        d = self.items_dir / str(item_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _create_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                short_desc  TEXT DEFAULT '',
                creator     TEXT DEFAULT '',
                type        TEXT DEFAULT 'Reel',
                category    TEXT DEFAULT 'INTERESTING',
                prefix      TEXT DEFAULT '',
                tags        TEXT DEFAULT '',
                ai_desc     TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                thumb_path  TEXT DEFAULT '',
                thumb_source TEXT DEFAULT '',
                source      TEXT DEFAULT 'manual',
                processed   INTEGER DEFAULT 0,
                created     INTEGER,
                modified    INTEGER
            );

            CREATE TABLE IF NOT EXISTS categories (
                name       TEXT PRIMARY KEY,
                color      TEXT NOT NULL DEFAULT '#888888',
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

        """)
        self.conn.commit()

    def _migrate(self):
        """Run schema and data migrations for older database files."""
        import shutil as _shutil, base64 as _b64
        c = self.conn.cursor()

        # Get existing columns
        cols = {r[1] for r in c.execute("PRAGMA table_info(items)").fetchall()}

        # 1. Add any missing columns
        column_defs = {
            'description':   "ALTER TABLE items ADD COLUMN description TEXT DEFAULT ''",
            'short_desc':    "ALTER TABLE items ADD COLUMN short_desc TEXT DEFAULT ''",
            'creator':       "ALTER TABLE items ADD COLUMN creator TEXT DEFAULT ''",
            'type':          "ALTER TABLE items ADD COLUMN type TEXT DEFAULT 'Reel'",
            'category':      "ALTER TABLE items ADD COLUMN category TEXT DEFAULT 'INTERESTING'",
            'prefix':        "ALTER TABLE items ADD COLUMN prefix TEXT DEFAULT ''",
            'tags':          "ALTER TABLE items ADD COLUMN tags TEXT DEFAULT ''",
            'ai_desc':       "ALTER TABLE items ADD COLUMN ai_desc TEXT DEFAULT ''",
            'notes':         "ALTER TABLE items ADD COLUMN notes TEXT DEFAULT ''",
            'thumb_path':    "ALTER TABLE items ADD COLUMN thumb_path TEXT DEFAULT ''",
            'thumb_source':  "ALTER TABLE items ADD COLUMN thumb_source TEXT DEFAULT ''",
            'source':        "ALTER TABLE items ADD COLUMN source TEXT DEFAULT 'manual'",
            'processed':     "ALTER TABLE items ADD COLUMN processed INTEGER DEFAULT 0",
            'created':       "ALTER TABLE items ADD COLUMN created INTEGER",
            'modified':      "ALTER TABLE items ADD COLUMN modified INTEGER",
            'analysis_done': "ALTER TABLE items ADD COLUMN analysis_done INTEGER DEFAULT 0",
            'analysis_path': "ALTER TABLE items ADD COLUMN analysis_path TEXT DEFAULT ''",
            'transcript':    "ALTER TABLE items ADD COLUMN transcript TEXT DEFAULT ''",
            # V6 favourites (holo cards); the Qt app ignores it
            'favourite':     "ALTER TABLE items ADD COLUMN favourite INTEGER DEFAULT 0",
        }
        for col, sql in column_defs.items():
            if col not in cols:
                c.execute(sql)
        self.conn.commit()

        # Indexes that depend on migrated columns must be created after the
        # ALTER TABLE pass, otherwise very old DBs fail before migration starts.
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_processed ON items(processed)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_created ON items(created)")
        self.conn.commit()

        # Refresh columns after potential additions
        cols = {r[1] for r in c.execute("PRAGMA table_info(items)").fetchall()}

        # 2. Extract any remaining thumb_b64 blobs to files
        if 'thumb_b64' in cols:
            # Back up DB first (once)
            backup = self.db_path.parent / (self.db_path.stem + '_backup_pre_migration.db')
            if not backup.exists():
                try:
                    _shutil.copy2(str(self.db_path), str(backup))
                except Exception:
                    pass
            rows = c.execute(
                "SELECT id, thumb_b64 FROM items "
                "WHERE thumb_b64 IS NOT NULL AND thumb_b64 != '' "
                "AND (thumb_path IS NULL OR thumb_path = '')"
            ).fetchall()
            for row in rows:
                item_id, b64 = row[0], row[1]
                if not b64 or len(b64) < 100:
                    continue
                try:
                    self.thumbs_dir.mkdir(parents=True, exist_ok=True)
                    img_data = _b64.b64decode(b64)
                    thumb_file = self.thumbs_dir / f'{item_id}.jpg'
                    with open(thumb_file, 'wb') as tf:
                        tf.write(img_data)
                    c.execute(
                        "UPDATE items SET thumb_path = ?, thumb_b64 = '' WHERE id = ?",
                        (f'{item_id}.jpg', item_id)
                    )
                except Exception:
                    pass
            if rows:
                self.conn.commit()

        # 3. Copy non-empty prefix values into tags
        try:
            rows = c.execute(
                "SELECT id, prefix, tags FROM items "
                "WHERE prefix IS NOT NULL AND prefix != ''"
            ).fetchall()
            for item_id, prefix_val, existing_tags in rows:
                prefix_val = (prefix_val or '').strip()
                existing_tags = (existing_tags or '').strip()
                if prefix_val and prefix_val not in existing_tags:
                    new_tags = (existing_tags + ', ' + prefix_val).strip(', ')
                    c.execute(
                        "UPDATE items SET tags = ?, prefix = '' WHERE id = ?",
                        (new_tags, item_id)
                    )
            if rows:
                self.conn.commit()
        except Exception:
            pass

        # 3b. A collection can be hidden from the main Library feed (NSFW)
        if 'hidden' not in {r[1] for r in c.execute("PRAGMA table_info(categories)").fetchall()}:
            c.execute("ALTER TABLE categories ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

        # 5. Migrate to per-item folder layout (data/items/<id>/)
        self._migrate_to_item_dirs(c)

        # 6. FTS5 full-text index
        self._setup_fts(c)

        # 7. Semantic-search embeddings + standing topics
        c.execute("""
            CREATE TABLE IF NOT EXISTS item_embeddings (
                item_id   INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                model     TEXT NOT NULL,
                dim       INTEGER NOT NULL,
                text_hash TEXT NOT NULL,
                vector    BLOB NOT NULL,
                updated   INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT UNIQUE NOT NULL,
                query     TEXT NOT NULL,
                note_path TEXT DEFAULT '',
                last_run  INTEGER,
                created   INTEGER
            )
        """)
        self.conn.commit()

        # 8. FTS index over the saved knowledge notes (data/notes/*.md). Notes are
        # plain files (no source table, no triggers), so the index is rebuilt in
        # full: here at startup and after every note save/rename/delete.
        c.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts "
            "USING fts5(filename UNINDEXED, topic, body)"
        )
        self.conn.commit()
        self.reindex_notes()

        # 9. Library assistant (Ask Deep mode, projects/library-assistant): websites and
        # tools mentioned in items, and embeddings for topic + note-section texts.
        c.executescript("""
            CREATE TABLE IF NOT EXISTS resources (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                domain  TEXT NOT NULL,
                url     TEXT NOT NULL,
                context TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_resources_item ON resources(item_id);
            CREATE INDEX IF NOT EXISTS idx_resources_domain ON resources(domain);
            CREATE TABLE IF NOT EXISTS aux_embeddings (
                key       TEXT PRIMARY KEY,
                kind      TEXT NOT NULL,
                model     TEXT NOT NULL,
                dim       INTEGER NOT NULL,
                text_hash TEXT NOT NULL,
                vector    BLOB NOT NULL,
                payload   TEXT NOT NULL,
                updated   INTEGER
            );
        """)
        self.conn.commit()

        # 10. Google Drive mirror (projects/mobile-app/PLAN.md Phase 3). items.uid names an item in
        # the mirror (a phone-saved link has one before the PC gives it an id); add_item (the only
        # insert path) sets it, rows without one are filled here. No trigger: an UPDATE fired from
        # an insert trigger would run items_au before items_ai and break the FTS index.
        # sync_state records what was published: one row per mirror file (its content signature
        # and its Drive file id).
        if 'uid' not in cols:
            c.execute("ALTER TABLE items ADD COLUMN uid TEXT")
        c.execute("UPDATE items SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL OR uid = ''")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_items_uid ON items(uid)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                name     TEXT PRIMARY KEY,
                sig      TEXT NOT NULL,
                drive_id TEXT NOT NULL,
                size     INTEGER DEFAULT 0,
                at       INTEGER
            )
        """)
        self.conn.commit()

    # ── Drive mirror state (server/sync.py loads and saves it on the Writer) ──
    def get_sync_state(self) -> dict:
        return {r['name']: {'sig': r['sig'], 'drive_id': r['drive_id'], 'size': r['size']}
                for r in self.conn.execute("SELECT name, sig, drive_id, size FROM sync_state")}

    def save_sync_state(self, put: dict, drop=()) -> None:
        """put: {name: {'sig', 'drive_id', 'size'}}; drop: names no longer in the mirror."""
        now = int(time.time() * 1000)
        c = self.conn.cursor()
        for name in drop:
            c.execute("DELETE FROM sync_state WHERE name = ?", (name,))
        for name, s in put.items():
            c.execute("INSERT OR REPLACE INTO sync_state (name, sig, drive_id, size, at) VALUES (?, ?, ?, ?, ?)",
                      (name, s['sig'], s['drive_id'], int(s.get('size') or 0), now))
        self.conn.commit()

    def clear_sync_state(self) -> None:
        self.conn.execute("DELETE FROM sync_state")
        self.conn.commit()

    def _migrate_to_item_dirs(self, c):
        """Move flat thumbs/reels/analysis dirs into data/items/<id>/. Idempotent."""
        import shutil as _sh, os as _os
        old_thumbs   = self.data_dir / 'thumbs'
        old_reels    = self.data_dir / 'reels'
        old_analysis = self.data_dir / 'analysis'

        # ── thumbnails ────────────────────────────────────────────────────────
        if old_thumbs.exists():
            rows = c.execute(
                "SELECT id, thumb_path FROM items "
                "WHERE thumb_path IS NOT NULL AND thumb_path != '' AND thumb_path != 'thumb.jpg'"
            ).fetchall()
            updated = False
            for item_id, tp in rows:
                src = old_thumbs / tp
                if tp != f'{item_id}.jpg' or old_thumbs.is_symlink() or old_thumbs.is_junction() or src.is_symlink() or src.is_junction() or src.resolve().parent != old_thumbs.resolve():
                    continue
                if src.is_file():
                    try:
                        from PIL import Image
                        with Image.open(src) as image:
                            image.verify()
                    except (OSError, ValueError):
                        continue
                    directory = self.items_dir / str(item_id)
                    if any(p.is_symlink() or p.is_junction() for p in (self.items_dir, directory)) or directory.resolve().parent != self.items_dir.resolve():
                        continue
                    dest = self.item_dir(item_id) / 'thumb.jpg'
                    if dest.is_symlink() or dest.is_junction():
                        continue
                    if not dest.exists():
                        _sh.move(str(src), str(dest))
                    c.execute("UPDATE items SET thumb_path = 'thumb.jpg' WHERE id = ?", (item_id,))
                    updated = True
            if updated:
                self.conn.commit()

        # ── analysis dirs ─────────────────────────────────────────────────────
        if old_analysis.exists():
            for analysis_subdir in old_analysis.iterdir():
                if not analysis_subdir.is_dir():
                    continue
                try:
                    item_id = int(analysis_subdir.name)
                except ValueError:
                    continue
                dest_dir = self.item_dir(item_id)
                for f in analysis_subdir.iterdir():
                    dest_f = dest_dir / f.name
                    if not dest_f.exists():
                        if f.is_dir():
                            _sh.copytree(str(f), str(dest_f))
                        else:
                            _sh.move(str(f), str(dest_f))
            # Update analysis_path column to point to new report.md location
            rows2 = c.execute(
                "SELECT id, analysis_path FROM items "
                "WHERE analysis_path IS NOT NULL AND analysis_path != ''"
            ).fetchall()
            updated2 = False
            for item_id, ap in rows2:
                if _os.sep + 'analysis' + _os.sep in ap or '/analysis/' in ap:
                    new_report = self.item_dir(item_id) / 'report.md'
                    if new_report.exists():
                        c.execute("UPDATE items SET analysis_path = ? WHERE id = ?",
                                  (str(new_report), item_id))
                        updated2 = True
            if updated2:
                self.conn.commit()

        # ── video/reels dirs ─────────────────────────────────────────────────
        if old_reels.exists():
            for reel_subdir in old_reels.iterdir():
                if not reel_subdir.is_dir():
                    continue
                try:
                    item_id = int(reel_subdir.name)
                except ValueError:
                    continue
                dest_video = self.item_dir(item_id) / 'video'
                if not dest_video.exists():
                    _sh.move(str(reel_subdir), str(dest_video))

    def _setup_fts(self, c=None):
        """Create FTS5 virtual table and sync triggers; rebuild index if newly created."""
        if c is None:
            c = self.conn.cursor()

        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        fts_new = 'items_fts' not in tables

        if fts_new:
            c.execute("""
                CREATE VIRTUAL TABLE items_fts USING fts5(
                    description, ai_desc, transcript, creator, tags,
                    content='items', content_rowid='id'
                )
            """)

        triggers = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}

        if 'items_ai' not in triggers:
            c.execute("""
                CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
                    INSERT INTO items_fts(rowid, description, ai_desc, transcript, creator, tags)
                    VALUES (new.id, COALESCE(new.description,''), COALESCE(new.ai_desc,''),
                            COALESCE(new.transcript,''), COALESCE(new.creator,''), COALESCE(new.tags,''));
                END
            """)

        if 'items_ad' not in triggers:
            c.execute("""
                CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, description, ai_desc, transcript, creator, tags)
                    VALUES ('delete', old.id, COALESCE(old.description,''), COALESCE(old.ai_desc,''),
                            COALESCE(old.transcript,''), COALESCE(old.creator,''), COALESCE(old.tags,''));
                END
            """)

        if 'items_au' not in triggers:
            c.execute("""
                CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, description, ai_desc, transcript, creator, tags)
                    VALUES ('delete', old.id, COALESCE(old.description,''), COALESCE(old.ai_desc,''),
                            COALESCE(old.transcript,''), COALESCE(old.creator,''), COALESCE(old.tags,''));
                    INSERT INTO items_fts(rowid, description, ai_desc, transcript, creator, tags)
                    VALUES (new.id, COALESCE(new.description,''), COALESCE(new.ai_desc,''),
                            COALESCE(new.transcript,''), COALESCE(new.creator,''), COALESCE(new.tags,''));
                END
            """)

        if fts_new:
            c.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")

        self.conn.commit()

    # ── Items ──────────────────────────────────────────────────────────────
    def add_item(self, data: dict) -> int:
        url = data.get('url', '')
        if facebook_post_key(url) and self.item_exists(url):
            raise sqlite3.IntegrityError('This Facebook post is already in the library.')
        now = int(time.time() * 1000)
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO items (
                url, description, short_desc, creator, type,
                category, prefix, tags, ai_desc,
                thumb_path, thumb_source, source,
                processed, created, modified, uid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('url', ''),
            data.get('description', ''),
            data.get('short_desc', ''),
            data.get('creator', ''),
            data.get('type', 'Reel'),
            data.get('category', 'INTERESTING'),
            '',  # prefix deprecated — use tags
            data.get('tags', ''),
            data.get('ai_desc', ''),
            data.get('thumb_path', ''),
            data.get('thumb_source', ''),
            data.get('source', 'manual'),
            1 if data.get('processed') else 0,
            data.get('created') or now,
            now,
            data.get('uid') or uuid.uuid4().hex,
        ))
        self.conn.commit()
        return c.lastrowid

    def update_item(self, item_id: int, data: dict):
        now = int(time.time() * 1000)
        allowed = {
            'url', 'description', 'short_desc', 'creator', 'type', 'category',
            'prefix', 'tags', 'ai_desc', 'notes', 'thumb_path', 'thumb_source', 'processed',
            'analysis_done', 'analysis_path', 'transcript', 'favourite',
        }
        fields, values = [], []
        bool_cols = {'processed', 'analysis_done', 'favourite'}
        for k, v in data.items():
            if k in allowed:
                fields.append(f"{k} = ?")
                values.append(1 if k in bool_cols and v else (0 if k in bool_cols else v))
        if not fields:
            return
        fields.append("modified = ?")
        values.extend([now, item_id])
        self.conn.cursor().execute(
            f"UPDATE items SET {', '.join(fields)} WHERE id = ?", values
        )
        self.conn.commit()

    # Fields the bulk editor may set directly (simple overwrite).
    BULK_SETTABLE = {'category', 'type', 'creator'}

    def set_field_bulk(self, item_ids, field: str, value: str) -> int:
        """Set one whitelisted field on many items in a single transaction. Returns row count.

        Far cheaper than per-id update_item (each commits). Used by the bulk-edit dialog."""
        if field not in self.BULK_SETTABLE:
            raise ValueError(f'field not bulk-settable: {field}')
        ids = [int(i) for i in item_ids]
        if not ids:
            return 0
        now = int(time.time() * 1000)
        self.conn.cursor().executemany(
            f"UPDATE items SET {field} = ?, modified = ? WHERE id = ?",
            [(value, now, i) for i in ids],
        )
        self.conn.commit()
        return len(ids)

    def set_category_bulk(self, item_ids, category: str) -> int:
        """Back-compat shim: set category on many items. See set_field_bulk."""
        return self.set_field_bulk(item_ids, 'category', category)

    @staticmethod
    def _split_tags(s: str) -> list:
        return [t.strip() for t in (s or '').split(',') if t.strip()]

    def modify_tags_bulk(self, item_ids, mode: str, tags: str) -> int:
        """Add or remove tags on many items in one transaction. mode in {'add','remove'}.
        Tags are comma-separated; add dedupes/preserves order, remove is case-insensitive."""
        if mode not in ('add', 'remove'):
            raise ValueError(f'bad tag mode: {mode}')
        delta = self._split_tags(tags)
        ids = [int(i) for i in item_ids]
        if not ids or not delta:
            return 0
        now = int(time.time() * 1000)
        c = self.conn.cursor()
        rows = c.execute(
            f"SELECT id, tags FROM items WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        updates = []
        for r in rows:
            current = self._split_tags(r['tags'])
            if mode == 'add':
                lower = {t.lower() for t in current}
                current += [t for t in delta if t.lower() not in lower]
                new = current
            else:  # remove
                drop = {t.lower() for t in delta}
                new = [t for t in current if t.lower() not in drop]
            updates.append((', '.join(new), now, r['id']))
        c.executemany("UPDATE items SET tags = ?, modified = ? WHERE id = ?", updates)
        self.conn.commit()
        return len(updates)

    def delete_items_bulk(self, item_ids, folders: bool = True) -> int:
        """Delete many items (rows + their data/items/<id>/ folders) in one transaction. folders=False keeps the
        folders for a caller that removes them after its own commit (server/delivery.py)."""
        import shutil as _shutil
        ids = [int(i) for i in item_ids]
        if not ids:
            return 0
        self.conn.cursor().executemany("DELETE FROM items WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()
        for i in ids if folders else ():
            try:
                _shutil.rmtree(self.items_dir / str(i), ignore_errors=True)  # don't recreate via item_dir()
            except Exception:
                pass
        return len(ids)

    def delete_item(self, item_id: int):
        self.conn.cursor().execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn.commit()

    def get_item(self, item_id: int) -> Optional[dict]:
        row = self.conn.cursor().execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_item_thumb(self, item_id: int) -> str:
        row = self.conn.cursor().execute(
            "SELECT thumb_path FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return row[0] if row else ''

    def has_thumb(self, item_id: int) -> bool:
        thumb_path = self.get_item_thumb(item_id)
        if not thumb_path:
            return False
        return (self.item_dir(item_id) / 'thumb.jpg').exists()

    def item_exists(self, url: str) -> bool:
        return self.get_item_by_url(url) is not None

    def get_item_by_url(self, url: str) -> Optional[dict]:
        row = self.conn.execute('SELECT * FROM items WHERE url = ?', (url,)).fetchone()
        if row:
            return dict(row)
        key = facebook_post_key(url)
        if key:
            # Match old stored URLs too, without rewriting links or merging existing items.
            for row in self.conn.execute("SELECT id, url FROM items WHERE url LIKE ? OR instr(url, '%') > 0 ORDER BY id",
                                         ('%' + key[3:] + '%',)):
                if facebook_post_key(row['url']) == key:
                    return self.get_item(row['id'])
        return None

    def count_items(self, category: str = None) -> int:
        c = self.conn.cursor()
        if category and category != 'ALL':
            row = c.execute(
                "SELECT COUNT(*) FROM items WHERE category = ?", (category,)
            ).fetchone()
        else:
            row = c.execute("SELECT COUNT(*) FROM items").fetchone()
        return row[0]

    def count_by_category(self) -> dict:
        rows = self.conn.cursor().execute(
            "SELECT category, COUNT(*) FROM items GROUP BY category"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_all_tags(self) -> list:
        rows = self.conn.cursor().execute(
            "SELECT tags FROM items WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()
        counts = {}
        for row in rows:
            for tag in (row[0] or '').split(','):
                t = tag.strip()
                if t:
                    counts[t] = counts.get(t, 0) + 1
        return sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    def search_items(
        self,
        category: str = 'ALL',
        query: str = '',
        type_filter: str = 'ALL',
        only_pending: bool = False,
        sort: str = 'new',
        include_thumbs: bool = False,
        tag_filter: str = '',
        status_filter: list = None
    ) -> list:
        clauses, params = [], []

        if category and category != 'ALL':
            clauses.append("category = ?")
            params.append(category)
        if type_filter and type_filter != 'ALL':
            clauses.append("type = ?")
            params.append(type_filter)
        if only_pending:
            clauses.append("processed = 0")
        tag_filter_norm = (tag_filter or '').strip().lower()

        # Processing-status filter: items missing at least one selected step (OR).
        if status_filter:
            status_sql = {
                'thumb':     "(thumb_path IS NULL OR thumb_path = '')",
                'describe':  "(ai_desc IS NULL OR ai_desc = '')",
                'analyze':   "(analysis_done = 0 AND type IN ('Reel','Video'))",
                'categorize': "(category = 'INTERESTING' AND (tags IS NULL OR tags = ''))",
            }
            conds = [status_sql[s] for s in status_filter if s in status_sql]
            if conds:
                clauses.append("(" + " OR ".join(conds) + ")")

        # Text search — FTS5 when available, LIKE fallback
        query = (query or '').strip()
        if query:
            fts_q = fts_match_query(query, match_all=True)
            try:
                if not fts_q:
                    raise ValueError('no searchable words')   # use the LIKE path
                fts_ids = [
                    r[0] for r in self.conn.cursor().execute(
                        "SELECT rowid FROM items_fts WHERE items_fts MATCH ?", (fts_q,)
                    ).fetchall()
                ]
                if not fts_ids:
                    return []
                clauses.append(f"id IN ({','.join('?' * len(fts_ids))})")
                params.extend(fts_ids)
            except Exception:
                q = f"%{query.lower()}%"
                clauses.append("""(
                    LOWER(description) LIKE ? OR LOWER(short_desc) LIKE ?
                    OR LOWER(creator) LIKE ? OR LOWER(url) LIKE ?
                    OR LOWER(tags) LIKE ? OR LOWER(ai_desc) LIKE ?
                    OR LOWER(transcript) LIKE ?
                )""")
                params.extend([q] * 7)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        order = {
            'new':  'COALESCE(created, modified, 0) DESC',
            'old':  'COALESCE(created, modified, 0) ASC',
            'az':   'description COLLATE NOCASE ASC',
            'za':   'description COLLATE NOCASE DESC',
            'type': 'type ASC, COALESCE(created, modified, 0) DESC',
        }.get(sort, 'COALESCE(created, modified, 0) DESC')

        cols = (
            "id, url, description, short_desc, creator, type, category, "
            "prefix, tags, ai_desc, notes, thumb_path, thumb_source, source, "
            "processed, analysis_done, analysis_path, created, modified, favourite"
            if not include_thumbs else "*"
        )

        sql = f"SELECT {cols} FROM items {where} ORDER BY {order}"
        rows = self.conn.cursor().execute(sql, params).fetchall()
        out = [dict(r) for r in rows]
        if tag_filter_norm:
            out = [
                r for r in out
                if tag_filter_norm in {
                    t.strip().lower()
                    for t in (r.get('tags') or '').split(',')
                    if t.strip()
                }
            ]
        return out

    def fts_ids(self, query: str, limit: int = 100, match_all: bool = False) -> list:
        """Return bm25-ranked item ids matching `query` (prefix-token FTS5 MATCH).

        Words are ORed by default (see fts_match_query); match_all=True requires
        every content word. Empty list when there is no query, no match, or FTS is
        unavailable."""
        fts_q = fts_match_query(query, match_all=match_all)
        if not fts_q:
            return []
        try:
            rows = self.conn.cursor().execute(
                "SELECT rowid FROM items_fts WHERE items_fts MATCH ? "
                "ORDER BY bm25(items_fts) LIMIT ?", (fts_q, limit)
            ).fetchall()
        except Exception:
            return []   # FTS unavailable
        return [r[0] for r in rows]

    def get_items_by_ids(self, ids) -> list:
        """Fetch full item dicts for `ids`, preserving the input order (missing ids skipped)."""
        ids = [int(i) for i in ids]
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        by_id = {
            r['id']: dict(r) for r in
            self.conn.cursor().execute(
                f"SELECT * FROM items WHERE id IN ({placeholders})", ids
            ).fetchall()
        }
        return [by_id[i] for i in ids if i in by_id]

    def fts_search(self, query: str, limit: int = 20, match_all: bool = False) -> list:
        """Return up to `limit` items most relevant to `query`, ranked by bm25(items_fts).

        Returns full item dicts (same shape as `search_items` rows, all columns). Empty
        list when there is no query, no match, or FTS is unavailable (caller may then
        fall back to `search_items`). `match_all` as in fts_ids. Main-thread only, like
        every other DB call."""
        query = (query or '').strip()
        if not query:
            return []
        ids = self.fts_ids(query, limit, match_all=match_all)
        # creator + tags are FTS columns so they already rank above; category is not
        # indexed, so also pull items whose category name matches the query and append
        # them (newest first) after the bm25-ranked hits. Lets the user type a category
        # to "compile everything from" it.
        seen = set(ids)
        for r in self.conn.cursor().execute(
            "SELECT id FROM items WHERE LOWER(category) LIKE ? "
            "ORDER BY COALESCE(created, modified, 0) DESC LIMIT ?",
            (f"%{query.lower()}%", limit)
        ).fetchall():
            if r[0] not in seen:
                seen.add(r[0])
                ids.append(r[0])
        return self.get_items_by_ids(ids)[:limit]

    # ── Embeddings (semantic search) ─────────────────────────────────────────
    def upsert_embedding(self, item_id: int, model: str, dim: int,
                         text_hash: str, blob: bytes):
        self.conn.cursor().execute(
            "INSERT OR REPLACE INTO item_embeddings "
            "(item_id, model, dim, text_hash, vector, updated) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, model, dim, text_hash, blob, int(time.time() * 1000))
        )
        self.conn.commit()

    def get_embedding_hashes(self, model: str) -> dict:
        """{item_id: text_hash} for staleness detection — no vector blobs loaded."""
        rows = self.conn.cursor().execute(
            "SELECT item_id, text_hash FROM item_embeddings WHERE model = ?", (model,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_all_embeddings(self, model: str) -> list:
        """[(item_id, dim, vector_blob)] for building the in-memory index."""
        return [tuple(r) for r in self.conn.cursor().execute(
            "SELECT item_id, dim, vector FROM item_embeddings WHERE model = ?", (model,)
        ).fetchall()]

    def iter_embeddings(self, model: str):
        """The same rows as get_all_embeddings, as a cursor (one row in memory at a time), for
        search.EmbeddingIndex.from_db. Reads only."""
        return self.conn.cursor().execute(
            "SELECT item_id, dim, vector FROM item_embeddings WHERE model = ?", (model,))

    def count_embeddings(self, model: str) -> int:
        return self.conn.cursor().execute(
            "SELECT COUNT(*) FROM item_embeddings WHERE model = ?", (model,)).fetchone()[0]

    # ── Topics (standing digests) ────────────────────────────────────────────
    def list_topics(self) -> list:
        rows = self.conn.cursor().execute(
            "SELECT * FROM topics ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_topic(self, name: str, query: str) -> int:
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO topics (name, query, created) VALUES (?, ?, ?)",
            (name.strip(), query.strip(), int(time.time() * 1000))
        )
        self.conn.commit()
        return c.lastrowid

    def update_topic(self, topic_id: int, **fields):
        allowed = {'name', 'query', 'note_path', 'last_run'}
        sets, values = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                values.append(v)
        if not sets:
            return
        values.append(topic_id)
        self.conn.cursor().execute(
            f"UPDATE topics SET {', '.join(sets)} WHERE id = ?", values
        )
        self.conn.commit()

    def delete_topic(self, topic_id: int):
        self.conn.cursor().execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        self.conn.commit()

    # ── Library assistant: resources index + aux embeddings ─────────────────
    def items_signature(self) -> str:
        """Cheap change key for the resources index: changes when items are added,
        deleted, analyzed, or their descriptions change."""
        row = self.conn.cursor().execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(analysis_done), 0), "
            "COALESCE(SUM(LENGTH(ai_desc)), 0), COALESCE(SUM(LENGTH(description)), 0) "
            "FROM items"
        ).fetchone()
        return ':'.join(str(v) for v in row)

    def items_for_resources(self) -> list:
        """[{'id','description','ai_desc'}] for librarian.resource_rows."""
        return [dict(r) for r in self.conn.cursor().execute(
            "SELECT id, description, ai_desc FROM items"
        ).fetchall()]

    def replace_resources(self, rows):
        """Replace the whole resources index with [(item_id, domain, url, context)]."""
        c = self.conn.cursor()
        c.execute("DELETE FROM resources")
        c.executemany(
            "INSERT INTO resources (item_id, domain, url, context) VALUES (?, ?, ?, ?)",
            rows)
        self.conn.commit()

    def all_resources(self) -> list:
        """[(item_id, domain, url, context)] in table order (what search_resources scans), for
        the Drive mirror (Wiskit Deep on the phone)."""
        return [tuple(r) for r in self.conn.cursor().execute(
            "SELECT item_id, domain, url, context FROM resources ORDER BY rowid").fetchall()]

    def resources_for_items(self, ids) -> list:
        """[(item_id, domain, url, context)] for the given item ids."""
        ids = [int(i) for i in ids]
        if not ids:
            return []
        ph = ','.join('?' * len(ids))
        return [tuple(r) for r in self.conn.cursor().execute(
            f"SELECT item_id, domain, url, context FROM resources WHERE item_id IN ({ph})",
            ids).fetchall()]

    def search_resources(self, terms, limit: int = 50) -> list:
        """[(item_id, domain, url, context)] whose domain or context contains any term."""
        terms = [t for t in terms if t]
        if not terms:
            return []
        where = ' OR '.join(['LOWER(domain) LIKE ? OR LOWER(context) LIKE ?'] * len(terms))
        params = []
        for t in terms:
            params += [f'%{t}%', f'%{t}%']
        return [tuple(r) for r in self.conn.cursor().execute(
            f"SELECT item_id, domain, url, context FROM resources WHERE {where} LIMIT ?",
            params + [limit]).fetchall()]

    def get_aux_hashes(self, model: str) -> dict:
        """{key: text_hash} of stored topic/note-section vectors (no blobs loaded)."""
        return {r[0]: r[1] for r in self.conn.cursor().execute(
            "SELECT key, text_hash FROM aux_embeddings WHERE model = ?", (model,)
        ).fetchall()}

    def get_aux_embeddings(self, model: str) -> list:
        """[{'key','kind','payload','blob','dim','hash'}] for model (corrupt rows skipped)."""
        out = []
        for key, kind, dim, blob, payload, text_hash in self.conn.cursor().execute(
                "SELECT key, kind, dim, vector, payload, text_hash FROM aux_embeddings WHERE model = ?",
                (model,)).fetchall():
            if len(blob) != dim * 4:
                continue
            out.append({'key': key, 'kind': kind, 'payload': json.loads(payload),
                        'blob': blob, 'dim': dim, 'hash': text_hash})
        return out

    def upsert_aux_embeddings(self, model: str, rows):
        """rows: [{'key','kind','hash','dim','blob','payload'}] (AskAgentWorker.aux_ready)."""
        now = int(time.time() * 1000)
        self.conn.cursor().executemany(
            "INSERT OR REPLACE INTO aux_embeddings "
            "(key, kind, model, dim, text_hash, vector, payload, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(r['key'], r['kind'], model, r['dim'], r['hash'], r['blob'],
              json.dumps(r['payload']), now) for r in rows])
        self.conn.commit()

    def delete_aux_embeddings(self, keys):
        keys = list(keys)
        if not keys:
            return
        self.conn.cursor().executemany(
            "DELETE FROM aux_embeddings WHERE key = ?", [(k,) for k in keys])
        self.conn.commit()

    # ── Notes search ─────────────────────────────────────────────────────────
    def reindex_notes(self):
        """Rebuild notes_fts from data/notes/*.md (dozens of small files — milliseconds).
        Cheap full rebuild instead of incremental sync because notes live on disk."""
        import re as _re
        from core import note_format
        c = self.conn.cursor()
        try:
            c.execute("DELETE FROM notes_fts")
        except sqlite3.OperationalError:
            return   # FTS5 unavailable
        if self.notes_dir.exists():
            for p in sorted(self.notes_dir.glob('*.md')):
                try:
                    text = p.read_text(encoding='utf-8')
                except Exception:
                    continue
                topic = p.stem
                body = text
                m = _re.match(r'^---\n(.*?)\n---\n+', text, flags=_re.DOTALL)
                if m:
                    body = text[m.end():]
                    tm = _re.search(r'^topic:\s*(.+)$', m.group(1), flags=_re.MULTILINE)
                    if tm:
                        topic = tm.group(1).strip()
                c.execute(
                    "INSERT INTO notes_fts (filename, topic, body) VALUES (?, ?, ?)",
                    (p.name, topic, note_format.plain(body))
                )
        self.conn.commit()

    def search_notes(self, query: str, limit: int = 10) -> list:
        """bm25-ranked saved-note matches:
        [{'filename','topic','snippet','body'}] (body = note text minus frontmatter)."""
        fts_q = fts_match_query(query)
        if not fts_q:
            return []
        try:
            rows = self.conn.cursor().execute(
                "SELECT filename, topic, snippet(notes_fts, 2, '[', ']', '…', 12), body "
                "FROM notes_fts WHERE notes_fts MATCH ? "
                "ORDER BY bm25(notes_fts) LIMIT ?", (fts_q, limit)
            ).fetchall()
        except Exception:
            return []
        return [{'filename': r[0], 'topic': r[1], 'snippet': r[2], 'body': r[3]}
                for r in rows]

    # ── Categories ──────────────────────────────────────────────────────────
    def item_ids_by_category(self, category: str) -> list:
        """All item ids in a category, newest first. Used by the Ask chat's
        whole-category scope mode. Main-thread read, like every other db call."""
        rows = self.conn.cursor().execute(
            "SELECT id FROM items WHERE category = ? "
            "ORDER BY COALESCE(created, modified, 0) DESC", (category,)
        ).fetchall()
        return [r[0] for r in rows]

    def get_categories(self) -> list:
        rows = self.conn.cursor().execute(
            "SELECT name, color, sort_order, hidden FROM categories ORDER BY sort_order, name"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_category(self, name: str, color: str, hidden: bool = False):
        c = self.conn.cursor()
        max_row = c.execute("SELECT MAX(sort_order) FROM categories").fetchone()
        max_order = (max_row[0] or 0) + 1
        try:
            c.execute(
                "INSERT INTO categories (name, color, sort_order, hidden) VALUES (?, ?, ?, ?)",
                (name, color, max_order, int(hidden))
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def update_category(self, old_name: str, new_name: str, color: str, hidden: bool = False):
        c = self.conn.cursor()
        if old_name != new_name:
            c.execute("UPDATE items SET category = ? WHERE category = ?", (new_name, old_name))
            c.execute("DELETE FROM categories WHERE name = ?", (old_name,))
            c.execute("INSERT OR IGNORE INTO categories (name, color) VALUES (?, ?)", (new_name, color))
        c.execute("UPDATE categories SET color = ?, hidden = ? WHERE name = ?", (color, int(hidden), new_name))
        self.conn.commit()

    def delete_category(self, name: str, move_items_to: str = 'INTERESTING'):
        c = self.conn.cursor()
        c.execute("UPDATE items SET category = ? WHERE category = ?", (move_items_to, name))
        c.execute("DELETE FROM categories WHERE name = ?", (name,))
        self.conn.commit()

    def category_color(self, name: str) -> str:
        row = self.conn.cursor().execute(
            "SELECT color FROM categories WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else '#888888'

    # ── Settings ────────────────────────────────────────────────────────────
    def get_setting(self, key: str, default: str = '') -> str:
        row = self.conn.cursor().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.cursor().execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def library_id(self) -> str:
        """The permanent random id of this library (spec 2026-10-28 map engine, decision 4), created the
        first time it is asked for and kept; a restored copy of the database keeps it on purpose."""
        value = self.get_setting('library_id', '')
        if not value:
            import secrets
            value = secrets.token_hex(16)
            self.set_setting('library_id', value)
        return value

    # ── Import ──────────────────────────────────────────────────────────────
    def import_from_json(self, json_path: Path, counts=None) -> tuple:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict):
            items_in = data.get('items', [])
            cats_in  = data.get('cats', [])
        else:
            items_in = data
            cats_in  = []

        text_fields = ('url', 'description', 'short_desc', 'creator', 'type', 'category', 'tags',
                       'ai_desc', 'notes', 'thumb_path', 'thumb_source', 'source')
        if not isinstance(items_in, list) or any(
            not isinstance(it, dict)
            or any(not isinstance(it.get(field, ''), str) for field in text_fields)
            or not (it.get('created') is None or isinstance(it['created'], int))
            or not isinstance(it.get('processed', False), (bool, int)) for it in items_in
        ):
            raise ValueError('JSON items must be a list of objects with text fields and valid dates.')
        if not isinstance(cats_in, list) or any(
            not isinstance(cat, dict) or not isinstance(cat.get('name', ''), str)
            or not isinstance(cat.get('color', '#888888'), str) for cat in cats_in
        ):
            raise ValueError('JSON categories must be a list of objects with text names and colors.')

        for cat in cats_in:
            if isinstance(cat, dict) and cat.get('name'):
                self.add_category(cat['name'], cat.get('color', '#888888'))

        added = skipped = 0
        for it in items_in:
            url = (it.get('url') or '').strip()
            if not http_url(url) or self.item_exists(url):
                if counts is not None:
                    key = 'duplicates' if http_url(url) else 'invalid'
                    counts[key] = counts.get(key, 0) + 1
                skipped += 1
                continue
            item_id = self.add_item({
                'url':          url,
                'description':  it.get('description', ''),
                'short_desc':   it.get('short_desc', ''),
                'creator':      it.get('creator', ''),
                'type':         it.get('type', 'Reel'),
                'category':     it.get('category', 'INTERESTING'),
                'tags':         it.get('tags', ''),
                'ai_desc':      it.get('ai_desc', ''),
                'thumb_path':   '',  # Metadata imports never grant filesystem access.
                'thumb_source': it.get('thumb_source', ''),
                'source':       it.get('source', 'imported'),
                'processed':    it.get('processed', False),
                'created':      it.get('created'),
            })
            if it.get('notes'):
                self.update_item(item_id, {'notes': it['notes']})
            added += 1

        return added, skipped

    def close(self):
        self.conn.close()


class ReadOnlyDatabase(Database):
    """Read-only view of the library for the Ask Deep-mode worker thread
    (ui/ask_agent_worker.py) - the one documented exception to "workers never touch
    SQLite". It opens its own connection with mode=ro (SQLite itself refuses writes),
    runs no schema/migration code, and inherits every read method from Database.
    Create it inside the worker's run() and close() it there."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.data_dir = self.db_path.parent
        self.items_dir = self.data_dir / 'items'
        self.thumbs_dir = self.data_dir / 'thumbs'
        self.reels_dir = self.data_dir / 'reels'
        self.analysis_dir = self.data_dir / 'analysis'
        self.notes_dir = self.data_dir / 'notes'
        self.conn = sqlite3.connect(f'file:{self.db_path.as_posix()}?mode=ro', uri=True)
        self.conn.row_factory = sqlite3.Row
