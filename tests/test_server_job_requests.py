"""Jobs asked for from outside the app wait for a click (projects/mcp-local/plans/01-confirm-in-app.md).

Run from the project root:  py -m unittest tests.test_server_job_requests -v
"""
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core.db import Database
from server import jobs as server_jobs
from server.app import create_app
from server.jobs import KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def _fake_vision(provider, model, *, prompt, images, max_tokens=2000):
    return f'described by {provider}/{model}'


class JobRequestTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
        self.ids = [db.add_item({'url': f'https://youtu.be/{i}', 'description': f'item {i}', 'type': 'Video'})
                    for i in range(3)]
        db.update_item(self.ids[0], {'ai_desc': 'already'})
        db.close()
        for p in (mock.patch.object(ai_client, 'complete_vision', _fake_vision),
                  mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}),
                  mock.patch.multiple(KINDS['describe'], gap=0.0, error_gap=0.0)):
            p.start()
            self.addCleanup(p.stop)
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def _ask(self, kind='describe', ids=None):
        return self.c.post('/api/jobs/request', json={'kind': kind, 'ids': self.ids if ids is None else ids}, headers=W)

    def _wait_idle(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s
            time.sleep(0.05)
        self.fail('job did not finish')

    def test_request_waits_and_approve_starts_without_force(self):
        r = self._ask()
        self.assertEqual(r.status_code, 200)
        req = r.json()
        self.assertEqual((req['state'], req['preview']['count']), ('pending', 2))
        snap = self.c.get('/api/jobs').json()
        self.assertIsNone(snap['current'])                       # nothing started
        self.assertEqual(snap['request']['id'], req['id'])
        a = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json()['request']['state'], 'approved')
        self._wait_idle()
        rows = {x['id']: x for x in self.c.get('/api/items').json()['items']}
        self.assertEqual(rows[self.ids[0]]['desc'], 'already')  # force stayed False
        self.assertTrue(rows[self.ids[1]]['desc'].startswith('described by'))

    def test_decline_starts_nothing_and_answers_once(self):
        req = self._ask().json()
        d = self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)
        self.assertEqual(d.json()['request']['state'], 'declined')
        self.assertIsNone(self.c.get('/api/jobs').json()['last'])
        again = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)
        self.assertEqual(again.status_code, 400)

    def test_only_fill_kinds_and_one_pending(self):
        for kind in ('analyze', 'note', 'index', 'download', 'nope'):
            self.assertEqual(self._ask(kind).status_code, 400, kind)
        self.assertEqual(self._ask(ids=[]).status_code, 400)
        self.assertEqual(self._ask(ids=[self.ids[0]]).status_code, 400)   # nothing to do
        self.assertEqual(self._ask().status_code, 200)
        self.assertEqual(self._ask().status_code, 409)                    # one pending at a time
        self.assertEqual(self.c.post('/api/jobs/request/1/maybe', headers=W).status_code, 404)

    def test_deferred_request_remains_pending_until_approved(self):
        req = self._ask().json()
        self.c.app.state.jobs.request['t0'] -= 24 * 60 * 60
        self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')
        self.assertEqual(self._ask().status_code, 409)
        self.assertEqual(self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W).status_code, 200)
        self._wait_idle()

    def test_approve_while_busy_keeps_it_pending(self):
        slow = mock.patch.object(ai_client, 'complete_vision', lambda *a, **k: (time.sleep(0.3), 'x')[1])
        slow.start()
        self.addCleanup(slow.stop)
        self.assertEqual(self.c.post('/api/jobs', json={'kind': 'describe', 'ids': self.ids[1:2]}, headers=W).status_code, 200)
        req = self._ask(ids=self.ids[2:]).json()
        busy = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')
        self.c.post('/api/jobs/stop', headers=W)
        self._wait_idle()

    def test_post_needs_the_header(self):
        r = self.c.post('/api/jobs/request', json={'kind': 'describe', 'ids': self.ids})
        self.assertEqual(r.status_code, 403)

    def _note(self, **kw):
        body = {'topic': 'Knee plan', 'body': f'Do the hip airplanes [id {self.ids[1]}].', 'sources': [self.ids[1]], **kw}
        return self.c.post('/api/notes/request', json=body, headers=W)

    def _notes(self):
        d = self.data / 'notes'
        return sorted(p.name for p in d.glob('*.md')) if d.exists() else []

    def test_note_request_waits_and_approve_writes_a_new_note(self):
        r = self._note()
        self.assertEqual(r.status_code, 200)
        req = r.json()
        self.assertEqual((req['type'], req['state'], req['topic']), ('note', 'pending', 'Knee plan'))
        self.assertNotIn('body', req)
        self.assertTrue(req['excerpt'].startswith('Do the hip airplanes'))
        self.assertNotIn('body', self.c.get('/api/jobs').json()['request'])
        self.assertEqual(self._notes(), [])                                   # nothing written yet
        a = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W).json()
        self.assertEqual(a['request']['state'], 'approved')
        first = a['saved']
        self.assertEqual(self._notes(), [first])
        text = (self.data / 'notes' / first).read_text(encoding='utf-8')
        self.assertIn('topic: Knee plan', text)
        self.assertIn(f'sources: {self.ids[1]}', text)
        self.assertIn('hip airplanes', text)
        req2 = self._note().json()
        second = self.c.post(f"/api/jobs/request/{req2['id']}/approve", headers=W).json()['saved']
        self.assertNotEqual(second, first)                                    # never replaces a note
        self.assertEqual(len(self._notes()), 2)

    def test_note_decline_limits_and_one_slot(self):
        req = self._note().json()
        self.assertEqual(self._ask().status_code, 409)                        # a note waiting blocks a job request
        self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)
        self.assertEqual(self._notes(), [])
        self.assertEqual(self._note(topic='  ').status_code, 400)
        self.assertEqual(self._note(body='x' * (server_jobs.NOTE_BODY_MAX + 1)).status_code, 400)
        self.assertEqual(self._ask().status_code, 200)
        self.assertEqual(self._note().status_code, 409)                       # a job request waiting blocks a note

    def test_note_replace_request(self):
        notes = self.data / 'notes'
        notes.mkdir(exist_ok=True)
        (notes / 'diary.md').write_text('---\ntopic: Diary\nkind: personal\ncategory: General\n---\n\nold', encoding='utf-8')
        (notes / 'wiki.md').write_text('---\ntopic: Wiki\nsources: 1\n---\n\nwiki', encoding='utf-8')
        bad = self.c.post('/api/notes/request', json={'topic': 'X', 'body': 'b', 'file': 'wiki.md'}, headers=W)
        self.assertEqual(bad.status_code, 400)                       # not a personal note
        self.assertEqual(self._note(file='missing.md').status_code, 400)
        r = self._note(topic='Diary', body='new', file='diary.md', category='Work')
        self.assertEqual(r.status_code, 200, r.text)
        req = r.json()
        self.assertEqual((req['type'], req['file'], req['state']), ('note', 'diary.md', 'pending'))
        self.assertIn('old', (notes / 'diary.md').read_text(encoding='utf-8'))   # nothing written yet
        a = self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W).json()
        self.assertEqual(a['saved'], 'diary.md')                     # same file, replaced
        text = (notes / 'diary.md').read_text(encoding='utf-8')
        self.assertIn('new', text)
        self.assertIn('kind: personal', text)
        self.assertIn('category: Work', text)

    def _category(self, **kw):
        return self.c.post('/api/items/category/request', json={'ids': self.ids, 'category': 'TARGET', **kw}, headers=W)

    def _categories(self):
        return {x['id']: x['cat'] for x in self.c.get('/api/items').json()['items']}

    def _target(self, name='TARGET'):
        self.c.app.state.writer.call(lambda db: db.add_category(name, '#123456'))

    def _answer_category(self, req):
        return self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)

    def test_category_validation_is_atomic_and_bounded(self):
        self._target()
        before = self._categories()
        cases = [({'category': 'Nope'}, 'No category'), ({'category': '  '}, 'No category'),
                 ({'ids': []}, 'between 1 and 500'), ({'ids': list(range(501))}, 'between 1 and 500'),
                 ({'ids': [self.ids[0], 999999]}, 'No such item'),
                 ({'ids': [2 ** 63]}, '64-bit'), ({'ids': [-(2 ** 63) - 1]}, '64-bit'),
                 ({'ids': ['bad']}, 'invalid literal'), ({'ids': [None]}, 'int()'),
                 ({'ids': [{}]}, 'int()')]
        for body, message in cases:
            with self.subTest(body=body):
                r = self._category(**body)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn(message, r.json()['detail'])
                self.assertEqual(self._categories(), before)
                self.assertIsNone(self.c.get('/api/jobs').json()['request'])
        # JSON 1e400 parses as infinity and int(infinity) raises OverflowError.
        r = self.c.post('/api/items/category/request', content='{"ids":[1e400],"category":"TARGET"}',
                        headers={**W, 'Content-Type': 'application/json'})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._categories(), before)
        for boundary in (-(2 ** 63), 2 ** 63 - 1):
            r = self._category(ids=[boundary])
            self.assertEqual(r.status_code, 400)
            self.assertIn('No such item', r.json()['detail'])
        self.c.app.state.writer.call(lambda db: db.set_field_bulk(self.ids, 'category', 'TARGET'))
        r = self._category()
        self.assertEqual(r.status_code, 400)
        self.assertIn('Nothing to do', r.json()['detail'])
        self.assertTrue(all(c == 'TARGET' for c in self._categories().values()))

    def test_category_exact_name_and_distinct_id_limit(self):
        name = 'Mixed  Case\tName'
        self._target(name)
        wrong_case = self._category(category=name.lower())
        self.assertEqual(wrong_case.status_code, 400)
        self.assertIn('No category named', wrong_case.json()['detail'])
        req = self._category(category=f'  {name} \t', ids=[self.ids[0]] * 501).json()
        self.assertEqual(req['category'], name)
        self.assertEqual(req['ids'], self.ids[:1])
        self.assertEqual(self._answer_category(req).json()['moved'], 1)
        self.assertEqual(self._categories()[self.ids[0]], name)
        def add(db):
            return [db.add_item({'url': f'https://x/limit/{i}'}) for i in range(500)]
        ids = self.c.app.state.writer.call(add)
        req = self._category(category=name, ids=ids).json()
        self.assertEqual(len(req['ids']), 500)
        self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)

    def test_category_route_requires_local_host_and_header(self):
        self._target()
        body = {'ids': self.ids, 'category': 'TARGET'}
        before = self._categories()
        self.assertEqual(self.c.post('/api/items/category/request', json=body).status_code, 403)
        self.assertEqual(self.c.post('/api/items/category/request', json=body,
                                     headers={**W, 'Host': 'foreign.example:8765'}).status_code, 403)
        self.assertEqual(self._categories(), before)

    def test_category_defer_decline_and_stale_id(self):
        self._target()
        before = self._categories()
        req = self._category().json()
        self.assertEqual(self._categories(), before)
        self.assertEqual(self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W).json()['request']['state'], 'declined')
        self.assertEqual(self._categories(), before)
        req = self._category().json()
        self.c.app.state.jobs.request['t0'] -= 24 * 60 * 60
        self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')
        self.assertEqual(self._category().status_code, 409)
        self.assertEqual(self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W).status_code, 200)
        replacement = self._category().json()
        self.assertNotEqual(replacement['id'], req['id'])
        self.assertEqual(self._answer_category(req).status_code, 400)
        self.assertEqual(self.c.get('/api/jobs').json()['request'], replacement)
        self.assertEqual(self._categories(), before)

    def test_category_revalidates_deleted_and_renamed_target(self):
        for change in ('delete', 'rename'):
            with self.subTest(change=change):
                self._target()
                req = self._category().json()
                def mutate(db):
                    if change == 'delete':
                        db.delete_category('TARGET')
                    else:
                        db.update_category('TARGET', 'RENAMED', '#123456')
                self.c.app.state.writer.call(mutate)
                before = self._categories()
                with mock.patch.object(self.c.app.state.hub, 'publish') as publish:
                    r = self._answer_category(req)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn('No category named TARGET', r.json()['detail'])
                publish.assert_not_called()
                self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')
                self.assertEqual(self._categories(), before)
                names = self.c.app.state.writer.call(lambda db: [c['name'] for c in db.get_categories()])
                self.assertNotIn('TARGET', names)
                self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)

    def test_category_missing_item_rejects_whole_approval(self):
        self._target()
        req = self._category().json()
        self.c.app.state.writer.call(lambda db: db.delete_item(self.ids[1]))
        before = self._categories()
        with mock.patch.object(self.c.app.state.hub, 'publish') as publish:
            r = self._answer_category(req)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn('No such item', r.json()['detail'])
        publish.assert_not_called()
        self.assertEqual(self._categories(), before)
        self.assertEqual(self.c.get('/api/jobs').json()['request']['state'], 'pending')

    def test_category_approval_reports_changed_subset_after_commit(self):
        self._target()
        req = self._category().json()
        self.c.app.state.writer.call(lambda db: db.set_field_bulk(self.ids[:1], 'category', 'TARGET'))
        seen = []
        def published(kind, data):
            if kind == 'items_changed':
                seen.append(data['ids'])
                self.assertTrue(all(self._categories()[i] == 'TARGET' for i in data['ids']))
        with mock.patch.object(self.c.app.state.hub, 'publish', side_effect=published):
            r = self._answer_category(req)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['moved'], 2)
        self.assertEqual(r.json()['request']['state'], 'approved')
        self.assertEqual(seen, [self.ids[1:]])
        self.assertEqual(self.c.app.state.jobs.dirty, set())

    def test_category_already_moved_and_failure_restore_pending(self):
        self._target()
        req = self._category().json()
        before = self._categories()
        jm = self.c.app.state.jobs
        with mock.patch.object(jm, '_set_category', side_effect=server_jobs.JobError('injected failure')), \
                mock.patch.object(jm.hub, 'publish') as publish:
            self.assertEqual(self._answer_category(req).status_code, 400)
        publish.assert_not_called()
        self.assertEqual(self._categories(), before)
        self.assertEqual(jm.request['state'], 'pending')
        self.c.app.state.writer.call(lambda db: db.set_field_bulk(self.ids, 'category', 'TARGET'))
        with mock.patch.object(jm.hub, 'publish') as publish:
            r = self._answer_category(req)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Nothing to do', r.json()['detail'])
        publish.assert_not_called()
        self.assertEqual(jm.request['state'], 'pending')
        self.assertTrue(all(c == 'TARGET' for c in self._categories().values()))

    def test_category_shares_pending_slot_in_both_directions(self):
        self._target()
        for other in (self._note, self._ask):
            with self.subTest(other=other.__name__):
                req = self._category().json()
                self.assertEqual(other().status_code, 409)
                self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)
                req = other().json()
                self.assertEqual(self._category().status_code, 409)
                self.c.post(f"/api/jobs/request/{req['id']}/decline", headers=W)

    def test_concurrent_category_note_job_reservations(self):
        self._target()
        jm = self.c.app.state.jobs
        calls = [('category', lambda: jm.ask_category(self.ids[:1], 'TARGET', 'category caller')),
                 ('note', lambda: jm.ask_note('Race note', 'Secret body', [], 'note caller')),
                 ('job', lambda: jm.ask('describe', self.ids[1:], 'job caller')),
                 ('category', lambda: jm.ask_category(self.ids[1:], 'TARGET', 'second category caller'))]
        for other in calls[1:]:
            with self.subTest(other=other[0]):
                ready = threading.Barrier(2)
                checked_once = threading.local()
                check_free = jm._check_free
                def checked():
                    check_free()
                    if not getattr(checked_once, 'done', False):
                        checked_once.done = True
                        ready.wait(timeout=5)  # both early checks passed, before either reserves
                with mock.patch.object(jm, '_check_free', side_effect=checked), \
                        ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(call) for _, call in (calls[0], other)]
                    results, busy = [], 0
                    for i, future in enumerate(futures):
                        try:
                            results.append((i, future.result(timeout=10)))
                        except server_jobs.Busy:
                            busy += 1
                self.assertEqual((len(results), busy), (1, 1))
                winner, view = results[0]
                self.assertEqual(view, jm._request_view())
                self.assertEqual(view['type'], (calls[0], other)[winner][0])
                self.assertEqual(view['source'], 'category caller' if winner == 0 else {
                    'note': 'note caller', 'job': 'job caller', 'category': 'second category caller'}[other[0]])
                if view['type'] == 'note':
                    self.assertNotIn('body', view)
                    self.assertEqual(view['topic'], 'Race note')
                else:
                    self.assertEqual(view['ids'], self.ids[:1] if winner == 0 else self.ids[1:])
                jm.answer(view['id'], False)

    def test_request_preparation_and_notifications_run_outside_lock(self):
        self._target()
        jm = self.c.app.state.jobs
        writer_call = jm.writer.call
        def writer(fn, *a, **kw):
            self.assertFalse(jm._lock.locked())
            return writer_call(fn, *a, **kw)
        def outside_lock(*a, **kw):
            self.assertFalse(jm._lock.locked())
        with mock.patch.object(jm.writer, 'call', side_effect=writer), \
                mock.patch.object(jm.hub, 'publish', side_effect=outside_lock), \
                mock.patch.object(jm, 'notify', side_effect=outside_lock):
            for ask in (self._category, self._note, self._ask):
                req = ask().json()
                self.assertEqual(req['state'], 'pending')
                jm.answer(req['id'], False)

    def test_settle_returns_its_own_request_when_replaced_during_notification(self):
        self._target()
        jm = self.c.app.state.jobs
        def replace(*args):
            jm.answer(jm.request['id'], False)
            with mock.patch.object(jm, '_settle', side_effect=lambda view, what: view):
                jm.ask_note('Replacement', 'Private body', [])
        with mock.patch.object(jm, 'notify', side_effect=replace):
            req = self._category().json()
        self.assertEqual(req['type'], 'category')
        self.assertEqual(req['category'], 'TARGET')
        self.assertNotEqual(req['id'], jm.request['id'])
        self.assertEqual(jm.request['topic'], 'Replacement')

    def test_approving_request_keeps_shared_slot_reserved(self):
        self._target()
        req = self._category().json()
        jm = self.c.app.state.jobs
        entered, release = threading.Event(), threading.Event()
        write = jm._set_category
        def held(r):
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError('approval not released')
            return write(r)
        with mock.patch.object(jm, '_set_category', side_effect=held), ThreadPoolExecutor(max_workers=1) as pool:
            approval = pool.submit(self._answer_category, req)
            try:
                self.assertTrue(entered.wait(timeout=5))
                self.assertEqual(jm.request['state'], 'approving')
                for ask in (self._category, self._note, self._ask):
                    self.assertEqual(ask().status_code, 409)
            finally:
                release.set()
            self.assertEqual(approval.result(timeout=10).json()['moved'], 3)

    def test_category_auto_approve_keeps_setting_behavior(self):
        self._target()
        self._set(server_jobs.AUTO_APPROVE_KEY, '1')
        self.assertEqual(self._category().json()['state'], 'approved')
        self.assertTrue(all(c == 'TARGET' for c in self._categories().values()))

    # ── auto-approve (Settings > Claude Code) and Windows notifications (Settings > App) ──
    def _set(self, key, value):
        self.c.app.state.writer.call(lambda db: db.set_setting(key, value))

    def _toasts(self):
        """Replace the real sender with a recorder; returns the list the toasts land in."""
        sent, notify = [], self.c.app.state.notify
        notify.sender, notify.focused = (lambda title, text: sent.append((title, text)) or True), (lambda: False)
        return sent

    def _wait_toasts(self, sent, n, timeout=3):
        end = time.time() + timeout
        while len(sent) < n and time.time() < end:
            time.sleep(0.02)
        return sent

    def test_auto_approve_starts_a_job_without_a_click(self):
        self._set(server_jobs.AUTO_APPROVE_KEY, '1')
        req = self._ask().json()
        self.assertEqual(req['state'], 'approved')
        self._wait_idle()
        rows = {x['id']: x for x in self.c.get('/api/items').json()['items']}
        self.assertEqual(rows[self.ids[0]]['desc'], 'already')       # still never forces
        self.assertTrue(rows[self.ids[1]]['desc'].startswith('described by'))

    def test_auto_approve_writes_and_replaces_notes(self):
        notes = self.data / 'notes'
        notes.mkdir(exist_ok=True)
        (notes / 'diary.md').write_text('---\ntopic: Diary\nkind: personal\ncategory: General\n---\n\nold', encoding='utf-8')
        self._set(server_jobs.AUTO_APPROVE_KEY, '1')
        self.assertEqual(self._note().json()['state'], 'approved')
        self.assertEqual(len(self._notes()), 2)
        self.assertEqual(self._note(topic='Diary', body='new', file='diary.md').json()['state'], 'approved')
        self.assertIn('new', (notes / 'diary.md').read_text(encoding='utf-8'))

    def test_auto_approve_off_by_default_and_through_the_setting(self):
        self.assertFalse(self.c.get('/api/claude-code').json()['auto_approve'])
        self.assertTrue(self.c.put('/api/claude-code', json={'auto_approve': True}, headers=W).json()['auto_approve'])
        self.assertEqual(self._ask().json()['state'], 'approved')
        self._wait_idle()
        self.assertFalse(self.c.put('/api/claude-code', json={'auto_approve': False}, headers=W).json()['auto_approve'])
        self.assertEqual(self._note().json()['state'], 'pending')

    def test_toasts_are_off_until_switched_on(self):
        sent = self._toasts()
        self.assertEqual(self.c.get('/api/app').json()['toasts'],
                         {'on': False, 'jobs': True, 'approval': True, 'claude': True, 'capture': True})
        self._ask()
        time.sleep(0.2)
        self.assertEqual(sent, [])
        v = self.c.put('/api/app/toasts', json={'on': True, 'claude': False}, headers=W).json()['toasts']
        self.assertEqual((v['on'], v['claude'], v['approval']), (True, False, True))

    def test_toast_when_a_request_waits_and_when_the_job_ends(self):
        sent = self._toasts()
        self.c.put('/api/app/toasts', json={'on': True}, headers=W)
        req = self._ask().json()
        self._wait_toasts(sent, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn('waiting for your OK', sent[0][0])
        self.c.post(f"/api/jobs/request/{req['id']}/approve", headers=W)
        self._wait_idle()
        self._wait_toasts(sent, 2)
        self.assertEqual(sent[1][0], 'Describe: done')

    def test_toast_when_claude_code_acts_alone(self):
        sent = self._toasts()
        self.c.put('/api/app/toasts', json={'on': True, 'jobs': False}, headers=W)
        self._set(server_jobs.AUTO_APPROVE_KEY, '1')
        self._note()
        self._wait_toasts(sent, 1)
        self.assertEqual(len(sent), 1)
        self.assertIn('did something', sent[0][0])
        self.assertIn('Saved the note', sent[0][1])

    def test_toast_skipped_while_the_window_is_in_front(self):
        sent = self._toasts()
        self.c.app.state.notify.focused = lambda: True
        self.c.put('/api/app/toasts', json={'on': True}, headers=W)
        self._ask()
        time.sleep(0.2)
        self.assertEqual(sent, [])

    def test_toast_for_a_link_and_the_test_button(self):
        sent = self._toasts()
        self.c.put('/api/app/toasts', json={'on': True}, headers=W)
        with mock.patch.object(server_jobs.JobManager, 'start', side_effect=server_jobs.JobError('x')):
            self.c.post('/api/inbox/link', json={'url': 'https://youtu.be/new1'}, headers=W)
        self._wait_toasts(sent, 1)
        self.assertEqual(sent[0][0], 'Link saved to your library')
        self.c.put('/api/app/toasts', json={'on': False}, headers=W)
        self.c.post('/api/app/toasts/test', headers=W)               # the test ignores the switches
        self._wait_toasts(sent, 2)
        self.assertEqual(sent[1], ('Brainamon', 'Windows notifications work.'))


if __name__ == '__main__':
    unittest.main()
