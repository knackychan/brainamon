"""Short-lived control records, authenticated by the existing encrypted mirror."""
import json
import time
import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from core import license, private_storage

LOGICAL = 'control/license-v1.json'
ACCESS_LOGICAL = 'control/access-v2.json'
CONTROL_LOGICALS = (LOGICAL, ACCESS_LOGICAL)
LIFETIME = 3600


def signer(path, create=False):
    try:
        return serialization.load_pem_private_key(private_storage.read(path), password=None)
    except FileNotFoundError:
        if not create:
            return None
    private = ec.generate_private_key(ec.SECP256R1())
    private_storage.write(path, private.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return private


def public(private):
    return base64.urlsafe_b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).rstrip(b'=').decode()


def _signed(body, private):
    body = json.dumps(body, separators=(',', ':'))
    r, s = decode_dss_signature(private.sign(body.encode(), ec.ECDSA(hashes.SHA256())))
    sig = base64.urlsafe_b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).rstrip(b'=').decode()
    return json.dumps({'body': body, 'sig': sig}).encode()


def access_record(key, private, enabled=True):
    """A pairing-bound one-hour grant; receipts never establish this security identity."""
    if type(enabled) is not bool:
        raise ValueError('Access enabled must be a boolean')
    now = int(time.time())
    return _signed({'v': 2, 'fp': key.fingerprint, 'issued': now,
                    'expires': now + LIFETIME, 'enabled': enabled}, private)


def record(key, private):
    """Legacy v1 for old phones; retain the real issuer-signed receipt, never forge one."""
    now = int(time.time())
    text = ''
    try:
        with license._FILE_LOCK:
            with license.LICENSE_PATH.open(encoding='utf-8') as f:
                candidate = f.read(license.MAX_KEY_LENGTH + 1)
        if license.parse(candidate).status == 'valid':
            text = license.normalize(candidate)
    except (OSError, UnicodeError):
        pass
    return _signed({'v': 1, 'fp': key.fingerprint, 'issued': now,
                    'expires': now + LIFETIME if text else now, 'license': text}, private)
