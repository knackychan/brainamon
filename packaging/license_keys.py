"""Admin-only permanent license issuer. See docs/LICENSING.md; never bundle private keys."""
import argparse
import base64
import datetime
import getpass
import json
import os
import re
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import license


def generate(path: Path, password: bytes) -> str:
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError('Keep the private signing key outside the source repository.')
    if not password:
        raise ValueError('A password is required to protect the private signing key.')
    private = Ed25519PrivateKey.generate()
    data = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.BestAvailableEncryption(password))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing an issuer key and invalidating its custody trail.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    return private.public_key().public_bytes_raw().hex()


def issue(path: Path, password: bytes, licensee: str, email: str = '') -> str:
    if not password:
        raise ValueError('The private key password is required.')
    private = serialization.load_pem_private_key(path.read_bytes(), password=password)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError('This is not an Ed25519 license signing key.')
    public = private.public_key().public_bytes_raw().hex()
    if public not in license.PUBLIC_KEYS:
        raise ValueError('Pin this issuer public key in core/license.py before issuing licenses.')
    payload = {'v': 1, 'id': str(uuid.uuid4()), 'ed': 'cloud', 'to': licensee.strip(),
               'email': email.strip(), 'iss': datetime.date.today().isoformat(), 'exp': None}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).rstrip(b'=').decode()
    signed = f'{license.PREFIX}.{body}'
    signature = base64.urlsafe_b64encode(private.sign(signed.encode('ascii'))).rstrip(b'=').decode()
    key = f'{signed}.{signature}'
    checked = license.parse(key)
    if checked.status != 'valid':
        raise ValueError(checked.error)
    return key


SERVICE_CONFIG = """<?php
// Brainamon activation service settings (docs/LICENSING.md, "Gumroad activation").
// Upload next to the website's root folder (www/), never inside it. Holds a signing key.
return ['product_id' => '{product_id}', 'seed_hex' => '{seed}'];
"""
SERVICE_URL = 'https://fredtomas.com/brainamon/activate.php'


def generate_service(path: Path, product_id: str) -> str:
    """The activation service's own issuer: a second trusted key, kept as the raw seed its PHP reads."""
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError('Keep the activation service settings outside the source repository.')
    if not re.fullmatch(r'[A-Za-z0-9_=+/-]{4,100}', product_id or ''):
        raise ValueError('Copy the Gumroad product ID exactly (product page, Share > API, or the license key section).')
    seed = os.urandom(32)
    public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw().hex()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(SERVICE_CONFIG.format(product_id=product_id, seed=seed.hex()))
    return public


def check_service(url: str) -> str:
    """The uploaded service signs with a key this build trusts, and its PHP has sodium and curl."""
    with urllib.request.urlopen(url + '?selftest=1', timeout=30) as r:
        info = json.loads(r.read(16384))
    try:
        public, sig = info['public'], info['sig']
        if public not in license.PUBLIC_KEYS:
            raise ValueError(f'The service signs with {public}, which core/license.py does not trust yet.')
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
            base64.urlsafe_b64decode(sig + '=' * (-len(sig) % 4)), b'BRAINAMON-SELFTEST')
    except (KeyError, TypeError, InvalidSignature) as e:
        raise ValueError('The activation service did not pass its self-test.') from e
    if info.get('curl') is not True:
        raise ValueError('PHP curl is missing on the host. Enable it in the OVH PHP settings.')
    return f'Activation service OK: PHP {info.get("php")}, signing key {public[:16]}...'


