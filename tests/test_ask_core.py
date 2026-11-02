"""ask_core (moved from ui/main_window.py in plan 11): list mode, cited ids, follow-up carry,
the context block and the Quick turn.

Run from the project root:  py -m unittest tests.test_ask_core -v
"""
import tempfile
import unittest
from pathlib import Path

from knowledge import ask_core
from core.db import Database


class AskCoreTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.db = Database(Path(td.name) / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.a = self.db.add_item({'url': 'https://x/1', 'description': 'Knee prehab with hip airplanes',
                                   'creator': 'Pulse', 'category': 'SPORT'})
        self.b = self.db.add_item({'url': 'https://x/2', 'description': 'Kettlebell swing finisher',
                                   'category': 'SPORT', 'ai_desc': 'A kettlebell routine.',
                                   'transcript': 'swing the kettlebell then rest'})
        self.db.update_item(self.b, {'transcript': 'swing the kettlebell then rest'})   # add_item has no transcript
        d = self.db.items_dir / str(self.b)
        d.mkdir(parents=True, exist_ok=True)
        (d / 'report.md').write_text('### Key information\n- 30 s swings\n### Tags\nx', encoding='utf-8')

    def test_list_mode_and_depth(self):
        self.assertTrue(ask_core.is_list('List all kettlebell workouts'))
        self.assertFalse(ask_core.is_list('What helps knee pain?'))
        self.assertEqual(ask_core.effective_depth('give me every knee reel', 25), ask_core.LIST_MAX)

    def test_cited_ids_and_notes(self):
        t = 'Try this [id 12] and [ids 3, 4] or [id 5, id 6]; see [note: knee.md]. Not [12].'
        self.assertEqual(ask_core.cited_ids(t), [12, 3, 4, 5, 6])
        self.assertEqual(ask_core.cited_notes(t), ['knee.md'])

    def test_follow_up_carries_cited_items(self):
        hist = [{'role': 'user', 'content': 'knee?'}, {'role': 'assistant', 'content': f'Use [id {self.a}].'}]
        self.assertEqual([r['id'] for r in ask_core.carried_items(self.db, hist, 'tell me more about it')], [self.a])
        self.assertEqual(ask_core.carried_items(self.db, hist, 'what blender lighting tutorials are there'), [])

    def test_context_detail_and_turn(self):
        rows = self.db.get_items_by_ids([self.b])
        ctx = ask_core.context_block(self.db, rows, question='kettlebell swing')
        self.assertIn(f'[id {self.b}]', ctx)
        self.assertIn('Key information: - 30 s swings', ctx)
        self.assertIn('Transcript excerpt', ctx)
        turn = ask_core.build_turn(self.db, 'List all kettlebell items', rows, [], 'keyword search only')
        self.assertTrue(turn['list_mode'])
        self.assertEqual(turn['max_tokens'], ask_core.LIST_MAX_TOKENS)
        self.assertIn('list mode', turn['info'])
        self.assertTrue(turn['messages'][-1]['content'].startswith('Question: List all kettlebell items'))

    def test_answer_sources_list_mode_keeps_cited(self):
        rows = self.db.get_items_by_ids([self.a, self.b])
        self.assertEqual([r['id'] for r in ask_core.answer_sources(rows, f'[id {self.b}]', True)], [self.b])
        self.assertEqual(len(ask_core.answer_sources(rows, f'[id {self.b}]', False)), 2)

    def test_save_note(self):
        p = ask_core.save_note(self.db, 'An answer [id 1].', [self.b, self.a])
        text = p.read_text(encoding='utf-8')
        self.assertIn(f'sources: {self.a},{self.b}', text)
        self.assertTrue(text.startswith('---\ntopic: Ask - '))

    def test_save_note_titled_by_heading(self):
        p = ask_core.save_note(self.db, '# Video & **Motion** Design [id 3]\n\nBody [id 1].', [self.a])
        text = p.read_text(encoding='utf-8')
        self.assertIn('topic: Video & Motion Design\n', text)
        self.assertTrue(text.endswith('---\n\nBody [id 1].\n'))
        self.assertEqual(p.name, 'video-motion-design.md')
        self.assertEqual(ask_core.answer_title('No heading here'), ('', 'No heading here'))

    def test_save_note_review_frontmatter(self):
        review = {'kind': 'weekly', 'start': '2026-10-13', 'end': '2026-10-19',
                  'timezone': 'Asia/Taipei', 'through': '2026-10-19T06:30:00+00:00'}
        p = ask_core.save_note(self.db, '# Weekly review — 2026-10-13 to 2026-10-19\n\nBody [id 1].', [self.a], review=review)
        text = p.read_text(encoding='utf-8')
        self.assertIn('review_kind: weekly\n', text)
        self.assertIn('review_start: 2026-10-13\n', text)
        self.assertIn('review_end: 2026-10-19\n', text)
        self.assertIn('review_timezone: Asia/Taipei\n', text)
        self.assertIn('review_through: 2026-10-19T06:30:00+00:00\n', text)
        self.assertIn(f'sources: {self.a}\n', text)
        self.assertTrue(any(n['filename'] == p.name for n in self.db.search_notes('weekly')))

    def test_save_note_ordinary_has_no_review_fields(self):
        p = ask_core.save_note(self.db, 'Hello [id 1].', [self.a])
        self.assertNotIn('review_kind', p.read_text(encoding='utf-8'))

    def test_save_note_duplicate_never_overwrites(self):
        md = '# Weekly review — 2026-10-13 to 2026-10-19\n\nBody [id 1].'
        p1 = ask_core.save_note(self.db, md, [self.a])
        p2 = ask_core.save_note(self.db, md, [self.a])
        self.assertNotEqual(p1.name, p2.name)
        self.assertIn('Body [id 1].', p1.read_text(encoding='utf-8'))

    def test_save_note_rejects_bad_review(self):
        with self.assertRaises(ValueError):
            ask_core.save_note(self.db, 'Body [id 1].', [self.a], review={'kind': 'weekly', 'bogus': 1})


if __name__ == '__main__':
    unittest.main()
