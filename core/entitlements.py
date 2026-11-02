"""Feature availability is payment-independent; receipts remain legacy metadata."""
from core import license
from contextvars import ContextVar

phone_request = ContextVar('phone_request', default=False)


def is_pro() -> bool:
    """Whether a valid legacy receipt is stored, not whether features are available."""
    return license.load().status == 'valid'


def feature_enabled(feature: str) -> bool:
    """All features are available; authentication, pairing and worker gates stay separate."""
    return True
