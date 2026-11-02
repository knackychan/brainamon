"""
ai_client.py — single construction point for every AI/model call in the app.

`config.py` centralizes the API *keys*; this module centralizes the *clients*. Every part of
the app that talks to Anthropic or OpenAI goes through the factories here instead of building
`anthropic.Anthropic(...)` / `openai.OpenAI(...)` inline. Two reasons:

1. Model IDs live in one place (no scattered string literals to update on a model bump).
2. This is the single seam for a future "managed AI" mode. Today the app is BYO-key: the client
   is built with the user's own key from `config`. To switch to a hosted proxy later (users
   subscribe; you hold the keys server-side), you only change these factories to point the SDK
   at your proxy endpoint + a session token — both SDKs accept `base_url`:
       anthropic.Anthropic(base_url=PROXY_URL, api_key=session_token)
       openai.OpenAI(base_url=PROXY_URL, api_key=session_token)
   No call site elsewhere needs to change. See docs/legacy/SPEC.md "Productization (deferred)".

The SDK imports stay inside the factories so the AI dependencies remain optional at import time
(the app still launches without `anthropic`/`openai` installed; the error only surfaces when an
AI feature is actually used).
"""

import json
import re
from contextlib import contextmanager
import threading
import time

from core import config
from core import app_console

# ── Model IDs (single source of truth) ───────────────────────────────────────
CLAUDE_MODEL = 'claude-sonnet-4-6'      # AI describe, auto-categorize, video analysis (Claude)
CLAUDE_HAIKU_MODEL = 'claude-haiku-4-5'  # cheap mode for the Ask-my-library chat
WHISPER_MODEL = 'whisper-1'             # OpenAI Whisper API transcription
# Ask chat only (confirmed in each provider's models.list on 2026-10-06):
ASK_CLAUDE_SONNET_55_MODEL = 'claude-sonnet-5-5'  # current Sonnet
ASK_OPENAI_GPT54_MINI_MODEL = 'gpt-5.4-mini'       # recommended for Ask Deep mode
ASK_OPENAI_GPT6_LUNA_MODEL = 'gpt-6-luna'          # most thorough Deep-mode answers (Fred, 2026-10-09)
# OpenAI default for every feature: video analysis, the cheap gates, the picker defaults.
# Fred moved everything from GPT-4.1 / GPT-4.1 mini to GPT-6 Luna on 2026-10-10.
OPENAI_ANALYSIS_MODEL = ASK_OPENAI_GPT6_LUNA_MODEL
# Retired model ids still found in saved settings and Ask conversations -> what they now run on.
RETIRED_MODELS = {
    'gpt-4.1': ASK_OPENAI_GPT6_LUNA_MODEL,
    'gpt-4.1-mini': ASK_OPENAI_GPT6_LUNA_MODEL,
}
EMBEDDING_MODEL = 'text-embedding-3-small'  # semantic search (Anthropic has no embeddings API)
EMBEDDING_DIM = 1536


# ── Ask chat: provider + model catalog ───────────────────────────────────────
# The Ask tab lets each conversation pick a provider and a model. The ids and labels
# live here (this module is the single model-id seam); ask_chats.py persists the choice
# per conversation and ui/ask_panel.py renders it through the ask_* helpers below.
# `local_openai` is a runtime-agnostic slot for an OpenAI-compatible local server
# (Ollama / LM Studio / llama.cpp); its models are discovered at runtime (Task 04), not
# listed here.
ASK_PROVIDER_ANTHROPIC = 'anthropic'
ASK_PROVIDER_OPENAI = 'openai'
ASK_PROVIDER_LOCAL_OPENAI = 'local_openai'
ASK_PROVIDER_FREELLMAPI = 'freellmapi'

# Ordered for display in the provider picker.
_ASK_PROVIDERS = [
    {'id': ASK_PROVIDER_ANTHROPIC, 'label': 'Anthropic'},
    {'id': ASK_PROVIDER_OPENAI, 'label': 'OpenAI'},
    {'id': ASK_PROVIDER_FREELLMAPI, 'label': 'FreeLLMAPI (free pool)'},
    {'id': ASK_PROVIDER_LOCAL_OPENAI, 'label': 'Local (OpenAI-compatible)'},
]

# Static cloud model catalogs. The Anthropic labels 'Sonnet' / 'Haiku' match the
# pre-existing Ask UI and already-saved conversations, so old chats migrate with no
# label change. OpenAI ids are the ones confirmed in models.list; add more only after
# confirming exact current ids.
_ASK_MODELS = {
    ASK_PROVIDER_ANTHROPIC: [
        {'id': CLAUDE_MODEL, 'label': 'Sonnet'},
        {'id': CLAUDE_HAIKU_MODEL, 'label': 'Haiku'},
        {'id': ASK_CLAUDE_SONNET_55_MODEL, 'label': 'Sonnet 5.5'},
    ],
    ASK_PROVIDER_OPENAI: [
        # First entry = default for new conversations (ask_default_model).
        {'id': ASK_OPENAI_GPT6_LUNA_MODEL, 'label': 'GPT-6 Luna'},
        {'id': ASK_OPENAI_GPT54_MINI_MODEL, 'label': 'GPT-5.4 mini'},
    ],
    ASK_PROVIDER_FREELLMAPI: [
        {'id': 'auto', 'label': 'Auto (free pool)'},
    ],
    ASK_PROVIDER_LOCAL_OPENAI: [],  # discovered at runtime (Task 04)
}

