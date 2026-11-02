"""Opt-in valid entitlement for sync fixtures; never changes production trust."""
from unittest import mock
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core import license
from tests.test_license import signed


def activate(test, root):
    private = Ed25519PrivateKey.generate()
    for patch in (mock.patch.object(license, 'PUBLIC_KEYS', (private.public_key().public_bytes_raw().hex(),)),
                  mock.patch.object(license, 'LICENSE_PATH', root / 'fixture-license.key')):
        patch.start()
        test.addCleanup(patch.stop)
    key = signed(private)
    license.save(key)
    return key
