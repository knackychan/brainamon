"""The Qt-free task helpers moved in plan 07: categorize parsing, analysis_update, synth.fold.

Run from the project root:  py -m unittest tests.test_tasks -v
"""
import unittest
from unittest import mock

from core import ai_client
from knowledge import synth
from knowledge import tasks

CATS = ['SPORT', 'AI', 'COOKING', 'INTERESTING', 'UNREAL ENGINE']


class CategorizeTest(unittest.TestCase):
    def test_json_answer(self):
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '```json\n{"category": "ai", "tags": "Claude, Tools"}\n```'):
            self.assertEqual(tasks.categorize_item({'id': 1}, CATS, 'anthropic', 'm'), ('AI', 'claude, tools'))

    def test_unknown_category_becomes_interesting(self):
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '{"category": "GARDEN", "tags": ""}'):
            self.assertEqual(tasks.categorize_item({'id': 1}, CATS, 'anthropic', 'm')[0], 'INTERESTING')

    def test_prose_answer_is_recovered(self):
        text = 'The category should be UNREAL ENGINE and the tags are "lumen", "lighting".'
        d = tasks.parse_category_response(text, {'id': 1}, CATS)
        self.assertEqual(d['category'], 'UNREAL ENGINE')
        self.assertIn('lumen', d['tags'])

    def test_freellmapi_prompt_lists_categories(self):
        p = tasks.categorize_user_prompt({'type': 'Reel'}, CATS, ai_client.ASK_PROVIDER_FREELLMAPI)
        self.assertIn('Allowed categories: SPORT, AI', p)
        self.assertNotIn('Allowed', tasks.categorize_user_prompt({'type': 'Reel'}, CATS, 'anthropic'))


class AnalysisUpdateTest(unittest.TestCase):
    def test_summary_and_tags_merge(self):
        report = '### Summary\nShort summary.\n### Tags\nKnee, **Mobility**, x\n### Other\n- ignored'
        u = tasks.analysis_update({'tags': 'old, knee'}, 'r.md', 'tr', report)
        self.assertEqual(u['ai_desc'], 'Short summary.')
        self.assertEqual(u['tags'], 'knee, mobility, old')
        self.assertEqual((u['analysis_done'], u['analysis_path'], u['transcript']), (1, 'r.md', 'tr'))

    def test_no_ai_keeps_desc(self):
        u = tasks.analysis_update(None, 'r.md', 'tr', '')
        self.assertNotIn('ai_desc', u)
        self.assertNotIn('tags', u)

    def test_bullet_fallback(self):
        self.assertEqual(tasks.tags_from_report('- Hip airplanes for balance\n- Ankle rocks'), ['hip airplanes for', 'ankle rocks'])


class SynthTest(unittest.TestCase):
    def test_fold_prompts(self):
        seen = []
        with mock.patch.object(ai_client, 'complete_text', lambda p, m, prompt, **k: (seen.append(prompt), '```markdown\n# Note\n```')[1]):
            out = synth.fold('anthropic', 'm', 'Knee', '', [{'id': 7, 'description': 'Knee prehab', 'creator': 'Pulse'}])
            self.assertEqual(out, '# Note')
            synth.fold('anthropic', 'm', 'Knee', '# Note', [{'id': 8, 'ai_desc': 'More'}], mode='append')
        self.assertIn('### Source 7', seen[0])
        self.assertIn('Creator: Pulse', seen[0])
        self.assertIn('do NOT rewrite', seen[1])

    def test_empty_batch_is_a_no_op(self):
        self.assertEqual(synth.fold('anthropic', 'm', 't', 'keep', [{'id': 1}]), 'keep')


if __name__ == '__main__':
    unittest.main()
