# Wiskit implementation reference

**Source snapshot:** 2026-10-26<br>
**Purpose:** portable implementation guide for Wiskit, Brainamon’s in-app assistant.

This report describes behavior found in the current source. It does not claim that a provider call, installed build, or physical-device flow was exercised during this inspection. The linked tests provide automated coverage, but they were not run for this report. When source and an old project-plan status disagree, treat the current source and tests as evidence of implementation and the plan as a possible validation-history signal.

Status labels used below:

- **Implemented:** a user-facing path and implementation are present.
- **Limited:** present with a specific boundary, provider requirement, or device difference.
- **Validation open:** implementation is present, while a linked plan still leaves manual, live-provider, or device acceptance open.
- **Not implemented:** no current user control or code path was found; this is not a promise that it is planned.

## 1. Product surfaces and execution paths

Wiskit is a local-library assistant in the Svelte interface. On desktop, the main conversation rail calls the local FastAPI server. The server owns chat persistence and reads the library through read-only database connections; database and note mutations are submitted to the app’s single Writer or to the existing review flow. Model calls are centralized in the AI client.

| Surface | How a user opens it | Where the answer runs | Main constraints |
|---|---|---|---|
| Desktop Wiskit rail | Ask Wiskit button/rail, selected-card menu, or selection command | PC server; selected API provider, or source-only Claude Code mode | Full chat controls, attachments, citations, and review actions are here. |
| Desktop widget/drop panel | Open Wiskit’s desktop widget/panel; ask or drop content | PC server for Ask | Compact Quick-style Ask and capture UI. It is not the full chat desk and does not expose Deep or Claude Code controls. |
| Phone connected directly to the PC | Open Wiskit on the phone while the PC server is reachable | PC server and its configured keys | Uses the same Ask endpoint. If the PC is unreachable, answering needs a phone-side key and local source mode. |
| Phone mirror or solo library | Open the phone’s Wiskit screen | Phone, with an explicitly available Anthropic or OpenAI key | Quick and Deep are implemented in the phone source. Claude Code is unavailable. The mirror phone can answer while the PC is off; solo mode uses phone-held content. |

The same phone interface can therefore represent either a remote PC-backed chat or a phone-local AI chat. The surface text identifies which one is active. See [WiskitDesk](../../web/src/components/WiskitDesk.svelte), [the phone Wiskit screen](../../web/src/mobile/screens/Wiskit.svelte), [the desktop Ask adapter](../../web/src/mobile/source/desktop.ts), [the phone mirror adapter](../../web/src/mobile/source/mirror.ts), and [the server app](../../server/app.py).

The desktop drop panel is a related quick-capture surface, not another full conversation client. It can ask Wiskit, attach files handed in by the widget, save pasted text to the Inbox, add a link to the library, digest a screenshot into the Inbox note, or copy another dropped file into the Inbox. Its response view is deliberately smaller than the main rail. See [Panel.svelte](../../web/src/panel/Panel.svelte) and [desktop window setup](../../server/desktop.py).

## 2. Chat behavior and interactive elements

### Main desktop chat

- **Quick and Deep:** select the mode above the transcript. Claude Code appears only when its source-build integration is available and enabled.
- **Ask settings:** SET chooses provider, model, retrieval depth, and an optional single-category scope. The implemented depth choices are 10, 25, and 50 items. A new chat starts with the shared Wiskit model from Settings; an existing chat retains its own choices.
- **Composer:** Enter sends; Shift+Enter adds a line. Attach, paste, or drag files onto the Wiskit rail. Send becomes Stop while an answer is running.
- **Live feedback:** the client consumes server-sent events for run start, retrieval context, research progress, text chunks, reset, completion, stop, and error. The transcript follows the latest answer while it streams.
- **Citations:** item citations open the corresponding library card. Hover/focus highlights the card and draws a tether; the citation stepper walks citations from the latest answer. Note citations open Knowledge notes.
- **Saved chats:** create, auto-name, open, rename, clear, and delete named chats. Clearing removes turns but keeps the chat; deleting removes the chat. The chat list also exposes recent chats from the empty state.
- **Save as note:** a separate answer action creates a Knowledge note. It does not happen automatically when a chat answer is saved.
- **Selection entry:** “Ask about this” or “Ask Wiskit about the selection” starts a chat with an opening question naming the selected card or the first eight selected IDs. It is an entry prompt; the regular retrieval flow still supplies evidence.
- **Weekly review:** a separate action reviews the last seven dates across collections. It requires a fresh question state (no draft or attached file) and an API model; Claude Code cannot run it. It produces a chat answer and coverage details rather than editing library records.

