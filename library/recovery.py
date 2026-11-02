"""Bounded, portable master-key envelopes. No filesystem, Drive or application state."""
import base64
import json
import re
import secrets
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from library.mirror import MirrorKey

PREFIX = 'vi-recovery-'
MAX_RECORD = 32768
KDF = {'name': 'scrypt', 'n': 131072, 'r': 8, 'p': 1}
KIT_FORMAT = 'brainamon-recovery-kit'
PHONE_FORMAT = 'brainamon-phone-recovery'


class RecoveryError(ValueError):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def parse(raw):
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_RECORD:
        raise RecoveryError('Recovery file is too large or invalid.')
    try:
        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise ValueError('duplicate')
                out[k] = v
            return out
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise RecoveryError('Recovery file is damaged.') from None
    if not isinstance(value, dict):
        raise RecoveryError('Recovery file must contain an object.')
    return value


def encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def decode(value, length):
    if not isinstance(value, str) or len(value) > length * 2 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise RecoveryError('Recovery key material is invalid.')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except ValueError:
        raise RecoveryError('Recovery key material is invalid.') from None
    if len(raw) != length or encode(raw) != value:
        raise RecoveryError('Recovery key material is invalid.')
    return raw


def password_bytes(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise RecoveryError('Use a recovery passphrase of 12 to 1024 characters.')
    try:
        raw = password.encode('utf-8')
    except UnicodeError:
        raise RecoveryError('The passphrase contains invalid text.') from None
    if len(raw) > 4096:
        raise RecoveryError('The passphrase is too long.')
    return raw


def validate(record):
    if not isinstance(record, dict) or len(dump(record)) > MAX_RECORD:
        raise RecoveryError('Invalid recovery envelope.')
    h = record.get('header')
    if not isinstance(h, dict) or set(h) != {'format', 'version', 'library', 'fingerprint', 'generation', 'created', 'account'}:
        raise RecoveryError('Unsupported recovery envelope.')
    if h['format'] != 'brainamon-recovery' or type(h['version']) is not int or h['version'] != 1:
        raise RecoveryError('Update Brainamon to open this recovery version.')
    for field, pattern in (('library', r'[0-9a-f]{32}'), ('generation', r'[0-9a-f]{32}'), ('fingerprint', r'[0-9a-f]{12}')):
        if not isinstance(h[field], str) or not re.fullmatch(pattern, h[field]):
            raise RecoveryError('Invalid recovery identity.')
    if type(h['created']) is not int or h['created'] <= 0 or not isinstance(h['account'], str) or len(h['account']) > 320:
        raise RecoveryError('Invalid recovery metadata.')
    if set(record) != {'header', 'password', 'kit'}:
        raise RecoveryError('Invalid recovery envelope fields.')
    for kind in ('password', 'kit'):
        w = record[kind]
        expected = {'nonce', 'ciphertext', 'kdf', 'salt'} if kind == 'password' else {'nonce', 'ciphertext'}
        if not isinstance(w, dict) or set(w) != expected:
            raise RecoveryError('Invalid recovery wrapper.')
        if kind == 'password':
            if w['kdf'] != KDF or any(type(w['kdf'].get(k)) is not int for k in ('n', 'r', 'p')):
                raise RecoveryError('Unsupported recovery password parameters.')
            decode(w['salt'], 16)
        decode(w['nonce'], 12)
        decode(w['ciphertext'], 48)
    return h


def name(record):
    h = validate(record)
    return f"{PREFIX}{h['library']}-{h['generation']}.json"


def _aad(header, kind, wrapper):
    return dump({'header': header, 'kind': kind, **{k: v for k, v in wrapper.items() if k != 'ciphertext'}})


def _derive(password, salt):
    return Scrypt(salt=salt, length=32, n=KDF['n'], r=KDF['r'], p=KDF['p']).derive(password_bytes(password))


def create(key, password, account, library=None, kit_secret=None):
    salt = secrets.token_bytes(16)
    password_key = _derive(password, salt)
    secret = kit_secret or secrets.token_bytes(32)
    if len(secret) != 32:
        raise RecoveryError('Invalid recovery kit secret.')
    h = {'format': 'brainamon-recovery', 'version': 1, 'library': library or secrets.token_hex(16),
         'fingerprint': key.fingerprint, 'generation': secrets.token_hex(16),
         'created': int(time.time()), 'account': account}
    record = {'header': h}
    for kind, wrapping_key in (('password', password_key), ('kit', secret)):
        w = {'nonce': encode(secrets.token_bytes(12))}
        if kind == 'password':
            w.update(kdf=dict(KDF), salt=encode(salt))
        w['ciphertext'] = encode(AESGCM(wrapping_key).encrypt(decode(w['nonce'], 12), key.master, _aad(h, kind, w)))
        record[kind] = w
    validate(record)
    return record, secret


def unlock(record, *, password=None, secret=None):
    h = validate(record)
    kind = 'password' if password is not None else 'kit'
    w = record[kind]
    wrapping_key = _derive(password, decode(w['salt'], 16)) if kind == 'password' else decode(secret, 32)
    try:
        raw = AESGCM(wrapping_key).decrypt(decode(w['nonce'], 12), decode(w['ciphertext'], 48), _aad(h, kind, w))
    except InvalidTag:
        raise RecoveryError('The recovery secret is incorrect or the envelope was changed.') from None
    key = MirrorKey(raw)
    if key.fingerprint != h['fingerprint']:
        raise RecoveryError('Recovery key does not match this library.')
    return key


def kit(record, secret):
    validate(record)
    decode(secret, 32)
    return {'format': KIT_FORMAT, 'version': 1, 'secret': secret, 'record': record,
            'instructions': 'Keep this file outside your PC and phone. It unlocks your encrypted Drive library; it is not a copy of the library. Never share it.'}


def import_key(text):
    """Accept a saved kit, phone export, legacy raw master or existing pairing URL/code."""
    if not isinstance(text, str) or len(text) > MAX_RECORD:
        raise RecoveryError('Recovery material is too large or invalid.')
    text = text.strip()
    if text.startswith('{'):
        value = parse(text)
        if value.get('format') == 'brainamon-phone-backup-kit':
            raise RecoveryError('This recovery file belongs to a standalone phone backup. Open it in the phone app: More > No PC? > Recover a library…, then File.')
        if value.get('format') == KIT_FORMAT and type(value.get('version')) is int and value['version'] == 1:
            key = unlock(value.get('record'), secret=value.get('secret'))
            return key, kit(value['record'], value['secret'])
        if value.get('format') == PHONE_FORMAT and type(value.get('version')) is int and value['version'] == 1:
            key = MirrorKey(decode(value.get('key'), 32))
            if value.get('fingerprint') != key.fingerprint:
                raise RecoveryError('Phone recovery key does not match its fingerprint.')
            return key, None
        raise RecoveryError('Unsupported recovery file.')
    if '#pair=' in text:
        text = text.split('#pair=', 1)[1]
    if len(text) != 43:
        try:
            value = parse(base64.urlsafe_b64decode(text + '=' * (-len(text) % 4)))
            text = value['k']
        except (ValueError, KeyError, TypeError):
            raise RecoveryError('Use a recovery kit, phone export or original pairing/recovery code.') from None
    return MirrorKey(decode(text, 32)), None
