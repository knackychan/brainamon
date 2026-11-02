"""Permanent sync licenses, verified offline for phone pairing and sync.

The format is BRAINAMON1.<base64url JSON>.<Ed25519 signature> (6ee5439's, renamed on 2026-10-25).
Only public verification keys ship with Brainamon. Activation stays on this PC,
outside the library, and makes no network call.
"""
import base64
import binascii
import datetime
import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core import app_paths

PREFIX = 'BRAINAMON1'
MAX_KEY_LENGTH = 8192
LICENSE_PATH = app_paths.LOCAL / 'license.key'
_FILE_LOCK = threading.RLock()
# Pin public keys printed by packaging/license_keys.py here before distributing licenses.
# The old development key is intentionally not trusted.
PUBLIC_KEYS: tuple[str, ...] = ('b0ada4930e2fd68072bc13ffed0c2920f3dcdd0eb26ead30089f1e420a64d8b1',
                                '5a139ade2cdb862835da1c6466a7fde96d1448a6fc4c82662b9dddacbd6657b2')


@dataclass(frozen=True)
class License:
    status: str
    licensee: str = ''
    email: str = ''
    key_id: str = ''
    issued: str = ''
    error: str = ''

    def view(self) -> dict:
        return asdict(self)


NONE = License('none')


def normalize(text: str) -> str:
    return ''.join(text.split())


def _decode(text: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', text):
        raise ValueError('Invalid base64url')
    raw = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
    if base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii') != text:
        raise ValueError('Noncanonical base64url')
    return raw


def parse(text: str) -> License:
    """Untrusted pasted/file input; invalid keys never grant an entitlement."""
    if not isinstance(text, str) or len(text) > MAX_KEY_LENGTH:
        return License('invalid', error='This license key is too long or is not text.')
    key = normalize(text)
    if not key:
        return NONE
    try:
        prefix, body, signature = key.split('.')
        if prefix != PREFIX:
            raise ValueError
        payload, sig = _decode(body), _decode(signature)
        if len(sig) != 64:
            raise ValueError
    except (ValueError, binascii.Error):
        return License('invalid', error='This is not a complete Brainamon license key. Paste it again.')
    if not PUBLIC_KEYS:
        return License('invalid', error='License activation is not configured in this build yet.')
    for public in PUBLIC_KEYS:
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(sig, f'{PREFIX}.{body}'.encode('ascii'))
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        return License('invalid', error='This license key is damaged or was not issued by Brainamon.')
    try:
        p = json.loads(payload)
        if (not isinstance(p, dict) or type(p.get('v')) is not int or p['v'] != 1
                or p.get('ed') != 'cloud' or p.get('exp') not in (None, '')):
            raise ValueError
        for field, limit in (('id', 128), ('to', 200), ('email', 320), ('iss', 10)):
            value = p.get(field)
            if not isinstance(value, str) or len(value) > limit or (field != 'email' and not value.strip()):
                raise ValueError
        if datetime.date.fromisoformat(p['iss']).isoformat() != p['iss']:
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        return License('invalid', error='This key is not a supported permanent Brainamon sync license.')
    return License('valid', licensee=p['to'], email=p['email'], key_id=p['id'], issued=p['iss'])


def load() -> License:
    with _FILE_LOCK:
        try:
            with LICENSE_PATH.open('rb') as f:
                text = f.read(MAX_KEY_LENGTH + 2).decode('utf-8')
        except FileNotFoundError:
            return NONE
        except (OSError, UnicodeError):
            return License('invalid', error='The saved license could not be read. Activate it again.')
        return parse(text.rstrip('\r\n'))


def save(text: str) -> License:
    with _FILE_LOCK:
        lic = parse(text)
        if lic.status != 'valid':
            raise ValueError(lic.error or 'Paste your Brainamon license key first.')
        LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=LICENSE_PATH.parent,
                                             prefix='license-', suffix='.tmp', delete=False) as f:
                temp = f.name
                f.write(normalize(text) + '\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, LICENSE_PATH)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
        return lic


def remove() -> None:
    with _FILE_LOCK:
        LICENSE_PATH.unlink(missing_ok=True)
