"""Swap the license key from a Gumroad receipt for a signed Brainamon key, once, at activation.

This is licensing's only network call. The Gumroad key goes to the seller's activation
service (projects/website/brainamon/activate.php on fredtomas.com), which asks Gumroad
whether the purchase is valid and answers a BRAINAMON1 key signed by its own issuer.
core/license.py then checks and saves that key offline, as for a key issued by hand.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from core import license
from core.version import __version__

ACTIVATION_URL = 'https://fredtomas.com/brainamon/activate.php'
MAX_ANSWER = 16384
MAX_MESSAGE = 300
# Gumroad keys look like 85DB562A-C11D4B06-A2335A6B-8C079166; a BRAINAMON1 key never matches.
GUMROAD_KEY = re.compile(r'[A-Za-z0-9]{4,16}(?:-[A-Za-z0-9]{4,16}){2,7}')
UNREACHABLE = 'Could not reach the activation service. Check the internet connection and retry.'
UNEXPECTED = 'The activation service gave an unexpected answer. Retry in a few minutes.'


class ActivationError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def is_gumroad_key(text) -> bool:
    return isinstance(text, str) and bool(GUMROAD_KEY.fullmatch(license.normalize(text)))


def _allowed(url: str) -> bool:
    u = urlsplit(url)
    return u.scheme == 'https' or (u.scheme == 'http' and u.hostname == '127.0.0.1')


def exchange(text: str, url: str = '') -> str:
    """The BRAINAMON1 key for a Gumroad key, or ActivationError (status 400: the service said no;
    502: the service could not be reached or answered something else)."""
    url = url or ACTIVATION_URL
    if not _allowed(url):
        raise ActivationError('The activation service address is not secure.', 502)
    request = urllib.request.Request(
        url, data=json.dumps({'key': license.normalize(text)}).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'User-Agent': f'Brainamon/{__version__} (license activation)'})
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            raw = r.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as e:
        with e:
            raw = e.read(MAX_ANSWER + 1)
    except (OSError, ValueError):
        raise ActivationError(UNREACHABLE, 502) from None
    try:
        answer = json.loads(raw) if len(raw) <= MAX_ANSWER else None
    except ValueError:
        answer = None
    if isinstance(answer, dict) and isinstance(answer.get('key'), str) and answer['key'].startswith(license.PREFIX + '.'):
        return answer['key']
    if isinstance(answer, dict) and isinstance(answer.get('error'), str) and answer['error'].strip():
        raise ActivationError(answer['error'].strip()[:MAX_MESSAGE])
    raise ActivationError(UNEXPECTED, 502)