Relevant UI/state files are [WiskitDesk.svelte](../../web/src/components/WiskitDesk.svelte), [WiskitMsg.svelte](../../web/src/components/WiskitMsg.svelte), and [ask.svelte.ts](../../web/src/lib/ask.svelte.ts). The server stream, chat routes, weekly review dispatch, and answer persistence are in [server/routes/ask.py](../../server/routes/ask.py); file-backed chat normalization and slug validation are in [knowledge/ask_chats.py](../../knowledge/ask_chats.py).

### Quick retrieval

Quick searches library items with full-text ranking and, when an embeddings key and index are available, semantic ranking. It can scope results to one collection. It also supplies matching saved notes, detailed evidence for the leading items, and previously cited items when a short follow-up refers to them. List-style questions widen the compact candidate pool. The UI shows whether retrieval fell back to keyword-only because embeddings are unavailable, no items are indexed, or embedding failed.

Quick is not simply “no tools” for every provider. Anthropic and OpenAI use the shared bounded librarian loop after the initial Quick context is assembled. That path can research further and use the same supported review proposals as Deep. FreeLLMAPI and the configured OpenAI-compatible local provider use a direct streamed answer over the supplied context; they do not get the native tool loop or its proposals.

Implementation: [ask_core.py](../../knowledge/ask_core.py), [ask route](../../server/routes/ask.py), [librarian.py](../../knowledge/librarian.py), and [Quick prompt and limits](../../knowledge/prompts/ask_quick.json).

### Deep research

Deep uses the librarian agent to move from topic clusters and note sections to item search, item details, reports/transcripts, and resources extracted from saved library content. It may use the optional About me note to tailor responses. If the embeddings key is missing, it continues with keyword search and reports that limitation.

The base research tools are find_topics, topic_items, search_library, read_items, search_notes, find_resources, and related_items. Desktop Deep additionally exposes read_note and propose_reformat. It can also propose category changes and canvas changes through shared review requests. These are bounded: prompt-configured limits cap research rounds, tool calls, item count, read batch size, context/result characters, token budget, and research time.

| Agent budget | Quick | Deep |
|---|---:|---:|
| Rounds including final answer | 4 | 8 |
| Tool calls | 12 | 28 |
| Distinct items | 25 | 100 |
| IDs per item read | 6 | 12 |
| Research characters | 32,000 | 128,000 |
| Result characters | 6,000 | 12,000 |
| Output token cap | 8,000 | 16,000 |
| Research time | 45 seconds | 180 seconds |

The shared agent implementation may further cap rounds or tokens. Current budgets are stored in [ask_deep.json](../../knowledge/prompts/ask_deep.json), not in the UI.

The phone has a TypeScript Deep implementation and its own source adapters. It supports phone-local Quick/Deep research and category review. Phone note-writing tools are not a direct port of desktop Deep’s note tools; the user can still use the separate Save as note control. Phone canvas proposals are present in source, but their implementation plan still records device validation as open.

Implementation: [librarian.py](../../knowledge/librarian.py), [ask_core.py](../../knowledge/ask_core.py), [Deep prompt and budgets](../../knowledge/prompts/ask_deep.json), [phone Deep engine](../../web/src/mobile/ai/deep.ts), and [phone Deep tests](../../tests/test_phone_deep.py).

### Stop, detach, and persistence behavior

Explicit Stop closes the active response and prevents later tools or a not-yet-started chat commit. If a successful commit has already started, a late Stop does not undo it. Closing or navigating away from the desktop page detaches the stream; the worker can finish and save the answer. This differs from pressing Stop. Phone-local operations likewise update chat memory only after the local or sync write succeeds.

Chats live as JSON files under the selected data folder’s ask_chats directory; the active slug is also a database setting. Turns, citations’ source IDs, per-chat model settings, review metadata, and Claude Code session IDs are normalized on load. Attachment text is included in the saved history with a smaller persistence cap than the current request cap. See [ask route](../../server/routes/ask.py), [chat store](../../knowledge/ask_chats.py), and [phone source](../../web/src/mobile/source/mirror.ts).

