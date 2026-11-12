"""Explicit debug-fixture controls and evidence; never touches the release app's data.

python -m tests.phone_sync_device status | start | queue | pause | resume | periodic | check | stop
The fake Drive must be running; see phone_sync_fixture.py.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.request

APP = 'app.brainamon.mobile.contributor'
ADB = str(Path(os.environ['LOCALAPPDATA']) / 'Android/Sdk/platform-tools/adb.exe')


def adb(*args):
    return subprocess.check_output([ADB, *args], timeout=20)


def status():
    data = adb('exec-out', 'run-as', APP, 'cat', 'databases/sync-fixture-brainamon-sync.db')
    with sqlite3.connect(':memory:') as db:
        db.deserialize(data)
        state = dict(db.execute("SELECT name,value FROM state WHERE scope=''"))
        result = dict(time=time.time(), status=json.loads(state.get('status', '{}')), runs=state.get('fixture-runs'),
                      outbox=db.execute('SELECT COUNT(*),SUM(remote IS NULL) FROM outbox').fetchone(),
                      cached=db.execute("SELECT COUNT(*) FROM state WHERE name LIKE 'file/%'").fetchone()[0])
    f = json.load(urllib.request.urlopen('http://127.0.0.1:18876/fixture'))
    result['requests'] = len(f['requests'])
    result['uploads'] = len([r for r in f['requests'] if r['method'] == 'POST'])
    result['vault_files'] = len(adb('shell', 'run-as', APP, 'ls', '-a', 'files/sync-fixture-vault').decode().splitlines())
    try:
        result['pid'] = adb('shell', 'pidof', APP).decode().strip()
    except subprocess.CalledProcessError:
        result['pid'] = None
    return result


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if command == 'status':
        result = status()
    elif command in {'init', 'start', 'queue', 'pause', 'resume', 'periodic', 'check', 'stop'}:
        args = ['shell', 'am', 'broadcast', '--user', '0', '-n', APP + '/app.brainamon.mobile.SyncProbeReceiver', '--es', 'command', command]
        if command == 'queue':
            args += ['--es', 'count', sys.argv[2] if len(sys.argv) > 2 else '64', '--es', 'size', sys.argv[3] if len(sys.argv) > 3 else '65536']
        result = dict(time=time.time(), command=command, output=adb(*args).decode().strip())
    else:
        raise SystemExit('Unknown fixture command')
    folder = Path('local/phone-background-work'); folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'native-sync-device.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(result) + '\n')
    print(json.dumps(result))
