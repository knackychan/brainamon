"""`py -m server.drive_check`: one round trip with the real Google Drive, for the day Brainamon's
Google sign-in app exists (audit 2026-10-11, M1: until then every Drive path is tested only
against fakes). Not part of the app; nothing imports it.

It uses the app's Google client (.env, core/config.py) and the app's sign-in when there is one
(the cloud folder, server/settings.CLOUD_DIR), else signs in in the browser and keeps that token in
memory only. Then, in the app data folder: about (the account), a 1 KB upload (multipart) and a
10 MB one (resumable), a listing that must show both, both downloads compared byte for byte, and
both deleted. Each step prints its result; the exit code is the number of failed steps. It touches
only its own two files (names start with `drive-check-`), never the mirror.

`--api URL` points it at another Drive (server/dev_drive.py's fake, http://127.0.0.1:18766), as the
tests do.
"""
import argparse
import os
import sys
import time
from pathlib import Path

from core import config
from library import drive_client

SMALL = 1024
BIG = 10 * 1024 * 1024


def run(client, say=print) -> int:
    """The checks against a signed-in DriveClient; returns how many failed."""
    failed = 0
    stamp = int(time.time())
    files = {f'drive-check-{stamp}-small.bin': os.urandom(SMALL), f'drive-check-{stamp}-big.bin': os.urandom(BIG)}
    ids: dict[str, str] = {}

    def step(name, fn):
        nonlocal failed
        t0 = time.monotonic()
        try:
            out = fn()
        except Exception as e:                  # a check reports, it does not stop the others
            failed += 1
            say(f'FAIL  {name}: {e}')
            return None
        say(f'ok    {name} ({time.monotonic() - t0:.1f} s){": " + str(out) if out not in (None, "") else ""}')
        return out

    step('about', lambda: client.about()['email'] or '(no e-mail in the answer)')
    for name, data in files.items():
        fid = step(f'upload {len(data):,} bytes', lambda name=name, data=data: client.upload(name, data))
        if fid:
            ids[name] = fid

    def listed():
        names = {f['name']: f for f in client.list()}
        missing = [n for n in ids if n not in names]
        if missing:
            raise AssertionError(f'not in the listing: {missing}')
        wrong = [n for n in ids if names[n]['size'] != len(files[n])]
        if wrong:
            raise AssertionError(f'wrong size in the listing: {wrong}')
        return f'{len(names)} file(s) in the app data folder'
    step('list', listed)
    for name, fid in ids.items():
        def same(name=name, fid=fid):
            if client.download(fid) != files[name]:
                raise AssertionError('the download differs from the upload')
        step(f'download {len(files[name]):,} bytes', same)
    for name, fid in ids.items():
        step(f'delete {name}', lambda fid=fid: client.delete(fid))
    return failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--api', help="another Drive's base URL (server/dev_drive.py: http://127.0.0.1:18766)")
    a = ap.parse_args(argv)
    config.load_env()
    if a.api:
        base = a.api.rstrip('/')
        drive_client.API, drive_client.UPLOAD = base + '/drive/v3', base + '/upload/drive/v3'
        cid, secret = 'dev', 'dev'
        tok, path = {'access_token': 'dev', 'refresh_token': 'dev', 'expires_at': 4e9}, None
    else:
        from server import settings
        cid, secret = config.google_client()
        if not cid:
            print('No Google sign-in app is configured (BRAINAMON_GOOGLE_CLIENT_ID in .env).')
            return 1
        path = Path(settings.CLOUD_DIR) / 'google_token.json'
        tok = drive_client.load_token(path)
        if tok is None:
            print('Not signed in in the app: signing in in the browser (the token is not kept).')
            tok, path = drive_client.sign_in(cid, secret), None
    failed = run(drive_client.DriveClient(cid, secret, tok, path))
    print('All Drive checks passed.' if not failed else f'{failed} Drive check(s) failed.')
    return failed


if __name__ == '__main__':
    sys.exit(main())
