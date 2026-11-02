"""
ai_defaults.py: one Wiskit provider/model, persisted in the DB settings table.

Qt-free. Main-thread only (takes a `db` handle). Workers never call this — the main thread
resolves (provider, model) here and passes the strings into the worker, preserving the
"workers never touch SQLite" invariant (see CLAUDE.md).

Providers are stored uniformly as 'anthropic'/'openai' (matching ai_client.ASK_PROVIDER_*).
The video pipeline speaks 'claude'/'openai'; callers map 'anthropic'->'claude' at the
analyze_media boundary.
"""

import json
from core import ai_client

DESCRIBE = 'describe'
CATEGORIZE = 'categorize'
SYNTHESIZE = 'synthesize'
SUMMARIZE = 'summarize'
VIDEO = 'video'
CONNECTIONS = 'connections'

WISKIT_KEY = 'ai_model_jarvis'

# Fallback when a key is absent/corrupt — reproduces today's hardcoded behavior
# (Anthropic claude-sonnet-4-6 for every feature).
_DEFAULT = (ai_client.ASK_PROVIDER_OPENAI, ai_client.ASK_OPENAI_GPT6_LUNA_MODEL)


def get(db, feature):
    """All features share Wiskit. Older installs inherit Describe without a migration."""
    raw = db.get_setting(WISKIT_KEY, None)
    if raw is None:
        raw = db.get_setting('ai_model_describe', '')
    if not raw:
        return _DEFAULT
    try:
        data = json.loads(raw)
        provider = data['provider']
        model = data['model']
    except (ValueError, KeyError, TypeError):
        return _DEFAULT
    if not isinstance(provider, str) or not isinstance(model, str) or not provider or not model:
        return _DEFAULT
    return provider, ai_client.current_model(model)   # retired ids (gpt-4.1*) -> GPT-6 Luna


def set(db, feature, provider, model):
    """Persist the shared choice; retain the feature argument for existing callers."""
    db.set_setting(WISKIT_KEY,
                   json.dumps({'provider': provider, 'model': model}))


# ── Embeddings provider (not a per-feature model row; model is pinned) ─────────
# Semantic-search vectors must all live in one model's space, so only the PROVIDER
# is user-selectable; the model is always ai_client.EMBEDDING_MODEL (text-embedding-3-small,
# 1536-dim). Default is FreeLLMAPI (free, same model/dimension as the existing index).
_EMBED_PROVIDER_KEY = 'embeddings_provider'
_EMBED_DEFAULT_PROVIDER = ai_client.ASK_PROVIDER_OPENAI


def embed_provider(db):
    """The provider serving embeddings: 'openai' (default) or 'freellmapi'."""
    return db.get_setting(_EMBED_PROVIDER_KEY, _EMBED_DEFAULT_PROVIDER)


def set_embed_provider(db, provider):
    db.set_setting(_EMBED_PROVIDER_KEY, provider)


def embed_credentials(db):
    """Resolve (api_key, base_url) for the embeddings endpoint. base_url is None for
    real cloud OpenAI; a '/v1' URL for the FreeLLMAPI proxy. Main-thread only (reads db);
    the result is passed into the embed workers, which never touch the db."""
    from core import config
    if embed_provider(db) == ai_client.ASK_PROVIDER_FREELLMAPI:
        return config.freellmapi_api_key(), ai_client.freellmapi_v1_base()
    return config.openai_api_key(), None


# ── Model lists fetched from the providers (Settings > AI models > Refresh) ────
# {provider: {'at': ISO time, 'models': [{'id','label'}]}}, appended after ai_client's built-in
# lists by every picker (projects/model-lists/PLAN.md). Missing or corrupt -> nothing extra.
FOUND_MODELS_KEY = 'models_found'


def _found_raw(db):
    try:
        data = json.loads(db.get_setting(FOUND_MODELS_KEY, '') or '{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def found_models(db):
    """{provider: [{'id','label'}]} from the last Refresh (well-formed entries only)."""
    out = {}
    for provider, entry in _found_raw(db).items():
        models = entry.get('models') if isinstance(entry, dict) else None
        if isinstance(models, list):
            out[provider] = [m for m in models if isinstance(m, dict) and isinstance(m.get('id'), str) and m['id']]
    return out


def found_at(db):
    """{provider: ISO time of its last successful Refresh}."""
    return {p: e.get('at', '') for p, e in _found_raw(db).items() if isinstance(e, dict)}


def set_found_models(db, provider, models, at):
    """Replace one provider's fetched list; the other providers' lists stay. Writer only."""
    data = _found_raw(db)
    data[provider] = {'at': at, 'models': models}
    db.set_setting(FOUND_MODELS_KEY, json.dumps(data))
