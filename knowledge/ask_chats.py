"""
ask_chats.py - Data layer for Ask named conversations.
Each conversation is a JSON file in data/ask_chats/<slug>.json.
See archive/2026-11-09/docs/superpowers/specs/2026-07-04-ask-named-conversations-design.md.
"""

import json, re
from datetime import datetime
from pathlib import Path

from core import ai_client
from core import app_paths
from knowledge import weekly_review


# A chat slug is a file name in data/ask_chats/: only what _slugify_name makes (as server/intake.py _SLUG),
# so a slug from a URL or the phone can never reach outside that folder.
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,80}')
# Claude Code mode's session id (knowledge/claude_code.py): it goes on the CLI's command line, so only a UUID passes.
SESSION = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def valid_slug(slug) -> bool:
    return isinstance(slug, str) and SLUG.fullmatch(slug) is not None


def _slugify_name(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    return s[:72].strip('-') or 'chat'          # room for a -N suffix within SLUG's 81 characters


class AskChatStore:
    """Manages Ask conversations stored as JSON files."""

    def __init__(self, data_dir: Path):
        self.chat_dir = Path(data_dir) / 'ask_chats'
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.error_log = app_paths.ERROR_LOG

    # ── logging ──────────────────────────────────────────────────────────────
    def _log_error(self, message: str):
        try:
            with open(self.error_log, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] "
                        f"ask_chats: {message}\n")
        except Exception:
            pass

    # ── internal helpers ─────────────────────────────────────────────────────
    def _path(self, slug: str) -> Path:
        if not valid_slug(slug):
            raise ValueError(f'Not a chat name: {slug!r}')
        return self.chat_dir / f'{slug}.json'

    def _unique_slug(self, name: str, current_slug: str = None) -> str:
        base = _slugify_name(name)
        slug = base
        n = 2
        while True:
            if slug == current_slug or not self._path(slug).exists():
                return slug
            slug = f'{base}-{n}'
            n += 1

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec='seconds')

    def _normalize(self, data: dict, fallback_name: str = 'New chat') -> dict:
        if not isinstance(data, dict):
            data = {}

        name = data.get('name')
        if not isinstance(name, str) or not name.strip():
            name = fallback_name

        created = data.get('created')
        if not isinstance(created, str) or not created:
            created = self._now_iso()

        updated = data.get('updated')
        if not isinstance(updated, str) or not updated:
            updated = created

        history = []
        for turn in data.get('history') or []:
            if (isinstance(turn, dict)
                    and turn.get('role') in ('user', 'assistant')
                    and isinstance(turn.get('content'), str)):
                entry = {'role': turn['role'], 'content': turn['content']}
                if turn['role'] == 'assistant' and turn.get('review') is not None:
                    try:
                        entry['review'] = weekly_review.validate_metadata(turn['review'])
                    except ValueError:
                        pass    # corrupt optional metadata: drop it, keep the turn's content
                history.append(entry)

        source_ids = []
        for i in data.get('source_ids') or []:
            try:
                source_ids.append(int(i))
            except (TypeError, ValueError):
                continue

        claude_session = data.get('claude_session')
        if not (isinstance(claude_session, str) and SESSION.fullmatch(claude_session)):
            claude_session = ''

        return {
            'name': name,
            'created': created,
            'updated': updated,
            'history': history,
            'source_ids': source_ids,
            'options': self._normalize_options(data.get('options')),
            'claude_session': claude_session,
        }

    def _normalize_options(self, options: dict) -> dict:
        """Normalize Ask options to the provider/model shape:
        {provider, model_id, model_label, depth, scope}.

        Backward compatible on read:
        - new-shape records (valid `provider` + non-empty `model_id`) pass through;
        - legacy records store only `model: 'Sonnet'|'Haiku'` and map to explicit
          Anthropic provider/model ids;
        - missing/invalid data falls back to the current Ask default provider/model.

        The legacy `model` label is only read here for migration; new records are written
        in the provider/model shape below.
        """
        if not isinstance(options, dict):
            options = {}

        depth = options.get('depth')
        if not isinstance(depth, int):
            depth = 25
        scope = options.get('scope')
        if not isinstance(scope, str):
            scope = ''

        valid_providers = {p['id'] for p in ai_client.ask_provider_options()}
        provider = options.get('provider')
        model_id = options.get('model_id')

        if provider in valid_providers and isinstance(model_id, str) and model_id:
            # Already new-shape: trust it, backfill the label if absent. A retired model id
            # (gpt-4.1-mini) moves to its replacement, label included.
            label = options.get('model_label')
            if ai_client.current_model(model_id) != model_id:
                model_id, label = ai_client.current_model(model_id), ''
            if not isinstance(label, str) or not label:
                label = ai_client.ask_model_label(provider, model_id)
        else:
            # Legacy `model` label, or missing/invalid -> deterministic mapping.
            legacy = options.get('model')
            if legacy == 'Haiku':
                provider = ai_client.ASK_PROVIDER_ANTHROPIC
                model_id = ai_client.CLAUDE_HAIKU_MODEL
                label = 'Haiku'
            elif legacy == 'Sonnet':
                provider = ai_client.ASK_PROVIDER_ANTHROPIC
                model_id = ai_client.CLAUDE_MODEL
                label = 'Sonnet'
            else:
                provider = ai_client.ask_default_provider()
                model_id = ai_client.ask_default_model(provider)
                label = ai_client.ask_model_label(provider, model_id)

        return {
            'provider': provider,
            'model_id': model_id,
            'model_label': label,
            'depth': depth,
            'scope': scope,
        }

    # ── public API ───────────────────────────────────────────────────────────
    def list_chats(self) -> list:
        """Return [{slug, name, created, updated, message_count, source_count}],
        sorted by updated newest first. Corrupt files are skipped and logged."""
        entries = []
        for path in self.chat_dir.glob('*.json'):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
            except Exception as e:
                self._log_error(f'list_chats: corrupt file {path.name}: {e}')
                continue
            data = self._normalize(raw)
            entries.append({
                'slug': path.stem,
                'name': data['name'],
                'created': data['created'],
                'updated': data['updated'],
                'message_count': len(data['history']),
                'source_count': len(data['source_ids']),
            })
        entries.sort(key=lambda e: e['updated'], reverse=True)
        return entries

    def load(self, slug: str):
        """Return a normalized conversation dict, or None if missing/corrupt (or not a valid slug)."""
        if not valid_slug(slug):
            return None
        path = self._path(slug)
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception as e:
            self._log_error(f'load: corrupt file {path.name}: {e}')
            return None
        return self._normalize(raw)

    def save(self, slug: str, data: dict) -> str:
        """Normalize data, bump updated, write JSON. Logs and re-raises on failure."""
        normalized = self._normalize(data)
        normalized['updated'] = self._now_iso()
        path = self._path(slug)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log_error(f'save: failed to write {path.name}: {e}')
            raise
        return slug

    def create(self, name: str = 'New chat', options: dict | None = None):
        """Create an empty conversation. Returns (slug, data)."""
        slug = self._unique_slug(name)
        now = self._now_iso()
        data = self._normalize({'name': name, 'created': now, 'updated': now, 'options': options})
        path = self._path(slug)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return slug, data

    def rename(self, slug: str, name: str):
        """Rename a conversation, re-slugging the filename (suffixed on collision).
        Preserves `created`. Returns (new_slug, data)."""
        self._path(slug)                        # ValueError for a slug that is not a chat name
        data = self.load(slug) or self._normalize({}, fallback_name=name)
        data['name'] = name.strip() if name and name.strip() else data['name']
        new_slug = self._unique_slug(data['name'], current_slug=slug)
        self.save(new_slug, data)
        if new_slug != slug:
            old_path = self._path(slug)
            if old_path.exists():
                try:
                    old_path.unlink()
                except Exception as e:
                    self._log_error(
                        f'rename: failed to remove old file {old_path.name}: {e}')
        return new_slug, self.load(new_slug)

    def delete(self, slug: str):
        if not valid_slug(slug):
            return
        path = self._path(slug)
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                self._log_error(f'delete: failed to remove {path.name}: {e}')