## 3. Files and other content operations

### Desktop Wiskit attachments

The main rail accepts file selection, paste, or drag/drop. The picker advertises PDF, Markdown, text, CSV, JSON, and PNG/JPEG/WebP/GIF. The backend text allowlist is broader and also recognizes common code/config/log formats such as Python, JavaScript, TypeScript, HTML, CSS, XML, YAML, and INI. Unsupported formats return a clear error; Word documents and video files are not accepted as ordinary Ask attachments.

Attachments are copied into data/inbox. The general Inbox copy limit is 200 MB, but Wiskit applies a 10 MB image limit and a 30 MB PDF limit. PDFs are parsed locally with pypdf, up to 300 pages; only the text layer is read. A scan with no text layer is rejected and the UI suggests attaching page screenshots. Each attachment’s text is capped at 40,000 characters for the request and 8,000 characters when retained in saved chat history.

Images are sent once to the configured Wiskit vision model for a text description. The original image and a companion text file are retained in the Inbox. The chat uses the derived text, not a continuing raw-image input. “Digest text” is a separate screenshot transcription action; it returns editable text that the user can append to a note, create as a new note, or copy.

Removing an attachment chip removes it from the pending Ask list; it does not delete the file already copied into data/inbox. The user can file a pending attachment into My Notes using one of three choices: create a new Inbox note, append its text under a dated heading, or ask the model to extend an existing note. Suggestions are limited to up to six candidate notes and fall back to a keyword match when the model suggestion fails. Topic-digest notes are excluded. Note writes run through the server Writer and trigger reindexing.

Finished Video Tools analyses can also be represented as an attachment ID at the server boundary; the resolver reads report.md and transcript.txt from the analysis folder. This is an API capability, not a general video-file attachment control in the chat picker.

Implementation: [attachments.py](../../knowledge/attachments.py), [inbox.py](../../knowledge/inbox.py), [WiskitFiling.svelte](../../web/src/components/WiskitFiling.svelte), [filing UI state](../../web/src/lib/filing.svelte.ts), [filing logic](../../knowledge/filing.py), [filing routes](../../server/routes/filing.py), and [Ask attachment route](../../server/routes/ask.py).

### Phone Add a picture or file

The phone’s Add screen reads supported files before the user sends their draft to Wiskit. Text files are decoded locally; PDFs and images are read with the phone’s selected Wiskit model and its own key. This is a different route from the desktop data/inbox attachment flow: file bytes are not uploaded to the PC as an attachment, but extracted text is included in the next question and may therefore be sent to the selected AI provider and retained as chat text. The file-reading implementation and capture-to-chat handoff are in [phone mirror source](../../web/src/mobile/source/mirror.ts), [Capture.svelte](../../web/src/mobile/screens/Capture.svelte), and [phone files tests](../../tests/test_phone_files.py).

### Safe reading and writing boundaries

Wiskit does not expose arbitrary model-directed filesystem browsing. The app’s item-file HTTP route serves only thumb.jpg, report.md, transcript.txt, and JPG frames below the selected item folder. The MCP read tool is narrower: read_item_file accepts report.md or transcript.txt, and saved-note reads resolve a safe note path. See [item file route](../../server/routes/files.py), [MCP reads](../../mcp_local/reads.py), and [knowledge path helpers](../../knowledge/knowledge.py).

Wiskit can write notes and propose categories/canvas changes, but these operations use app-owned code paths rather than giving the model direct disk or database access. Category and canvas proposals are revalidated at apply time; all Wiskit category and canvas proposals require a user action. The app’s note filing button is an explicit user action. Deep reformat is a proposal whose note changes only after Apply. For Claude Code, eligible note/job requests can be auto-approved only if the separate “Run requests without asking” setting is enabled; category batches and canvas proposals still require review.

## 4. APIs, events, and MCP integrations

### Local HTTP API

The main Ask API is a local FastAPI interface. Important routes are:

