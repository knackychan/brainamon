"""Wiskit's third Ask mode, "Claude Code" (projects/milestone-2026-10-14/claude-code-engine/PLAN.md).

The app runs `claude -p` (the Claude Code CLI, logged in on this PC) and Claude answers from the library
through the local Brainamon MCP server (mcp_local/). The session is closed off: no built-in tools
(--tools ""), only the Brainamon MCP server (--mcp-config + --strict-mcp-config), no user / project / local
settings, so no hooks, plugins or permission rules (--setting-sources ""), no skills
(--disable-slash-commands), no CLAUDE.md and no auto memory (QUIET_ENV), a working folder outside the
repo, the default permission mode with every prompt denied (--permission-prompts none). The login still
works (--bare would drop it; --safe-mode drops the MCP server), and the app's API keys are kept out of the
CLI's environment (KEY_ENV) so the login, not the API account, pays. Flags verified on claude 2.1.296; the MCP
config's per-server `timeout` (MCP_TOOL_TIMEOUT_MS) checked on claude 2.1.300.

Nothing here writes to the library or opens SQLite: a note or a job is a request (save_note / start_job)
that waits for Fred's click in the app (server/jobs.py ask / ask_note). The question goes to the CLI on
stdin, never on the command line.
"""
import collections
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from core import ai_client
from core import app_console
from core import app_paths
from core import note_format
from knowledge import ask_core
from knowledge import librarian
from knowledge import prompt_files

P = prompt_files.load('ask_claude_code')

PATH_KEY, ENABLED_KEY, MODEL_KEY = 'claude_code_path', 'claude_code_enabled', 'claude_code_model'   # DB settings
WORK_DIR = Path(tempfile.gettempdir()) / 'brainamon-claude-code'   # the session's working folder: outside the repo
TIMEOUT = 600            # seconds an answer may take before Wiskit stops it
MCP_TOOL_TIMEOUT_MS = 90_000   # one Brainamon tool call; a hung call returns an error to Claude instead of using
                               # up TIMEOUT. Above mcp_local/jobs.py's 60 s HTTP wait.
CHECK_TIMEOUT = 30       # claude --version / claude auth status
STDERR_TAIL = 2000
MCP_NAME = 'brainamon'
READ_TOOLS = ('library_stats', 'search_library', 'list_items', 'show_item', 'read_item_file',
              'list_notes', 'search_notes', 'read_note', 'list_personal_notes', 'note_categories',
              'list_canvases', 'read_canvas', 'list_frames')
ASK_TOOLS = ('job_status', 'preview_job', 'start_job', 'save_note', 'set_category', 'set_categories',
             'set_canvas')                                              # writes only ask Fred in the app
ALLOWED = tuple(f'mcp__{MCP_NAME}__{t}' for t in READ_TOOLS + ASK_TOOLS)
DENIED = (f'mcp__{MCP_NAME}__control_job',)                            # Wiskit never pauses or stops a running job
QUIET_ENV = {'CLAUDE_CODE_DISABLE_CLAUDE_MDS': '1', 'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1'}
# The app loads .env into os.environ (config.load_env). With ANTHROPIC_API_KEY set the CLI bills the API account
# (auth status: authMethod api_key; live 2026-10-15 "Credit balance is too low") instead of the claude.ai login.
KEY_ENV = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
SOURCE = 'Wiskit (Claude Code)'                                        # who asks, in the confirm window
LOST_SESSION = 'No conversation found with session ID'
NOT_IN_BUILD = 'Claude Code mode is not part of this build.'
NOT_LOGGED_IN = 'Claude Code is not logged in: open a terminal, run claude, then type /login.'
LOST_LINE = "Claude Code no longer has this chat's session: starting a new one with the chat so far."


class Failed(Exception):
    """A user-facing reason the answer did not come (the Ask stream's `error` event)."""


# ── where the CLI is ─────────────────────────────────────────────────────────
def available() -> bool:
    """The mode needs mcp_local and the MCP SDK: from source they import, and the installed build bundles them
    (packaging/brainamon.spec; the server runs as Brainamon.exe --mcp, launch.pyw)."""
    return importlib.util.find_spec('mcp_local') is not None and importlib.util.find_spec('mcp') is not None


