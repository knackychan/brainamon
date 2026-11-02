"""Trusted local bootstrap. Never expose this credential through an HTTP endpoint."""
import json
import secrets
from urllib.parse import urlsplit

from core import app_paths, private_storage


def _path(port):
    return app_paths.LOCAL / 'auth' / f'{int(port)}.token'


def create(port):
    token = secrets.token_urlsafe(32)
    private_storage.write(_path(port), token.encode('ascii'))
    return token


def headers(port, extra=None):
    token = private_storage.read(_path(port)).decode('ascii')
    return {**(extra or {}), 'Authorization': 'Bearer ' + token}


def browser_url(url, port=None):
    port = port or urlsplit(url).port
    token = private_storage.read(_path(port)).decode('ascii')
    return url.split('#', 1)[0] + '#cm-auth=' + token


if __name__ == '__main__':
    import argparse
    import webbrowser
    parser = argparse.ArgumentParser(description='Open the local UI using its protected per-run credential.')
    parser.add_argument('--browser', default=f'http://127.0.0.1:{app_paths.DEFAULT_PORT}/')
    parser.add_argument('--port', type=int, default=app_paths.DEFAULT_PORT)
    args = parser.parse_args()
    parsed = urlsplit(args.browser)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password:
        parser.error('Only an explicit local HTTP UI can receive the bootstrap.')
    webbrowser.open(browser_url(args.browser, args.port))
