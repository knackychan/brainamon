from tests.test_ask_tool_stream import json_api
"""Tests for librarian.py (the Qt-free Deep-mode knowledge tools).

Run from the project root:  py -m unittest tests.test_librarian -v
No network: the embed function returns None, so every tool takes its keyword path.
"""

import json
import tempfile
import unittest
from pathlib import Path

from core import ai_client
from knowledge import librarian
from library import search


class _FakeDb:
    """Just the Database methods librarian.Librarian calls, over in-memory rows."""

    def __init__(self, items, items_dir, resources=()):
        self.items = {it['id']: it for it in items}
        self.items_dir = items_dir
        self.resources = list(resources)

    def fts_ids(self, query, limit=100, match_all=False):
        terms = librarian.fts_terms(query)
        hits = [i for i, it in self.items.items()
                if any(t in (it.get('ai_desc') or '').lower() for t in terms)]
        return hits[:limit]

    def get_items_by_ids(self, ids):
        return [dict(self.items[i]) for i in ids if i in self.items]

    def item_ids_by_category(self, category):
        return [i for i, it in self.items.items() if it.get('category') == category]

    def count_by_category(self):
        out = {}
        for it in self.items.values():
            out[it.get('category')] = out.get(it.get('category'), 0) + 1
        return out

    def search_notes(self, query, limit=10):
        return []

    def resources_for_items(self, ids):
        ids = set(ids)
        return [r for r in self.resources if r[0] in ids]

    def search_resources(self, terms, limit=50):
        return [r for r in self.resources if any(t in r[1] or t in r[3] for t in terms)]


def _item(item_id, ai_desc, category='SPORT', creator='coach'):
    return {'id': item_id, 'ai_desc': ai_desc, 'description': '', 'transcript': '',
            'short_desc': '', 'category': category, 'creator': creator,
            'type': 'Reel', 'url': f'https://example.org/{item_id}'}


class TextHelpersTest(unittest.TestCase):
    def test_split_frontmatter(self):
        meta, body = librarian.split_frontmatter('---\ntopic: Knees\nsources: 1, 2\n---\nBody')
        self.assertEqual(meta['topic'], 'Knees')
        self.assertEqual(body, 'Body')

    def test_split_frontmatter_without_block(self):
        self.assertEqual(librarian.split_frontmatter('plain'), ({}, 'plain'))

    def test_report_section(self):
        rep = '# A\n### Key information\n- swing 10 reps\n### Summary\nshort'
        self.assertEqual(librarian.report_section(rep, 'Key information'), '- swing 10 reps')
        self.assertEqual(librarian.report_section(rep, 'Missing'), '')


class ResourceExtractionTest(unittest.TestCase):
    def test_urls_and_bare_domains(self):
        found = librarian.extract_resources(
            'Try Godly.website for layouts and https://www.skills.sh/agents today.')
        domains = {d for d, _url, _ctx in found}
        self.assertEqual(domains, {'godly.website', 'skills.sh'})

    def test_skips_social_and_file_names(self):
        found = librarian.extract_resources(
            'See facebook.com/reel/1 and config.py and node.js, follow instagram.com/x')
        self.assertEqual(found, [])

    def test_one_row_per_domain(self):
        found = librarian.extract_resources('github.com/a\ngithub.com/b')
        self.assertEqual(len(found), 1)

    def test_resource_rows_reads_report_before_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            items_dir = Path(tmp)
            (items_dir / '7').mkdir()
            (items_dir / '7' / 'report.md').write_text(
                '### Key information\n- gamma.app\n## Description\nhidden.io',
                encoding='utf-8')
            rows = librarian.resource_rows(
                [{'id': 7, 'description': '', 'ai_desc': ''}], items_dir)
        self.assertEqual([r[1] for r in rows], ['gamma.app'])


