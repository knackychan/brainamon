"""Server push: one Server-Sent Events stream (GET /api/events) carries job progress, item
changes, console lines and toasts to every open page.

SSE, not WebSocket: the server only ever pushes (commands are plain POSTs), EventSource
reconnects by itself, and it is a plain GET that works in WebView2 and in a browser tab alike.

Event kinds (event: name, data: JSON):
  hello          {jobs: <snapshot>, asks: <int>, cloud: <SyncService.status()> | null}  first event on every connection
  job            <JobManager.snapshot()>            job started / progressed / paused / finished
  job_item       {job, id, state, error?}           one item changed state in the running job
  items_changed  {ids: [int]}                       rows to refetch (GET /api/items?ids=...)
  log            <app_console entry>                one console line
  toast          {text, level}                      a short message for the toast stack
  canvas_changed {id, rev, count}                   a canvas file was written (rev 0: deleted)
  canvas_active  {id}                               the active canvas (where attaches land) changed
  scrape         {line, c}                          a Scrapers window activity line (watcher, Playwright)
  export_done    {kind, path, text}                 an export finished (the page offers Open folder)
  video_tools    {report, folder, transcript, analysis}  a Video Tools analysis finished
  settings_changed {cookies}                        Settings saved (the CK lamp state)
  cloud          <SyncService.status()>             Upload to Google Drive: state, upload progress
  ask_run        {running}                          how many Wiskit answers run now (Wiskit's dot, desktop/activity.py)
"""
import asyncio
import itertools
import threading

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

_QUEUE_MAX = 2000


class EventHub:
    """publish() is safe from any thread; subscribers are asyncio queues on the server loop."""

    def __init__(self):
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, kind: str, data) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            ev = (next(self._seq), kind, data)
        try:
            loop.call_soon_threadsafe(self._fanout, ev)
        except RuntimeError:      # loop shut down between the check and the call
            pass

    def _fanout(self, ev) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # a stalled page (a suspended window, plan 10-footprint A1): end its stream so
                # EventSource reconnects and gets a fresh hello, instead of waiting forever on a
                # queue nobody fills
                self._subs.discard(q)
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(None)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(_QUEUE_MAX)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)


router = APIRouter()


async def _cloud(state):
    """The Drive upload state for hello (desktop/activity.py), read off the event loop; None when it cannot
    be read, so a token or key problem never breaks the stream."""
    sync = getattr(state, 'sync', None)
    if sync is None:
        return None
    try:
        return await asyncio.to_thread(sync.status)
    except Exception:
        return None


@router.get('/api/events', response_class=EventSourceResponse)
async def events(request: Request):
    hub: EventHub = request.app.state.hub
    q = hub.subscribe()
    try:
        state = request.app.state
        yield ServerSentEvent(data={'jobs': state.jobs.snapshot(), 'asks': len(getattr(state, 'ask_runs', None) or {}),
                                    'cloud': await _cloud(state)}, event='hello')
        while True:
            ev = await q.get()
            if ev is None:            # dropped by _fanout
                return
            seq, kind, data = ev
            yield ServerSentEvent(data=data, event=kind, id=str(seq))
    finally:
        hub.unsubscribe(q)
