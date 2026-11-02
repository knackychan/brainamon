"""Tests for skills.py (the Qt-free skill-candidate proposer).

Run from the project root:  py -m unittest tests.test_skills -v
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from knowledge import skills

_HOWTO = ("This tutorial shows how to install the tool step by step. Step 1: open the "
          "terminal and run `pip install markitdown`. Step 2: copy the config file "
          "settings.json. Then paste it. Finally, click export to finish the workflow.")
_VLOG = ("A relaxed vlog about a sunny afternoon at the beach with friends, some music "
         "and a lot of laughing. Nothing much happens but the colours are lovely and "
         "the mood is calm from start to end of the clip.")


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _item(item_id, text=_HOWTO, creator='c', description=''):
    return {'id': item_id, 'ai_desc': text, 'description': description,
            'transcript': '', 'creator': creator, 'short_desc': ''}


class ScoreTest(unittest.TestCase):
    def test_howto_outscores_vlog(self):
        self.assertGreater(skills.procedure_score(_HOWTO), skills._MIN_SCORE)
        self.assertLess(skills.procedure_score(_VLOG), skills._MIN_SCORE)

    def test_short_text_is_halved(self):
        short = 'Step 1: run `npx skills add x`. Step 2: done.'
        sig = skills.procedure_signals(short)
        full = sum(min(sig[n], cap) / cap * w for n, _rx, cap, w in skills._SIGNALS)
        self.assertAlmostEqual(skills.procedure_score(short), round(full * 0.5, 3))

    def test_numbered_ai_desc_is_not_a_step_list(self):
        desc = '1. This video shows a dog.\n2. The tone is warm.\n3. Viewers smile.'
        scored = skills.score_items([_item(1, text=desc)])
        self.assertEqual(scored[1]['signals']['numbered'], 0)

    def test_gate_keyword(self):
        self.assertEqual(skills.gate_keyword({'description': 'Commente « SKILL » et voila'}), 'SKILL')
        self.assertEqual(skills.gate_keyword({'description': 'comment GUIDE for the link'}), 'GUIDE')
        self.assertEqual(skills.gate_keyword({'description': 'a comment about guides'}), '')


class LedgerTest(unittest.TestCase):
    def test_reads_ids_notes_and_meta(self):
        with tempfile.TemporaryDirectory() as d:
            sk = Path(d) / 'my-skill'
            sk.mkdir()
            (sk / 'SKILL.md').write_text('Sources: [id 12], [id 40], notes context-playbook.md',
                                         encoding='utf-8')
            (sk / 'meta.json').write_text('{"sources": [7], "notes": ["x.md"]}', encoding='utf-8')
            ids, notes, names = skills.skill_ledger([d, Path(d) / 'missing'])
        self.assertEqual(ids, {7, 12, 40})
        self.assertEqual(notes, {'context-playbook.md', 'x.md'})
        self.assertEqual(names, {'my-skill'})


class MergeTest(unittest.TestCase):
    def _setup(self, creators):
        items = [_item(i + 1, creator=c) for i, c in enumerate(creators)]
        base = _unit([1, 0, 0])
        rows = [_unit(base + np.array([0, 0.01 * i, 0])) for i in range(len(items))]
        return items, [i['id'] for i in items], np.vstack(rows)

    def test_same_technique_from_several_creators_merges(self):
        items, ids, matrix = self._setup(['a', 'b', 'c'])
        res = skills.candidates(items, ids, matrix)
        self.assertEqual(len(res['merges']), 1)
        self.assertEqual(sorted(res['merges'][0]['item_ids']), [1, 2, 3])
        self.assertEqual(res['items'], [])      # merged items are not listed again

    def test_one_creator_series_does_not_merge(self):
        items, ids, matrix = self._setup(['a', 'a', 'a', 'a'])
        res = skills.candidates(items, ids, matrix)
        self.assertEqual(res['merges'], [])
        self.assertEqual(len(res['items']), 4)

    def test_no_embeddings_no_merges(self):
        items, _ids, _m = self._setup(['a', 'b', 'c'])
        res = skills.candidates(items)
        self.assertEqual(res['merges'], [])
        self.assertEqual(len(res['items']), 3)


class CandidatesTest(unittest.TestCase):
    def test_covered_and_gated(self):
        items = [_item(1), _item(2), _item(3, text=_VLOG, description='Comment GUIDE now')]
        with tempfile.TemporaryDirectory() as d:
            sk = Path(d) / 'skills' / 'done'
            sk.mkdir(parents=True)
            (sk / 'SKILL.md').write_text('[id 1]', encoding='utf-8')
            notes = Path(d) / 'notes'
            notes.mkdir()
            (notes / 'how.md').write_text('---\ntopic: How to\n---\n\n' + _HOWTO, encoding='utf-8')
            (notes / 'vlog.md').write_text('---\ntopic: Vlog\n---\n\n' + _VLOG, encoding='utf-8')
            res = skills.candidates(items, notes_dir=notes, skills_dirs=[Path(d) / 'skills'])
        self.assertEqual([i['id'] for i in res['items']], [2])
        self.assertEqual(res['covered'], 1)
        self.assertEqual(res['gated'], [3])
        self.assertEqual([n['file'] for n in res['notes']], ['how.md'])
        self.assertEqual(res['skills'], ['done'])


class GateTest(unittest.TestCase):
    def _payload(self):
        items = [_item(1, creator='a'), _item(2, creator='b'), _item(3, creator='c'),
                 _item(9, creator='z')]
        by_id = {i['id']: i for i in items}
        res = {'skills': ['call-ai-model'],
               'merges': [{'key': 'merge-1-2-3', 'item_ids': [1, 2, 3], 'creators': 3}],
               'items': [{'id': 9}], 'notes': []}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'how.md').write_text('---\ntopic: How\n---\n\nStep 1: run it.',
                                            encoding='utf-8')
            res['notes'] = [{'file': 'how.md', 'topic': 'How'}]
            return skills.gate_payload(res, by_id, d)

    def test_payload_and_prompt(self):
        payload = self._payload()
        keys = [c['key'] for c in payload['candidates']]
        self.assertEqual(keys, ['merge-1-2-3', 'item-9', 'note-how.md'])
        self.assertIn('Step 1: run it.', payload['candidates'][2]['text'])
        self.assertNotIn('topic:', payload['candidates'][2]['text'])
        prompt = skills.gate_prompt(payload)
        self.assertIn('EXISTING SKILLS: call-ai-model', prompt)
        self.assertIn('CANDIDATE merge-1-2-3', prompt)

    def test_parse_and_verdicts(self):
        payload = self._payload()
        reply = ('Here you go: {"merge-1-2-3": {"bucket": "skill", "name": "Install Tools!", '
                 '"use_when": "Use when installing.", "overlaps": ""}, '
                 '"item-9": {"bucket": "reject"}, '
                 '"note-how.md": {"bucket": "weird", "name": "x"}}')
        res = skills.parse_gate(reply)
        self.assertEqual(res['merge-1-2-3']['name'], 'install-tools')
        self.assertEqual(res['note-how.md']['bucket'], 'reject')     # unknown bucket
        kept = skills.verdicts(payload, res)
        self.assertEqual([v['key'] for v in kept], ['merge-1-2-3'])
        self.assertEqual(kept[0]['item_ids'], [1, 2, 3])

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            skills.parse_gate('I cannot help with that.')


if __name__ == '__main__':
    unittest.main()
