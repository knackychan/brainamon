"""Job-start tools for the local MCP server (projects/mcp-local/PLAN.md Part B).

Jobs live in the running app (server/jobs.py JobManager needs the Writer and the SSE hub), so this
module only sends HTTP to 127.0.0.1 with the X-CM header the localhost guard requires. It never
sends force=true: a job started here only fills what is missing and cannot overwrite a finished item.
"""
import json
import os
import urllib.error
import urllib.request
from core import local_auth

from server import settings

BASE = f'http://{settings.HOST}:{settings.PORT}'
KINDS = ('describe', 'categorize', 'thumb', 'analyze')     # not exposed: note, download, exports, scrape, ...
ACTIONS = ('pause', 'resume', 'stop')
MAX_IDS = 500
NOT_RUNNING = 'Brainamon is not running: start it with run.bat, then try again.'
SOURCE = os.environ.get('CM_MCP_SOURCE') or 'Claude Code'   # who asks, in the app's confirm window


class JobToolError(Exception):
    """A message meant for Claude and Fred."""


class AppNotRunning(JobToolError):
    pass


def _http(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    try:
        req = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers=local_auth.headers(settings.PORT, {'X-CM': '1', 'Content-Type': 'application/json'}))
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b'null')
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get('detail')
        except (ValueError, AttributeError):
            detail = exc.reason
        return exc.code, {'detail': detail}
    except OSError as exc:                      # URLError is an OSError: connection refused, timeout
        raise AppNotRunning(NOT_RUNNING) from exc


transport = _http        # tests replace this with a function that talks to an in-process app


def _check(status, body):
    if status == 409:
        raise JobToolError(f"Busy: {body.get('detail')}. Call job_status, and try again when it is idle "
                           'or the waiting request is answered. An automatic index pass can follow a text job.')
    if status >= 400:
        raise JobToolError(str(body.get('detail') or f'HTTP {status}'))
    return body


def _kind(kind):
    if kind not in KINDS:
        raise JobToolError(f"kind must be one of: {', '.join(KINDS)}")
    return kind


def _ids(ids):
    out = sorted({int(i) for i in ids or []})
    if not out:
        raise JobToolError('Give at least one item id (list_items with missing=... finds them).')
    if len(out) > MAX_IDS:
        raise JobToolError(f'At most {MAX_IDS} ids per call (got {len(out)}).')
    return out


def _recent_errors(limit=20):
    """Error lines of the app console, newest last. The app keeps only its last job, and the automatic
    index pass after a text job replaces it at once, so the failures of the job before live only here."""
    out = []
    for e in _check(*transport('GET', '/api/console')) or []:
        if e.get('level') != 'error':
            continue
        line = {'ts': e.get('ts'), 'title': e.get('title'), 'error': str(e.get('error') or '')[:300]}
        if (e.get('payload') or {}).get('item_id') is not None:
            line['item_id'] = e['payload']['item_id']
        out.append(line)
    return out[-limit:]


def status():
    jobs = _check(*transport('GET', '/api/jobs'))
    progress = _check(*transport('GET', '/api/jobs/progress'))
    errors = [i for i in progress.get('items') or [] if i.get('state') == 'error']
    return {'current': jobs['current'], 'last': jobs['last'], 'request': jobs.get('request'),
            'errors': errors[:50], 'recent_errors': _recent_errors()}


def preview(kind, ids):
    body = {'kind': _kind(kind), 'ids': _ids(ids), 'force': False}
    return _check(*transport('POST', '/api/jobs/preview', body))


