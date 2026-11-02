"""What Wiskit shows while the window sleeps, server side (projects/wiskit-activity): the `hello` fields
`asks` and `cloud`, and the `ask_run` event. No uvicorn, no model calls.

Run from the project root:  py -m unittest tests.test_server_activity -v
"""
import asyncio
import types
import unittest
from unittest import mock

from server import events
from server.routes import ask


def _request(**state):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(**state)))


def _hello(request):
    """The first event of GET /api/events, then the stream is closed."""
    async def first():
        gen = events.events(request)
        try:
            return await gen.__anext__()
        finally:
            await gen.aclose()
    return asyncio.run(first())


class HelloTest(unittest.TestCase):
    def test_hello_carries_the_running_answers_and_the_drive_state(self):
        jobs = mock.Mock(snapshot=lambda: {'current': None, 'last': None, 'request': None})
        sync = mock.Mock(status=lambda: {'state': 'publishing', 'running': True, 'done': 3, 'total': 18})
        hub = events.EventHub()
        ev = _hello(_request(hub=hub, jobs=jobs, sync=sync, ask_runs={'a1': object(), 'b2': object()}))
        self.assertEqual(ev.event, 'hello')
        self.assertEqual(ev.data, {'jobs': {'current': None, 'last': None, 'request': None}, 'asks': 2,
                                   'cloud': {'state': 'publishing', 'running': True, 'done': 3, 'total': 18}})
        self.assertEqual(hub._subs, set())                  # closing the stream unsubscribed it

    def test_hello_without_answers_or_a_readable_drive_state(self):
        jobs = mock.Mock(snapshot=lambda: {'current': None})

        def broken():
            raise OSError('token file locked')
        ev = _hello(_request(hub=events.EventHub(), jobs=jobs, sync=mock.Mock(status=broken)))
        self.assertEqual(ev.data, {'jobs': {'current': None}, 'asks': 0, 'cloud': None})
        ev = _hello(_request(hub=events.EventHub(), jobs=jobs))      # no sync service at all
        self.assertEqual(ev.data, {'jobs': {'current': None}, 'asks': 0, 'cloud': None})


class AskRunTest(unittest.TestCase):
    def test_track_publishes_how_many_answers_run(self):
        hub = mock.Mock()
        app = types.SimpleNamespace(state=types.SimpleNamespace(hub=hub))
        ask._track(app, 'r1', object())
        ask._track(app, 'r2', object())
        ask._track(app, 'r1')
        ask._track(app, 'r1')                    # already gone: it still says how many run
        ask._track(app, 'r2')
        self.assertEqual([c.args for c in hub.publish.call_args_list],
                         [('ask_run', {'running': n}) for n in (1, 2, 1, 1, 0)])
        self.assertEqual(app.state.ask_runs, {})


if __name__ == '__main__':
    unittest.main()