def configure_public_key(public: str) -> None:
    """First-run setup only; never replace an already configured issuer."""
    if public in license.PUBLIC_KEYS:
        return
    if license.PUBLIC_KEYS:
        raise ValueError('This checkout already trusts a different issuer. Use its private key; no trust keys were changed.')
    source = ROOT / 'core' / 'license.py'
    text = source.read_text(encoding='utf-8')
    marker = 'PUBLIC_KEYS: tuple[str, ...] = ()'
    if text.count(marker) != 1:
        raise ValueError('Public-key configuration changed. Follow docs/LICENSING.md; no source was modified.')
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=source.parent,
                                         prefix='license-issuer-', suffix='.tmp', delete=False) as f:
            temp = f.name
            f.write(text.replace(marker, f'PUBLIC_KEYS: tuple[str, ...] = ({public!r},)'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, source)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    license.PUBLIC_KEYS = (public,)
    print('Configured the public verification key in core/license.py.')


def interactive(path: Path) -> None:
    if path.resolve().is_relative_to(ROOT):
        raise ValueError('Keep the private signing key outside the source repository.')
    holder = input('License holder [Local test]: ').strip() or 'Local test'
    if len(holder) > 200:
        raise ValueError('License holder must be at most 200 characters.')
    fresh = not path.exists()
    if fresh and license.PUBLIC_KEYS:
        raise ValueError('An issuer is already configured. Supply its existing private key with --private-key.')
    password = getpass.getpass('Private key password: ').encode('utf-8')
    if not password:
        raise ValueError('A password is required to protect the private signing key.')
    if fresh:
        if password != getpass.getpass('Confirm password: ').encode('utf-8'):
            raise ValueError('Passwords do not match.')
        public = generate(path, password)
        print(f'Created encrypted private issuer: {path}')
    else:
        private = serialization.load_pem_private_key(path.read_bytes(), password=password)
        if not isinstance(private, Ed25519PrivateKey):
            raise ValueError('This is not an Ed25519 license signing key.')
        public = private.public_key().public_bytes_raw().hex()
    print(f'Public verification key: {public}')
    configure_public_key(public)
    key = issue(path, password, holder)
    print('\nPaste this key into Settings > License:\n')
    print(key)
    print('\nRestart the source app after first setup. Installed apps need a rebuild with this public key.')
    print('Keep the encrypted issuer and password backed up separately. A valid license is required for phone pairing and sync.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('keygen', 'issue', 'interactive', 'keygen-service', 'check-service'))
    parser.add_argument('--private-key', type=Path, help='keygen, issue, interactive: the encrypted issuer key')
    parser.add_argument('--to', default='', help='License holder (required for issue)')
    parser.add_argument('--email', default='')
    parser.add_argument('--config', type=Path, help='keygen-service: the PHP settings file to create, outside the repo')
    parser.add_argument('--product-id', default='', help='keygen-service: the Gumroad product ID')
    parser.add_argument('--url', default=SERVICE_URL, help='check-service: the activation service address')
    args = parser.parse_args()
    if args.command in ('keygen', 'issue', 'interactive') and args.private_key is None:
        parser.error(f'--private-key is required for {args.command}')
    if args.command == 'keygen-service' and args.config is None:
        parser.error('--config is required for keygen-service')
    if args.command == 'issue' and not args.to.strip():
        parser.error('--to is required for issue')
    try:
        if args.command == 'interactive':
            interactive(args.private_key)
            return
        if args.command == 'keygen-service':
            public = generate_service(args.config, args.product_id)
            print(f'Created {args.config}. Upload it next to www/ on the host, never inside it.')
            print('Add this PUBLIC key to PUBLIC_KEYS in core/license.py, after the existing one:')
            print(public)
            return
        if args.command == 'check-service':
            print(check_service(args.url))
            return
        password = getpass.getpass('Private key password: ').encode('utf-8')
        if args.command == 'keygen':
            if password != getpass.getpass('Confirm password: ').encode('utf-8'):
                raise ValueError('Passwords do not match.')
            public = generate(args.private_key, password)
            print('Add this PUBLIC verification key to PUBLIC_KEYS in core/license.py:')
            print(public)
        else:
            print(issue(args.private_key, password, args.to, args.email))
    except (OSError, ValueError, EOFError) as e:
        parser.exit(1, f'{e}\n')


if __name__ == '__main__':
    main()
