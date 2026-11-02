"""Wiskit's Claude Code mode, the engine (knowledge/claude_code.py) against a fake CLI (tests/fake_claude.py):
no network, no login, no real claude.

Run from the project root:  py -m unittest tests.test_claude_code -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from knowledge import claude_code
from knowledge.ask_chats import AskChatStore

FAKE = str(Path(__file__).with_name('fake_claude.py'))
FIXTURE = Path(__file__).parent / 'fixtures' / 'claude_stream.jsonl'
SID = '11111111-2222-4333-8444-555555555555'


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)
        self.log = self.dir / 'calls.jsonl'
        self.error_log = self.dir / 'error_log.txt'
        for p in (mock.patch.object(claude_code, 'launcher', lambda path: [sys.executable, FAKE]),
                  mock.patch.object(claude_code, 'WORK_DIR', self.dir / 'work'),
                  mock.patch.object(claude_code.app_paths, 'ERROR_LOG', self.error_log),
                  mock.patch.dict(os.environ, {'FAKE_CLAUDE_LOG': str(self.log), 'FAKE_CLAUDE_MODE': 'ok',
                                               'ANTHROPIC_API_KEY': 'sk-ant-from-dotenv'})):
            p.start()
            self.addCleanup(p.stop)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding='utf-8').splitlines()] if self.log.exists() else []

    def answer(self, **kw):
        events = []
        args = dict(session='', history=[], attached='', model='', system_text='Be Wiskit.', data_dir=self.dir,
                    port=1, on_event=lambda k, d: events.append((k, d)), should_stop=lambda: False)
        args.update(kw)
        text, sid = claude_code.answer(FAKE, 'knee prehab?', **args)
        return text, sid, events


class CommandTest(Base):
    def test_command_is_isolated(self):
        files = claude_code.write_files(self.dir / 'w', self.dir / 'data', 4321, 'Be Wiskit.')
        cmd = claude_code.build_command(FAKE, files, SID, resume=False)
        self.assertEqual(cmd[:2], [sys.executable, FAKE])
        a = cmd[2:]
        for flag in ('-p', '--verbose', '--include-partial-messages', '--strict-mcp-config', '--disable-slash-commands'):
            self.assertIn(flag, a)
        pairs = {a[i]: a[i + 1] for i in range(len(a) - 1) if a[i].startswith('--')}
        self.assertEqual(pairs['--output-format'], 'stream-json')
        self.assertEqual(pairs['--tools'], '')
        self.assertEqual(pairs['--setting-sources'], '')
        self.assertEqual(pairs['--permission-prompts'], 'none')
        self.assertEqual(pairs['--disallowedTools'], 'mcp__brainamon__control_job')
        allowed = pairs['--allowedTools'].split(',')
        self.assertIn('mcp__brainamon__save_note', allowed)
        self.assertIn('mcp__brainamon__search_library', allowed)
        self.assertNotIn('mcp__brainamon__control_job', allowed)
        self.assertTrue(all(t.startswith('mcp__brainamon__') for t in allowed))
        self.assertEqual(pairs['--session-id'], SID)
        self.assertEqual(pairs['--append-system-prompt-file'], str(files['system']))
        self.assertNotIn('--model', a)
        for bad in ('--dangerously-skip-permissions', '--allow-dangerously-skip-permissions', '--permission-mode',
                    '--bare', '--safe-mode', '--add-dir', '--continue'):
            self.assertNotIn(bad, a)
        resumed = claude_code.build_command(FAKE, files, SID, resume=True, model='sonnet')
        self.assertIn('--resume', resumed)
        self.assertNotIn('--session-id', resumed)
        self.assertEqual(resumed[-2:], ['--model', 'sonnet'])
        cfg = json.loads(files['mcp'].read_text(encoding='utf-8'))['mcpServers']
        self.assertEqual(list(cfg), ['brainamon'])
        self.assertEqual(cfg['brainamon']['args'], ['-m', 'mcp_local'])
        self.assertEqual(cfg['brainamon']['timeout'], claude_code.MCP_TOOL_TIMEOUT_MS)
        env = cfg['brainamon']['env']
        self.assertEqual((env['CM_DATA_DIR'], env['CM_PORT'], env['CM_MCP_SOURCE']),
                         (str(self.dir / 'data'), '4321', claude_code.SOURCE))
        self.assertEqual(files['system'].read_text(encoding='utf-8'), 'Be Wiskit.')

    def test_stream_events_from_recorded_lines(self):
        s = claude_code.Stream()
        events = [e for line in FIXTURE.read_text(encoding='utf-8').splitlines() for e in s.feed(line)]
        self.assertEqual(events, [
            ('chunk', {'text': 'Let me search.'}),
            ('reset', {}),
            ('progress', {'line': 'Claude Code · search_library: knee prehab'}),
            ('progress', {'line': 'Claude usage: 84% of the seven-day limit used.'}),
            ('chunk', {'text': 'Do the hip airplanes '}),
            ('chunk', {'text': '[id 1].'}),
        ])
        self.assertEqual(s.text, 'Do the hip airplanes [id 1].')
        self.assertEqual(s.pending, {})               # the fixture's search got its result
        self.assertEqual(s.error, '')
        self.assertEqual(s.feed('not json'), [])

    def test_timeout_names_the_tool_still_waiting(self):
        s = claude_code.Stream()

        def use(tid, query):
            return json.dumps({'type': 'assistant', 'parent_tool_use_id': None, 'message': {'content': [
                {'type': 'tool_use', 'id': tid, 'name': 'mcp__brainamon__search_library', 'input': {'query': query}}]}})
        s.feed(use('t1', 'logo tools'))
        s.feed(json.dumps({'type': 'user', 'parent_tool_use_id': None, 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 't1', 'content': '{}'}]}}))
        s.feed(use('t2', 'codex skills'))
        s.feed(use('t3', 'design'))
        self.assertEqual(sorted(s.pending), ['t2', 't3'])
        s.timed_out = True
        why = claude_code.failure(s)
        self.assertIn('Wiskit stopped it', why)
        self.assertIn('waiting on search_library: codex skills for 0 min', why)
        self.assertIn('(1 more call also had no result)', why)
        self.assertNotIn('logo tools', why)

    def test_python_for_the_mcp_server(self):
        (self.dir / 'pythonw.exe').write_text('')
        (self.dir / 'python.exe').write_text('')
        with mock.patch.object(sys, 'executable', str(self.dir / 'pythonw.exe')):
            self.assertEqual(claude_code._python(), str(self.dir / 'python.exe'))

    def test_installed_build_runs_the_mcp_server_from_its_exe(self):
        exe = str(self.dir / 'Brainamon.exe')
        with mock.patch.object(claude_code.app_paths, 'FROZEN', True), mock.patch.object(sys, 'executable', exe):
            self.assertEqual(claude_code.mcp_command(), (exe, ['--mcp'], {}))
            files = claude_code.write_files(self.dir / 'run', self.dir / 'data', 4321, 'rules')
            cfg = json.loads(files['mcp'].read_text(encoding='utf-8'))['mcpServers']['brainamon']
        self.assertEqual((cfg['command'], cfg['args']), (exe, ['--mcp']))
        self.assertNotIn('PYTHONPATH', cfg['env'])
        with mock.patch.object(claude_code.app_paths, 'FROZEN', False):
            self.assertEqual(claude_code.mcp_command()[1], ['-m', 'mcp_local'])

    def test_detect_finds_the_native_and_winget_installs(self):
        native = self.dir / 'home' / '.local' / 'bin' / 'claude.exe'
        winget = self.dir / 'local' / 'Microsoft' / 'WinGet' / 'Links' / 'claude.exe'
        env = {'USERPROFILE': str(self.dir / 'home'), 'LOCALAPPDATA': str(self.dir / 'local'), 'APPDATA': ''}
        with mock.patch.object(claude_code.shutil, 'which', lambda _: None), mock.patch.dict(os.environ, env):
            self.assertEqual(claude_code.detect(), '')
            winget.parent.mkdir(parents=True)
            winget.write_text('')
            self.assertEqual(claude_code.detect(), str(winget))
            native.parent.mkdir(parents=True)
            native.write_text('')
            self.assertEqual(claude_code.detect(), str(native))


class AnswerTest(Base):
    def test_new_session_then_resume(self):
        text, sid, events = self.answer()
        self.assertEqual(text, 'Do the hip airplanes [id 1].')
        self.assertIn(('reset', {}), events)
        first = self.calls()[0]
        self.assertEqual(first['argv'][first['argv'].index('--session-id') + 1], sid)
        self.assertEqual(first['stdin'], 'knee prehab?')
        self.assertEqual(first['env'], {'CLAUDE_CODE_DISABLE_CLAUDE_MDS': '1', 'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1',
                                        'ANTHROPIC_API_KEY': ''})         # the login answers, not the .env key
        self.assertEqual(Path(first['cwd']), self.dir / 'work')
        self.assertEqual(list((self.dir / 'work').glob('*-*.*')), [])          # the run's files are gone
        text2, sid2, _ = self.answer(session=sid, history=[{'role': 'user', 'content': 'old'}])
        second = self.calls()[1]
        self.assertEqual(second['argv'][second['argv'].index('--resume') + 1], sid)
        self.assertEqual(second['stdin'], 'knee prehab?')                      # a resumed session needs no history
        self.assertEqual(sid2, sid)

    def test_first_turn_carries_earlier_turns_and_attachments(self):
        hist = [{'role': 'user', 'content': 'old question'}, {'role': 'assistant', 'content': 'old answer'}]
        self.answer(history=hist, attached='ATTACHED TEXT')
        stdin = self.calls()[0]['stdin']
        self.assertIn('Earlier in this chat', stdin)
        self.assertIn('User: old question', stdin)
        self.assertIn('Wiskit: old answer', stdin)
        self.assertIn('ATTACHED TEXT', stdin)
        self.assertTrue(stdin.endswith('knee prehab?'))

    def test_lost_session_starts_again_once(self):
        os.environ['FAKE_CLAUDE_MODE'] = 'lost'
        text, sid, events = self.answer(session=SID)
        self.assertEqual(text, 'Do the hip airplanes [id 1].')
        self.assertNotEqual(sid, SID)
        self.assertIn(('progress', {'line': claude_code.LOST_LINE}), events)
        argv = [c['argv'] for c in self.calls()]
        self.assertIn('--resume', argv[0])
        self.assertIn('--session-id', argv[1])

    def test_errors_are_plain_messages(self):
        for mode, needle in (('logged_out', 'not logged in'), ('crash', 'exit 3'), ('silent', 'without an answer')):
            os.environ['FAKE_CLAUDE_MODE'] = mode
            with self.assertRaises(claude_code.Failed) as ctx:
                self.answer()
            self.assertIn(needle, str(ctx.exception))
        os.environ['FAKE_CLAUDE_MODE'] = 'crash'
        with self.assertRaises(claude_code.Failed) as ctx:
            self.answer()
        self.assertIn('boom', str(ctx.exception))
        with mock.patch.object(claude_code, 'launcher', lambda path: [str(self.dir / 'nope.exe')]):
            with self.assertRaises(claude_code.Failed) as ctx:
                self.answer()
        self.assertIn('did not start', str(ctx.exception))

    def test_stop_kills_the_cli(self):
        os.environ['FAKE_CLAUDE_MODE'] = 'slow'
        stop = threading.Event()
        t0 = time.monotonic()
        text, sid, _ = self.answer(on_event=lambda k, d: stop.set(), should_stop=stop.is_set)
        self.assertIsNone(text)
        self.assertEqual(sid, '')
        self.assertLess(time.monotonic() - t0, 15)

    def test_timeout(self):
        os.environ['FAKE_CLAUDE_MODE'] = 'slow'
        s = claude_code.run([sys.executable, FAKE, '-p', '--session-id', SID], 'q', cwd=self.dir,
                            on_event=lambda *a: None, should_stop=lambda: False, timeout=1)
        self.assertTrue(s.timed_out)
        self.assertIn('Wiskit stopped it', claude_code.failure(s))
        claude_code.log_failure(claude_code.failure(s), s, session=SID, model='sonnet', seconds=1)
        text = self.error_log.read_text(encoding='utf-8')
        self.assertIn('claude_code: Claude Code took longer than', text)
        self.assertIn(f'session {SID}, model sonnet, 1 s', text)
        self.assertIn('timed out True', text)

    def test_failures_survive_in_the_error_log(self):
        """The app console is memory only: a failed run is also appended to error_log.txt."""
        os.environ['FAKE_CLAUDE_MODE'] = 'crash'
        with self.assertRaises(claude_code.Failed) as ctx:
            self.answer(model='sonnet')
        text = self.error_log.read_text(encoding='utf-8')
        self.assertIn(f'claude_code: {ctx.exception}', text)
        self.assertIn('model sonnet', text)
        self.assertIn('exit 3', text)
        self.assertIn('0 tool call(s): none', text)
        self.assertIn('stderr: boom: the fake CLI crashed', text)
        with mock.patch.object(claude_code, 'launcher', lambda path: [str(self.dir / 'nope.exe')]):
            with self.assertRaises(claude_code.Failed):
                self.answer()
        self.assertIn('Claude Code did not start', self.error_log.read_text(encoding='utf-8'))
        os.environ['FAKE_CLAUDE_MODE'] = 'ok'
        self.answer()
        self.assertEqual(self.error_log.read_text(encoding='utf-8').count('claude_code:'), 2)   # success logs nothing


class SettingsTest(Base):
    def test_check_states(self):
        r = claude_code.check(FAKE)
        self.assertEqual((r['ok'], r['state'], r['version']), (True, 'found', '2.1.296 (Claude Code)'))
        self.assertEqual(r['message'], 'Logged in (pro).')                    # not api_key: the .env key is not passed
        os.environ['FAKE_CLAUDE_MODE'] = 'logged_out'
        self.assertEqual(claude_code.check(FAKE)['state'], 'logged_out')
        self.assertEqual(claude_code.check('')['state'], 'missing')
        self.assertEqual(claude_code.check(str(self.dir / 'none.exe'))['state'], 'missing')

    def test_problem_and_model_setting(self):
        s = {}
        get = lambda k, d='': s.get(k, d)
        with mock.patch.object(claude_code, 'available', lambda: True):
            self.assertIn('Turn on', claude_code.problem(get))
            s[claude_code.ENABLED_KEY] = '1'
            self.assertIn('not found', claude_code.problem(get))
            s[claude_code.PATH_KEY] = FAKE
            self.assertEqual(claude_code.problem(get), '')
        with mock.patch.object(claude_code, 'available', lambda: False):
            self.assertEqual(claude_code.problem(get), claude_code.NOT_IN_BUILD)
        s[claude_code.MODEL_KEY] = 'gpt-6-luna'
        self.assertEqual(claude_code.model_setting(get), claude_code.ai_client.CLAUDE_CODE_DEFAULT_MODEL)
        s[claude_code.MODEL_KEY] = 'sonnet'
        self.assertEqual(claude_code.model_setting(get), 'sonnet')

    def test_system_prompt(self):
        notes = self.dir / 'notes'
        notes.mkdir()
        (notes / 'about-me.md').write_text('---\ntopic: About me\n---\n\nI train at home.\n', encoding='utf-8')
        db = types.SimpleNamespace(count_by_category=lambda: {'SPORT': 3, 'AI': 5}, count_items=lambda: 8,
                                   get_categories=lambda: [{'name': 'SPORT'}, {'name': 'AI'}], notes_dir=notes,
                                   data_dir=self.dir)
        text = claude_code.system_prompt(db)
        self.assertIn('set_canvas', text)
        self.assertIn('Existing canvases (JSON: id, name, elements): []', text)
        self.assertNotIn('propose_canvas', text)
        self.assertIn('holds 8 saved', text)
        self.assertIn('AI (5), SPORT (3)', text)
        self.assertIn('search_library', text)
        self.assertIn('save_note', text)
        self.assertIn('I train at home.', text)


class LauncherTest(unittest.TestCase):
    def test_detect_and_launcher(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            npm = Path(td) / 'npm'
            npm.mkdir()
            cmd = npm / 'claude.cmd'
            cmd.write_text('@echo off')
            with mock.patch('shutil.which', lambda name: None), mock.patch.dict(os.environ, {'APPDATA': td}):
                self.assertEqual(claude_code.detect(), str(cmd))
            with mock.patch('shutil.which', lambda name: 'C:/x/claude.exe'):
                self.assertEqual(claude_code.detect(), 'C:/x/claude.exe')
            self.assertEqual(claude_code.launcher(str(cmd)), [str(cmd)])
            exe = npm / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'bin' / 'claude.exe'
            exe.parent.mkdir(parents=True)
            exe.write_text('')
            self.assertEqual(claude_code.launcher(str(cmd)), [str(exe)])
            self.assertEqual(claude_code.launcher('C:/y/claude.exe'), [str(Path('C:/y/claude.exe'))])

    def test_chat_session_must_be_a_uuid(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            store = AskChatStore(Path(td))
            slug, data = store.create('x')
            self.assertEqual(data['claude_session'], '')
            store.save(slug, {**data, 'claude_session': SID})
            self.assertEqual(store.load(slug)['claude_session'], SID)
            store.save(slug, {**data, 'claude_session': 'x & calc'})
            self.assertEqual(store.load(slug)['claude_session'], '')


if __name__ == '__main__':
    unittest.main()
