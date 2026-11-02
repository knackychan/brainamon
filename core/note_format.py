"""core/note_format.py - the My Notes file format shared by the editor, Wiskit, the local MCP, Reformat and
search (projects/note-organic-ui/plans/01-note-format-agents.md).

A note body is Markdown plus exactly three inline tags: <u>, <mark data-mark="..."> and
<span data-ink="...">. Stamps are one frontmatter line, `stamps: [...]`, single-line JSON: the
frontmatter parsers read flat `key: value` lines and every writer copies unknown keys back.
Pure functions, no I/O except the contract text. web/src/lib/note-format.ts holds the same rules for
the page and the phone; tests/fixtures/note_format.json checks that both agree."""
import json
import math
import re
from functools import lru_cache

from core import app_paths

INKS = ('graphite', 'indigo', 'sky', 'leaf', 'sun', 'ember', 'rose')
MARKS = ('sun', 'mint', 'peach', 'sky')
STAMPS = ('flower', 'sun', 'star', 'heart', 'check', 'arrow', 'sprout', 'mushroom', 'cloud', 'bolt',
          'coffee', 'bulb', 'kettlebell', 'pin', 'note', 'question', 'snail', 'sparkle', 'flag', 'smile')
SIZES = (2, 3, 4)            # cells of 24 px
ANCHOR_TOP, ANCHOR_END = 'top', 'end'
X_RANGE = (-40, 40)          # cells: negative from the sheet's right edge, 0 and up from the text column's left edge
Y_RANGE = (-400, 400)        # rows from the anchor's row
ANCHOR_MAX = 120             # characters of a heading kept as an anchor
MAX_STAMPS = 60
DEFAULT_INK = 'indigo'
KEY = 'stamps'               # the frontmatter key

_TAG = re.compile(r'</?u>|<mark data-mark="(?:%s)">|</mark>|<span data-ink="(?:%s)">|</span>'
                  % ('|'.join(MARKS), '|'.join(INKS)))
_HIGHLIGHT = re.compile(r'==(?=\S)(.+?)(?<=\S)==')
_TASK = re.compile(r'^([ \t]*[-*•][ \t]+)\[[ xX]\][ \t]?', re.MULTILINE)


@lru_cache(maxsize=None)
def contract() -> str:
    """The format as the models read it (Reformat, Deep's note tools, the Claude Code mode, the MCP): the
    shared prompt file knowledge/prompts/note_format.json (read by path: core does not import knowledge)."""
    path = app_paths.BUNDLE / 'knowledge' / 'prompts' / 'note_format.json'
    return json.loads(path.read_text(encoding='utf-8'))['contract']


def plain(body: str) -> str:
    """The note as words for search, embeddings and Wiskit context: the three tags, == highlights and
    task boxes removed. The rest of the Markdown stays (the search tokenizers skip its punctuation)."""
    text = _TAG.sub('', body or '')
    text = _HIGHLIGHT.sub(r'\1', text)
    return _TASK.sub(r'\1', text)


HEAD_LINES = 14    # the phone's note card shows the top of a note: at most this many whole lines,
HEAD_CHARS = 600   # stopping after the line that brings it to this many characters


def head(body: str) -> str:
    """The top of a note for the phone's note card (plans/08-note-cards.md): whole lines, leading
    blank lines dropped, at most HEAD_LINES, stopping after the line that reaches HEAD_CHARS
    characters, trailing whitespace trimmed. note-format.ts head is the same rule."""
    out, size = [], 0
    for line in (body or '').replace('\r\n', '\n').split('\n'):
        if not out and not line.strip():
            continue
        out.append(line)
        size += len(line) + 1
        if len(out) >= HEAD_LINES or size >= HEAD_CHARS:
            break
    return '\n'.join(out).rstrip()


def word_count(body: str) -> int:
    """Words of plain(): whitespace-separated pieces holding a letter or a digit (so '-', '##' and
    '—' do not count). note-format.ts wordCount is the same rule."""
    return sum(1 for t in plain(body).split() if any(c.isalnum() for c in t))


def _num(v, lo, hi, default):
    """An integer in [lo, hi]; JSON numbers only (strings, booleans and null give the default).
    Rounds half up, the same as Math.floor(v + 0.5) in note-format.ts."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return max(lo, min(hi, math.floor(v + 0.5)))


def _anchor(v) -> str:
    if not isinstance(v, str):
        return ANCHOR_END
    return ' '.join(v.split())[:ANCHOR_MAX] or ANCHOR_END


def clean_stamps(items) -> list:
    """Valid stamps in file order: unknown drawings and non-objects dropped, every field clamped to the
    contract, at most MAX_STAMPS. Keys in the order k, at, x, y, s, c, r."""
    out = []
    for st in items if isinstance(items, list) else []:
        if not isinstance(st, dict) or st.get('k') not in STAMPS:
            continue
        r = _num(st.get('r'), -90, 90, 0)
        out.append({'k': st['k'], 'at': _anchor(st.get('at')),
                    'x': _num(st.get('x'), X_RANGE[0], X_RANGE[1], -4),
                    'y': _num(st.get('y'), Y_RANGE[0], Y_RANGE[1], 0),
                    's': _num(st.get('s'), SIZES[0], SIZES[-1], SIZES[0]),
                    'c': st.get('c') if st.get('c') in INKS else DEFAULT_INK,
                    'r': -8 if r < 0 else 8 if r > 0 else 0})
        if len(out) == MAX_STAMPS:
            break
    return out


def parse_stamps(value) -> list:
    """The frontmatter value (a JSON string) as clean stamps; anything unreadable is no stamps."""
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        return clean_stamps(json.loads(value))
    except ValueError:
        return []


def dump_stamps(items) -> str:
    """Clean stamps as the one-line frontmatter value; '' when there are none."""
    items = clean_stamps(items)
    return json.dumps(items, ensure_ascii=False, separators=(',', ':')) if items else ''


def set_stamps(meta: dict, items) -> dict:
    """Write stamps into a note's meta: the key holds the dumped list, or is removed when empty."""
    value = dump_stamps(items)
    if value:
        meta[KEY] = value
    else:
        meta.pop(KEY, None)
    return meta