def detect() -> str:
    """The Claude Code CLI on this PC: PATH first, then the native installer's, WinGet's and npm's folders
    (a fresh install is not yet on the running app's PATH). '' when not found."""
    found = shutil.which('claude')
    if found:
        return found
    home, local, appdata = (os.environ.get(k) for k in ('USERPROFILE', 'LOCALAPPDATA', 'APPDATA'))
    for base, rel in ((home, '.local/bin/claude.exe'), (local, 'Microsoft/WinGet/Links/claude.exe'),
                      (appdata, 'npm/claude.cmd')):
        if base and (Path(base) / rel).is_file():
            return str(Path(base) / rel)
    return ''


def open_login(path: str) -> None:
    """Settings > Claude Code > Sign in: a console window running `claude auth login` (the CLI's own sign-in; the
    app never sees the account). No user text is in argv."""
    if not path or not Path(path).is_file():
        raise Failed('Claude Code was not found: install it, then press Find again.')
    subprocess.Popen(launcher(path) + ['auth', 'login'], env=cli_env(), cwd=str(Path.home()),
                     creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))


def launcher(path: str) -> list:
    """The argv prefix that starts the CLI. npm's claude.cmd only calls bin/claude.exe beside it: start the exe
    itself (no cmd.exe in between). A .cmd without it is started as given; no user text is ever in argv."""
    p = Path(path)
    if p.suffix.lower() in ('.cmd', '.bat'):
        exe = p.parent / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'bin' / 'claude.exe'
        if exe.is_file():
            return [str(exe)]
    return [str(p)]


def cli_env() -> dict:
    """The CLI's environment: the app's, minus the API keys (so the login is used), plus QUIET_ENV."""
    return {**{k: v for k, v in os.environ.items() if k.upper() not in KEY_ENV}, **QUIET_ENV}


def _quick(path: str, *args) -> tuple:
    r = subprocess.run(launcher(path) + list(args), capture_output=True, stdin=subprocess.DEVNULL,
                       env=cli_env(), timeout=CHECK_TIMEOUT, creationflags=app_paths.NO_WINDOW)
    return r.returncode, r.stdout.decode('utf-8', 'replace').strip(), r.stderr.decode('utf-8', 'replace').strip()


def check(path: str) -> dict:
    """The Settings Test button, no model call: {'ok', 'state', 'version', 'message'}; state is found
    (and logged in), missing, logged_out or error."""
    if not path or not Path(path).is_file():
        return {'ok': False, 'state': 'missing', 'version': '', 'message': 'Claude Code was not found at that path.'}
    try:
        code, out, err = _quick(path, '--version')
        if code != 0 or not out:
            return {'ok': False, 'state': 'error', 'version': '',
                    'message': f'claude --version failed: {(err or out or f"exit {code}")[-300:]}'}
        version = out.splitlines()[0]
        code, out, err = _quick(path, 'auth', 'status')
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'state': 'error', 'version': '', 'message': f'Claude Code did not start: {exc}'}
    try:
        status = json.loads(out)
    except ValueError:
        return {'ok': False, 'state': 'error', 'version': version,
                'message': f'claude auth status: {(err or out or f"exit {code}")[-300:]}'}
    if not isinstance(status, dict) or not status.get('loggedIn'):
        return {'ok': False, 'state': 'logged_out', 'version': version, 'message': NOT_LOGGED_IN}
    how = status.get('subscriptionType') or status.get('authMethod') or ''
    return {'ok': True, 'state': 'found', 'version': version, 'message': 'Logged in' + (f' ({how}).' if how else '.')}


def problem(get_setting) -> str:
    """Why Claude Code mode cannot answer now ('' when it can). get_setting is a db.get_setting."""
    if not available():
        return NOT_IN_BUILD
    if get_setting(ENABLED_KEY, '') != '1':
        return 'Turn on Claude Code in ⚙️ Settings > Claude Code first.'
    path = get_setting(PATH_KEY, '')
    if not path or not Path(path).is_file():
        return 'Claude Code was not found: set its path in ⚙️ Settings > Claude Code.'
    return ''


def ready(get_setting) -> bool:
    return not problem(get_setting)


def model_setting(get_setting) -> str:
    v = get_setting(MODEL_KEY, ai_client.CLAUDE_CODE_DEFAULT_MODEL)
    return v if v in {m for m, _ in ai_client.CLAUDE_CODE_MODELS} else ai_client.CLAUDE_CODE_DEFAULT_MODEL


