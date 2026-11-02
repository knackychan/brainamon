"""Initialize the private update signer once, or sign a finished installer."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import private_storage, update_signing
from core.version import __version__


def key_path():
    return Path(os.environ.get('BRAINAMON_UPDATE_KEY') or
                Path(os.environ['LOCALAPPDATA']) / 'Brainamon-Updates' / 'release.key')


def outside_repo(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError('Keep the private update key outside the source repository.')
    return path


def signer(path):
    path = outside_repo(path)
    private = Ed25519PrivateKey.from_private_bytes(private_storage.read(path))
    if private.public_key().public_bytes_raw().hex() != update_signing.PUBLIC_KEY:
        raise ValueError('Update key does not match the pinned public key; no trust was changed.')
    return private


def initialize(path):
    path = outside_repo(path)
    target = private_storage.location(path)
    if target.exists() or path.exists():
        private = Ed25519PrivateKey.from_private_bytes(private_storage.read(path))
    else:
        if update_signing.PUBLIC_KEY:
            raise ValueError('An update key is already pinned. Restore its private key; do not replace it.')
        private_storage._secure(path.parent)
        with path.open('xb'):
            pass
        private = Ed25519PrivateKey.generate()
        private_storage.write(path, private.private_bytes_raw())
    public = private.public_key().public_bytes_raw().hex()
    if update_signing.PUBLIC_KEY and update_signing.PUBLIC_KEY != public:
        raise ValueError('A different update key is already pinned; no trust was changed.')
    if not update_signing.PUBLIC_KEY:
        source = ROOT / 'core/update_signing.py'
        text = source.read_text(encoding='utf-8')
        marker = "PUBLIC_KEY = ''"
        if text.count(marker) != 1:
            raise ValueError('Public key configuration changed; no source was modified.')
        atomic_write(source, text.replace(marker, f'PUBLIC_KEY = {public!r}'))
        update_signing.PUBLIC_KEY = public
    signer(path)
    return target


def atomic_write(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def sign_installer(path, private_path):
    if path.name != f'Brainamon-Setup-{__version__}.exe':
        raise ValueError('Installer name must match the current app version.')
    private = signer(private_path)
    size = path.stat().st_size
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    release = {'v': 1, 'repo': update_signing.REPOSITORY, 'version': __version__,
               'name': path.name, 'size': size, 'sha256': digest}
    envelope = {'release': release, 'signature': base64.b64encode(private.sign(update_signing.message(release))).decode('ascii')}
    raw = json.dumps(envelope, sort_keys=True, separators=(',', ':'))
    update_signing.verify(raw)
    manifest = path.with_name(path.name + '.update.json')
    atomic_write(manifest, raw + '\n')
    atomic_write(path.with_name(path.name + '.sha256'), f'{digest}  {path.name}\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'check', 'sign'))
    parser.add_argument('installer', nargs='?', type=Path)
    parser.add_argument('--private-key', type=Path)
    args = parser.parse_args()
    path = args.private_key or key_path()
    if args.command == 'init':
        print('Protected update key:', initialize(path))
        print('Public verifier configured in core/update_signing.py. DPAPI key recovery needs this Windows user/profile.')
    elif args.command == 'check':
        signer(path)
        print('Private update key matches the pinned public verifier.')
    else:
        if args.installer is None:
            parser.error('sign requires an installer')
        print('Signed release manifest:', sign_installer(args.installer, path))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