| Route | Role |
|---|---|
| GET /api/ask/options | Available providers/models, defaults, provider problems, depths, scopes, and Claude Code readiness. |
| POST /api/ask | Starts a streamed answer or weekly review. The client sends question, chat, mode, provider/model options, scope/depth, and attachment IDs as applicable. |
| POST /api/ask/stop | Stops a specific active run ID. |
| POST /api/ask/attach | Copies and resolves file/text/analysis attachments into the inbox flow. |
| POST /api/ask/panel | Hands attachment IDs to the open desktop drop panel via an app event. |
| GET/POST/PUT/DELETE /api/chats… | Lists, opens, creates, selects, changes options, renames, clears, and deletes chats. |
| POST /api/ask/save-note | Saves a non-empty answer into Knowledge. |
| POST /api/filing/suggest, /file, /digest, /read | Suggests note destinations, writes an explicit filing action, transcribes screenshots, or reads a phone Add file without retaining the file on the PC. |

POST /api/ask streams events named start, context, progress, chunk, reset, done, stopped, and error. The route and event emission are in [server/routes/ask.py](../../server/routes/ask.py); client decoding is in [ask.svelte.ts](../../web/src/lib/ask.svelte.ts) and [mobile source types](../../web/src/mobile/source/types.ts).

### Local developer MCP server

Follow [MCP setup](MCP.md) to register the Brainamon stdio server in your own client configuration. Run it with the checkout’s Python environment and mcp package. The server reads the selected local library through read-only database connections. Read tools cover library stats/search/list/detail, safe item reports/transcripts, saved notes and note categories, canvases and frames. Job tools preview or request selected fills, save a note, request category changes, and request canvas changes. Some write-request tools need the Brainamon app running because they submit to its local HTTP API and Writer; read tools can work without the app server.

The exact read tool names are library_stats, search_library, list_items, show_item, read_item_file, list_notes, search_notes, read_note, list_personal_notes, note_categories, list_canvases, read_canvas, and list_frames. The request/action tools are job_status, preview_job, start_job, save_note, set_category, set_categories, set_canvas, and control_job. Job fills are limited to the supported describe/categorize/thumb kinds and do not force-overwrite completed item work. control_job can pause, resume, or stop a running job in the regular developer MCP.

The MCP process does not itself open a writable SQLite connection or edit the library’s files. Item and note paths are allowlisted/validated. It has no delete or arbitrary file-write tool. The named save_note request can create a note or replace a specified personal note through the app’s request path; the normal behavior waits for approval, with the Claude Code auto-approval setting applying only to eligible request types. Category batches and canvas proposals always wait for review. In Wiskit’s Claude Code mode, control_job is explicitly denied even though the regular developer MCP defines it. The MCP implementation is in [mcp_local/app.py](../../mcp_local/app.py), [reads.py](../../mcp_local/reads.py), and [jobs.py](../../mcp_local/jobs.py). This developer MCP server is separate from the in-app Claude Code mode below.

### Wiskit’s Claude Code mode

This is a third Wiskit engine, not a synonym for the API provider named Anthropic. The app launches the installed Claude Code CLI in print/stream mode, sends the question on stdin, and supplies a per-run MCP configuration pointing only at Brainamon’s MCP server. The CLI’s logged-in Claude account is used; the app removes Anthropic API key variables from that child process. This path does not require Wiskit API keys and does not silently fall back to the API engine.

The subprocess is isolated: no Claude built-in tools, shell, file editing, browser, user/project settings, hooks, skills, CLAUDE.md, or auto memory are enabled for the run. Its allowlist is Brainamon’s library/note reads and eligible request tools; control_job is explicitly denied. Per-run prompt/config files are written outside the repository and removed afterward. Sessions use a validated UUID and resume per chat. Stop or the ten-minute answer timeout ends the CLI process tree. The CLI’s own login/plan limits and model availability still apply.

Setup is Settings > Claude Code: choose/detect the CLI path, test version and login status, turn on the mode, and choose a CLI model alias. The aliases in code are account default, Sonnet, Opus, and Fable; the app default is Sonnet. Availability is explicitly false in a frozen/installed build, so this remains a source/developer feature. The mode and settings API are in [knowledge/claude_code.py](../../knowledge/claude_code.py), [Claude Code prompt](../../knowledge/prompts/ask_claude_code.json), [settings route](../../server/routes/claude_code.py), and [AI model aliases](../../core/ai_client.py).

## 5. Model choice, reasoning effort, and configuration

### API providers and defaults

Ask provider choices in the main desktop chat are Anthropic, OpenAI, FreeLLMAPI’s configured free pool, and a configured OpenAI-compatible local server. The model picker combines built-in choices with refreshed provider lists. Settings > AI models > Refresh queries Anthropic and OpenAI model catalogs using their saved keys. A configured local server has its own OpenAI-compatible model discovery. FreeLLMAPI exposes its auto model choice.