# ── the session ──────────────────────────────────────────────────────────────
def system_prompt(db) -> str:
    """Wiskit's rules for the session, with the library's size, categories and the "About me" note (as Deep).
    db is a reader (ReadOnlyDatabase)."""
    cats = ', '.join(f'{name} ({n})' for name, n in sorted(db.count_by_category().items(), key=lambda kv: -kv[1]))
    text = prompt_files.fill(P['system'], total_items=db.count_items(), categories=cats)
    profile = librarian.read_profile(db.notes_dir)
    if profile:
        text += prompt_files.fill(librarian.PROMPTS['profile'], profile=profile)
    return (text + '\n\n' + librarian.category_instructions(db, 'set_category') + '\n\n'
            + librarian.canvas_instructions(db, mcp=True) + '\n\n' + note_format.contract())


def build_prompt(question: str, earlier=(), attached: str = '') -> str:
    """What goes to the CLI's stdin: the chat's earlier turns when the session is new, the attached files'
    text, then the question."""
    parts = []
    if earlier:
        cap = P['earlier_turn_chars']
        turns = '\n\n'.join(f"{'User' if t['role'] == 'user' else 'Wiskit'}: {t['content'][:cap]}" for t in earlier)
        parts.append(prompt_files.fill(P['earlier'], turns=turns))
    if attached:
        parts.append(attached)
    parts.append(question)
    return '\n\n---\n\n'.join(parts)


