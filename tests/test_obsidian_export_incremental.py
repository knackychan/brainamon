"""Export to Obsidian writes only changed files and removes only stale ones (vault sync depends on it).

Run from the project root:  py -m unittest tests.test_obsidian_export_incremental -v
"""
import os
import tempfile
import unittest
from pathlib import Path

from library import obsidian_export as OE


def payload(names):
    return {'items': [{'id': i, 'filename': f'{n}.md', 'title': n, 'url': f'https://x/{i}', 'tags': [], 'platform': 'youtube'}
                      for i, n in enumerate(names, 1)], 'notes': [], 'topics': {}, 'categories': {}}


class IncrementalExportTest(unittest.TestCase):
    def test_second_run_touches_nothing_and_stale_files_go(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        vault = Path(td.name)
        OE.write_obsidian_vault(payload(['one', 'two']), vault)
        one = vault / 'Content Manager' / 'items' / 'one.md'
        self.assertTrue(one.exists())
        os.utime(one, ns=(1_000_000_000, 1_000_000_000))
        OE.write_obsidian_vault(payload(['one']), vault)
        self.assertEqual(one.stat().st_mtime_ns, 1_000_000_000)           # same bytes: not rewritten
        self.assertFalse((vault / 'Content Manager' / 'items' / 'two.md').exists())   # stale: removed

    def test_review_note_copied_byte_for_byte(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        note = root / 'weekly-review-2026-10-13-to-2026-10-19.md'
        content = ('---\ntopic: Weekly review — 2026-10-13 to 2026-10-19\ncreated: 2026-10-19T12:00:00\n'
                   'sources: 12\nreview_kind: weekly\nreview_start: 2026-10-13\nreview_end: 2026-10-19\n'
                   'review_timezone: Asia/Taipei\nreview_through: 2026-10-19T06:30:00+00:00\n---\n\n'
                   '# Weekly review — 2026-10-13 to 2026-10-19\n\n## Coverage\n- Period: 2026-10-13 to 2026-10-19.\n\n'
                   '## What stood out\n- Theme [id 12].\n')
        note.write_text(content, encoding='utf-8')
        vault = root / 'vault'
        OE.write_obsidian_vault({'items': [], 'notes': [str(note)], 'topics': {}, 'categories': {}}, vault)
        copied = vault / 'Content Manager' / 'notes' / note.name
        self.assertEqual(copied.read_bytes(), note.read_bytes())


    def test_classic_export_reads_v2_cache_topics(self):
        from library import map_engine, obsidian_run
        from core.db import Database
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        db = Database(root / 'data' / 'content_manager.db')
        self.addCleanup(db.close)
        a = db.add_item({'url': 'https://x/a', 'description': 'Swing'})
        b = db.add_item({'url': 'https://x/b', 'description': 'Press'})
        cache = map_engine.empty('m')
        cache['clusters']['t-1'] = {'title': 'Kettlebell', 'synthesis': 'Ballistics.', 'member_ids': [a, b], 'name': 'kettlebell-t1',
                                    'summary_basis': {}, 'stale': True}
        cache['clusters']['t-2'] = {'title': '', 'synthesis': '', 'member_ids': [a], 'name': '', 'summary_basis': None, 'stale': False}
        map_engine.save(root / 'data' / 'obsidian_graph.json', cache)
        tag_map, topics = obsidian_run.export_inputs(db, root / 'data' / 'obsidian_graph.json')
        self.assertEqual(topics, [{'key': 't-1', 'title': 'Kettlebell', 'synthesis': 'Ballistics.', 'member_ids': [a, b]}])
        payload = OE.build_obsidian_payload(db, ai_topics=topics)
        vault = root / 'vault'
        OE.write_obsidian_vault(payload, vault)
        page = (vault / 'Content Manager' / 'topics' / 'ai-kettlebell.md').read_text(encoding='utf-8')
        self.assertIn('Ballistics.', page)

if __name__ == '__main__':
    unittest.main()
