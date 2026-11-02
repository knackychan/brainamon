"""Validation shared by imported links, API ingestion and external tools."""
from urllib.parse import urlsplit


def http_url(value):
    if not isinstance(value, str) or not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return False
    try:
        p = urlsplit(value)
        return p.scheme in ('http', 'https') and bool(p.hostname) and p.username is None and p.password is None and (p.port is None or 0 < p.port < 65536) and '\\' not in value
    except ValueError:
        return False
