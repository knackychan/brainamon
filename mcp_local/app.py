"""Local MCP server for Claude Code on this PC (projects/mcp-local/PLAN.md). stdio only.

Reads go through server.store.reader (a read-only SQLite connection). The process never opens a
writable connection, deletes, moves or overwrites anything. Nothing may print to stdout: it is the
protocol channel (logs go to stderr).
"""
import sys
import threading
import time

from mcp.server.fastmcp import FastMCP

from core import config
from core import note_format
from mcp_local import jobs, reads
from server import settings, store

DB_PATH = settings.DATA_DIR / settings.DB_NAME

mcp = FastMCP(
    'brainamon',
    log_level='WARNING',
    instructions=(
    'Brainamon library on this PC (saved reels, posts, videos). Read tools search '
        'and open items, notes and canvases. No tool deletes anything; a note is written, a personal note '
        'replaced, an item re-categorized or a canvas made or extended only when Fred clicks in the app.'
    ),
)


def _db():
    return store.reader(DB_PATH)


EMBED_TIMEOUT = 10       # seconds the query embedding may take; then the search answers full-text only
EMBED_COOLDOWN = 300     # after a failed or slow embedding, searches skip it this long (no retry per query)
_embed_off_until = 0.0


def _embed(query):
    """The query vector, or None (no key, no network, too slow): the search then stays full-text only.
    The OpenAI SDK's own wait (600 s read, 2 retries) could eat Wiskit's whole run budget and, as tools are
    synchronous, block the MCP server, so the call runs on a daemon thread and is abandoned after
    EMBED_TIMEOUT. A failure turns embedding off for EMBED_COOLDOWN instead of paying the wait per query."""
    global _embed_off_until
    if time.monotonic() < _embed_off_until:
        return None
    box = {}

    def call():
        try:
            from core import ai_client
            vecs = ai_client.embed_texts([query])
            box['vec'] = vecs[0] if vecs else None
        except Exception as exc:
            box['error'] = exc

    worker = threading.Thread(target=call, name='mcp-embed', daemon=True)
    worker.start()
    worker.join(EMBED_TIMEOUT)
    if 'vec' in box:
        return box['vec']
    _embed_off_until = time.monotonic() + EMBED_COOLDOWN
    why = box.get('error') or f'no answer in {EMBED_TIMEOUT} s'
    print(f'semantic search off for {EMBED_COOLDOWN} s: {why}', file=sys.stderr)
    return None


# ── read tools ────────────────────────────────────────────────────────────────
@mcp.tool()
def library_stats() -> dict:
    """Item count, count per category, and how many items lack a description, a thumbnail or a category."""
    return reads.stats(_db())


@mcp.tool()
def search_library(query: str, limit: int = 10, semantic: bool = True) -> dict:
    """Search saved items (full text, plus meaning when an embeddings key is set). Returns ranked items
    with id, title, creator, category, url and a snippet. semantic=false skips the embedding call."""
    return reads.search(_db(), query, limit, embed=_embed if semantic else None)


@mcp.tool()
def list_items(category: str | None = None, missing: str | None = None, offset: int = 0, limit: int = 50) -> dict:
    """Page through items. missing is 'description', 'thumbnail' or 'category' (still INTERESTING): the items
    a job could fill. Use it to choose the ids for preview_job."""
    return reads.list_items(_db(), category, missing, offset, limit)


@mcp.tool()
def show_item(item_id: int) -> dict:
    """One item: clipped text fields, tags, its folder path under data/items/ and the file names in it."""
    return reads.show_item(_db(), item_id)


@mcp.tool()
def read_item_file(item_id: int, name: str) -> dict:
    """The AI report ('report.md') or the transcript ('transcript.txt') of an item. Capped at 40000 chars."""
    return reads.read_item_file(_db(), item_id, name)


@mcp.tool()
def list_notes() -> dict:
    """File names of the saved notes in data/notes/."""
    return reads.list_notes(_db())


