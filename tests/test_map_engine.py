"""The knowledge map cache (docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md, decision 5).

Run from the project root:  py -m unittest tests.test_map_engine -v
Pure: temp files only, no DB except one Database in a temp folder for the fingerprint test, no network.
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from library import map_engine as M
from library import search


def vec(*xs):
    v = np.zeros(4, dtype=np.float32)
    for i, x in enumerate(xs):
        v[i] = x
    return v


def index(rows):
    """rows: {item id: vector}; the same shape db.get_all_embeddings returns."""
    return search.EmbeddingIndex([(i, 4, search.vec_to_blob(v)) for i, v in rows.items()])


def topic(members, title='', synthesis='', basis=None, name=''):
    return {'title': title, 'synthesis': synthesis, 'member_ids': sorted(members), 'name': name,
            'summary_basis': basis, 'stale': False}


class CacheTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.path = Path(td.name) / 'obsidian_graph.json'

    def test_missing_and_corrupt_cache_are_empty(self):
        self.assertEqual(M.load(self.path), {'version': 2, 'model': '', 'next_id': 1, 'clusters': {}})
        self.path.write_text('{not json', encoding='utf-8')
        self.assertEqual(M.load(self.path)['clusters'], {})

    def test_v1_migration_keeps_summaries_all_stale(self):
        v1 = {'version': 1, 'model': 'm', 'clusters': {
            'aaaa': {'title': 'Small', 'synthesis': 'two items', 'member_ids': [1, 2]},
            'bbbb': {'title': 'Big', 'synthesis': 'three items', 'member_ids': [3, 4, 5]},
            'cccc': {'title': 'No text', 'synthesis': '', 'member_ids': [6, 7]}}}
        self.path.write_text(json.dumps(v1), encoding='utf-8')
        c = M.load(self.path)
        self.assertEqual(c['version'], 2)
        self.assertEqual(c['model'], 'm')
        self.assertEqual(list(c['clusters']), ['t-1', 't-2', 't-3'])          # size order, largest first
        self.assertEqual(c['clusters']['t-1']['member_ids'], [3, 4, 5])
        self.assertEqual(c['clusters']['t-1']['synthesis'], 'three items')     # summaries kept
        self.assertEqual(c['next_id'], 4)
        M.recompute_stale(c, {})
        self.assertTrue(c['clusters']['t-1']['stale'] and c['clusters']['t-2']['stale'])
        self.assertFalse(c['clusters']['t-3']['stale'])                        # no summary: waiting, not stale
        self.assertEqual(M.status(c['clusters']['t-3']), 'new')
        M.save(self.path, c)
        again = M.load(self.path)
        self.assertEqual(again['clusters']['t-1']['summary_basis'], None)
        self.assertEqual(again['next_id'], 4)

    def test_save_round_trip_and_next_id_floor(self):
        c = M.empty('m')
        tid = M.new_id(c)
        c['clusters'][tid] = topic([1, 2], 'T', 'S', {'1': 'a', '2': 'b'}, 'tt-t1')
        M.save(self.path, c)
        d = json.loads(self.path.read_text(encoding='utf-8'))
        d['next_id'] = 1                                   # a hand-edited file: the floor still protects ids
        self.path.write_text(json.dumps(d), encoding='utf-8')
        again = M.load(self.path)
        self.assertEqual(again['next_id'], 2)
        self.assertEqual(again['clusters']['t-1'], topic([1, 2], 'T', 'S', {'1': 'a', '2': 'b'}, 'tt-t1'))

    def test_two_topics_same_title_distinct_names(self):
        self.assertEqual(M.page_name('Kettlebell basics', 't-1'), 'kettlebell-basics-t1')
        self.assertEqual(M.page_name('Kettlebell basics', 't-12'), 'kettlebell-basics-t12')
        self.assertNotEqual(M.page_name('X', 't-1'), M.page_name('X', 't-2'))
        self.assertEqual(M.page_name('', 't-3'), 'untitled-t3')


class StaleTest(unittest.TestCase):
    def test_fingerprint_follows_current_text_not_item_embeddings(self):
        from core.db import Database
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(db.close)
        iid = db.add_item({'url': 'https://x/1', 'description': 'first text'})
        item = db.get_item(iid)
        before = M.fingerprint('m', item)
        db.upsert_embedding(iid, 'm', 4, search.text_hash('m', search.build_embed_text(item)), search.vec_to_blob(vec(1)))
        db.update_item(iid, {'description': 'corrected text'})
        after = M.fingerprint('m', db.get_item(iid))
        self.assertNotEqual(before, after)                                       # current text, at once
        self.assertEqual(db.get_embedding_hashes('m')[iid], before)              # indexing has not run

    def test_drift_counts_added_removed_changed(self):
        t = topic([1, 2, 3, 5], basis={'1': 'a', '2': 'b', '3': 'c', '4': 'd'}, synthesis='s')
        fps = {1: 'a', 2: 'B', 3: 'c', 5: 'e'}
        self.assertEqual(M.drift(t, fps), (1, 1, 1))          # 5 added, 4 removed, 2 changed
        self.assertEqual(M.drift(topic([1], basis=None, synthesis='s'), fps), (0, 0, 0))

    def test_stale_at_25_percent(self):
        basis = {str(i): 'f' for i in range(1, 9)}             # 8 members summarized
        fps = {i: 'f' for i in range(1, 20)}
        fresh = topic(range(1, 9), synthesis='s', basis=basis)
        self.assertFalse(M.is_stale(fresh, fps))
        one = topic(range(1, 10), synthesis='s', basis=basis)                   # 1 of 8 = 12.5%
        self.assertFalse(M.is_stale(one, fps))
        two = topic(range(1, 11), synthesis='s', basis=basis)                   # 2 of 8 = 25%
        self.assertTrue(M.is_stale(two, fps))
        changed = topic(range(1, 9), synthesis='s', basis=basis)
        self.assertTrue(M.is_stale(changed, {**fps, 1: 'x', 2: 'y'}))          # two texts edited
        self.assertFalse(M.is_stale(topic(range(1, 11), synthesis='', basis=basis), fps))   # no summary: never stale
        self.assertTrue(M.is_stale(topic([1], synthesis='s', basis=None), fps))             # migrated
        self.assertTrue(M.is_stale(topic([1], synthesis='s', basis={}), fps))               # empty basis

    def test_first_build_is_a_rebuild(self):
        self.assertTrue(M.needs_rebuild(M.empty('m'), 'm'))

    def test_model_change_forces_rebuild(self):
        c = M.empty('old-model')
        c['clusters']['t-1'] = topic([1, 2, 3], 'T', 'S', {'1': 'a'})
        self.assertTrue(M.needs_rebuild(c, 'new-model'))
        self.assertFalse(M.needs_rebuild(c, 'old-model'))


class MapTest(unittest.TestCase):
    def test_assign_nearest_centroid_with_floor(self):
        c = M.empty('m')
        c['clusters']['t-1'] = topic([1, 2], 'A', 'sa', {'1': 'f', '2': 'f'})
        c['clusters']['t-2'] = topic([3, 4], 'B', 'sb', {'3': 'f', '4': 'f'})
        idx = index({1: vec(1, 0.1), 2: vec(1, -0.1), 3: vec(0, 1), 4: vec(0.1, 1),
                     5: vec(0.9, 0.2),        # near A
                     6: vec(0, 0, 1),         # orthogonal to both: under the floor, stays unassigned
                     9: vec(0, 1)})           # deleted from the library: not live
        fps = {i: 'f' for i in range(1, 7)}
        changed = M.assign(c, idx, fps, live_ids=[1, 2, 3, 4, 5, 6])
        self.assertTrue(changed)
        self.assertEqual(c['clusters']['t-1']['member_ids'], [1, 2, 5])
        self.assertEqual(c['clusters']['t-2']['member_ids'], [3, 4])
        self.assertFalse(M.assign(c, idx, fps, live_ids=[1, 2, 3, 4, 5, 6]))   # a second pass changes nothing
        # a deleted item leaves its topic
        M.assign(c, idx, fps, live_ids=[1, 3, 4, 5, 6])
        self.assertEqual(c['clusters']['t-1']['member_ids'], [1, 5])
        self.assertTrue(c['clusters']['t-1']['stale'])                       # 1 added + 1 removed of 2

    def test_rebuild_carries_ids_by_overlap_and_retires(self):
        c = M.empty('m')
        c['clusters']['t-1'] = topic([1, 2, 3, 4], 'One', 's1', {str(i): 'f' for i in (1, 2, 3, 4)}, 'one-t1')
        c['clusters']['t-2'] = topic([5, 6, 7], 'Two', 's2', {str(i): 'f' for i in (5, 6, 7)}, 'two-t2')
        c['clusters']['t-3'] = topic([8, 9, 10], 'Three', 's3', {str(i): 'f' for i in (8, 9, 10)}, 'three-t3')
        c['next_id'] = 4
        fps = {i: 'f' for i in range(1, 20)}
        new = M.rebuild(c, [[1, 2, 3, 11], [5, 6, 12, 13, 14], [15, 16, 17]], fps, 'm')
        self.assertEqual(new['clusters']['t-1']['member_ids'], [1, 2, 3, 11])    # 3 of 4 came from t-1: carried
        self.assertEqual(new['clusters']['t-1']['title'], 'One')
        self.assertEqual(new['clusters']['t-1']['name'], 'one-t1')
        self.assertTrue(new['clusters']['t-1']['stale'])                         # 1 added + 1 removed of 4 = 50%: stale
        self.assertNotIn('t-2', new['clusters'])        # only 2 of 5 came from t-2: not carried, t-2 retires
        self.assertNotIn('t-3', new['clusters'])
        fresh = sorted(t for t in new['clusters'] if t not in ('t-1',))
        self.assertEqual(fresh, ['t-4', 't-5'])
        self.assertEqual(new['next_id'], 6)
        self.assertEqual(M.status(new['clusters']['t-4']), 'new')

    def test_next_id_never_reused(self):
        c = M.empty('m')
        a = M.new_id(c)                                        # t-1: handed out, never placed in clusters
        b = M.new_id(c)                                        # t-2
        c['clusters'][b] = topic([1, 2, 3])
        new = M.rebuild(c, [[7, 8, 9]], {}, 'm')              # no overlap: b retires, a stays burnt
        self.assertNotIn(a, new['clusters'])
        self.assertNotIn(b, new['clusters'])
        self.assertEqual(list(new['clusters']), ['t-3'])
        self.assertEqual(M.new_id(new), 't-4')


def excerpts(rows):
    return [r['description'] for r in rows if r.get('description')]


class MergeTest(unittest.TestCase):
    def test_summary_jobs_capture_inputs_for_new_and_stale_only(self):
        c = M.empty('m')
        c['clusters']['t-1'] = topic([1, 2], 'Fresh', 's', {'1': 'f1', '2': 'f2'})
        c['clusters']['t-2'] = topic([3, 4])                                      # new
        c['clusters']['t-3'] = topic([5, 6], 'Old', 's', None)                   # migrated: stale
        c['clusters']['t-4'] = topic([7])                                         # no usable text
        items = {i: {'id': i, 'description': f'text {i}'} for i in range(1, 7)}
        items[7] = {'id': 7, 'description': ''}
        fps = {i: f'f{i}' for i in range(1, 8)}
        M.recompute_stale(c, fps)
        jobs = M.summary_jobs(c, items, fps, excerpts)
        self.assertEqual([j['topic_id'] for j in jobs], ['t-2', 't-3'])
        self.assertEqual(jobs[0], {'topic_id': 't-2', 'member_ids': [3, 4], 'basis': {'3': 'f3', '4': 'f4'},
                                   'excerpts': ['text 3', 'text 4']})

    def test_merge_keeps_membership_records_basis_and_marks_stale(self):
        c = M.empty('m')
        c['clusters']['t-2'] = topic([3, 4])
        job = {'topic_id': 't-2', 'member_ids': [3, 4], 'basis': {'3': 'f3', '4': 'f4'}, 'excerpts': ['a', 'b']}
        c['clusters']['t-2']['member_ids'] = [3, 4, 5]          # maintenance assigned 5 while the model answered
        fps_now = {3: 'f3', 4: 'f4-edited', 5: 'f5'}            # and 4's text changed
        self.assertTrue(M.merge_summary(c, job, 'Title', 'Summary', fps_now))
        t = c['clusters']['t-2']
        self.assertEqual(t['member_ids'], [3, 4, 5])             # membership as maintenance left it
        self.assertEqual(t['summary_basis'], {'3': 'f3', '4': 'f4'})   # the captured inputs, not the current ones
        self.assertEqual((t['title'], t['synthesis'], t['name']), ('Title', 'Summary', 'title-t2'))
        self.assertTrue(t['stale'])                              # 1 added + 1 changed of 2 = 100%
        M.merge_summary(c, job, 'Renamed', 'Summary 2', fps_now)
        self.assertEqual(c['clusters']['t-2']['name'], 'title-t2')   # the name is chosen once

    def test_merge_drops_retired_topic(self):
        c = M.empty('m')
        job = {'topic_id': 't-9', 'member_ids': [1], 'basis': {'1': 'f'}, 'excerpts': ['x']}
        self.assertFalse(M.merge_summary(c, job, 'T', 'S', {1: 'f'}))
        self.assertEqual(c['clusters'], {})

    def test_stats_and_rows(self):
        c = M.empty('m')
        c['clusters']['t-1'] = topic([1, 2, 3], 'Big', 's', {'1': 'f', '2': 'f', '3': 'f'}, 'big-t1')
        c['clusters']['t-2'] = topic([4, 5], 'Old', 's', None, 'old-t2')
        c['clusters']['t-3'] = topic([6])
        M.recompute_stale(c, {i: 'f' for i in range(1, 7)})
        self.assertEqual(M.stats(c), {'topics': 3, 'stale': 1, 'pending': 1})
        rows = M.topic_rows(c)
        self.assertEqual([r['id'] for r in rows], ['t-1', 't-2', 't-3'])
        self.assertEqual(rows[1]['status'], 'stale')
        self.assertEqual(rows[0]['count'], 3)


if __name__ == '__main__':
    unittest.main()