def start(kind, ids, confirm_count):
    """Ask Fred in the app. Nothing starts here: the job starts only when he clicks Start in Brainamon."""
    p = preview(kind, ids)
    if p['count'] == 0:
        raise JobToolError('Nothing to do: every one of these items already has this step done.')
    if int(confirm_count) != p['count']:
        raise JobToolError(f"The preview now says {p['count']} item(s), not {confirm_count}. "
                           'Show Fred the preview (count, provider, model) and ask again.')
    body = {'kind': kind, 'ids': _ids(ids), 'source': SOURCE}
    req = _check(*transport('POST', '/api/jobs/request', body))
    if req.get('state') == 'approved':
        return {'requested': req, 'preview': p,
                'next': 'Fred turned on auto-approve (Settings > Claude Code), so the job started at once. '
                        'Call job_status to follow it.'}
    return {'requested': req, 'preview': p,
            'next': 'Nothing has started. Brainamon now shows Fred a confirm window; the job starts only when he '
                    'clicks Start there. Close keeps it pending in Jobs. Call job_status: request.state becomes '
                    'approved or declined when Fred answers.'}


def save_note(topic, body, sources, file='', category='', stamps=None):
    """Ask Fred in the app. Nothing is written here: the note is saved only when he clicks in Brainamon.
    With `file`, the request replaces that existing personal note (a reformat Fred previews); `stamps`
    (a list, with `file` only) replaces its stamps, None keeps them."""
    ids = sorted({int(i) for i in sources or []})
    payload = {'topic': str(topic or ''), 'body': str(body or ''), 'sources': ids,
               'file': str(file or ''), 'category': str(category or ''), 'source': SOURCE}
    if stamps is not None:
        payload['stamps'] = list(stamps)
    req = _check(*transport('POST', '/api/notes/request', payload))
    if req.get('state') == 'approved':
        return {'requested': req,
                'next': 'Fred turned on auto-approve (Settings > Claude Code), so the note was written at once.'}
    return {'requested': req,
            'next': 'Nothing is saved yet. Brainamon now shows Fred the note in a confirm window; it is written '
                    '(a new file, or the named personal note replaced) only when he clicks there. Call job_status: '
                    'request.state becomes approved or declined when Fred answers. Close keeps it pending in Jobs.'}


def set_category(ids, category):
    """Ask Fred in the app to move items to an existing category. Nothing changes here: it is applied only when
    he clicks in Brainamon (or at once with auto-approve). Unlike the categorize job it replaces a current category."""
    body = {'ids': _ids(ids), 'category': str(category or ''), 'source': SOURCE}
    req = _check(*transport('POST', '/api/items/category/request', body))
    if req.get('state') == 'approved':
        return {'requested': req,
                'next': 'Fred turned on auto-approve (Settings > Claude Code), so the category was set at once.'}
    return {'requested': req,
            'next': 'Nothing has changed. Brainamon now shows Fred which items would move; they move only when he '
                    'clicks there. Close keeps it pending in Jobs. Call job_status: request.state becomes '
                    'approved or declined when Fred answers.'}


def set_categories(groups):
    """Queue one mixed-category batch. Batches always require manual approval."""
    req = _check(*transport('POST', '/api/items/categories/request', {'groups': groups, 'source': SOURCE}))
    return {'requested': req,
            'next': 'Review all category assignments in Brainamon and click Apply batch once. '
                    'If pending, nothing has changed. Call job_status to check the result.'}


def control(action):
    if action not in ACTIONS:
        raise JobToolError(f"action must be one of: {', '.join(ACTIONS)}")
    return _check(*transport('POST', f'/api/jobs/{action}'))


def set_canvas(proposal):
    """Ask Fred in the app to create or extend a canvas. Nothing is written here: Brainamon shows the review window
    and applies it only on his click (never by auto-approve)."""
    req = _check(*transport('POST', '/api/canvases/request', {'proposal': proposal, 'source': SOURCE}))
    return {'requested': req,
            'next': 'Nothing is written yet. Brainamon shows Fred the canvas in a review window; it is applied only when '
                    'he clicks Apply there. Close keeps it pending in Jobs. One request waits at a time: call job_status '
                    'and make the next request (for example save_note) only after request.state is approved or declined.'}