class AuxJobsTest(unittest.TestCase):
    def _setup(self, tmp):
        data = Path(tmp)
        notes = data / 'notes'
        notes.mkdir()
        (data / 'obsidian_graph.json').write_text(json.dumps({'clusters': {
            'abc': {'title': 'Kettlebells', 'synthesis': 'Swings and presses.',
                    'member_ids': [1, 2]}}}), encoding='utf-8')
        (notes / 'kb.md').write_text(
            '---\ntopic: KB plan\nsources: 1, 2\n---\n# KB plan\n'
            '## Warm-up\nHalos and goblet marches before every session.\n'
            '## Main\nSwings, cleans and presses in five rounds.\n', encoding='utf-8')
        (notes / librarian.PROFILE_FILE).write_text('I own one 16 kg kettlebell.',
                                                   encoding='utf-8')
        return data, notes

    def test_jobs_cover_topics_and_sections_but_not_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, notes = self._setup(tmp)
            jobs, obsolete = librarian.aux_jobs(data, notes, {}, 'm')
        keys = sorted(j['key'] for j in jobs)
        self.assertEqual(keys, ['note:kb.md#0', 'note:kb.md#1', 'topic:abc'])
        self.assertEqual(obsolete, [])
        note = next(j for j in jobs if j['key'] == 'note:kb.md#0')
        self.assertEqual(note['payload']['sources'], [1, 2])
        self.assertEqual(note['payload']['heading'], 'Warm-up')

    def test_stored_hashes_skip_and_obsolete_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, notes = self._setup(tmp)
            first, _ = librarian.aux_jobs(data, notes, {}, 'm')
            stored = {j['key']: j['hash'] for j in first}
            stored['note:gone.md#0'] = 'x'
            jobs, obsolete = librarian.aux_jobs(data, notes, stored, 'm')
        self.assertEqual(jobs, [])
        self.assertEqual(obsolete, ['note:gone.md#0'])

    def test_read_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            _data, notes = self._setup(tmp)
            self.assertIn('16 kg', librarian.read_profile(notes))


class LibrarianToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        items_dir = Path(self.tmp.name)
        (items_dir / '1').mkdir()
        (items_dir / '1' / 'report.md').write_text(
            '### Key information\n- 10 kettlebell swings, 5 rounds\n'
            '### How you could use this\nAs a finisher.\n', encoding='utf-8')
        items = [_item(1, 'Kettlebell swing circuit'),
                 _item(2, 'Blender merge by distance tip', category='BLENDER')]
        db = _FakeDb(items, items_dir,
                     resources=[(2, 'blenderkit.com', 'https://blenderkit.com', 'assets')])
        self.lib = librarian.Librarian(db, search.EmbeddingIndex([]), [], lambda t: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_library_keyword_path(self):
        out = self.lib.run_tool('search_library', {'query': 'kettlebell swings'})
        self.assertIn('[id 1]', out)
        self.assertNotIn('[id 2]', out)

    def test_search_library_category_filter_and_unknown(self):
        out = self.lib.run_tool('search_library', {'query': 'blender', 'category': 'blender'})
        self.assertIn('[id 2]', out)
        bad = self.lib.run_tool('search_library', {'query': 'x', 'category': 'NOPE'})
        self.assertTrue(bad.startswith('Error: unknown category'))

    def test_read_items_includes_report_sections(self):
        out = self.lib.run_tool('read_items', {'ids': [1, 99]})
        self.assertIn('10 kettlebell swings', out)
        self.assertIn('As a finisher.', out)
        self.assertIn('Not found: 99', out)
        self.assertIn(1, self.lib.consulted)

    def test_find_resources(self):
        out = self.lib.run_tool('find_resources', {'query': 'blender assets'})
        self.assertIn('blenderkit.com', out)
        self.assertIn('[id 2]', out)

    def test_errors_are_text(self):
        self.assertTrue(self.lib.run_tool('nope', {}).startswith('Error: unknown tool'))
        self.assertTrue(self.lib.run_tool('read_items', {'bogus': 1}).startswith('Error:'))

    def test_topics_without_map(self):
        self.assertIn('No topics', self.lib.run_tool('find_topics', {'query': 'x'}))

    def test_tool_schemas_are_consistent(self):
        for tool in librarian.TOOLS:
            self.assertTrue(hasattr(self.lib, 'tool_' + tool['name']), tool['name'])
            self.assertEqual(tool['parameters']['type'], 'object')

    def test_describe_call(self):
        line = librarian.describe_call('search_library', {'query': 'kb', 'offset': 20})
        self.assertIn('more results', line)


    def test_topic_items_reads_current_members_from_cache(self):
        from library import map_engine
        data = Path(self.tmp.name)
        self.lib.db.data_dir = data
        cache = map_engine.empty('m')
        cache['clusters']['t-1'] = {'title': 'Strength', 'synthesis': 'Swings.', 'member_ids': [1, 2],
                                    'name': 'strength-t1', 'summary_basis': {'1': 'a', '2': 'b'}, 'stale': False}
        map_engine.save(data / 'obsidian_graph.json', cache)
        aux = [{'key': 'topic:t-1', 'kind': 'topic', 'vec': [1.0, 0.0],
                'payload': {'title': 'Strength', 'synthesis': 'Swings.', 'member_ids': [1]}}]   # embedded before item 2 joined
        lib = librarian.Librarian(self.lib.db, search.EmbeddingIndex([]), aux, lambda t: None)
        out = lib.run_tool('topic_items', {'topic_id': 't-1'})
        self.assertIn('2 items', out)                                   # the cache, not the payload
        self.assertIn('[id 1]', out)
        self.assertIn('[id 2]', out)
        found = lib.run_tool('find_topics', {'query': 'strength'})
        self.assertIn('topic_id=t-1 | Strength | 2 items', found)
        # a key the cache no longer has (retired) falls back to the payload, so old phones and the parity test agree
        aux.append({'key': 'topic:gone', 'kind': 'topic', 'vec': [0.0, 1.0],
                    'payload': {'title': 'Gone', 'synthesis': 'x', 'member_ids': [2]}})
        lib = librarian.Librarian(self.lib.db, search.EmbeddingIndex([]), aux, lambda t: None)
        self.assertIn("Topic 'Gone': 1 items", lib.run_tool('topic_items', {'topic_id': 'gone'}))


class PromptTest(unittest.TestCase):
    def test_system_prompt_includes_profile_and_rules(self):
        p = librarian.build_system_prompt('Knee injury.', {'SPORT': 3}, 3)
        self.assertIn('Knee injury.', p)
        self.assertIn('(general knowledge)', p)
        self.assertIn('SPORT (3)', p)


class AgentLoopTest(unittest.TestCase):
    """ai_client.ask_agent with fake clients: tool round trip + forced final round."""

    def test_anthropic_loop(self):
        from types import SimpleNamespace as NS
        calls = []

        class Msgs:
            def create(self, **kw):
                calls.append(kw)
                if len(calls) == 1:
                    return NS(stop_reason='tool_use', content=[
                        NS(type='tool_use', id='t1', name='search_library',
                           input={'query': 'kb'})])
                return NS(stop_reason='end_turn', content=[NS(type='text', text='Done [id 1].')])

        orig = ai_client.anthropic_client
        ai_client.anthropic_client = lambda api_key=None: NS(messages=json_api(Msgs()), with_options=lambda **kw: NS(messages=json_api(Msgs())))
        try:
            out = ai_client.ask_agent(
                [{'role': 'user', 'content': 'q'}], ai_client.ASK_PROVIDER_ANTHROPIC, 'm',
                system_prompt='s', tools=librarian.TOOLS, run_tool=lambda n, a: 'r')
        finally:
            ai_client.anthropic_client = orig
        self.assertEqual(out, 'Done [id 1].')
        self.assertEqual(calls[1]['messages'][-1]['content'][0]['type'], 'tool_result')

    def test_last_round_forbids_tools(self):
        from types import SimpleNamespace as NS
        calls = []

        class Msgs:
            def create(self, **kw):
                calls.append(kw)
                return NS(stop_reason='end_turn', content=[NS(type='text', text='x')])

        orig = ai_client.anthropic_client
        ai_client.anthropic_client = lambda api_key=None: NS(messages=json_api(Msgs()), with_options=lambda **kw: NS(messages=json_api(Msgs())))
        try:
            ai_client.ask_agent([{'role': 'user', 'content': 'q'}],
                                ai_client.ASK_PROVIDER_ANTHROPIC, 'm', system_prompt='s',
                                tools=librarian.TOOLS, run_tool=lambda n, a: 'r',
                                max_rounds=1)
        finally:
            ai_client.anthropic_client = orig
        self.assertEqual(calls[0]['tool_choice'], {'type': 'none'})

    def test_openai_loop(self):
        """Responses API: function_call -> function_call_output round trip, no storage."""
        from types import SimpleNamespace as NS
        calls = []

        class Responses:
            def create(self, **kw):
                calls.append(kw)
                if len(calls) == 1:
                    fc = NS(type='function_call', call_id='c1', name='read_items',
                            arguments='{"ids": [1]}')
                    return NS(status='completed', output=[fc], output_text='')
                return NS(status='completed', output=[NS(type='message', status='completed')], output_text='Answer')

        ran = []
        orig = ai_client.openai_client
        ai_client.openai_client = lambda api_key=None, base_url=None: NS(
            responses=json_api(Responses()), with_options=lambda **kw: NS(responses=json_api(Responses())))
        try:
            out = ai_client.ask_agent(
                [{'role': 'user', 'content': 'q'}], ai_client.ASK_PROVIDER_OPENAI, 'm',
                system_prompt='s', tools=librarian.TOOLS,
                run_tool=lambda n, a: (ran.append((n, a)), 'r')[1])
        finally:
            ai_client.openai_client = orig
        self.assertEqual(out, 'Answer')
        self.assertEqual(ran, [('read_items', {'ids': [1]})])
        self.assertEqual(calls[1]['input'][-1],
                         {'type': 'function_call_output', 'call_id': 'c1', 'output': 'r'})
        self.assertIs(calls[0]['store'], False)
        self.assertEqual(calls[0]['instructions'], 's')


if __name__ == '__main__':
    unittest.main()