One shared Wiskit provider/model is configured in Settings > AI models and is the default for new chats and other AI features. At this source snapshot, that default is OpenAI GPT-6 Luna. Ask stores provider/model/depth/scope overrides on each named chat. Legacy saved model IDs are normalized when loaded. The current shared default and provider catalogs are in [ai_defaults.py](../../core/ai_defaults.py) and [ai_client.py](../../core/ai_client.py); settings validation and model refresh are in [server/routes/settings.py](../../server/routes/settings.py).

Semantic-search embeddings have a separate provider setting (OpenAI or FreeLLMAPI) and use a pinned embedding model/dimension so the stored vectors remain compatible. This setting is independent of the chat provider/model choice.

The mobile Wiskit screen offers Anthropic/OpenAI keys available to that phone and a phone-side provider/model selection. In solo mode keys are entered on the phone; paired mode may receive keys the user explicitly chose to include when pairing. The phone refreshes model lists with those keys. Local/FreeLLMAPI desktop provider choices are not part of the phone’s own-key Ask picker. See [More.svelte](../../web/src/mobile/screens/More.svelte), [mobile mirror source](../../web/src/mobile/source/mirror.ts), and [pairing code](../../web/src/mobile/mirror/pairing.ts).

### Reasoning effort

**No user-facing reasoning-effort control was found.** Quick and Deep select research strategy and tool budget, not a model’s reasoning effort. The desktop “Depth” control changes the Quick retrieval count, with an optional collection scope. Cloud token caps reserve output headroom for models that reason internally, and the OpenAI agent path uses the Responses API for supported tool calls, but the Ask interface does not send a user-selected reasoning-effort value. Do not port the depth selector as if it were a reasoning-effort setting.

Claude Code has its separate CLI model alias picker; it also has no Wiskit reasoning-effort control.

### Keys, endpoint configuration, and data flow

API keys are edited through Settings and read through [core/config.py](../../core/config.py). On Windows their bytes use the app’s protected private storage; API key values are not returned to the frontend, which receives set/unset status. The local OpenAI-compatible provider additionally needs a base URL and can have a key. FreeLLMAPI uses its configured base URL and key. Phone keys use the phone’s protected storage. API-based chats send the selected question, relevant library/note/chat context, and any selected attachment text to the configured provider or endpoint; the local option sends to the configured local server. Provider billing, processing, and retention are external to Wiskit.

## 6. Permissions, errors, and constraints

- **Local API boundary:** the app binds to loopback. Protected API/file routes require the current-run local credential, a permitted Host/Origin, and X-CM on non-GET requests. See [server/guard.py](../../server/guard.py) and [server/settings.py](../../server/settings.py).
- **Database writes:** the server’s Writer owns writable SQLite access. Ask/research code reads with read-only connections; any persistent action is routed through the Writer or established job manager. See [server/store.py](../../server/store.py).
- **Provider readiness:** missing API keys or local base URL are shown before dispatch. If semantic search cannot embed, retrieval degrades to keyword mode and labels that state. FreeLLMAPI connection failures become an explicit error; there is no paid-provider fallback.
- **Unsupported mode/provider:** Deep requires Anthropic or OpenAI. A direct server request for Deep under another provider emits a progress notice and answers through Quick behavior instead. This is an intentional limitation, not a change to the user’s selected model.
- **Attachment failures:** unsupported formats return 415, stale or unsafe attachment IDs return 404, and empty/oversize/unreadable files return validation errors. Scanned PDFs without a text layer are not OCR’d.
- **Agent/tool failures:** librarian tools return bounded error text to the model instead of taking down the whole tool loop. Research time and output budgets are enforced. The app emits an error event for provider/route failures.
- **Claude Code failures:** the CLI must be present, logged in, tested, and explicitly enabled. Authentication/usage errors, timeout, process startup errors, and missing sessions are surfaced; there is no API fallback. The built app returns unavailable for this mode.
- **Review requests:** category, canvas, and note/reformat changes use app review/request paths. Wiskit category and canvas changes always require a user Apply action. Eligible Claude Code note/fill requests may use auto-approval if the user turns it on in Settings; do not generalize that exception to all Wiskit mutations.
- **No general web search:** find_resources searches/indexes websites and tools referenced in the user’s saved library content; it is not a general-purpose browser or live web-search tool.