_ASK_DEFAULT_PROVIDER = ASK_PROVIDER_OPENAI   # Fred's choice: GPT-6 Luna (was GPT-5.6 Luna until 2026-10-09)


def _ask_local_v1_base(base_url):
    """Normalize a local base URL to the OpenAI '/v1' root the SDK expects. '' if unset."""
    base = (base_url or '').strip().rstrip('/')
    if not base:
        return ''
    return base if base.endswith('/v1') else base + '/v1'


def ask_local_available():
    """True when a local base URL is configured (cheap check, no network)."""
    return bool(config.local_openai_base_url())


def ask_discover_local_models(base_url=None, api_key=None):
    """Query an OpenAI-compatible models endpoint and return [{'id', 'label'}].
    Returns [] on any failure (unset/unreachable/bad response). Network call — run this
    off the main thread (see ui/ask_worker.LocalModelsWorker)."""
    base = _ask_local_v1_base(base_url or config.local_openai_base_url())
    if not base:
        return []
    try:
        client = openai_client(
            api_key=api_key or config.local_openai_api_key() or 'local', base_url=base)
        with app_console.api_call('Local OpenAI models.list', {'base_url': base}):
            resp = client.models.list()
    except Exception as exc:
        app_console.emit(
            'api', 'Local OpenAI model discovery failed',
            level='error', payload={'base_url': base}, error=exc
        )
        return []
    out = []
    for m in getattr(resp, 'data', []) or []:
        mid = getattr(m, 'id', None)
        if mid:
            out.append({'id': mid, 'label': mid})
    return out


def ask_provider_options():
    """Ordered provider options for the Ask provider picker: [{'id', 'label', 'enabled',
    'note'}]. Cloud providers are always enabled (their key is checked at dispatch);
    `local_openai` is enabled only when a base URL is configured, with `note` explaining
    why it is unavailable otherwise."""
    opts = []
    for p in _ASK_PROVIDERS:
        o = dict(p)
        if p['id'] == ASK_PROVIDER_LOCAL_OPENAI:
            o['enabled'] = ask_local_available()
            o['note'] = ('' if o['enabled']
                         else 'Configure the local model server in ⚙️ Settings')
        else:
            o['enabled'] = True
            o['note'] = ''
        opts.append(o)
    return opts


def _with_extra(models, extra_models):
    """`models` followed by each `extra_models` entry whose id is new (label falls back to the id)."""
    models = [dict(m) for m in models]
    known = {m['id'] for m in models}
    for m in extra_models or []:
        mid = m.get('id') if isinstance(m, dict) else m
        if not mid or mid in known:
            continue
        label = (m.get('label') if isinstance(m, dict) else None) or mid
        models.append({'id': mid, 'label': label})
        known.add(mid)
    return models


def ask_models(provider_id, extra_models=None):
    """Models for a provider as [{'id', 'label'}]. `extra_models` (the local slot's discovered
    models, or the cloud lists from Settings > AI models > Refresh) is appended, de-duped by id,
    with the raw id as a label fallback."""
    return _with_extra(_ASK_MODELS.get(provider_id, []), extra_models)


def ask_default_provider():
    """The provider a brand-new Ask conversation starts on."""
    return _ASK_DEFAULT_PROVIDER


def ask_default_model(provider_id):
    """First/default model id for a provider, or '' when none are statically known
    (e.g. local_openai before discovery)."""
    models = _ASK_MODELS.get(provider_id) or []
    return models[0]['id'] if models else ''


def ask_model_label(provider_id, model_id):
    """Display label for a provider/model id. Falls back to the raw id for unknown
    models (migrated ids, runtime-discovered local models)."""
    for m in _ASK_MODELS.get(provider_id, []):
        if m['id'] == model_id:
            return m['label']
    return model_id or ''


def anthropic_client(api_key: str = None):
    """Return a configured Anthropic client. Falls back to the .env key from config.

    Single swap point for managed/proxy mode (base_url + session token)."""
    import anthropic
    return anthropic.Anthropic(api_key=api_key or config.anthropic_api_key())


def openai_client(api_key: str = None, base_url: str = None):
    """Return a configured OpenAI client. Falls back to the .env key from config.

    `base_url` points the SDK at an OpenAI-compatible endpoint (a local Ollama/LM Studio
    server for the `local_openai` Ask provider, or a future managed proxy). `base_url=None`
    preserves the default cloud behavior exactly."""
    import openai
    return openai.OpenAI(api_key=api_key or config.openai_api_key(), base_url=base_url)


def transcribe_file(path, client=None) -> str:
    """Whisper transcription of one audio file (under the API's 25 MB). The only call site of
    WHISPER_MODEL; video analysis and voice notes both come through here."""
    from pathlib import Path
    p = Path(path)
    client = client or openai_client()
    payload = {'model': WHISPER_MODEL, 'file': str(p), 'bytes': p.stat().st_size if p.exists() else None}
    with app_console.api_call('OpenAI audio.transcriptions.create', payload):
        with open(p, 'rb') as audio:
            response = client.audio.transcriptions.create(model=WHISPER_MODEL, file=audio)
    if isinstance(response, str):
        return response.strip()
    text = response.get('text', '') if isinstance(response, dict) else getattr(response, 'text', '')
    return str(text or '').strip()


def freellmapi_v1_base() -> str:
    """Normalized '/v1' base URL for the FreeLLMAPI proxy ('' only if config is empty)."""
    return _ask_local_v1_base(config.freellmapi_base_url())


