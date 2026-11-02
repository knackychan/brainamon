"""Tests for connections.py (the Qt-free Connections detection core).

Run from the project root:  py -m unittest tests.test_connections -v
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from knowledge import connections


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _item(item_id, desc_len=300, creator='c', tags='', created=0):
    """Minimal item dict shaped like a db.get_items_by_ids row for these tests."""
    return {'id': item_id, 'description': 'x' * desc_len, 'ai_desc': '',
            'tags': tags, 'creator': creator, 'transcript': '', 'created': created}


class KeyTest(unittest.TestCase):
    def test_bridge_key_orders_ids(self):
        self.assertEqual(connections.bridge_key(12, 3), '3-12')

    def test_label_key_slug(self):
        self.assertEqual(connections.label_key('Local LLMs!'), 'drift-local-llms')
        self.assertEqual(connections.label_key(''), 'drift-theme')


class LedgerTest(unittest.TestCase):
    def test_parses_sources_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'note.md'
            p.write_text('---\ntopic: t\ncreated: x\nsources: 3,7,12\n---\n\nbody',
                         encoding='utf-8')
            noted_ids, noted_pairs = connections.load_note_ledger(td)
        self.assertEqual(noted_ids, {3, 7, 12})
        self.assertIn(frozenset((3, 12)), noted_pairs)
        self.assertIn(frozenset((3, 7)), noted_pairs)

    def test_missing_dir_is_empty(self):
        noted_ids, noted_pairs = connections.load_note_ledger('does/not/exist')
        self.assertEqual((noted_ids, noted_pairs), (set(), set()))


class KMeansTest(unittest.TestCase):
    def test_separates_two_blobs_deterministically(self):
        rng = np.random.default_rng(0)
        a = rng.normal(loc=(1, 0, 0), scale=0.05, size=(30, 3))
        b = rng.normal(loc=(0, 1, 0), scale=0.05, size=(30, 3))
        m = np.vstack([a, b]).astype(np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True)
        labels1, cents1 = connections.kmeans(m, k=2)
        labels2, _ = connections.kmeans(m, k=2)
        self.assertTrue((labels1 == labels2).all())           # seeded -> deterministic
        self.assertEqual(len(set(labels1[:30].tolist())), 1)  # blob A in one cluster
        self.assertEqual(len(set(labels1[30:].tolist())), 1)  # blob B in one cluster
        self.assertNotEqual(labels1[0], labels1[30])          # different clusters
        self.assertEqual(cents1.shape, (2, 3))

    def test_k_is_clamped_to_n(self):
        m = np.vstack([_unit((1, 0, 0)), _unit((0, 1, 0))]).astype(np.float32)
        labels, cents = connections.kmeans(m, k=20)
        self.assertEqual(len(labels), 2)
        self.assertLessEqual(cents.shape[0], 2)


class BridgeTest(unittest.TestCase):
    def _fixture(self):
        # rows 0,1 -> cluster 0; rows 2,3 -> cluster 1. Rows 1 and 2 are nearly
        # identical vectors in different clusters -> the expected bridge.
        m = np.vstack([
            _unit((1, 0, 0)),
            _unit((0.8, 0.6, 0)),
            _unit((0.79, 0.61, 0)),
            _unit((0, 1, 0)),
        ]).astype(np.float32)
        ids = [10, 11, 12, 13]
        labels = np.array([0, 0, 1, 1])
        items = {10: _item(10, creator='a'), 11: _item(11, creator='b'),
                 12: _item(12, creator='c'), 13: _item(13, creator='d')}
        return ids, m, labels, items

    def test_finds_best_cross_cluster_pair_first(self):
        ids, m, labels, items = self._fixture()
        out = connections.find_bridges(ids, m, labels, items, set(), set())
        self.assertTrue(out)
        self.assertEqual(out[0]['key'], '11-12')
        self.assertGreater(out[0]['score'], 0.99)

    def test_each_item_used_at_most_once(self):
        ids, m, labels, items = self._fixture()
        out = connections.find_bridges(ids, m, labels, items, set(), set())
        seen = [i for o in out for i in (o['a_id'], o['b_id'])]
        self.assertEqual(len(seen), len(set(seen)))

    def test_same_creator_pair_is_skipped(self):
        ids, m, labels, items = self._fixture()
        items[12]['creator'] = 'b'          # same creator as item 11
        out = connections.find_bridges(ids, m, labels, items, set(), set())
        self.assertNotIn('11-12', [o['key'] for o in out])

    def test_noted_and_dismissed_pairs_are_skipped(self):
        ids, m, labels, items = self._fixture()
        out = connections.find_bridges(ids, m, labels, items,
                                       {frozenset((11, 12))}, set())
        self.assertNotIn('11-12', [o['key'] for o in out])
        out = connections.find_bridges(ids, m, labels, items, set(), {'11-12'})
        self.assertNotIn('11-12', [o['key'] for o in out])

    def test_short_text_items_are_ineligible(self):
        ids, m, labels, items = self._fixture()
        items[11] = _item(11, desc_len=50, creator='b')   # below _MIN_TEXT
        out = connections.find_bridges(ids, m, labels, items, set(), set())
        self.assertNotIn('11-12', [o['key'] for o in out])


class DriftTest(unittest.TestCase):
    NOW = 1_000_000_000_000

    def test_recent_uncovered_cluster_is_reported(self):
        recent = self.NOW - 5 * 86400 * 1000
        old = self.NOW - 90 * 86400 * 1000
        ids = list(range(1, 9))                     # 8 items, all one cluster
        labels = np.zeros(8, dtype=np.int64)
        items = {i: _item(i, tags='local llms, ai', created=recent) for i in ids}
        items[8]['created'] = old                   # 7 recent >= _DRIFT_MIN_ITEMS
        out = connections.find_drift(ids, labels, items, set(), self.NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out[0]['member_ids']), list(range(1, 8)))
        self.assertIn('local llms', out[0]['top_tags'])

    def test_covered_cluster_is_not_reported(self):
        recent = self.NOW - 5 * 86400 * 1000
        ids = list(range(1, 8))
        labels = np.zeros(7, dtype=np.int64)
        items = {i: _item(i, created=recent) for i in ids}
        noted = {1, 2, 3, 4}                        # more than half covered by notes
        out = connections.find_drift(ids, labels, items, noted, self.NOW)
        self.assertEqual(out, [])

    def test_small_recent_cluster_is_not_reported(self):
        recent = self.NOW - 5 * 86400 * 1000
        ids = [1, 2, 3]                             # below _DRIFT_MIN_ITEMS
        labels = np.zeros(3, dtype=np.int64)
        items = {i: _item(i, created=recent) for i in ids}
        out = connections.find_drift(ids, labels, items, set(), self.NOW)
        self.assertEqual(out, [])


if __name__ == '__main__':
    unittest.main()
