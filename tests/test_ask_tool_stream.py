"""Native streaming and non-streaming calls share one tool loop; SDK clients are mocked."""
import json
import importlib
import unittest
from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest import mock

from core import ai_client
from knowledge import librarian


class AskToolStreamTest(unittest.TestCase):
    def test_timeout_uses_the_selected_sdk_transport(self):
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider):
                sdk = importlib.import_module(provider)
                client, _, _ = self.client(provider)
                client.with_options = mock.Mock(return_value=client)
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    answer = ai_client.ask_agent([], provider, 'm', system_prompt='s',
                        tools=librarian.CATEGORY_TOOLS, run_tool=lambda *a: 'Prepared for review.')
                self.assertEqual(answer, 'Waiting for approval.')
                options = client.with_options.call_args.kwargs
                self.assertEqual(options['max_retries'], 0)
                self.assertIsInstance(options['timeout'], sdk.Timeout)
                self.assertEqual(options['timeout'].connect, 10)
                for phase in ('read', 'write', 'pool'):
                    self.assertEqual(getattr(options['timeout'], phase), 60)

    def client(self, provider, arguments=None):
        arguments = {'ids': [1], 'category': 'AI'} if arguments is None else arguments
        if provider == 'anthropic':
            responses = [NS(stop_reason='tool_use', content=[
                NS(type='text', text='Preparing'), NS(type='tool_use', name='propose_category', input=arguments, id='t1')]),
                NS(stop_reason='end_turn', content=[NS(type='text', text='Waiting for approval.')])]
        else:
            responses = [NS(status='completed', output=[NS(type='reasoning', encrypted_content='private'),
                NS(type='function_call', name='propose_category', arguments=json.dumps(arguments), call_id='t1')],
                output_text='Preparing'), NS(status='completed', output=[], output_text='Waiting for approval.')]
        requests, closed = [], []

        @contextmanager
        def stream(**kw):
            requests.append(kw)
            resp = responses[len(requests) - 1]
            try:
                if provider == 'anthropic':
                    yield AnthropicEvents(resp, 'Preparing' if len(requests) == 1 else 'Waiting for approval.')
                else:
                    yield ResponseEvents(resp, 'Preparing' if len(requests) == 1 else 'Waiting for approval.')
            finally:
                closed.append(True)

        api = json_api(NS(stream=stream, create=mock.Mock(side_effect=responses), fixtures=responses))
        client = NS(messages=api, responses=api)
        client.with_options = lambda **kw: client
        return client, requests, closed

    def test_quick_streams_text_then_resets_and_reports_tool_result(self):
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider):
                client, requests, closed = self.client(provider)
                parts, notifications = [], []
                run = mock.Mock(return_value='Nothing has changed; awaiting approval.')
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    for delta in ai_client.ask_chat_stream([{'role': 'user', 'content': 'Categorize'}],
                            provider, 'm', system_prompt='SYSTEM', tools=librarian.CATEGORY_TOOLS,
                            run_tool=run, on_tool=lambda *a: notifications.append(a), on_reset=parts.clear):
                        parts.append(delta)
                self.assertEqual(''.join(parts), 'Waiting for approval.')
                run.assert_called_once_with('propose_category', {'ids': [1], 'category': 'AI'})
                self.assertEqual(len(notifications), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(closed, [True, True])
                if provider == 'openai':
                    self.assertFalse(requests[0]['store'])
                    self.assertEqual(requests[1]['tool_choice'], 'none')
                    outputs = [r for r in requests[1]['input'] if isinstance(r, dict) and r.get('type') == 'function_call_output']
                    self.assertIn('awaiting approval', outputs[0]['output'])
                else:
                    self.assertEqual(requests[1]['tool_choice'], {'type': 'none'})
                    self.assertIn('awaiting approval', requests[1]['messages'][-1]['content'][0]['content'])

    def test_deep_keeps_the_same_non_streaming_tool_protocol(self):
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider):
                client, _, _ = self.client(provider)
                run = mock.Mock(return_value='Error: request is busy')
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    text = ai_client.ask_agent([], provider, 'm', system_prompt='SYSTEM',
                        tools=librarian.CATEGORY_TOOLS, run_tool=run)
                self.assertEqual(text, 'Waiting for approval.')
                run.assert_called_once()
                self.assertEqual(client.messages.create.call_count, 2)

    def test_cancelling_stream_closes_sdk_before_tool_execution(self):
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider):
                client, _, closed = self.client(provider)
                run = mock.Mock()
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    gen = ai_client.ask_chat_stream([], provider, 'm', tools=librarian.CATEGORY_TOOLS, run_tool=run)
                    self.assertEqual(next(gen), 'Preparing')
                    gen.close()
                run.assert_not_called()
                self.assertEqual(closed, [True])

    def test_openai_malformed_tool_arguments_return_error_without_running(self):
        client, requests, _ = self.client('openai', arguments=['wrong shape'])
        run = mock.Mock()
        with mock.patch.object(ai_client, 'openai_client', return_value=client):
            list(ai_client.ask_chat_stream([], 'openai', 'm', tools=librarian.CATEGORY_TOOLS, run_tool=run))
        run.assert_not_called()
        self.assertTrue(requests[1]['input'][-1]['output'].startswith('Error:'))

    def test_stream_eof_never_dispatches_complete_arguments(self):
        for provider, cls in [('anthropic', AnthropicEvents), ('openai', ResponseEvents)]:
            client, _, closed = self.client(provider)
            original = cls.__iter__
            def incomplete(self):
                yield from list(original(self))[:-1]
            run = mock.Mock()
            with mock.patch.object(cls, '__iter__', incomplete), mock.patch.object(ai_client, provider + '_client', return_value=client):
                with self.assertRaisesRegex(RuntimeError, 'without successful completion'):
                    ai_client.ask_agent([], provider, 'm', system_prompt='s', tools=librarian.CATEGORY_TOOLS,
                                        run_tool=run, on_text=lambda _: None)
            run.assert_not_called()
            self.assertEqual(closed, [True])

    def test_stop_after_first_delta_prevents_dispatch(self):
        for provider in ('anthropic', 'openai'):
            client, _, closed = self.client(provider)
            stopped, run = [], mock.Mock()
            with mock.patch.object(ai_client, provider + '_client', return_value=client):
                with self.assertRaisesRegex(RuntimeError, 'Stopped'):
                    ai_client.ask_agent([], provider, 'm', system_prompt='s', tools=librarian.CATEGORY_TOOLS,
                        run_tool=run, on_text=lambda _: stopped.append(True), should_stop=lambda: bool(stopped))
            run.assert_not_called()
            self.assertEqual(closed, [True])

    def test_call_budget_counts_each_call_and_reserves_final_answer(self):
        for provider in ('anthropic', 'openai'):
            for streamed in (False, True):
                client, requests, _ = self.client(provider)
                first = client.messages.fixtures[0]
                if provider == 'anthropic':
                    first.content = [NS(type='tool_use', id=f't{i}', name='propose_category', input={'ids':[1], 'category':'AI'}) for i in range(5)]
                else:
                    first.output = [NS(type='function_call', call_id=f't{i}', name='propose_category', arguments='{"ids":[1],"category":"AI"}') for i in range(5)]
                run = mock.Mock(return_value='Prepared for review.')
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    out = ai_client.ask_agent([], provider, 'm', system_prompt='s', tools=librarian.CATEGORY_TOOLS,
                        run_tool=run, max_rounds=4, max_tool_calls=2, on_text=(lambda _: None) if streamed else None)
                self.assertEqual(out, 'Waiting for approval.')
                self.assertEqual(run.call_count, 2)
                if streamed:
                    final = requests[1]
                    results = final['messages'][-1]['content'] if provider == 'anthropic' else [r for r in final['input'] if isinstance(r,dict) and r.get('type')=='function_call_output']
                    self.assertEqual(len(results), 5)
                    self.assertEqual(final['tool_choice'], {'type':'none'} if provider=='anthropic' else 'none')

    def test_incomplete_outcomes_never_dispatch_even_without_callbacks(self):
        for provider in ('anthropic', 'openai'):
            for streamed in (False, True):
                client, _, _ = self.client(provider)
                first = client.messages.fixtures[0]
                if provider == 'anthropic': first.stop_reason = 'max_tokens'
                else: first.status = 'incomplete'
                run = mock.Mock()
                with mock.patch.object(ai_client, provider + '_client', return_value=client):
                    with self.assertRaises(RuntimeError):
                        ai_client.ask_agent([], provider, 'm', system_prompt='s', tools=librarian.CATEGORY_TOOLS,
                            run_tool=run, on_text=(lambda _:None) if streamed else None)
                run.assert_not_called()

    def test_invalid_argument_sibling_does_not_block_valid_call(self):
        for provider in ('anthropic', 'openai'):
            client, _, _ = self.client(provider, arguments=['invalid'])
            first = client.messages.fixtures[0]
            if provider == 'anthropic': first.content.append(NS(type='tool_use',id='valid',name='propose_category',input={'ids':[1],'category':'AI'}))
            else: first.output.append(NS(type='function_call',call_id='valid',name='propose_category',arguments='{"ids":[1],"category":"AI"}'))
            run = mock.Mock(return_value='Prepared for review.')
            with mock.patch.object(ai_client, provider + '_client', return_value=client):
                self.assertEqual(ai_client.ask_agent([],provider,'m',system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=run), 'Waiting for approval.')
            run.assert_called_once()

    def test_refusal_empty_and_final_only_protocol(self):
        for provider in ('anthropic', 'openai'):
            for outcome in ('refusal', 'empty', 'final_calls'):
                client, _, _ = self.client(provider)
                first = client.messages.fixtures[0]
                if provider == 'anthropic':
                    if outcome == 'refusal': first.stop_reason = 'refusal'
                    elif outcome == 'empty': first.stop_reason, first.content = 'end_turn', []
                else:
                    if outcome == 'refusal': first.output, first.output_text = [NS(type='message',status='completed',content=[NS(type='refusal',refusal='Declined')])], ''
                    elif outcome == 'empty': first.output, first.output_text = [], ''
                run = mock.Mock()
                with mock.patch.object(ai_client,provider+'_client',return_value=client):
                    kw=dict(system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=run,max_rounds=1)
                    if outcome == 'refusal': self.assertTrue(ai_client.ask_agent([],provider,'m',**kw))
                    else:
                        with self.assertRaises(RuntimeError): ai_client.ask_agent([],provider,'m',**kw)
                run.assert_not_called()

    def test_deadline_between_calls_goes_directly_to_final_answer(self):
        for provider in ('anthropic','openai'):
            client, requests, _ = self.client(provider)
            first = client.messages.fixtures[0]
            if provider == 'anthropic': first.content.append(NS(type='tool_use',id='second',name='propose_category',input={'ids':[1],'category':'AI'}))
            else: first.output.append(NS(type='function_call',call_id='second',name='propose_category',arguments='{"ids":[1],"category":"AI"}'))
            clock, seen = [0], []
            def run(*a): seen.append(a); clock[0]=2; return 'Prepared for review.'
            with mock.patch.object(ai_client,provider+'_client',return_value=client), mock.patch.object(ai_client.time,'monotonic',lambda:clock[0]):
                self.assertEqual(ai_client.ask_agent([],provider,'m',system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=run,
                    on_text=lambda _:None,research_deadline=1,max_rounds=4),'Waiting for approval.')
            self.assertEqual(len(seen),1)
            self.assertEqual(len(requests),2)
            self.assertEqual(requests[-1]['tool_choice'],{'type':'none'} if provider=='anthropic' else 'none')

    def test_optional_openai_item_status_and_required_response_status(self):
        client, _, _ = self.client('openai')
        first=client.messages.fixtures[0]
        for item in first.output: item.status=None
        with mock.patch.object(ai_client,'openai_client',return_value=client):
            self.assertEqual(ai_client.ask_agent([],'openai','m',system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=lambda *a:'Prepared for review.'),'Waiting for approval.')
        client, _, _ = self.client('openai')
        client.messages.fixtures[0].status=None
        run=mock.Mock()
        with mock.patch.object(ai_client,'openai_client',return_value=client),self.assertRaises(RuntimeError):
            ai_client.ask_agent([],'openai','m',system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=run)
        run.assert_not_called()

    def test_duplicate_call_ids_fail_before_any_dispatch(self):
        for provider in ('anthropic','openai'):
            client, _, _ = self.client(provider)
            first=client.messages.fixtures[0]
            if provider=='anthropic': first.content.append(first.content[-1])
            else: first.output.append(first.output[-1])
            run=mock.Mock()
            with mock.patch.object(ai_client,provider+'_client',return_value=client),self.assertRaisesRegex(RuntimeError,'IDs'):
                ai_client.ask_agent([],provider,'m',system_prompt='s',tools=librarian.CATEGORY_TOOLS,run_tool=run)
            run.assert_not_called()