def freellmapi_client():
    """OpenAI SDK client pointed at the FreeLLMAPI proxy. FreeLLMAPI speaks the OpenAI
    wire format; a key is always sent (the proxy requires the unified key)."""
    return openai_client(api_key=config.freellmapi_api_key() or 'freellmapi',
                         base_url=freellmapi_v1_base() or None)


def _run_freellmapi(fn):
    """Call `fn` and convert an unreachable-proxy connection error into a clear message
    (no retry, no fallback to paid providers — per the design's failure mode)."""
    import openai
    try:
        return fn()
    except openai.APIConnectionError:
        raise RuntimeError(
            f"FreeLLMAPI unreachable at {config.freellmapi_base_url()} — is Docker running?"
        )


_ASK_MAX_TOKENS = 4000    # Quick answers that quote or reformat note sections truncated at 2000
_ASK_CLOUD_MIN_TOKENS = 8000


def _ask_cap(provider_id, max_tokens):
    """Answer token cap. Cloud models that think before answering (Claude Sonnet 5.5,
    the GPT-5 family) spend part of the cap on reasoning, so cloud providers get an
    8000 floor; local / FreeLLMAPI servers keep the requested cap."""
    if provider_id in (ASK_PROVIDER_ANTHROPIC, ASK_PROVIDER_OPENAI):
        return max(max_tokens, _ASK_CLOUD_MIN_TOKENS)
    return max_tokens


def _ask_token_kwargs(provider_id, max_tokens):
    """Chat Completions cap kwarg. Cloud OpenAI GPT-5 models reject 'max_tokens' (400,
    verified 2026-10-06) and 'max_completion_tokens' also works on gpt-4.1-mini, so
    cloud OpenAI uses it; local / FreeLLMAPI servers keep the classic 'max_tokens'."""
    if provider_id == ASK_PROVIDER_OPENAI:
        return {'max_completion_tokens': max_tokens}
    return {'max_tokens': max_tokens}


def ask_chat(messages, provider_id, model_id, *, system_prompt='',
             local_base_url=None, local_api_key=None):
    """Provider-neutral Ask chat dispatch — the single seam that owns all provider
    branching for the Ask tab.

    `messages` is an OpenAI-style list of {'role','content'} user/assistant turns.
    `system_prompt` is passed separately and adapted per provider (Anthropic takes a
    `system` kwarg; OpenAI-compatible providers take a leading system message). Returns
    the answer text. Keys for cloud providers come from `config`; the local provider uses
    `local_base_url` / `local_api_key`."""
    mt = _ask_cap(provider_id, _ASK_MAX_TOKENS)
    if provider_id == ASK_PROVIDER_ANTHROPIC:
        payload = {
            'provider': provider_id, 'model': model_id,
            'max_tokens': mt, 'system': system_prompt,
            'messages': messages,
        }
        with app_console.api_call('Anthropic messages.create', payload):
            resp = anthropic_client().messages.create(
                model=model_id, max_tokens=mt,
                system=system_prompt, messages=messages)
        return "".join(b.text for b in resp.content
                       if getattr(b, 'type', '') == 'text').strip()

    # openai + local_openai + freellmapi share one Chat Completions path; only the client differs.
    if provider_id == ASK_PROVIDER_LOCAL_OPENAI:
        client = openai_client(api_key=local_api_key or 'local',
                               base_url=_ask_local_v1_base(local_base_url) or None)
    elif provider_id == ASK_PROVIDER_OPENAI:
        client = openai_client()
    elif provider_id == ASK_PROVIDER_FREELLMAPI:
        client = freellmapi_client()
    else:
        raise ValueError(f'Unknown Ask provider: {provider_id!r}')

    oai_messages = list(messages)
    if system_prompt:
        oai_messages = [{'role': 'system', 'content': system_prompt}] + oai_messages
    payload = {
        'provider': provider_id, 'model': model_id,
        **_ask_token_kwargs(provider_id, mt), 'messages': oai_messages,
    }
    _call = lambda: client.chat.completions.create(
        model=model_id, messages=oai_messages, **_ask_token_kwargs(provider_id, mt))
    with app_console.api_call('OpenAI chat.completions.create', payload):
        resp = _run_freellmapi(_call) if provider_id == ASK_PROVIDER_FREELLMAPI else _call()
    return (resp.choices[0].message.content or '').strip()