## 7. Implementation status and what remains open

| Capability | Status from current code and repository records |
|---|---|
| Desktop API Quick/Deep, streamed answers, chats, citations, save-answer, file attachments | **Implemented.** Automated route, retrieval, attachment, and browser-streaming checks are linked below. |
| Phone Quick/Deep, own-key mirror/solo execution, direct-PC execution | **Implemented in source.** Unit and browser-oriented tests exist; they do not establish live provider behavior or physical-device parity. |
| Desktop note filing, screenshot digest, safe item/notes reads, category proposals | **Implemented.** Source includes bounded parsing, validated IDs/paths, Writer writes, and review actions. |
| Wiskit canvas reads/proposals on desktop and phone | **Implemented in source; phone validation open.** The phone canvas plan is marked validation in progress and retains device/flow checks. |
| Wiskit Claude Code mode | **Implemented as a source-only feature; manual live acceptance open.** It is disabled in frozen builds. The Claude Code plan records its real-app check as open. |
| API reasoning-effort selector | **Not implemented.** No such user control or request setting was found. |
| Arbitrary model filesystem/shell/browser access | **Not implemented for Wiskit.** Claude Code mode explicitly disables built-in CLI tools; MCP exposes only named Brainamon tools. |
| Mobile Claude Code mode | **Not implemented.** Phone offers Quick/Deep only. |
| General video-file attachment in the Ask picker | **Not implemented.** A completed Video Tools analysis can be referenced by the server attachment API; the picker does not accept video. |

Automated evidence is distributed across [test_server_ask.py](../../tests/test_server_ask.py), [test_ask_core.py](../../tests/test_ask_core.py), [test_ask_tool_stream.py](../../tests/test_ask_tool_stream.py), [test_attachments.py](../../tests/test_attachments.py), [test_server_claude_code.py](../../tests/test_server_claude_code.py), [test_claude_code.py](../../tests/test_claude_code.py), [test_mcp_reads.py](../../tests/test_mcp_reads.py), [test_mcp_jobs.py](../../tests/test_mcp_jobs.py), [test_phone_deep.py](../../tests/test_phone_deep.py), [test_phone_files.py](../../tests/test_phone_files.py), and [check_wiskit_streaming_browser.py](../../tests/check_wiskit_streaming_browser.py).

These code paths have automated local checks. Live-provider, real-device and
installed integration checks still require release evidence. This reference
does not claim universal provider or device validation. See
[BUILDING.md](BUILDING.md) and [MCP.md](MCP.md) for independent local commands.

## 8. Reusable design and project-specific assumptions

### Concepts worth porting

1. **One transport contract for the stream.** A small named event vocabulary lets a web, native, and phone client share streaming behavior, progress, stop, and terminal errors.
2. **Separate retrieval from generation.** Retrieval code builds bounded, inspectable context and preserves evidence IDs; model adapters only handle provider-specific request/stream/tool formats.
3. **Evidence-backed answers.** Keep source IDs and note filenames alongside answer text, render citations as navigable controls, and validate displayed citations against evidence actually returned by tools.
4. **Read-only agent tools plus mediated writes.** Give the agent narrow named tools over a read-only repository adapter. Represent mutations as typed proposals, validate at request and Apply time, and let the app own the actual commit.
5. **Per-conversation settings.** Store provider/model and user-visible retrieval controls with the conversation while keeping a shared default for new sessions.
6. **Typed file ingestion.** Route files by kind, enforce byte/page/character caps at the server boundary, retain an explicit distinction between original bytes and extracted text, and report OCR/format limits to the user.
7. **Provider adapters at one seam.** Keep key lookup, endpoint selection, model catalog normalization, streaming, and tool-call protocol differences out of UI components.
8. **Parity tests for duplicated clients.** When a phone or second app must run the same behavior, compare shared prompt/schema fixtures and test the same bounded inputs against both implementations.

### Brainamon-specific pieces to replace when porting

