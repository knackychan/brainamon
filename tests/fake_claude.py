"""A stand-in for the Claude Code CLI (tests/test_claude_code.py, tests/test_server_claude_code.py): no network,
no login. FAKE_CLAUDE_LOG (a file): each call appends {argv, stdin, env, cwd} as one JSON line.
FAKE_CLAUDE_MODE: ok (default: replays tests/fixtures/claude_stream.jsonl) | logged_out | lost (only --resume
fails) | crash | silent | slow (one text delta, then waits 30 s)."""
import json
import os
import sys
import time

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'claude_stream.jsonl')


def main():
    args = sys.argv[1:]
    mode = os.environ.get('FAKE_CLAUDE_MODE', 'ok')
    printing = '-p' in args
    stdin = sys.stdin.buffer.read().decode('utf-8') if printing else ''
    log = os.environ.get('FAKE_CLAUDE_LOG')
    if log:
        with open(log, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'argv': args, 'stdin': stdin, 'cwd': os.getcwd(),
                                'env': {k: os.environ.get(k, '') for k in
                                        ('CLAUDE_CODE_DISABLE_CLAUDE_MDS', 'CLAUDE_CODE_DISABLE_AUTO_MEMORY',
                                         'ANTHROPIC_API_KEY')}}) + '\n')
    if args == ['--version']:
        print('2.1.296 (Claude Code)')
        return 0
    if args[:2] == ['auth', 'status']:
        ok = mode != 'logged_out'
        if os.environ.get('ANTHROPIC_API_KEY'):          # the real CLI 2.1.296 then bills the API key
            print(json.dumps({'loggedIn': True, 'authMethod': 'api_key', 'apiKeySource': 'ANTHROPIC_API_KEY'}))
            return 0
        print(json.dumps({'loggedIn': ok, 'authMethod': 'claude.ai' if ok else 'none', 'subscriptionType': 'pro'}))
        return 0 if ok else 1
    sid = args[args.index('--resume') + 1] if '--resume' in args else args[args.index('--session-id') + 1]

    def out(d):
        sys.stdout.write(json.dumps({**d, 'session_id': sid}) + '\n')
        sys.stdout.flush()

    if mode == 'logged_out':
        out({'type': 'result', 'subtype': 'success', 'is_error': True, 'result': 'Not logged in · Please run /login'})
        return 1
    if mode == 'lost' and '--resume' in args:
        sys.stderr.write(f'No conversation found with session ID: {sid}\n')
        out({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True,
             'errors': [f'No conversation found with session ID: {sid}']})
        return 1
    if mode == 'crash':
        sys.stderr.write('boom: the fake CLI crashed\n')
        return 3
    if mode == 'silent':
        return 0
    if mode == 'slow':
        out({'type': 'stream_event', 'parent_tool_use_id': None,
             'event': {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'Thinking'}}})
        time.sleep(30)
        return 0
    with open(FIXTURE, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                out(json.loads(line))
    return 0


sys.exit(main())