def _python() -> str:
    """The interpreter for the MCP server: python.exe beside pythonw.exe (run.bat starts the app with pythonw)."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and (exe.parent / 'python.exe').is_file():
        return str(exe.parent / 'python.exe')
    return str(exe)


def mcp_command() -> tuple:
    """(command, args, extra env) that start the Brainamon MCP server: the installed exe with --mcp (launch.pyw),
    or from source python -m mcp_local on the repo."""
    if app_paths.FROZEN:
        return sys.executable, ['--mcp'], {}
    return _python(), ['-m', 'mcp_local'], {'PYTHONPATH': str(app_paths.BUNDLE)}


def write_files(folder: Path, data_dir, port: int, system_text: str) -> dict:
    """This run's MCP config (the Brainamon server only, on this app's data folder and port) and Wiskit's
    system prompt, in files named for the run (two answers can run at once). remove_files() deletes them."""
    folder.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:12]
    command, args, env = mcp_command()
    cfg = {'mcpServers': {MCP_NAME: {
        'command': command, 'args': args,
        'env': {**env, 'CM_DATA_DIR': str(data_dir), 'CM_PORT': str(port), 'CM_MCP_SOURCE': SOURCE},
        'timeout': MCP_TOOL_TIMEOUT_MS}}}
    files = {'mcp': folder / f'mcp-{tag}.json', 'system': folder / f'system-{tag}.md'}
    files['mcp'].write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    files['system'].write_text(system_text, encoding='utf-8')
    return files


def remove_files(files: dict) -> None:
    for p in files.values():
        try:
            p.unlink()
        except OSError:
            pass


def build_command(path: str, files: dict, session_id: str, *, resume: bool, model: str = '') -> list:
    """The isolated `claude -p` command (flags verified on claude 2.1.296). The question is not in it."""
    cmd = launcher(path) + [
        '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
        '--tools', '',                                   # no built-in tool: no Bash, Read, Edit, web
        '--mcp-config', str(files['mcp']), '--strict-mcp-config',
        '--allowedTools', ','.join(ALLOWED), '--disallowedTools', ','.join(DENIED),
        '--permission-prompts', 'none',                  # anything not allowed is denied; nobody is asked
        '--setting-sources', '',                         # no user / project / local settings: no hooks, plugins, rules
        '--disable-slash-commands',                      # no skills
        '--append-system-prompt-file', str(files['system']),
    ]
    cmd += ['--resume', session_id] if resume else ['--session-id', session_id]
    if model:
        cmd += ['--model', model]
    return cmd


# ── the stream ───────────────────────────────────────────────────────────────
def tool_line(name, args) -> str:
    """'Claude Code · search_library: knee prehab', for the trace under the answer."""
    short = str(name or '?').removeprefix(f'mcp__{MCP_NAME}__')
    args = args if isinstance(args, dict) else {}
    hint = next((args[k] for k in ('query', 'topic', 'filename', 'item_id', 'kind', 'category', 'missing')
                 if args.get(k) not in (None, '')), '')
    return f'Claude Code · {short}' + (f': {str(hint)[:80]}' if hint != '' else '')


def usage_line(info: dict) -> str:
    window = str(info.get('rateLimitType') or 'usage').replace('_', '-')
    try:
        return f"Claude usage: {round(float(info['utilization']) * 100)}% of the {window} limit used."
    except (KeyError, TypeError, ValueError):
        return f"Claude usage: {info.get('status')} ({window} limit)."


class Stream:
    """Turns the CLI's stream-json lines into Ask events (server/routes/ask.py): `chunk` for answer text,
    `reset` when that text was only a lead-in to a tool call (the page clears it), `progress` for each tool
    call and for one usage warning. After the run: text (the final answer; None when no result line came),
    error, session_id, stopped, timed_out, returncode, stderr, pending (tool calls still waiting for a result)."""

    def __init__(self):
        self.text = None
        self.error = ''
        self.session_id = ''
        self.stopped = self.timed_out = False
        self.returncode = None
        self.stderr = ''
        self.tools = []             # the tool_line of each tool call, for log_failure
        self._said = False          # answer text streamed since the last tool call
        self._warned = False        # the usage line was shown
        self.pending = {}           # tool_use id -> (trace line, time.monotonic() at the call): no result yet

    def feed(self, line: str) -> list:
        try:
            d = json.loads(line)
        except ValueError:
            return []
        if not isinstance(d, dict):
            return []
        self.session_id = str(d.get('session_id') or self.session_id)
        kind, out = d.get('type'), []
        if kind == 'stream_event' and not d.get('parent_tool_use_id'):
            ev = d.get('event') or {}
            delta = ev.get('delta') or {}
            if ev.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta':
                self._said = True
                out.append(('chunk', {'text': str(delta.get('text') or '')}))
            elif ev.get('type') == 'content_block_start' and (ev.get('content_block') or {}).get('type') == 'tool_use':
                if self._said:
                    out.append(('reset', {}))
                    self._said = False
        elif kind == 'assistant' and not d.get('parent_tool_use_id'):
            for block in (d.get('message') or {}).get('content') or []:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    self.tools.append(tool_line(block.get('name'), block.get('input')))
                    self.pending.setdefault(str(block.get('id') or ''), (self.tools[-1], time.monotonic()))
                    out.append(('progress', {'line': self.tools[-1]}))
        elif kind == 'user' and not d.get('parent_tool_use_id'):
            content = (d.get('message') or {}).get('content')
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    self.pending.pop(str(block.get('tool_use_id') or ''), None)
        elif kind == 'rate_limit_event' and not self._warned:
            info = d.get('rate_limit_info') or {}
            if info.get('status') and info.get('status') != 'allowed':
                self._warned = True
                out.append(('progress', {'line': usage_line(info)}))
        elif kind == 'result':
            errors = [str(e) for e in d.get('errors') or []]
            if d.get('is_error') or errors:
                self.error = '; '.join(errors) or str(d.get('result') or d.get('subtype') or 'unknown error')
            else:
                self.text = str(d.get('result') or '').strip()
        return out


def kill(proc) -> None:
    """End the CLI and its children (the MCP server)."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                       creationflags=app_paths.NO_WINDOW)
    else:
        proc.kill()


def run(cmd: list, prompt: str, *, cwd, on_event, should_stop, timeout: float = TIMEOUT) -> Stream:
    """Start the CLI, send the prompt on stdin, pass each event to on_event(kind, data). should_stop() or the
    timeout end the whole process tree. Raises OSError when the CLI cannot start."""
    s = Stream()
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=cli_env(),
                            creationflags=app_paths.NO_WINDOW)
    tail = collections.deque(maxlen=40)

    def drain():
        for raw in proc.stderr:
            tail.append(raw.decode('utf-8', 'replace'))

    finished = threading.Event()

    def watch():
        end = time.monotonic() + timeout
        while not finished.wait(0.25):
            if should_stop():
                s.stopped = True
            elif time.monotonic() > end:
                s.timed_out = True
            else:
                continue
            kill(proc)
            return

    drainer = threading.Thread(target=drain, name='cm-claude-err', daemon=True)
    drainer.start()
    threading.Thread(target=watch, name='cm-claude-watch', daemon=True).start()
    try:
        proc.stdin.write(prompt.encode('utf-8'))
        proc.stdin.close()
    except OSError:              # the CLI quit before reading (a bad flag): its stderr says why
        pass
    try:
        for raw in proc.stdout:
            for kind, data in s.feed(raw.decode('utf-8', 'replace')):
                if not s.stopped:
                    on_event(kind, data)
        proc.wait()
    finally:
        finished.set()
    drainer.join(2)
    for pipe in (proc.stdout, proc.stderr):
        try:
            pipe.close()
        except OSError:
            pass
    s.returncode = proc.returncode
    s.stderr = ''.join(tail)[-STDERR_TAIL:]
    return s


