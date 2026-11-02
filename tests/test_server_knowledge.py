"""V6 plan 08 endpoints: find sources, notes CRUD, topics (with a digest refresh job), connections
(scan job with the gate stubbed, dismiss, sources, accept job).

Run from the project root:  py -m unittest tests.test_server_knowledge -v
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import ai_defaults
from knowledge import knowledge
from library import search
from core.db import Database
from server.app import create_app
from server.jobs import KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


class KnowledgeServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.ids = [db.add_item({'url': f'https://x/{i}', 'description': f'knee exercise number {i} ' * 20,
                                 'creator': f'c{i}', 'category': 'SPORT'}) for i in range(4)]
        for i, item_id in enumerate(self.ids):
            db.upsert_embedding(item_id, ai_client.EMBEDDING_MODEL, 3, f'h{i}', search.vec_to_blob([1.0, i * 0.1, 0.0]))
        self.note, _ = knowledge.save_new_note(db.notes_dir, 'Knee care', self.ids[:1], '# Knee\nUse No. 1.')
        db.reindex_notes()
        db.close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                  mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None))):
            p.start()
            self.addCleanup(p.stop)
        for k in KINDS.values():
            p = mock.patch.multiple(k, gap=0.0, error_gap=0.0)
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def wait(self):
        end = time.time() + 10
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def test_sources_and_category(self):
        r = self.c.post('/api/knowledge/sources', json={'topic': 'knee exercise', 'limit': 2}, headers=W).json()
        self.assertEqual(r['mode'], 'fts')
        self.assertEqual(len(r['items']), 2)
        self.assertEqual(r['notes'][0]['file'], 'knee-care.md')
        self.assertEqual(len(self.c.get('/api/knowledge/category/SPORT').json()['items']), 4)

    def test_notes_crud(self):
        rows = self.c.get('/api/notes?sort=az').json()
        self.assertEqual(rows[0]['file'], 'knee-care.md')
        n = self.c.get('/api/notes/knee-care.md').json()
        self.assertEqual(n['meta']['topic'], 'Knee care')
        r = self.c.put('/api/notes/knee-care.md', json={'body': '# Edited'}, headers=W).json()
        self.assertIn('updated', self.c.get('/api/notes/knee-care.md').json()['meta'])
        self.assertEqual(self.c.get('/api/notes/knee-care.md').json()['body'], '# Edited')
        r = self.c.post('/api/notes/knee-care.md/rename', json={'title': 'Knee plan'}, headers=W).json()
        self.assertEqual(r['file'], 'knee-plan.md')
        self.assertEqual(self.c.delete('/api/notes/knee-plan.md', headers=W).json(), {'ok': True})
        self.assertEqual(self.c.get('/api/notes/knee-plan.md').status_code, 404)
        self.assertEqual(self.c.get('/api/notes/..%2Fcontent_manager.db').status_code, 404)

    def test_reveal_note(self):
        with mock.patch('server.routes.knowledge._reveal_file') as rv:
            self.assertEqual(self.c.post('/api/notes/knee-care.md/reveal', headers=W).json(), {'ok': True})
            self.assertEqual(Path(rv.call_args.args[0]), self.data / 'notes' / 'knee-care.md')
            self.assertEqual(self.c.post('/api/notes/..%2Fcontent_manager.db/reveal', headers=W).status_code, 404)
            self.assertEqual(self.c.post('/api/notes/nope.md/reveal', headers=W).status_code, 404)
            self.assertEqual(rv.call_count, 1)

    def test_topic_digest_refresh(self):
        t = self.c.post('/api/topics', json={'name': 'Knee'}, headers=W).json()
        self.assertEqual(t[0]['new'], 4)
        self.assertEqual(self.c.post('/api/topics', json={'name': 'Knee'}, headers=W).status_code, 409)
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '## Knee digest'):
            r = self.c.post(f"/api/topics/{t[0]['id']}/refresh", headers=W)
            self.assertEqual(r.status_code, 200, r.text)
            self.wait()
        t = self.c.get('/api/topics').json()
        self.assertEqual((t[0]['new'], t[0]['note_path']), (0, 'topic-knee.md'))
        self.assertIn('## Knee digest', (self.data / 'notes' / 'topic-knee.md').read_text(encoding='utf-8'))
        self.assertEqual(self.c.post(f"/api/topics/{t[0]['id']}/refresh", headers=W).status_code, 400)

    def test_topics_rank_hybrid_with_embeddings(self):
        t = self.c.post('/api/topics', json={'name': 'Knee'}, headers=W).json()
        self.assertEqual((t[0]['mode'], t[0]['mode_reason']), ('fts', 'no OpenAI key for embeddings'))
        db = Database(self.data / 'content_manager.db')
        extra = db.add_item({'url': 'https://x/9', 'description': 'patella tendon rehab'})
        db.upsert_embedding(extra, ai_client.EMBEDDING_MODEL, 3, 'h9', search.vec_to_blob([1.0, 0.0, 0.0]))
        db.close()
        self.app.state.embed_index = None
        calls = []
        with mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('k', None)), \
             mock.patch.object(ai_client, 'embed_texts', lambda texts, **k: calls.append(texts) or [[1.0, 0.0, 0.0]]):
            t = self.c.get('/api/topics').json()
            self.assertEqual((t[0]['mode'], t[0]['new']), ('hybrid', 5))   # the semantic-only item joins
            self.c.get('/api/topics')
            self.assertEqual(calls, [['Knee']])                              # query vector cached
        self.app.state.topic_vecs = None

        def boom(*a, **k):
            raise RuntimeError('offline')
        with mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('k', None)), \
             mock.patch.object(ai_client, 'embed_texts', boom):
            t = self.c.get('/api/topics').json()
        self.assertEqual((t[0]['mode'], t[0]['new'], t[0]['mode_reason']), ('fts', 4, 'embedding failed: offline'))

    def test_augment_skips_sources_already_in_the_note(self):
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '# Knee v2'):
            r = self.c.post('/api/jobs', json={'kind': 'note', 'ids': self.ids[:2], 'force': True,
                                               'opts': {'topic': 'Knee care', 'mode': 'augment', 'note': 'knee-care.md'}}, headers=W)
            self.assertEqual(r.json()['total'], 1)
            self.wait()
        meta, body = knowledge.split_frontmatter((self.data / 'notes' / 'knee-care.md').read_text(encoding='utf-8'))
        self.assertEqual(body.strip(), '# Knee v2')
        self.assertEqual(knowledge.parse_source_ids(meta['sources']), set(self.ids[:2]))

    def test_connections_scan_dismiss_accept(self):
        drift = [{'member_ids': self.ids, 'top_tags': ['knee']}]
        with mock.patch('knowledge.connections.find_drift', lambda *a, **k: drift), \
             mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '{"bridges": {}, "drifts": {"d0": {"label": "Knee work"}}}'):
            self.assertEqual(self.c.post('/api/connections/scan', headers=W).status_code, 200)
            self.wait()
        st = self.c.get('/api/connections').json()
        self.assertEqual([c['key'] for c in st['cards']], ['drift-knee-work'])
        self.assertGreater(st['last_scan'], 0)
        st = self.c.post('/api/connections/drift-knee-work/sources', json={'ids': self.ids[:2]}, headers=W).json()
        self.assertEqual(st['cards'][0]['item_ids'], self.ids[:2])
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '# Connection note'):
            self.c.post('/api/connections/drift-knee-work/accept', headers=W)
            self.wait()
        self.assertEqual(self.c.get('/api/connections').json()['cards'], [])
        st = self.c.post('/api/connections/drift-x/dismiss', headers=W).json()
        self.assertEqual(st['cards'], [])


if __name__ == '__main__':
    unittest.main()