def ask_chat_stream(messages, provider_id, model_id, *, system_prompt='',
                    local_base_url=None, local_api_key=None, max_tokens=None,
                    tools=None, run_tool=None, on_tool=None, on_reset=None):
    """Streaming variant of `ask_chat`: a generator that yields answer-text deltas
    (str) as they arrive, over the same provider branching and inputs. The caller
    accumulates the full text; see `ask_chat` for parameter semantics.

    Anthropic uses the `messages.stream()` helper (`text_stream`); the OpenAI and
    local OpenAI-compatible providers share one Chat Completions streaming path,
    exactly as the non-streaming call does. `max_tokens` overrides the default
    answer cap (the Ask list mode needs room to enumerate many items).
    Optional tools use the shared native agent loop for one action round and one
    final answer; on_reset clears text that preceded a tool call."""
    mt = _ask_cap(provider_id, max_tokens or _ASK_MAX_TOKENS)
    if tools:
        for delta in _ask_agent_stream(messages, provider_id, model_id, system_prompt=system_prompt,
                tools=tools, run_tool=run_tool, on_tool=on_tool, max_rounds=2, stream=True, max_tokens=mt):
            if delta is None:
                if on_reset:
                    on_reset()
            else:
                yield delta
        return
    if provider_id == ASK_PROVIDER_ANTHROPIC:
        payload = {
            'provider': provider_id, 'model': model_id,
            'max_tokens': mt, 'system': system_prompt,
            'messages': messages, 'stream': True,
        }
        with app_console.api_call('Anthropic messages.stream', payload):
            with anthropic_client().messages.stream(
                    model=model_id, max_tokens=mt,
                    system=system_prompt, messages=messages) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
        return

    # openai + local_openai + freellmapi share one Chat Completions path; only the client differs.
    if provider_id == ASK_PROVIDER_LOCAL_OPENAI:
        client = openai_client(api_key=local_api_key or 'local',
                               base_url=_ask_local_v1_base(local_base_url) or None)
    elif provider_id == ASK_PROVIDER_OPENAI:
        client = openai_client()
    elif provider_id == ASK_PROVIDER_FREELLMAPI:
        client = freellmapi_client()
    else:
        raise ValueError(f'Unknown Ask provider: {provider_id!r}')

    oai_messages = list(messages)
    if system_prompt:
        oai_messages = [{'role': 'system', 'content': system_prompt}] + oai_messages
    payload = {
        'provider': provider_id, 'model': model_id,
        **_ask_token_kwargs(provider_id, mt), 'messages': oai_messages, 'stream': True,
    }
    _open = lambda: client.chat.completions.create(
        model=model_id, messages=oai_messages, stream=True,
        **_ask_token_kwargs(provider_id, mt))
    with app_console.api_call('OpenAI chat.completions.stream', payload):
        stream = _run_freellmapi(_open) if provider_id == ASK_PROVIDER_FREELLMAPI else _open()
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def embed_texts(texts: list, api_key: str = None, base_url: str = None) -> list:
    """Embed a batch of strings with EMBEDDING_MODEL; returns one vector per input,
    in input order. Routed through the OpenAI client; `base_url` points it at an
    OpenAI-compatible endpoint (the FreeLLMAPI proxy) while keeping the SAME model
    (text-embedding-3-small, 1536-dim) so vectors stay compatible. base_url=None keeps
    today's cloud-OpenAI behavior exactly."""
    try:
        payload = {
            'model': EMBEDDING_MODEL, 'input_count': len(texts),
            'base_url': base_url, 'input': texts,
        }
        with app_console.api_call('OpenAI embeddings.create', payload):
            resp = openai_client(api_key, base_url=base_url).embeddings.create(
                model=EMBEDDING_MODEL, input=texts)
    except Exception as exc:
        import openai
        if isinstance(exc, openai.InternalServerError):
            msg = str(exc)
            if 'embedding family' in msg and 'no usable keys' in msg:
                raise RuntimeError(
                    'FreeLLMAPI embeddings are not configured for text-embedding-3-small. '
                    'Open the FreeLLMAPI dashboard and enable an embeddings provider on '
                    'Models -> Embeddings.'
                ) from exc
        raise
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


# ── Per-feature model defaults: provider + model catalog (Anthropic + OpenAI) ──
# The ⚙️ Settings "AI models (defaults)" section renders these. Kept next to the
# ask_* catalog so every model id lives in this one module.
_FEATURE_PROVIDERS = [
    {'id': ASK_PROVIDER_ANTHROPIC, 'label': 'Anthropic'},
    {'id': ASK_PROVIDER_OPENAI, 'label': 'OpenAI'},
    {'id': ASK_PROVIDER_FREELLMAPI, 'label': 'FreeLLMAPI (free pool)'},
]

_FEATURE_MODELS = {
    ASK_PROVIDER_ANTHROPIC: [
        {'id': 'claude-opus-4-8', 'label': 'Opus 4.8'},
        {'id': 'claude-sonnet-5', 'label': 'Sonnet 5'},
        {'id': CLAUDE_MODEL, 'label': 'Sonnet 4.6'},        # claude-sonnet-4-6
        {'id': CLAUDE_HAIKU_MODEL, 'label': 'Haiku 4.5'},   # claude-haiku-4-5
    ],
    ASK_PROVIDER_OPENAI: [
        {'id': ASK_OPENAI_GPT6_LUNA_MODEL, 'label': 'GPT-6 Luna'},
    ],
    ASK_PROVIDER_FREELLMAPI: [
        {'id': 'auto', 'label': 'Auto (free pool)'},
    ],
}


def feature_provider_options():
    """Ordered provider options for the per-feature model pickers: [{'id','label'}]."""
    return [dict(p) for p in _FEATURE_PROVIDERS]


def feature_models(provider_id, extra_models=None):
    """Models for a provider as [{'id','label'}] (empty for an unknown provider); `extra_models`
    is appended as in ask_models."""
    if provider_id not in _FEATURE_MODELS:
        return []
    return _with_extra(_FEATURE_MODELS[provider_id], extra_models)


# ── Model lists from the providers (projects/model-lists/PLAN.md) ────────────
# Settings > AI models > Refresh asks Anthropic and OpenAI which models the saved key can use. The
# answer is kept in the DB (ai_defaults.found_models) and appended after the built-in lists above,
# so a new model shows up in the pickers without a rebuild. Defaults stay in this module.
DISCOVER_PROVIDERS = (ASK_PROVIDER_ANTHROPIC, ASK_PROVIDER_OPENAI)
_OPENAI_SKIP = ('audio', 'realtime', 'tts', 'transcribe', 'search', 'image', 'embedding',
                'instruct', 'moderation', 'dall-e', 'whisper', 'codex', 'davinci', 'babbage')
_DATED = re.compile(r'-\d{4}-\d{2}-\d{2}$')


