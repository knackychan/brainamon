"""Plan 10-footprint part A: the streaming embedding index, its idle drop, the shared /api/items
cache, the thread pool size and the SSE drop of a stalled page.

Run from the project root:  py -m unittest tests.test_server_footprint -v
Uses a temporary data folder; never touches data/.
"""
import asyncio
import random
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from tests.auth_client import TestClient

from core import ai_client
from core.db import Database
from library import search
from server import events
from server.app import THREADS, create_app
from server.routes import smart
from server.store import reader

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def _old_index(rows):
    """The pre-A2 EmbeddingIndex build, kept here as the reference: (ids, matrix)."""
    ids, vecs = [], []
    expected_dim = rows[0][1] if rows else 0
    for item_id, dim, blob in rows:
        if dim != expected_dim or len(blob) != dim * 4:
            continue
        ids.append(item_id)
        vecs.append(search.blob_to_vec(blob, dim))
    if not vecs:
        return ids, np.empty((0, expected_dim), dtype=np.float32)
    m = np.vstack(vecs).astype(np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, m / norms


class StreamingIndexTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        rng = random.Random(7)
        dim = 24
        self.ids = []
        for n in range(1200):                      # more than one 512-row normalize block
            i = self.db.add_item({'url': f'https://example.com/{n}', 'description': f'item {n}'})
            self.ids.append(i)
            vec = [0.0] * dim if n == 5 else [rng.uniform(-1, 1) for _ in range(dim)]   # one zero vector
            self.db.upsert_embedding(i, ai_client.EMBEDDING_MODEL, dim, f'h{n}', search.vec_to_blob(vec))
        bad = self.db.add_item({'url': 'https://example.com/bad', 'description': 'bad'})
        self.db.upsert_embedding(bad, ai_client.EMBEDDING_MODEL, dim, 'hb', b'\0' * 12)   # corrupt blob
        other = self.db.add_item({'url': 'https://example.com/other', 'description': 'other'})
        self.db.upsert_embedding(other, ai_client.EMBEDDING_MODEL, 8, 'ho', search.vec_to_blob([1] * 8))
        self.rows = self.db.get_all_embeddings(ai_client.EMBEDDING_MODEL)

    def test_same_ids_matrix_and_scores_as_the_old_build(self):
        old_ids, old_m = _old_index(self.rows)
        for idx in (search.EmbeddingIndex(self.rows),
                    search.EmbeddingIndex.from_db(self.db, ai_client.EMBEDDING_MODEL)):
            self.assertEqual(idx.ids(), old_ids)
            self.assertEqual(idx.matrix().dtype, np.float32)
            self.assertTrue(np.array_equal(idx.matrix(), old_m))
            q = old_m[3]
            old_scores = old_m @ (q / np.linalg.norm(q))
            hits = idx.topk(q, 50)
            self.assertEqual([i for i, _ in hits], [old_ids[j] for j in np.argsort(-old_scores)[:50]])
            for item_id, score in hits:     # einsum instead of BLAS: float32 rounding only
                self.assertAlmostEqual(score, float(old_scores[old_ids.index(item_id)]), places=6)
            self.assertEqual(idx.similar_to(self.ids[10], 5), search.EmbeddingIndex(self.rows).similar_to(self.ids[10], 5))

    def test_count_lower_than_rows_grows(self):
        idx = search.EmbeddingIndex(iter(self.rows), count=3)    # rows added after the count
        self.assertEqual(idx.ids(), _old_index(self.rows)[0])

    def test_empty(self):
        idx = search.EmbeddingIndex([])
        self.assertEqual(len(idx), 0)
        self.assertEqual(idx.matrix().shape, (0, 0))
        self.assertEqual(idx.topk([1, 0], 5), [])
        self.assertEqual(len(search.EmbeddingIndex.from_db(self.db, 'no-such-model')), 0)
        self.assertEqual(self.db.count_embeddings(ai_client.EMBEDDING_MODEL), len(self.rows))


class ServerFootprintTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.a = db.add_item({'url': 'https://www.facebook.com/reel/1', 'description': 'Knee prehab'})
        db.upsert_embedding(self.a, ai_client.EMBEDDING_MODEL, 4, 'h1', search.vec_to_blob([1, 0, 0, 0]))
        db.close()
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'nope', cards_dir=self.data / 'nope')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def creator(self):
        return {x['id']: x for x in self.c.get('/api/items').json()['items']}[self.a]['creator']

    def test_items_cache_is_shared_and_follows_writer_writes(self):
        self.assertEqual(self.creator(), '')
        body = self.app.state.items_cache['']
        out = []
        t = threading.Thread(target=lambda: out.append(self.c.get('/api/items').text))
        t.start()
        t.join()
        self.assertEqual(out[0], body[1])                             # another thread: the same body
        self.assertEqual(set(self.app.state.items_cache), {''})
        gen = self.app.state.writer.generation
        r = self.c.patch(f'/api/items/{self.a}', json={'creator': 'me'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreater(self.app.state.writer.generation, gen)
        self.assertEqual(self.creator(), 'me')
        self.c.get('/api/items?fmt=cols')
        self.assertEqual(set(self.app.state.items_cache), {'', 'cols'})

    def test_writer_bumps_on_failure_too(self):
        gen = self.app.state.writer.generation
        with self.assertRaises(ZeroDivisionError):
            self.app.state.writer.call(lambda db: 1 / 0)
        self.assertEqual(self.app.state.writer.generation, gen + 1)

    def test_thread_pool_is_small(self):
        async def tokens():
            import anyio.to_thread
            return anyio.to_thread.current_default_thread_limiter().total_tokens
        self.assertEqual(self.c.portal.call(tokens), THREADS)

    def test_index_dropped_after_idle(self):
        rd = reader(self.app.state.db_path)
        idx = smart.embed_index(self.app, rd)
        self.assertEqual(len(idx), 1)
        # Exact synthetic time avoids rounding (used + timeout) back below the boundary.
        self.app.state.embed_used = used = 1000.0
        self.assertFalse(smart.drop_if_idle(self.app, now=used + smart.IDLE_DROP_S - 1))
        self.assertIs(self.app.state.embed_index, idx)
        self.assertTrue(smart.drop_if_idle(self.app, now=used + smart.IDLE_DROP_S))
        self.assertIsNone(self.app.state.embed_index)
        self.assertFalse(smart.drop_if_idle(self.app, now=used + 10 * smart.IDLE_DROP_S))
        self.assertIsNot(smart.embed_index(self.app, rd), idx)        # rebuilt on next use


class EventHubDropTest(unittest.TestCase):
    def test_stalled_subscriber_gets_an_end_marker(self):
        async def go():
            hub = events.EventHub()
            hub.bind(asyncio.get_running_loop())
            stalled = hub.subscribe()
            for n in range(events._QUEUE_MAX + 1):
                hub._fanout((n, 'log', {}))
            return hub, stalled
        hub, stalled = asyncio.run(go())
        self.assertNotIn(stalled, hub._subs)
        self.assertEqual(stalled.qsize(), 1)                          # the backlog is gone
        self.assertIsNone(stalled.get_nowait())                       # the stream generator returns on it


if __name__ == '__main__':
    unittest.main()