@mcp.tool()
def search_notes(query: str, limit: int = 10) -> dict:
    """Full-text search over the saved notes: filename, topic, snippet."""
    return reads.search_notes(_db(), query, limit)


@mcp.tool(description="A saved note by file name (for example 'cooking.md'), as written: the frontmatter (a personal "
                      "note's stamps line included) and the Markdown body. Capped at 40000 chars.\n\n" + note_format.contract())
def read_note(filename: str) -> dict:
    """The tool text is the description above (it carries the note format)."""
    return reads.read_note(_db(), filename)


@mcp.tool()
def list_personal_notes() -> dict:
    """The user's own notes (My Notes, kind: personal): file, title, category, updated, size in characters.
    Newest first. Read one with read_note(file)."""
    return reads.list_personal_notes(_db())


@mcp.tool()
def note_categories() -> dict:
    """The My Notes categories: the stored list plus any used in existing personal notes. A reformat
    must file the note under one of these."""
    return reads.note_categories(_db())


@mcp.tool()
def list_topics() -> dict:
    """The knowledge map's AI topics (Settings > Obsidian > Refresh map builds them): id, title, item count, status
    (new = no summary yet, stale = summary out of date, fresh) and the summary's first line. Largest first."""
    return reads.list_topics(_db())


@mcp.tool()
def read_topic(topic_id: str) -> dict:
    """One topic by id (from list_topics): title, status, the full summary and its member items (id, title, creator,
    category, url). The rendered vault's pages under Brainamon/Topics/ hold the same text."""
    return reads.read_topic(_db(), topic_id)


# ── tools that ask Fred in the app (need the app running; they only send HTTP to 127.0.0.1) ───
@mcp.tool()
def job_status() -> dict:
    """The current and last background job (state, total, done, errors), the items of that job that errored,
    and recent_errors: the app console's latest error lines (item failures with item_id, job summaries).
    The automatic index pass after a text job becomes the last job, so read a text job's failures in
    recent_errors."""
    return jobs.status()


@mcp.tool()
def preview_job(kind: str, ids: list[int]) -> dict:
    """What start_job would do, without starting anything: how many of the ids still need the step
    (count), which provider and model would run. kind is 'describe', 'categorize', 'thumb' or 'analyze'
    (video analysis: download, frames, Whisper transcript, AI report; Reels and Videos only, with the options
    Fred saved in the app's Analyze options). Show Fred this result before start_job: describe, categorize and
    analyze call paid AI models once per item, and analyze is the slowest and dearest."""
    return jobs.preview(kind, ids)


@mcp.tool()
def start_job(kind: str, ids: list[int], confirm_count: int) -> dict:
    """Ask Fred to start a background job on those item ids. confirm_count must equal preview_job's count.
    Nothing starts here: Brainamon shows Fred a confirm window and the job starts only when he clicks Start there
    (job_status shows request.state: pending, approved or declined). Close keeps it pending in Jobs. It fills what is missing
    (descriptions, categories of items still INTERESTING, thumbnails, video analyses) and skips finished items; it never
    overwrites. One request and one job at a time."""
    return jobs.start(kind, ids, confirm_count)


SAVE_NOTE_DOC = (
    "Ask Fred to save a note in the library's notes (data/notes/). topic is its title, body the Markdown "
    "text (cite items as [id N]), sources the item ids it cites. Nothing is written here: Brainamon shows Fred "
    "a confirm window and the note is saved only when he clicks there (job_status shows request.state: "
    "pending, approved or declined). Close keeps it pending in Jobs. Without file it becomes a new note. With file (a name from "
    "list_personal_notes) it replaces that personal note: the reformat and formatting path; Fred's window names "
    "the file and shows the text. Only personal notes can be replaced. stamps (only with file) replaces the "
    "note's stamps with this list; leave it out to keep them. One request at a time: a job request still "
    "waiting blocks it, and the other way round.\n\n" + note_format.contract())