def _openai_chat_id(mid):
    """True for an OpenAI chat model id worth offering: gpt-* or o<digit>*, not a dated snapshot,
    not an audio / image / embedding / search variant."""
    if not (mid.startswith('gpt-') or re.match(r'o\d', mid)):
        return False
    return not _DATED.search(mid) and not any(s in mid for s in _OPENAI_SKIP)


def chat_models_from_list(provider, rows):
    """[{'id','label'}] from a provider's models.list rows (objects with `id`, and `display_name`
    or `created`), retired ids dropped. OpenAI: chat ids only, newest first. Pure: tests feed it
    plain objects."""
    if provider == ASK_PROVIDER_OPENAI:
        rows = sorted(rows, key=lambda r: getattr(r, 'created', 0) or 0, reverse=True)
    out, seen = [], set()
    for r in rows:
        mid = getattr(r, 'id', None)
        if not isinstance(mid, str) or not mid or mid in seen or mid in RETIRED_MODELS:
            continue
        if provider == ASK_PROVIDER_OPENAI and not _openai_chat_id(mid):
            continue
        label = getattr(r, 'display_name', None) if provider == ASK_PROVIDER_ANTHROPIC else None
        out.append({'id': mid, 'label': label or mid})
        seen.add(mid)
    return out


def discover_cloud_models(provider, api_key):
    """Ask Anthropic or OpenAI which models `api_key` can use -> [{'id','label'}]. Network call: run
    it off the event loop and off the Writer. Raises on a failed call so Settings can say why."""
    if provider == ASK_PROVIDER_ANTHROPIC:
        with app_console.api_call('Anthropic models.list', {}):
            resp = anthropic_client(api_key=api_key).models.list(limit=1000)
    elif provider == ASK_PROVIDER_OPENAI:
        with app_console.api_call('OpenAI models.list', {}):
            resp = openai_client(api_key=api_key).models.list()
    else:
        raise ValueError(f'No model list for provider {provider!r}')
    return chat_models_from_list(provider, getattr(resp, 'data', None) or [])


# Cheapest sensible model per provider — used for high-volume/low-stakes calls
# (e.g. the Connections gate) so switching a feature's provider still routes the
# gate to that provider instead of a hardcoded Anthropic model.
_CHEAP_MODEL = {
    ASK_PROVIDER_ANTHROPIC: CLAUDE_HAIKU_MODEL,
    ASK_PROVIDER_OPENAI: ASK_OPENAI_GPT6_LUNA_MODEL,   # gpt-6-luna
    ASK_PROVIDER_FREELLMAPI: 'auto',
}


def cheap_model(provider):
    """The cheap model id for a provider (falls back to Anthropic Haiku)."""
    return _CHEAP_MODEL.get(provider, CLAUDE_HAIKU_MODEL)


def phone_settings(synth_provider, synth_model, found=None):
    """What the phone needs to call the AI itself (projects/mobile-app/PLAN.md Phase 5), carried in
    the Drive mirror's library/meta.json so model ids stay in this module: the Ask providers the
    phone can use with its own keys and their models (first = default), the Synthesize choice, the
    embedding model of vectors.bin, the answer caps (`_ask_cap`: cloud models get the floor) and
    the Deep agent's caps (ask_agent: rounds, tokens per round; plans/07-wiskit-deep.md). `found`
    ({provider: [{'id','label'}]}, ai_defaults.found_models) is appended to the Ask model lists."""
    return {
        'ask': {'default': ask_default_provider(),
                'models': {p: ask_models(p, (found or {}).get(p)) for p in ASK_AGENT_PROVIDERS}},
        'synth': {'provider': synth_provider, 'model': current_model(synth_model)},
        'embedding_model': EMBEDDING_MODEL,
        'transcription_model': WHISPER_MODEL,
        'ask_max_tokens': _ASK_MAX_TOKENS,
        'cloud_min_tokens': _ASK_CLOUD_MIN_TOKENS,
        'agent_max_tokens': _AGENT_MAX_TOKENS,
        'agent_max_rounds': _AGENT_MAX_ROUNDS,
        'retired': sorted(RETIRED_MODELS),     # dropped from the lists the phone fetches itself (More > Refresh)
    }


def current_model(model_id):
    """The id a saved model choice runs on today: retired ids map to their replacement
    (RETIRED_MODELS), everything else is returned unchanged."""
    return RETIRED_MODELS.get(model_id, model_id)


def complete_text(provider, model, *, prompt, system='', max_tokens=2000):
    """Provider-neutral single-shot text completion. The single branch point for the
    text AI features (categorize / synthesize / note-summarize / obsidian). Keys come
    from `config` (same as ask_chat). Returns the answer text."""
    return complete_text_info(provider, model, prompt=prompt, system=system, max_tokens=max_tokens)[0]