The portable concepts depend here on Brainamon’s SQLite schema, item IDs, category names, data/items reports and transcripts, data/notes Markdown/frontmatter format, data/ask_chats JSON files, embeddings index, canvas JSON model, and server Writer. The UI assumes Svelte 5, FastAPI, SSE, pywebview on desktop, and a TypeScript phone source abstraction. Provider wiring assumes Anthropic/OpenAI SDKs, FreeLLMAPI’s OpenAI-compatible endpoint, optional local OpenAI-compatible servers, pypdf, and the MCP Python SDK. Claude Code mode additionally requires the Windows Claude Code CLI and a source checkout.

For another app, replace the library adapter, identity model, note/file resolver, auth/secret store, and commit mechanism. Preserve the policy shape—bounded reads and app-owned writes—but do not transplant Brainamon’s paths, category rules, approvals, key transfer, or local bearer guard without mapping them to the target app’s trust boundaries.

### Porting out and bringing improvements back

- To port a feature out, start from the user action and its data contract, then identify its current source of truth, provider dependency, write boundary, and tests using the map below. Implement an adapter for the other app’s repository and approval model; keep the stream and typed proposal semantics where the target supports them.
- To bring a useful pattern back, add it at the existing seam rather than forking behavior: provider/model work belongs in core/ai_client.py and core/ai_defaults.py; retrieval/tool policy belongs in knowledge/ask_core.py, knowledge/librarian.py, and the prompt JSON; chat controls belong in ask.svelte.ts and WiskitDesk.svelte; phone parity belongs behind MobileSource and its source adapters.
- Add a regression test at the boundary being changed: a mocked provider for route/tool flow, a fixture for cross-language prompt/schema parity, and a synthetic temporary data folder for file or persistence behavior. For device-specific changes, keep source tests distinct from physical-device acceptance.
- Reconcile docs and plans only after confirming the new behavior exists in the target path. Keep user-facing mode names and the distinction between retrieval depth and model reasoning effort explicit.

## 9. Lightweight maintenance procedure

When a Wiskit capability changes, review the corresponding row and source links above, then inspect these areas:

| Change | Review these implementation areas |
|---|---|
| Chat UI, mode controls, citations, save/stop | [WiskitDesk](../../web/src/components/WiskitDesk.svelte), [WiskitMsg](../../web/src/components/WiskitMsg.svelte), [ask state](../../web/src/lib/ask.svelte.ts), [server Ask route](../../server/routes/ask.py) |
| Retrieval, prompts, tool names, limits, citations | [ask_core](../../knowledge/ask_core.py), [librarian](../../knowledge/librarian.py), [prompt files](../../knowledge/prompts/ask_quick.json), [Deep prompt](../../knowledge/prompts/ask_deep.json), [AI agent loop](../../core/ai_client.py) |
| Model catalog, keys, endpoint, reasoning request shape | [ai_client](../../core/ai_client.py), [ai_defaults](../../core/ai_defaults.py), [config](../../core/config.py), [settings API](../../server/routes/settings.py), [Settings UI](../../web/src/windows/SettingsWin.svelte) |
| Attachments, file read/limits, filing and notes | [attachments](../../knowledge/attachments.py), [inbox](../../knowledge/inbox.py), [filing](../../knowledge/filing.py), [Ask route](../../server/routes/ask.py), [filing routes](../../server/routes/filing.py), [WiskitFiling](../../web/src/components/WiskitFiling.svelte) |
| MCP tools or Claude Code mode | [mcp_local](../../mcp_local/app.py), [MCP reads](../../mcp_local/reads.py), [MCP jobs](../../mcp_local/jobs.py), [Claude Code engine](../../knowledge/claude_code.py), [Claude Code route](../../server/routes/claude_code.py), [MCP setup](MCP.md) |
| Phone behavior or provider/key path | [phone Wiskit screen](../../web/src/mobile/screens/Wiskit.svelte), [mobile AI](../../web/src/mobile/ai/), [desktop adapter](../../web/src/mobile/source/desktop.ts), [mirror adapter](../../web/src/mobile/source/mirror.ts), [More screen](../../web/src/mobile/screens/More.svelte) |
| Guard, permissions, or persistence boundary | [server guard](../../server/guard.py), [server store](../../server/store.py), [jobs](../../server/jobs.py), [chat store](../../knowledge/ask_chats.py) |

Then update the relevant status row and automated-test links. Check linked project plans for remaining manual/provider/device gates; do not convert an unchecked gate into a completed claim based on unit tests alone. Use the source snapshot date above as the report’s inspection date and refresh it on the next substantive review.
