"""App-owned update signatures, independent of Windows and license signing."""
import base64
import binascii
import json
import re
import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PUBLIC_KEY = '6819ba46d632746278cf181431793768566ba5947430b31def50ec5871fcaead'
REPOSITORY = 'knackychan/brainamon'
MAX_MANIFEST_SIZE = 4096
DOMAIN = b'Brainamon update manifest v1\n'


def message(release):
    return DOMAIN + json.dumps(release, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def verify(raw):
    """Return only authenticated, bounded release metadata; trust no supplied keys."""
    try:
        if not PUBLIC_KEY or len(raw) > MAX_MANIFEST_SIZE:
            raise ValueError
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or set(envelope) != {'release', 'signature'}:
            raise ValueError
        release = envelope['release']
        if (not isinstance(release, dict) or set(release) != {'v', 'repo', 'version', 'name', 'size', 'sha256'}
                or type(release['v']) is not int or release['v'] != 1 or release['repo'] != REPOSITORY
                or not isinstance(release['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', release['version'])
                or release['name'] != f'Brainamon-Setup-{release["version"]}.exe'
                or type(release['size']) is not int or not 0 < release['size'] <= 1024 ** 3
                or not isinstance(release['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', release['sha256'])):
            raise ValueError
        signature = base64.b64decode(envelope['signature'], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(signature, message(release))
        return release
    except (InvalidSignature, ValueError, TypeError, KeyError, binascii.Error, RecursionError) as error:
        raise ValueError('Update release signature is missing, invalid or from an untrusted key.') from error


def verify_file(path):
    path = Path(path)
    with path.with_name(path.name + '.update.json').open('rb') as stream:
        release = verify(stream.read(MAX_MANIFEST_SIZE + 1))
    if path.name != release['name'] or path.stat().st_size != release['size']:
        raise ValueError('Installer name or size does not match its signed release.')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != release['sha256']:
        raise ValueError('Installer does not match its release signature.')
    return release
