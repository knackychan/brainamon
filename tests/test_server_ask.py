from tests.test_ask_tool_stream import agent_from_stream
"""V6 plan 11: the Ask stream (Quick and Deep) with the model calls stubbed, chats, Save as note.

Run from the project root:  py -m unittest tests.test_server_ask -v
"""
import asyncio
import json
import os
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import ai_defaults
from core.db import Database
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def events(resp):
    out, ev = [], None
    for line in resp.iter_lines():
        if line.startswith('event:'):
            ev = line.split(':', 1)[1].strip()
        elif line.startswith('data:') and ev:
            out.append((ev, json.loads(line.split(':', 1)[1])))
            ev = None
    return out


class AskTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.add_category('SPORT', '#2E75B6')
        db.add_category('BLENDER', '#E46C0A')
        self.a = db.add_item({'url': 'https://x/1', 'description': 'Knee prehab with hip airplanes', 'category': 'SPORT'})
        self.b = db.add_item({'url': 'https://x/2', 'description': 'Blender glass shader', 'category': 'BLENDER'})
        db.close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                  mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None))):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def ask(self, **body):
        with self.c.stream('POST', '/api/ask', json=body, headers=W) as r:
            self.assertEqual(r.status_code, 200)
            return events(r)

    def test_quick_stream_and_saved_chat(self):
        a = self.a

        def stream(messages, provider, model, **kw):
            self.assertIn('Knee prehab', messages[-1]['content'])
            yield 'Do the hip airplanes '
            yield f'[id {a}].'
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(question='knee prehab', provider='anthropic', model='claude-sonnet-5-5', mode='quick')
        kinds = [k for k, _ in ev]
        self.assertEqual(kinds[:2], ['start', 'context'])
        self.assertTrue(ev[0][1]['run'])
        self.assertIn('keyword search only (no embeddings API key)', ev[1][1]['line'])
        self.assertEqual(kinds.count('chunk'), 2)
        done = ev[-1][1]
        self.assertEqual(kinds[-1], 'done')
        self.assertEqual(done['cited'], [a])
        self.assertEqual(done['chat']['name'], 'knee prehab')
        chat = self.c.get(f"/api/chats/{done['chat']['slug']}").json()
        self.assertEqual(len(chat['history']), 2)
        self.assertEqual([s['id'] for s in chat['sources']], [a])
        listing = self.c.get('/api/chats').json()
        self.assertEqual(listing['active'], done['chat']['slug'])

    def test_answer_publishes_ask_run_when_it_starts_and_ends(self):
        """projects/wiskit-activity: Wiskit's dot counts the answers that run (desktop/activity.py)."""
        def stream(messages, provider, model, **kw):
            yield 'Hip airplanes.'
        hub = self.app.state.hub
        with mock.patch.object(hub, 'publish', wraps=hub.publish) as pub, \
                mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(question='knee prehab', provider='anthropic', model='claude-sonnet-5-5', mode='quick')
        self.assertEqual(ev[-1][0], 'done')
        self.assertEqual([c.args[1] for c in pub.call_args_list if c.args[0] == 'ask_run'],
                         [{'running': 1}, {'running': 0}])
        self.assertEqual(self.app.state.ask_runs, {})

    def slow_stream(self, release):
        def stream(messages, provider, model, **kw):
            yield 'first '
            release.wait(5)
            yield 'second'
        return stream

    def drive(self, script, **overrides):
        """Run the /api/ask route's generator directly (TestClient buffers a whole stream, so a page
        that leaves mid-answer cannot be played through it). script(agen) is a coroutine."""
        from server.routes import ask as ask_route
        req = types.SimpleNamespace(app=self.app)
        body = {'question': 'knee prehab', 'provider': 'anthropic', 'model': 'm', **overrides}

        async def main():
            agen = ask_route.ask(req, body)
            try:
                return await script(agen)
            finally:
                await agen.aclose()
        return asyncio.run(main())

    def test_stop_by_run_id_saves_nothing(self):
        release = threading.Event()

        async def script(agen):
            run = (await agen.__anext__()).data['run']
            ok = await asyncio.to_thread(lambda: self.c.post('/api/ask/stop', json={'run': run}, headers=W).json()['ok'])
            release.set()
            kinds = [ev.event async for ev in agen]
            return run, ok, kinds
        with mock.patch.multiple(ai_client, ask_chat_stream=self.slow_stream(release), ask_agent=agent_from_stream(self.slow_stream(release))):
            run, ok, kinds = self.drive(script)
        self.assertTrue(ok)
        self.assertEqual(kinds[-1], 'stopped')
        self.assertFalse(self.c.post('/api/ask/stop', json={'run': run}, headers=W).json()['ok'])   # over
        self.assertTrue(all(not c.get('message_count') for c in self.c.get('/api/chats').json()['chats']))

    def test_answer_finishes_and_saves_after_the_page_leaves(self):
        release, published = threading.Event(), []
        hub = self.app.state.hub
        real = hub.publish
        hub.publish = lambda kind, data: (published.append((kind, data)), real(kind, data))

        async def script(agen):
            async for ev in agen:
                if ev.event == 'chunk':
                    return                         # the window closes mid-answer (aclose = the disconnect)
        with mock.patch.multiple(ai_client, ask_chat_stream=self.slow_stream(release), ask_agent=agent_from_stream(self.slow_stream(release))):
            self.drive(script)
            release.set()
            for _ in range(100):
                if any(k == 'ask_saved' for k, _ in published):
                    break
                time.sleep(0.05)
        saved = [d for k, d in published if k == 'ask_saved']
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0]['detached'])
        chat = self.c.get(f"/api/chats/{saved[0]['slug']}").json()
        self.assertEqual(chat['history'][-1], {'role': 'assistant', 'content': 'first second'})

    def test_stop_before_and_after_writer_commit_boundary(self):
        from server.routes import ask as route
        for late in (False, True):
            with self.subTest(late=late):
                chat = self.c.post('/api/chats', json={'name':'Boundary'}, headers=W).json()
                slug = chat['slug']
                entered, release = threading.Event(), threading.Event()
                store, writer = route._store(self.app), self.app.state.writer
                original_save, original_call = store.save, writer.call
                def save(*args, **kw):
                    entered.set(); release.wait(5)
                    return original_save(*args, **kw)
                def call(fn, *args, **kw):
                    if getattr(fn, '__name__', '') == 'save':
                        entered.set(); release.wait(5)
                    return original_call(fn, *args, **kw)
                async def script(agen):
                    run = (await agen.__anext__()).data['run']
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                        self.assertTrue(await asyncio.to_thread(lambda: self.c.post('/api/ask/stop',json={'run':run},headers=W).json()['ok']))
                    finally: release.set()
                    return [(e.event,e.data) async for e in agen]
                with mock.patch.object(ai_client,'ask_agent',return_value='Saved answer'), mock.patch.object(route,'_refresh_resources'), \
                        (mock.patch.object(store,'save',save) if late else mock.patch.object(writer,'call',call)):
                    result = self.drive(script, chat=slug)
                self.assertEqual(result[-1][0], 'done' if late else 'stopped')
                saved = self.c.get(f'/api/chats/{slug}').json()['history']
                self.assertEqual(saved[-1]['content'] if saved else None, 'Saved answer' if late else None)

    def test_missing_key_is_an_error_event(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch('core.config.anthropic_api_key', lambda: ''):
            ev = self.ask(question='x', provider='anthropic', model='m')
        self.assertEqual(ev[-1][0], 'error')
        self.assertIn('Anthropic API key', ev[-1][1]['message'])

    def test_deep_mode(self):
        b = self.b

        def agent(messages, provider, model, *, system_prompt, tools, run_tool, on_tool=None, **kw):
            on_tool('search_library', {'query': 'glass'})
            run_tool('read_items', {'ids': [b]})
            return f'Glass needs transmission 1 [id {b}].'
        with mock.patch.object(ai_client, 'ask_agent', agent):
            ev = self.ask(question='blender glass', provider='openai', model='gpt-6-luna', mode='deep')
        kinds = [k for k, _ in ev]
        self.assertIn('progress', kinds)
        self.assertEqual(ev[-1][0], 'done')
        self.assertEqual(ev[-1][1]['cited'], [b])

    def test_deep_needs_agent_provider(self):
        with mock.patch.object(ai_client, 'ask_chat_stream', lambda *a, **k: iter(['ok'])), \
             mock.patch('core.config.freellmapi_api_key', lambda: 'k'):
            ev = self.ask(question='knee', provider='freellmapi', model='auto', mode='deep')
        self.assertIn('fast mode', ev[1][1]['line'])
        self.assertEqual(ev[-1][0], 'done')

    def test_chats_crud_and_note(self):
        r = self.c.post('/api/chats', json={'name': 'Plan'}, headers=W).json()
        slug = r['slug']
        r = self.c.post(f'/api/chats/{slug}/rename', json={'name': 'Training'}, headers=W).json()
        self.assertEqual(r['name'], 'Training')
        slug = r['slug']
        self.assertEqual(self.c.post(f'/api/chats/{slug}/clear', headers=W).json(), {'ok': True})
        r = self.c.put(f'/api/chats/{slug}', json={'options': {'depth': 50}}, headers=W).json()
        self.assertEqual(r['options']['depth'], 50)
        self.c.delete(f'/api/chats/{slug}', headers=W)
        self.assertEqual(self.c.get(f'/api/chats/{slug}').status_code, 404)
        n = self.c.post('/api/ask/save-note', json={'answer_md': 'Hello [id 1]', 'source_ids': [self.a]}, headers=W).json()
        self.assertTrue((self.data / 'notes' / n['file']).is_file())

    def test_options(self):
        o = self.c.get('/api/ask/options').json()
        self.assertIn('anthropic', o['models'])
        self.assertEqual(o['depths'], [10, 25, 50])
        self.assertIn('SPORT', o['scopes'])

    def test_options_name_the_provider_without_a_key(self):
        with mock.patch('core.config.anthropic_api_key', lambda: ''), mock.patch('core.config.openai_api_key', lambda: ''):
            o = self.c.get('/api/ask/options').json()
        self.assertIn('OpenAI API key', o['problems']['openai'])
        self.assertIn('Anthropic API key', o['problems']['anthropic'])
        self.assertIn('local_openai', o['problems'])
        o = self.c.get('/api/ask/options').json()                    # setUp put both keys in the environment
        self.assertEqual((o['problems']['openai'], o['problems']['anthropic']), ('', ''))

    def test_wiskit_default_and_saved_chat_override(self):
        provider = ai_client.ASK_PROVIDER_OPENAI
        model = ai_client.feature_models(provider)[-1]['id']
        self.app.state.writer.call(lambda db: ai_defaults.set(db, ai_defaults.DESCRIBE, provider, model))
        o = self.c.get('/api/ask/options').json()
        self.assertEqual((o['default_provider'], o['default_models'][provider]), (provider, model))
        created = self.c.post('/api/chats', json={'name': 'Shared default'}, headers=W).json()
        self.assertEqual((created['options']['provider'], created['options']['model_id']), (provider, model))
        seen = []

        def stream(messages, p, m, **kw):
            seen.append((p, m))
            yield 'A test answer.'

        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(question='knee prehab', mode='quick')
            self.assertEqual(ev[-1][0], 'done', ev)
            self.assertEqual(seen[-1], (provider, model))
            slug = ev[-1][1]['chat']['slug']
            other = ai_client.ASK_PROVIDER_ANTHROPIC
            other_model = ai_client.ask_models(other)[-1]['id']
            self.c.put(f'/api/chats/{slug}', json={'options': {'provider': other, 'model_id': other_model}}, headers=W)
            ev = self.ask(question='knee prehab again', chat=slug, mode='quick')
            self.assertEqual(ev[-1][0], 'done', ev)
            self.assertEqual(seen[-1], (other, other_model))
            ev = self.ask(question='override', chat=slug, provider=provider, model=model, mode='quick')
            self.assertEqual(ev[-1][0], 'done', ev)
            self.assertEqual(seen[-1], (provider, model))

    def test_ask_without_a_key_ends_with_the_reason(self):
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': ''}), mock.patch('core.config.openai_api_key', lambda: ''):
            ev = self.ask(question='knee prehab', provider='openai', model='gpt-6-luna', mode='quick')
        self.assertEqual(ev[-1][0], 'error')
        self.assertIn('OpenAI API key', ev[-1][1]['message'])

    # ── weekly review (projects/knowledge-maintenance) ───────────────────────
    def review_body(self, **over):
        body = {
            'question': 'Review this week', 'chat': '', 'mode': 'quick',
            'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'depth': 25, 'scope': '',
            'attachments': [], 'task': 'weekly_review',
            'review_at': datetime.now(timezone.utc).isoformat(),
            'review_timezone': 'UTC',
        }
        body.update(over)
        return body

    def add_note(self, name, body='note text', extra=''):
        notes = self.data / 'notes'
        notes.mkdir(parents=True, exist_ok=True)
        (notes / name).write_text(f'---\ntopic: N\nupdated: {datetime.now(timezone.utc).date().isoformat()}\n{extra}---\n\n{body}', encoding='utf-8')
        return name

    def review_md(self, a):
        return (f'## What stood out\n- Theme [id {a}].\n\n## Notes worth revisiting\n'
                '- None found in the reviewed material.\n\n## Open questions\n'
                f'- Suggested: think [id {a}].\n\n## Possible next steps\n- Try [id {a}].')

    def test_weekly_review_streams_saves_and_reopens(self):
        a = self.a
        calls = []

        def stream(messages, provider, model, **kw):
            calls.append((messages, provider, model))
            self.assertIn('<weekly_review_data>', messages[-1]['content'])
            yield self.review_md(a)

        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(**self.review_body())
        kinds = [k for k, _ in ev]
        self.assertEqual(kinds[0], 'start')
        self.assertIn('context', kinds)
        self.assertTrue(ev[1][1]['line'].startswith('Weekly review · '))
        self.assertEqual(kinds[-1], 'done')
        done = ev[-1][1]
        self.assertEqual(done['review']['kind'], 'weekly')
        self.assertEqual(done['cited'], [a])
        self.assertTrue(done['text'].startswith('# Weekly review — '))
        self.assertIn('## Coverage', done['text'])
        self.assertEqual(len(calls), 1)

        chat = self.c.get(f"/api/chats/{done['chat']['slug']}").json()
        self.assertEqual(chat['history'][-1]['review'], done['review'])
        # save as note keeps the whitelisted review frontmatter
        n = self.c.post('/api/ask/save-note', json={'answer_md': done['text'], 'source_ids': [a],
                                                    'review': done['review']}, headers=W).json()
        saved = (self.data / 'notes' / n['file']).read_text(encoding='utf-8')
        self.assertIn('review_kind: weekly\n', saved)
        self.assertIn('review_through: ', saved)

    def test_weekly_review_deep_still_bounded(self):
        a = self.a

        def stream(messages, provider, model, **kw):
            yield self.review_md(a)
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)), \
             mock.patch.object(ai_client, 'ask_agent', side_effect=AssertionError('agent must not run')):
            ev = self.ask(**self.review_body(mode='deep'))
        self.assertEqual(ev[-1][0], 'done')

    def test_weekly_review_claude_code_rejected(self):
        with mock.patch.object(ai_client, 'ask_chat_stream', side_effect=AssertionError('no call')), \
             mock.patch('knowledge.claude_code.answer', side_effect=AssertionError('no cli')):
            ev = self.ask(**self.review_body(mode='claude_code'))
        self.assertEqual(ev[-1][0], 'error')
        self.assertIn('Choose an API model', ev[-1][1]['message'])

    def test_weekly_review_unknown_task(self):
        ev = self.ask(**self.review_body(task='something_else'))
        self.assertEqual(ev[-1][0], 'error')
        self.assertEqual(ev[-1][1]['message'], 'Unknown task.')

    def test_weekly_review_rejects_chat_or_attachments(self):
        ev = self.ask(**self.review_body(chat='a-chat'))
        self.assertEqual(ev[-1][0], 'error')
        ev = self.ask(**self.review_body(attachments=['x.txt']))
        self.assertEqual(ev[-1][0], 'error')

    def test_weekly_review_stop_saves_nothing(self):
        a = self.a
        release = threading.Event()

        def stream(messages, provider, model, **kw):
            yield self.review_md(a)[:20]
            release.wait(5)
            yield self.review_md(a)[20:]
        from server.routes import ask as ask_route
        req = types.SimpleNamespace(app=self.app)
        body = self.review_body()

        async def script(agen):
            run = (await agen.__anext__()).data['run']
            await asyncio.to_thread(lambda: self.c.post('/api/ask/stop', json={'run': run}, headers=W).json()['ok'])
            release.set()
            kinds = [ev.event async for ev in agen]
            return kinds
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            kinds = asyncio.run(self._drive_review(req, body, script))
        self.assertEqual(kinds[-1], 'stopped')
        self.assertTrue(all(not c.get('message_count') for c in self.c.get('/api/chats').json()['chats']))

    async def _drive_review(self, req, body, script):
        from server.routes import ask as ask_route
        agen = ask_route.ask(req, body)
        try:
            return await script(agen)
        finally:
            await agen.aclose()

    def test_weekly_review_history_is_sanitized_on_followup(self):
        a = self.a
        review = None
        seen = []

        def stream(messages, provider, model, **kw):
            seen.append(messages)
            if review is None:
                yield self.review_md(a)
            else:
                yield f'Follow-up [id {a}].'
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            ev = self.ask(**self.review_body())
        review = ev[-1][1]['review']
        slug = ev[-1][1]['chat']['slug']
        seen.clear()
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            self.ask(question='tell me more', chat=slug, provider='anthropic', model='claude-sonnet-5-5', mode='quick')
        for messages in seen:
            for m in messages:
                self.assertEqual(set(m.keys()), {'role', 'content'})
        chat = self.c.get(f'/api/chats/{slug}').json()
        self.assertTrue(any('review' in t for t in chat['history']))

    def test_weekly_review_invalid_metadata_dropped_on_load(self):
        from server.routes.ask import _store
        store = _store(self.app)
        slug, data = store.create('corrupt')
        data['history'] = [{'role': 'user', 'content': 'hi'},
                           {'role': 'assistant', 'content': 'yo', 'review': {'kind': 'weekly', 'bogus': 1}}]
        store.save(slug, data)
        chat = self.c.get(f'/api/chats/{slug}').json()
        self.assertEqual(chat['history'][-1]['content'], 'yo')
        self.assertNotIn('review', chat['history'][-1])

    def test_weekly_review_does_not_mutate_sources(self):
        from core.db import ReadOnlyDatabase
        a = self.a
        self.add_note('keep.md', body='keep body')
        note_path = self.data / 'notes' / 'keep.md'
        before_note = note_path.read_bytes()
        ro = ReadOnlyDatabase(self.app.state.db_path)
        before_row = ro.get_items_by_ids([a])[0]
        ro.close()

        def stream(messages, provider, model, **kw):
            yield self.review_md(a)
        with mock.patch.multiple(ai_client, ask_chat_stream=stream, ask_agent=agent_from_stream(stream)):
            self.ask(**self.review_body())
        self.assertEqual(note_path.read_bytes(), before_note)
        ro = ReadOnlyDatabase(self.app.state.db_path)
        self.assertEqual(ro.get_items_by_ids([a])[0], before_row)
        ro.close()


class EmptyReviewTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        db.close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                  mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None))):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def test_empty_review_makes_no_model_call(self):
        body = {'question': 'Review this week', 'chat': '', 'mode': 'quick', 'provider': 'anthropic',
                'model': 'claude-sonnet-5-5', 'depth': 25, 'scope': '', 'attachments': [],
                'task': 'weekly_review', 'review_at': datetime.now(timezone.utc).isoformat(),
                'review_timezone': 'UTC'}
        with mock.patch.object(ai_client, 'ask_chat_stream', side_effect=AssertionError('no call')):
            with self.c.stream('POST', '/api/ask', json=body, headers=W) as r:
                ev = events(r)
        self.assertEqual(ev[-1][0], 'done')
        self.assertIn('No material found for these dates.', ev[-1][1]['text'])
        self.assertEqual(ev[-1][1]['review']['kind'], 'weekly')


if __name__ == '__main__':
    unittest.main()
