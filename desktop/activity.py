"""What the server does while the main window sleeps, for Wiskit's dot, hover card and the tray tooltip
(projects/wiskit-activity).

Pure functions over the snapshots desktop/widget.py already receives on GET /api/events: no tkinter, no HTTP,
no SQLite.
  jobs   JobManager.snapshot() {current, last, request}      the `hello` jobs field, then every `job` event
  cloud  SyncService.status()  {running, state, done, total, vault_running, vault_state, vault_done, vault_total}
                                                             the `hello` cloud field, then every `cloud` event
  asks   how many Wiskit answers run                         the `hello` asks field, then every `ask_run` event
The busy rules are the rail's (web/src/components/RailJobs.svelte).
"""

SEGMENTS = 12                               # the card's bar: the rail's 12 segments
LIT, UNLIT = '\u2588', '\u2591'             # full block, light shade: both in Consolas
MIRROR_BUSY = ('publishing', 'starting')    # = RailJobs.svelte mirrorBusy
VAULT_BUSY = ('syncing', 'starting')        # = RailJobs.svelte vaultBusy
MOVING = {'stopping': 'Stopping the upload', 'disconnecting': 'Disconnecting from Google Drive'}   # = RailJobs.svelte MOVING
TIP = 'Brainamon'                           # = desktop/tray.py TITLE (tests check)
TIP_MAX = 120                               # NOTIFYICONDATAW.szTip holds 128 characters with its terminator
WAITING = '1 request waits for you'
LAST_ANSWER = "Last: Wiskit's answer saved"


def _count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def bar(done: int, total: int) -> str:
    """12 segments lit in proportion; '' without a total."""
    if total <= 0:
        return ''
    lit = min(SEGMENTS, SEGMENTS * done // total)
    return LIT * lit + UNLIT * (SEGMENTS - lit)


def waiting(jobs: dict | None) -> bool:
    """A request (category, note, canvas, job) waits for Fred's Apply or Decline."""
    return ((jobs or {}).get('request') or {}).get('state') == 'pending'


def _job_lines(job: dict) -> list[tuple[str, str]]:
    label = str(job.get('label') or job.get('kind') or 'Job')
    total, err = _count(job.get('total')), _count(job.get('err'))
    n = _count(job.get('done')) + err                       # = RailJobs.svelte n: done and failed items
    text = label + (' paused' if job.get('state') == 'paused' else '')
    if total:
        text += f' {n} / {total}'
    if err:
        text += f', {err} failed'
    return [('line', text)] + ([('bar', bar(n, total))] if total else [])


def _cloud_lines(cloud: dict) -> list[tuple[str, str]]:
    out = []
    state, vstate = cloud.get('state'), cloud.get('vault_state')
    if cloud.get('running') and state in MIRROR_BUSY:
        done, total = _count(cloud.get('done')), _count(cloud.get('total'))
        out.append(('line', f'Drive upload {done} / {total}' if total else 'Drive upload starting'))
    elif state in MOVING:
        out.append(('line', MOVING[state]))
    if cloud.get('vault_running') and vstate in VAULT_BUSY:
        done, total = _count(cloud.get('vault_done')), _count(cloud.get('vault_total'))
        out.append(('line', f'Vault sync {done} / {total}' if total else 'Vault sync starting'))
    elif vstate == 'stopping':
        out.append(('line', 'Stopping the vault sync'))
    return out


def lines(jobs: dict | None, cloud: dict | None, asks, last: str = '') -> list[tuple[str, str]]:
    """The hover card top to bottom, as (tone, text) with tone 'line' | 'bar' | 'last'. [] when there is
    nothing to say (then no card opens)."""
    jobs, cloud, asks = jobs or {}, cloud or {}, _count(asks)
    out = _job_lines(jobs['current']) if jobs.get('current') else []
    if asks:
        out.append(('line', 'Wiskit is answering' + (f' ({asks})' if asks > 1 else '')))
    out += _cloud_lines(cloud)
    if waiting(jobs):
        out.append(('line', WAITING))
    if last:
        out.append(('last', last))
    return out


def dot(jobs: dict | None, cloud: dict | None, asks) -> str:
    """'waiting' (a request waits for Fred's click: it wins), 'busy' (something runs) or '' (no dot)."""
    if waiting(jobs):
        return 'waiting'
    return 'busy' if lines(jobs, cloud, asks) else ''


def last_job(job: dict | None) -> str:
    """The card's "Last:" line once a job ended (JobManager.snapshot() 'last'); '' when there is none."""
    if not job:
        return ''
    label = str(job.get('label') or job.get('kind') or 'Job')
    done, err, total = _count(job.get('done')), _count(job.get('err')), _count(job.get('total'))
    if job.get('state') == 'stopped':
        return f'Last: {label} stopped after {done} of {total}'
    return f'Last: {label} done, {done} item{"s" * (done != 1)}' + (f', {err} failed' if err else '')


def tooltip(card: list[tuple[str, str]]) -> str:
    """The tray icon's tooltip: 'Brainamon - ' and the card's first text line, or 'Brainamon' alone."""
    first = next((text for tone, text in card if tone != 'bar'), '')
    return (f'{TIP} - {first}' if first else TIP)[:TIP_MAX]