class ResponseEvents:
    def __init__(self, response, text):
        self.response, self.text = response, text

    def __iter__(self):
        yield NS(type='response.function_call_arguments.delta', delta='not answer text')
        yield NS(type='response.output_text.delta', delta=self.text)
        yield NS(type='response.completed')

    def get_final_response(self):
        return self.response


class AnthropicEvents(ResponseEvents):
    def __iter__(self):
        yield NS(type='content_block_delta', delta=NS(type='text_delta', text=self.text))
        yield NS(type='message_stop')

    def get_final_message(self):
        return self.response


def agent_from_stream(stream):
    """Keep existing route scenarios while exercising the new shared entry point."""
    def agent(*args, **kw):
        parts = []
        original = kw.get('on_reset')
        def reset():
            parts.clear()
            if original:
                original()
        kw['on_reset'] = reset
        gen = stream(*args, **kw)
        try:
            for delta in gen:
                parts.append(delta)
                if kw.get('on_text'):
                    kw['on_text'](delta)
        finally:
            gen.close()
        return ''.join(parts)
    return agent


class LocalSdkStreamTest(unittest.TestCase):
    def test_real_sdk_streams_against_local_fake_providers(self):
        import tempfile
        import threading
        from pathlib import Path
        from server import dev_drive
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as td:
                server = dev_drive.serve(Path(td), port=0, fake_ai=True)
                gate, first = threading.Event(), threading.Event()
                server.ai_terminal_gate = gate
                base = f'http://127.0.0.1:{server.server_address[1]}/ai/{provider}'
                factory = getattr(ai_client, provider + '_client')
                client = (factory('fake').with_options(base_url=base) if provider == 'anthropic'
                          else factory('fake', base + '/v1'))
                result, errors, calls = [], [], []
                def work():
                    try:
                        result.append(ai_client.ask_agent([{'role': 'user', 'content': 'Question: knee?'}], provider, 'fake',
                            system_prompt='s', tools=librarian.TOOLS, max_rounds=4,
                            run_tool=lambda n,a: calls.append(n) or '[id 102] knee', on_text=lambda _: first.set()))
                    except Exception as e: errors.append(e)
                try:
                    with mock.patch.object(ai_client, provider + '_client', return_value=client):
                        thread = threading.Thread(target=work); thread.start()
                        self.assertTrue(first.wait(5), errors)
                        self.assertEqual(calls, [])
                        gate.set(); thread.join(10)
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])
                    self.assertTrue(result[0])
                    self.assertEqual(calls, ['search_library', 'read_items'])
                finally:
                    gate.set(); server.shutdown(); server.server_close(); client.close()

    def test_stop_closes_established_sdk_read(self):
        import tempfile
        import threading
        from pathlib import Path
        from server import dev_drive
        from server.routes.ask import _Run
        for provider in ('anthropic', 'openai'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as td:
                server = dev_drive.serve(Path(td), port=0, fake_ai=True)
                gate, first, finished = threading.Event(), threading.Event(), threading.Event()
                server.ai_terminal_gate = gate
                base = f'http://127.0.0.1:{server.server_address[1]}/ai/{provider}'
                factory = getattr(ai_client, provider + '_client')
                client = factory('fake').with_options(base_url=base) if provider == 'anthropic' else factory('fake', base + '/v1')
                stop, calls, errors = _Run(), [], []
                def work():
                    try:
                        ai_client.ask_agent([{'role':'user','content':'Question: knee?'}], provider, 'fake', system_prompt='s', tools=librarian.TOOLS,
                            run_tool=lambda *a: calls.append(a) or 'ok', on_text=lambda _: first.set(),
                            should_stop=stop.is_set, on_stream=stop.register)
                    except Exception as e: errors.append(e)
                    finally: finished.set()
                try:
                    with mock.patch.object(ai_client, provider + '_client', return_value=client):
                        worker = threading.Thread(target=work); worker.start()
                        self.assertTrue(first.wait(5))
                        stopper = threading.Thread(target=stop.set); stopper.start()
                        released = finished.wait(3)
                        gate.set(); worker.join(5); stopper.join(5)
                        self.assertTrue(released, 'Stop did not interrupt an established blocked read')
                        self.assertEqual(calls, [])
                        self.assertTrue(errors)
                finally:
                    gate.set(); server.shutdown(); server.server_close(); client.close()


def json_api(api):
    @contextmanager
    def raw(**kw):
        yield NS(parse=lambda: api.create(**kw), close=lambda: None)
    api.with_streaming_response = NS(create=raw)
    return api