def waiting(s: Stream) -> str:
    """' It was still waiting on search_library: x for 9 min.' for the oldest tool call with no result
    (plus how many others had none); '' when every call got its result."""
    if not s.pending:
        return ''
    trace, started = min(s.pending.values(), key=lambda p: p[1])
    mins = int((time.monotonic() - started) // 60)
    n = len(s.pending)
    more = f' ({n - 1} more call{"s" if n > 2 else ""} also had no result)' if n > 1 else ''
    return f" It was still waiting on {trace.removeprefix('Claude Code · ')} for {mins} min{more}."


def failure(s: Stream) -> str:
    """The message for a run that gave no answer; '' when it did."""
    if s.timed_out:
        return f'Claude Code took longer than {TIMEOUT // 60} minutes, so Wiskit stopped it.' + waiting(s)
    if 'Not logged in' in s.error:
        return NOT_LOGGED_IN
    if s.error:
        return f'Claude Code: {s.error[:300]}'
    if s.text is None:
        last = (s.stderr.strip().splitlines() or [''])[-1][:200]
        return f'Claude Code stopped without an answer (exit {s.returncode}).' + (f' {last}' if last else '')
    if not s.text:
        return 'Claude Code sent an empty answer.'
    return ''


def log_failure(why: str, s: Stream = None, *, session: str = '', model: str = '', seconds: float = 0) -> None:
    """Append a failed run to error_log.txt (app_paths.ERROR_LOG), so the evidence survives a restart: the app
    console keeps its entries in memory only. A file append, not SQLite: safe from the Ask thread."""
    lines = [f"[{datetime.now().isoformat(timespec='seconds')}] claude_code: {why}"]
    if s is not None:
        tools = '; '.join(t.removeprefix('Claude Code · ') for t in s.tools[-10:]) or 'none'
        lines.append(f"  session {session or s.session_id or '?'}, model {model or 'default'}, "
                     f'{seconds:.0f} s, exit {s.returncode}, timed out {s.timed_out}, '
                     f'{len(s.tools)} tool call(s): {tools}')
        lines += [f'  stderr: {line}' for line in s.stderr.strip().splitlines()[-20:]]
    try:
        with open(app_paths.ERROR_LOG, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError:
        pass


def answer(path: str, question: str, *, session: str, history: list, attached: str, model: str,
           system_text: str, data_dir, port: int, on_event, should_stop, folder=None):
    """One Wiskit turn in Claude Code mode -> (answer text, session id), or (None, '') after Stop.
    Raises Failed with the reason to show. A new session gets the chat's earlier turns in the prompt; a
    session the CLI no longer has (its transcripts were cleaned up) starts again once as a new one."""
    folder = Path(folder or WORK_DIR)
    files = write_files(folder, data_dir, port, system_text)
    try:
        for attempt in (1, 2):
            fresh = not session
            sid = session or str(uuid.uuid4())
            earlier = history[-(ask_core.HISTORY_TURNS * 2):] if fresh else []
            cmd = build_command(path, files, sid, resume=not fresh, model=model)
            started = time.monotonic()
            try:
                s = run(cmd, build_prompt(question, earlier, attached), cwd=folder,
                        on_event=on_event, should_stop=should_stop)
            except OSError as exc:
                why = f'Claude Code did not start ({exc}). Check its path in ⚙️ Settings > Claude Code.'
                log_failure(why, model=model)
                raise Failed(why) from None
            if s.stopped:
                return None, ''
            if attempt == 1 and not fresh and LOST_SESSION in s.error:
                on_event('reset', {})
                on_event('progress', {'line': LOST_LINE})
                session = ''
                continue
            why = failure(s)
            if why:
                if s.stderr.strip():
                    app_console.emit('error', 'Claude Code stderr', level='error', details=s.stderr)
                log_failure(why, s, session=sid, model=model, seconds=time.monotonic() - started)
                raise Failed(why)
            return s.text, sid
    finally:
        remove_files(files)
