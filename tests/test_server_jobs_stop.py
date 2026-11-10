"""POST /api/jobs/stop with a job id (projects/phone-processing-flow, plans/00-review-repairs.md R4).

The phone's Tools panel stops the job it shows by its id. The manager compares that id to the running job under its lock,
so a Stop meant for a job that has ended cannot stop the job that replaced it; a refused Stop changes nothing, and a call
without an id (the desktop windows, Forget, Connections reset) behaves as it always did. Temporary data and cloud folders;
the model call is a stub.  py -m unittest tests.test_server_jobs_stop -v
"""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core.db import Database
from server.app import create_app
from server.jobs import KINDS, Job, JobError

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class AnalyzeSnapshotTest(unittest.TestCase):
    def test_joined_analysis_reports_resolved_options_without_credentials(self):
        job = Job(id=1, kind='analyze', label='Analyze', ids=[1], force=False, opts={})
        job.ctx = {'opts': {'frame_interval': 5, 'transcribe': False, 'analysis_provider': 'none', 'extra': 'private'},
                   'analysis_key': 'private', 'whisper_key': 'private'}
        expected = {'frame_interval': 5, 'transcribe': False, 'analysis_provider': 'none'}
        self.assertEqual(job.snapshot()['options'], expected)
        self.assertNotIn('private', str(job.snapshot()))
        job.snapshot()['options']['frame_interval'] = 99
        self.assertEqual(job.ctx['opts']['frame_interval'], 5)
        job.kind = 'describe'
        self.assertNotIn('options', job.snapshot())


class StopByIdTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.set_setting('ai_model_jarvis', '{"provider":"anthropic","model":"claude-sonnet-4-6"}')
        self.ids = [db.add_item({'url': f'https://youtu.be/s{i}', 'description': f'item {i}', 'type': 'Video'}) for i in range(6)]
        db.close()
        self.gate = threading.Event()
        self.entered = threading.Semaphore(0)

        def slow(provider, model, *, prompt, images, max_tokens=2000):
            self.entered.release()
            self.gate.wait(10)
            return 'x'

        for p in (mock.patch.object(ai_client, 'complete_vision', slow), mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}),
                  mock.patch.multiple(KINDS['describe'], gap=0.0, error_gap=0.0)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.gate.set)
        app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def start(self, ids):
        r = self.c.post('/api/jobs', json={'kind': 'describe', 'ids': ids, 'force': True}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.entered.acquire(timeout=5), 'the job did not reach its first item')
        return r.json()['id']

    def idle(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.05)
        self.fail('job did not finish')

    def current(self):
        return self.c.get('/api/jobs').json()['current']

    def test_stopping_the_running_job_by_its_id(self):
        job = self.start(self.ids)
        r = self.c.post('/api/jobs/stop', json={'id': job}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.gate.set()
        last = self.idle()
        self.assertEqual((last['id'], last['state']), (job, 'stopped'))
        self.assertLess(last['done'] + last['err'], len(self.ids))

    def test_a_stale_id_does_not_stop_the_job_that_replaced_it(self):
        old = self.start(self.ids[:2])
        self.gate.set()
        self.assertEqual(self.idle()['id'], old)
        self.gate.clear()
        new = self.start(self.ids)
        self.assertNotEqual(new, old)
        r = self.c.post('/api/jobs/stop', json={'id': old}, headers=W)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn('not running any more', r.json()['detail'])
        cur = self.current()
        self.assertEqual((cur['id'], cur['state']), (new, 'running'))
        self.assertFalse(self.c.app.state.jobs.current.stopping, 'the replacement must not be stopping')
        self.assertEqual(self.c.post('/api/jobs/stop', json={'id': new}, headers=W).status_code, 200)
        self.gate.set()
        self.assertEqual(self.idle()['state'], 'stopped')

    def test_an_id_with_no_running_job_is_refused_and_changes_nothing(self):
        r = self.c.post('/api/jobs/stop', json={'id': 7}, headers=W)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIsNone(self.current())

    def test_a_bad_id_is_refused(self):
        job = self.start(self.ids)
        for bad in ('1', 0, -3, 1.5, True, [1], {'a': 1}):
            with self.subTest(bad=bad):
                r = self.c.post('/api/jobs/stop', json={'id': bad}, headers=W)
                self.assertEqual(r.status_code, 400, r.text)
        self.assertFalse(self.c.app.state.jobs.current.stopping)
        self.assertEqual(self.current()['id'], job)

    def test_calls_without_an_id_work_as_before(self):
        # no body at all (the desktop windows), an empty object, and no job running
        self.assertEqual(self.c.post('/api/jobs/stop', headers=W).status_code, 200)
        self.assertIsNone(self.current())
        job = self.start(self.ids)
        self.assertEqual(self.c.post('/api/jobs/stop', json={}, headers=W).status_code, 200)
        self.assertTrue(self.c.app.state.jobs.current.stopping)
        self.gate.set()
        last = self.idle()
        self.assertEqual((last['id'], last['state']), (job, 'stopped'))

    def test_the_manager_refuses_a_stale_id_directly(self):
        jobs = self.c.app.state.jobs
        with self.assertRaises(JobError):
            jobs.stop(3)
        job = self.start(self.ids)
        with self.assertRaises(JobError):
            jobs.stop(job + 1)
        self.assertFalse(jobs.current.stopping)
        self.assertEqual(jobs.stop(job)['current']['id'], job)
        self.assertTrue(jobs.current.stopping)


if __name__ == '__main__':
    unittest.main()