@mcp.tool(description=SAVE_NOTE_DOC)
def save_note(topic: str, body: str, sources: list[int] | None = None, file: str = '', category: str = '',
              stamps: list[dict] | None = None) -> dict:
    """The tool text is SAVE_NOTE_DOC (it carries the note format)."""
    return jobs.save_note(topic, body, sources or [], file=file, category=category, stamps=stamps)


@mcp.tool()
def set_category(ids: list[int], category: str) -> dict:
    """Ask Fred to move items into an existing category (a name from library_stats), whatever category they are
    in now: use it to re-file items the categorize job cannot reach. Nothing changes here: Brainamon shows Fred
    the items and they move only when he clicks there (job_status shows request.state: pending, approved,
    declined). Close keeps it pending in Jobs. Check each item with show_item first. One request at a time, shared with
    start_job and save_note."""
    return jobs.set_category(ids, category)


@mcp.tool()
def set_categories(groups: list[dict]) -> dict:
    """Preferred category action: prepare one batch of up to 100 items across existing categories.
    Each group is {ids: [integer item IDs], category: exact name from library_stats}.
    Check items with show_item first. Include all groups in one call, with no duplicate IDs.
    Brainamon shows every current and proposed category; one Apply batch click applies them all.
    Always requires manual approval, even with auto-approve. Nothing changes before approval.
    One pending request at a time; do not submit each category separately."""
    return jobs.set_categories(groups)


@mcp.tool()
def list_canvases() -> dict:
    """The canvases (moodboards): id, name, element count, last change (ms). Newest first."""
    return reads.list_canvases(_db())


@mcp.tool()
def read_canvas(canvas_id: str) -> dict:
    """One canvas's elements (at most 150): id, type (image or note), item_id (an item's thumbnail) or file_path
    (an uploaded image or frame), label, note text (clipped), x, y, w, h."""
    return reads.read_canvas(_db(), canvas_id)


@mcp.tool()
def list_frames(item_id: int) -> dict:
    """The extracted video frames of an item (file names, made by the analyze job). Use these exact names in
    set_canvas. Empty: the item has no frames; use its thumbnail or suggest analyze."""
    return reads.list_frames(_db(), item_id)


@mcp.tool()
def set_canvas(elements: list[dict], new_name: str = '', canvas_id: str = '', layout: str = 'rows',
               arrange: bool = False) -> dict:
    """Ask Fred to create a themed canvas (new_name) or add to one (canvas_id from list_canvases). Only when the
    user asks for a canvas. Each element is {kind, ...}: {kind: 'thumbnail', item_id}, {kind: 'frame', item_id,
    frame} (a name from list_frames), {kind: 'text', text, color?} (a short heading, caption or step), each with
    optional label (images), group (its section title) and order; or explicit x, y offsets instead of a group.
    {kind: 'existing', id} moves an element already on the canvas, only with arrange: true. layout 'columns' puts
    sections left to right (routine steps), 'rows' one section per row. At most 60 elements and 20 text notes. The
    app arranges them without overlaps; never invent ids or frame names. Nothing is written here: Brainamon shows
    Fred a review window and applies it all or nothing only on his click, never by auto-approve; nothing is ever
    deleted or changed on the canvas. One request at a time, shared with start_job, save_note and set_category."""
    proposal = {'elements': elements, 'layout': layout, 'arrange': arrange}
    if new_name:
        proposal['new_name'] = new_name
    if canvas_id:
        proposal['canvas_id'] = canvas_id
    return jobs.set_canvas(proposal)


@mcp.tool()
def control_job(action: str) -> dict:
    """pause, resume or stop the running job. Stop keeps the work already done."""
    return jobs.control(action)


def main():
    config.load_env()           # API keys from .env, only for the optional query embedding
    mcp.run(transport='stdio')