def complete_text_info(provider, model, *, prompt, system='', max_tokens=2000):
    """As complete_text, but returns (text, truncated): truncated is True when the provider
    stopped at the token cap (Anthropic stop_reason 'max_tokens', OpenAI-style finish_reason
    'length'), so a caller can refuse a cut-off answer instead of using it."""
    if provider == ASK_PROVIDER_ANTHROPIC:
        payload = {
            'provider': provider, 'model': model, 'max_tokens': max_tokens,
            'system': system, 'messages': [{'role': 'user', 'content': prompt}],
        }
        with app_console.api_call('Anthropic messages.create', payload):
            resp = anthropic_client().messages.create(
                model=model, max_tokens=max_tokens,
                system=system, messages=[{'role': 'user', 'content': prompt}])
        text = ''.join(b.text for b in resp.content
                       if getattr(b, 'type', '') == 'text').strip()
        return text, getattr(resp, 'stop_reason', '') == 'max_tokens'
    if provider == ASK_PROVIDER_OPENAI:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        mt = _ask_cap(provider, max_tokens)   # reasoning models need headroom
        payload = {
            'provider': provider, 'model': model,
            **_ask_token_kwargs(provider, mt), 'messages': messages,
        }
        with app_console.api_call('OpenAI chat.completions.create', payload):
            resp = openai_client().chat.completions.create(
                model=model, messages=messages, **_ask_token_kwargs(provider, mt))
        choice = resp.choices[0]
        return (choice.message.content or '').strip(), getattr(choice, 'finish_reason', '') == 'length'
    if provider == ASK_PROVIDER_FREELLMAPI:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        payload = {
            'provider': provider, 'model': model,
            'max_tokens': max_tokens, 'messages': messages,
        }
        with app_console.api_call('FreeLLMAPI chat.completions.create', payload):
            resp = _run_freellmapi(lambda: freellmapi_client().chat.completions.create(
                model=model, max_tokens=max_tokens, messages=messages))
        choice = resp.choices[0]
        return (choice.message.content or '').strip(), getattr(choice, 'finish_reason', '') == 'length'
    raise ValueError(f'Unknown provider: {provider!r}')


def _responses_output_text(resp):
    """Best-effort text extraction from an OpenAI Responses API result."""
    txt = getattr(resp, 'output_text', None)
    if txt:
        return str(txt).strip()
    output = getattr(resp, 'output', None)
    if isinstance(output, list) and output:
        content = getattr(output[0], 'content', None)
        if isinstance(content, list):
            for chunk in content:
                t = getattr(chunk, 'text', None)
                if t:
                    return str(t).strip()
    return ''


def complete_vision(provider, model, *, prompt, images, max_tokens=2000):
    """Provider-neutral text+image completion — the single branch point for the vision
    AI features (AI Describe, Video analyze). `images` is a list of (media_type, base64)
    tuples, e.g. ('image/jpeg', '<b64>'). Keys come from `config`. Returns the answer text.

    Anthropic uses Messages image blocks; OpenAI uses the Responses API input_image
    (the path already proven by the video analyzer)."""
    if provider == ASK_PROVIDER_ANTHROPIC:
        content = [{'type': 'image',
                    'source': {'type': 'base64', 'media_type': m, 'data': d}}
                   for (m, d) in images]
        content.append({'type': 'text', 'text': prompt})
        payload = {
            'provider': provider, 'model': model, 'max_tokens': max_tokens,
            'image_count': len(images), 'messages': [{'role': 'user', 'content': content}],
        }
        with app_console.api_call('Anthropic vision messages.create', payload):
            resp = anthropic_client().messages.create(
                model=model, max_tokens=max_tokens,
                messages=[{'role': 'user', 'content': content}])
        return ''.join(b.text for b in resp.content
                       if getattr(b, 'type', '') == 'text').strip()
    if provider == ASK_PROVIDER_OPENAI:
        parts = [{'type': 'input_text', 'text': prompt}]
        for (m, d) in images:
            parts.append({'type': 'input_image', 'image_url': f'data:{m};base64,{d}'})
        payload = {
            'provider': provider, 'model': model,
            'image_count': len(images), 'input': [{'role': 'user', 'content': parts}],
        }
        with app_console.api_call('OpenAI responses.create', payload):
            resp = openai_client().responses.create(
                model=model, input=[{'role': 'user', 'content': parts}])
        return _responses_output_text(resp)
    if provider == ASK_PROVIDER_FREELLMAPI:
        # Chat Completions image_url blocks — the proxy does not accept images on /v1/responses.
        content = [{'type': 'text', 'text': prompt}]
        for (m, d) in images:
            content.append({'type': 'image_url',
                            'image_url': {'url': f'data:{m};base64,{d}'}})
        payload = {
            'provider': provider, 'model': model, 'max_tokens': max_tokens,
            'image_count': len(images), 'messages': [{'role': 'user', 'content': content}],
        }
        with app_console.api_call('FreeLLMAPI vision chat.completions.create', payload):
            resp = _run_freellmapi(lambda: freellmapi_client().chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{'role': 'user', 'content': content}]))
        return (resp.choices[0].message.content or '').strip()
    raise ValueError(f'Unknown provider: {provider!r}')


# ── Ask Quick/Deep: shared native tool loop ───────────────────────────────────
# Providers whose APIs this loop drives with tool calling. Local / FreeLLMAPI servers
# are not assumed to support tools, so Deep mode falls back to the fast path for them.
ASK_AGENT_PROVIDERS = (ASK_PROVIDER_ANTHROPIC, ASK_PROVIDER_OPENAI)

# Wiskit's Claude Code mode (knowledge/claude_code.py) runs the Claude Code CLI, which takes these --model
# aliases (claude --help, 2.1.296). '' passes no --model: the CLI's own default for the logged-in account.
CLAUDE_CODE_MODELS = (('', 'Claude Code default'), ('sonnet', 'Sonnet'), ('opus', 'Opus'), ('fable', 'Fable'))
CLAUDE_CODE_DEFAULT_MODEL = 'sonnet'       # Fred 2026-10-15 (Q1): lighter on the plan's weekly limit
_AGENT_MAX_TOKENS = 16000   # per round; under the Anthropic SDK's non-streaming guard
_AGENT_MAX_ROUNDS = 8


