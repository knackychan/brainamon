"""knowledge.py and the connections.py additions (plan 08): frontmatter, note rows and sorts,
write-back, rename / delete, topic_new_ids, the gate parser and the card building.

Run from the project root:  py -m unittest tests.test_knowledge -v
"""
import tempfile
import time
import unittest
from pathlib import Path

from knowledge import connections
from knowledge import knowledge
from core.db import Database


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.nd = self.db.notes_dir
        self.nd.mkdir(parents=True, exist_ok=True)
        self.a = self.db.add_item({'url': 'https://x/1', 'description': 'knee prehab airplanes'})
        self.b = self.db.add_item({'url': 'https://x/2', 'description': 'knee mobility holds'})

    def test_frontmatter_and_ids(self):
        meta, body = knowledge.split_frontmatter('---\ntopic: Knee\nsources: 3, 1,x\n---\n\n# Body')
        self.assertEqual(meta['topic'], 'Knee')
        self.assertEqual(body, '# Body')
        self.assertEqual(knowledge.parse_source_ids(meta['sources']), {1, 3})
        self.assertEqual(knowledge.split_frontmatter('no front'), ({}, 'no front'))

    def test_save_rows_sort_writeback_rename_delete(self):
        p1, _ = knowledge.save_new_note(self.nd, 'Knee care', [self.b, self.a], '# Knee\nText')
        time.sleep(0.01)
        p2, _ = knowledge.save_new_note(self.nd, 'Alpha', [], 'A')
        self.assertEqual(p1.name, 'knee-care.md')
        rows = knowledge.note_rows(self.nd, set())
        self.assertEqual([r['file'] for r in knowledge.sort_note_rows(rows, 'az')], ['alpha.md', 'knee-care.md'])
        r1 = next(r for r in rows if r['file'] == 'knee-care.md')
        self.assertEqual(r1['sources'], [self.a, self.b])
        self.assertEqual(r1['kind'], 'Synthesized')
        meta, _ = knowledge.split_frontmatter(p1.read_text(encoding='utf-8'))
        meta = knowledge.write_back_note(p1, '# Knee v2', meta, [99], 'Knee care')
        self.assertEqual(meta['sources'], f'{self.a},{self.b},99')
        self.assertIn('updated', meta)
        new = knowledge.rename_note(self.nd, p1, 'Knee plan')
        self.assertEqual(new.name, 'knee-plan.md')
        self.assertFalse(p1.exists())
        self.assertIn('topic: Knee plan', new.read_text(encoding='utf-8'))
        knowledge.delete_note(new)
        self.assertFalse(new.exists())
        self.assertIsNone(knowledge.safe_note_path(self.nd, '../content_manager.db'))
        self.assertEqual(knowledge.safe_note_path(self.nd, 'alpha.md'), p2)

    def test_topic_new_ids(self):
        tid = self.db.add_topic('Knee', 'knee')
        t = next(x for x in self.db.list_topics() if x['id'] == tid)
        self.assertEqual(sorted(knowledge.topic_new_ids(self.db, self.nd, t)), sorted([self.a, self.b]))
        p, _ = knowledge.save_new_note(self.nd, 'Knee digest', [self.a], 'digest')
        self.db.update_topic(tid, note_path=p.name)
        t = next(x for x in self.db.list_topics() if x['id'] == tid)
        self.assertEqual(knowledge.topic_new_ids(self.db, self.nd, t), [self.b])
        self.assertEqual(knowledge.new_digest_path(self.nd, 'Knee').name, 'topic-knee.md')

    def test_topic_candidates_hybrid(self):
        from library import search
        c = self.db.add_item({'url': 'https://x/3', 'description': 'patella tendon rehab'})   # no 'knee'
        d = self.db.add_item({'url': 'https://x/4', 'description': 'sourdough starter'})
        idx = search.EmbeddingIndex([(i, 2, search.vec_to_blob(v)) for i, v in
                                     ((self.a, [1, 0.1]), (self.b, [1, 0.2]), (c, [1, 0.05]), (d, [0, 1]))])
        q = [1, 0]
        self.assertEqual(knowledge.topic_candidates(self.db, 'knee'), self.db.fts_ids('knee', 100, match_all=True))
        self.assertEqual(knowledge.topic_candidates(self.db, 'knee', idx, None), knowledge.topic_candidates(self.db, 'knee'))
        hyb = knowledge.topic_candidates(self.db, 'knee', idx, q)
        self.assertEqual(set(hyb), {self.a, self.b, c})      # semantic adds c; d is below the floor
        self.assertEqual(knowledge.topic_candidates(self.db, 'zzz', idx, q), [c, self.a, self.b])
        tid = self.db.add_topic('Knee', 'knee')
        p, _ = knowledge.save_new_note(self.nd, 'Knee digest', [self.a, self.b], 'digest')
        self.db.update_topic(tid, note_path=p.name)
        t = next(x for x in self.db.list_topics() if x['id'] == tid)
        self.assertEqual(knowledge.topic_new_ids(self.db, self.nd, t), [])
        self.assertEqual(knowledge.topic_new_ids(self.db, self.nd, t, index=idx, query_vec=q), [c])


class ConnectionsGateTest(unittest.TestCase):
    def test_parse_gate(self):
        r = connections.parse_gate('ok {"bridges": {"1-2": {"verdict": "keep", "insight": "Shared idea."}, '
                                   '"3-4": {"verdict": "reject"}}, "drifts": {"d0": {"label": "Knee work"}}}')
        self.assertEqual(r, {'bridges': {'1-2': 'Shared idea.'}, 'drifts': {'d0': 'Knee work'}})
        with self.assertRaises(ValueError):
            connections.parse_gate('no json')

    def test_cards_and_merge(self):
        items = {1: {'id': 1, 'ai_desc': 'one'}, 2: {'id': 2, 'ai_desc': 'two'}, 3: {'id': 3, 'ai_desc': 'three'}}
        pending = {'bridges': [{'key': '1-2', 'a_id': 1, 'b_id': 2, 'score': 0.5}],
                   'drifts': [{'member_ids': [1, 2, 3], 'top_tags': ['knee']}], 'items_by_id': items,
                   'dismissed_keys': set()}
        cards = connections.cards_from_gate(pending, {'bridges': {'1-2': 'Insight.'}, 'drifts': {'d0': 'Knee work'}})
        self.assertEqual([c['kind'] for c in cards], ['bridge', 'drift'])
        self.assertEqual(cards[1]['key'], 'drift-knee-work')
        ungated = connections.cards_from_gate(pending, None)
        self.assertEqual([c['kind'] for c in ungated], ['drift'])          # never a bridge without the gate
        merged, n = connections.merge_cards(cards[:1], cards)
        self.assertEqual((n, len(merged)), (1, 2))
        old = int(time.time() * 1000) - 40 * 86400 * 1000
        kept = connections.prune_dismissed([{'key': 'drift-x', 'ts': old}, {'key': '1-2', 'ts': old}])
        self.assertEqual(kept, [{'key': '1-2', 'ts': old}])


if __name__ == '__main__':
    unittest.main()