def ask_agent(messages, provider_id, model_id, *, system_prompt, tools, run_tool,
              on_tool=None, max_rounds=_AGENT_MAX_ROUNDS, on_text=None, on_reset=None,
              should_stop=None, on_stream=None, max_tokens=_AGENT_MAX_TOKENS,
              max_tool_calls=None, research_deadline=None):
    """Run the shared native tool loop and return its final answer."""
    parts = []
    for delta in _ask_agent_stream(messages, provider_id, model_id, system_prompt=system_prompt,
            tools=tools, run_tool=run_tool, on_tool=on_tool, max_rounds=max_rounds,
            stream=on_text is not None, should_stop=should_stop, on_stream=on_stream,
            max_tokens=max_tokens, max_tool_calls=max_tool_calls, research_deadline=research_deadline):
        if delta is None:
            parts.clear()
            if on_reset:
                on_reset()
        else:
            parts.append(delta)
            if on_text:
                on_text(delta)
    return ''.join(parts).strip()


def _ask_agent_stream(messages, provider_id, model_id, *, system_prompt, tools, run_tool,
                      on_tool=None, max_rounds=_AGENT_MAX_ROUNDS, stream=False,
                      max_tokens=_AGENT_MAX_TOKENS, should_stop=None, on_stream=None,
                      max_tool_calls=None, research_deadline=None):
    """Shared Quick/Deep native tool loop; text deltas, None to reset text before a tool.

    `tools`: provider-neutral [{'name','description','parameters' (JSON schema)}]
    (librarian.TOOLS). `run_tool(name, args) -> str` executes one call (never raises;
    errors come back as text starting with 'Error:'). `on_tool(name, args)` is called
    before each execution (progress UI/cancellation). The last round forbids tools.
    Text callbacks enable streaming; whole-answer callers use the same validated loop."""
    notify = on_tool or (lambda name, args: None)
    names = {t['name'] for t in tools}
    used = 0
    control_used, remaining_calls = 0, 0

    def reserve(calls):
        nonlocal remaining_calls
        ids = [getattr(c, 'id' if provider_id == ASK_PROVIDER_ANTHROPIC else 'call_id', None) for c in calls]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids) or any(
                not isinstance(getattr(c, 'name', None), str) or not c.name for c in calls):
            raise RuntimeError('Malformed provider tool call IDs or names.')
        remaining_calls = len(calls)
        if control_used + 64 * remaining_calls + 128 > 2048:
            raise RuntimeError('Tool round exceeds control reserve.')

    def control_result(name, out):
        nonlocal control_used, remaining_calls
        remaining_calls -= 1
        if name.startswith('propose_') or out.startswith('Error:'):
            if out.startswith('Error:') and len(out) > 64:
                out = 'Error: tool returned an oversized error.'
            if len(out) > 512:
                out = 'Error: tool receipt exceeded its reserved size.'
            control_used += len(out)
        return out

    def check():
        if should_stop and should_stop():
            raise RuntimeError('Stopped.')

    def limited():
        return ((max_tool_calls is not None and used >= max_tool_calls)
                or (research_deadline is not None and time.monotonic() >= research_deadline))

    def dispatch(name, args):
        nonlocal used
        check()
        if not isinstance(args, dict):
            return 'Error: tool arguments were not a JSON object.'
        if name not in names:
            return 'Error: unadvertised tool.'
        if limited():
            return 'Error: research budget exhausted; call skipped.'
        if name.startswith('propose_') and control_used + 512 + 64 * (remaining_calls - 1) + 128 > 2048:
            return 'Error: proposal control reserve exhausted; call skipped.'
        used += 1
        notify(name, args)
        check()
        return run_tool(name, args)

    def configure(client):
        # Use the SDK's transport type: source and packaged SDKs use different HTTP clients.
        if provider_id == ASK_PROVIDER_ANTHROPIC:
            from anthropic import Timeout
        else:
            from openai import Timeout
        return client.with_options(max_retries=0, timeout=Timeout(60, connect=10))

    @contextmanager
    def request_limit(client):
        # SDK timeouts bound each I/O phase; this timer bounds the whole request.
        expired = threading.Event()
        def timeout():
            expired.set()
            client.close()  # this turn's factory-created client, never a shared client
        timer = threading.Timer(60, timeout)
        timer.daemon = True
        timer.start()
        try:
            yield
            if expired.is_set():
                raise RuntimeError('Provider request timed out.')
        finally:
            timer.cancel()

    def read_json(api, kwargs):
        with api.with_streaming_response.create(**kwargs) as raw:
            try:
                if on_stream:
                    on_stream(raw.close)
                check()
                response = raw.parse()
                check()
                return response
            finally:
                if on_stream:
                    on_stream(None)

    def events(response, anthropic):
        try:
            if on_stream:
                on_stream(response.close)
            terminal = False
            blocks = set()
            for event in response:
                check()
                if event.type in ('error', 'response.failed', 'response.incomplete'):
                    raise RuntimeError('Provider stream failed or was incomplete.')
                if event.type == ('message_stop' if anthropic else 'response.completed'):
                    terminal = True
                if anthropic and event.type == 'content_block_start':
                    blocks.add(event.index)
                if anthropic and event.type == 'content_block_stop':
                    blocks.discard(event.index)
                if anthropic:
                    delta = getattr(event, 'delta', None)
                    text = getattr(delta, 'text', '') if getattr(delta, 'type', '') == 'text_delta' else ''
                else:
                    text = event.delta if event.type == 'response.output_text.delta' else ''
                if text:
                    yield text
            check()
            if not terminal or blocks:
                raise RuntimeError('Provider stream ended without successful completion.')
        finally:
            if on_stream:
                on_stream(None)

    if provider_id == ASK_PROVIDER_ANTHROPIC:
        a_tools = [{'name': t['name'], 'description': t['description'],
                    'input_schema': t['parameters']} for t in tools]
        msgs = list(messages)
        client = configure(anthropic_client())
        for rnd in range(max_rounds):
            check()
            last = rnd == max_rounds - 1 or limited()
            instructions = system_prompt + ('\nFinal answer only: research is bounded by the remaining rounds, calls and deadline. State limited coverage honestly.' if last else '')
            payload = {'provider': provider_id, 'model': model_id, 'round': rnd,
                       'max_tokens': max_tokens, 'messages': len(msgs)}
            with request_limit(client), app_console.api_call('Anthropic messages.create (agent)', payload):
                kwargs = dict(model=model_id, max_tokens=max_tokens, system=instructions,
                              messages=msgs, tools=a_tools,
                              tool_choice={'type': 'none'} if last else {'type': 'auto'})
                if stream:
                    with client.messages.stream(**kwargs) as response_stream:
                        yield from events(response_stream, True)
                        resp = response_stream.get_final_message()
                else:
                    resp = read_json(client.messages, kwargs)
            check()
            if resp.stop_reason == 'refusal':
                yield None
                yield 'The model declined to answer this request.'
                return
            uses = [b for b in resp.content if b.type == 'tool_use']
            if resp.stop_reason not in ('end_turn', 'stop_sequence', 'tool_use') or (resp.stop_reason == 'tool_use') != bool(uses):
                raise RuntimeError('Anthropic response was incomplete or inconsistent.')
            if last and uses:
                raise RuntimeError('Tools in an answer-only round.')
            if resp.stop_reason != 'tool_use' or not uses:
                if not any(b.type == 'text' and b.text.strip() for b in resp.content):
                    raise RuntimeError('Provider returned an empty answer.')
                if not stream:
                    yield ''.join(b.text for b in resp.content if b.type == 'text').strip()
                return
            reserve(uses)
            yield None
            # Append the full content (text, tool_use and any thinking blocks) unchanged.
            msgs.append({'role': 'assistant', 'content': resp.content})
            results = []
            for b in uses:
                out = control_result(b.name, dispatch(b.name, b.input))
                results.append({'type': 'tool_result', 'tool_use_id': b.id,
                                'content': out, 'is_error': out.startswith('Error:')})
            msgs.append({'role': 'user', 'content': results})   # all results, one message
        return

    if provider_id == ASK_PROVIDER_OPENAI:
        # Responses API, not Chat Completions: the GPT-5.6 models reject function tools
        # with reasoning on /v1/chat/completions (400, verified 2026-10-06). store=False
        # keeps library content off OpenAI's response storage; reasoning travels between
        # rounds as encrypted items instead. Verified on gpt-5.6-luna, gpt-5.4-mini and
        # gpt-4.1-mini.
        r_tools = [{'type': 'function', 'name': t['name'], 'description': t['description'],
                    'parameters': t['parameters'], 'strict': False} for t in tools]
        items = [{'role': m['role'], 'content': m['content']} for m in messages]
        client = configure(openai_client())
        for rnd in range(max_rounds):
            check()
            last = rnd == max_rounds - 1 or limited()
            instructions = system_prompt + ('\nFinal answer only: research is bounded by the remaining rounds, calls and deadline. State limited coverage honestly.' if last else '')
            payload = {'provider': provider_id, 'model': model_id, 'round': rnd,
                       'max_output_tokens': max_tokens, 'input_items': len(items)}
            with request_limit(client), app_console.api_call('OpenAI responses.create (agent)', payload):
                kwargs = dict(
                    model=model_id, instructions=instructions, input=items,
                    tools=r_tools, tool_choice='none' if last else 'auto',
                    max_output_tokens=max_tokens, store=False,
                    include=['reasoning.encrypted_content'])
                if stream:
                    with client.responses.stream(**kwargs) as response_stream:
                        yield from events(response_stream, False)
                        resp = response_stream.get_final_response()
                else:
                    resp = read_json(client.responses, kwargs)
            check()
            if getattr(resp, 'status', None) != 'completed' or any(
                    getattr(o, 'status', None) not in (None, 'completed') or
                    (o.type == 'message' and getattr(o, 'status', None) != 'completed') for o in resp.output):
                raise RuntimeError('OpenAI response was not completed.')
            calls = [o for o in resp.output if o.type == 'function_call']
            refusals = [getattr(c, 'refusal', '') for o in resp.output if o.type == 'message'
                        for c in getattr(o, 'content', []) if c.type == 'refusal']
            if refusals:
                yield None
                yield ''.join(refusals)
                return
            if last and calls:
                raise RuntimeError('Tools in an answer-only round.')
            if not calls:
                if not (resp.output_text or '').strip():
                    raise RuntimeError('Provider returned an empty answer.')
                if not stream:
                    yield (resp.output_text or '').strip()
                return
            reserve(calls)
            yield None
            items += resp.output   # reasoning + function_call items, unchanged
            for c in calls:
                try:
                    args = json.loads(c.arguments or '{}')
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    out = 'Error: tool arguments were not valid JSON.'
                else:
                    out = dispatch(c.name, args)
                out = control_result(c.name, out)
                items.append({'type': 'function_call_output', 'call_id': c.call_id,
                              'output': out})
        return

    raise ValueError(f'Agent does not support provider {provider_id!r}')
