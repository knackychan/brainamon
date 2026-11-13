"""Validation shared by imported links, API ingestion and external tools."""
import re
from urllib.parse import parse_qs, urlsplit


def http_url(value):
    if not isinstance(value, str) or not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        return False
    try:
        p = urlsplit(value)
        return p.scheme in ('http', 'https') and bool(p.hostname) and p.username is None and p.password is None and (p.port is None or 0 < p.port < 65536) and '\\' not in value
    except ValueError:
        return False


def facebook_post_key(url: str) -> str:
    """The phone reader's Facebook identity, independent of reel/watch URL and caption."""
    if not http_url(url):
        return ''
    p = urlsplit(url)
    if not (p.hostname == 'facebook.com' or p.hostname.endswith('.facebook.com')):
        return ''
    if p.port not in (None, 443 if p.scheme == 'https' else 80):
        return ''
    if re.fullmatch(r'/watch/?', p.path):
        video = parse_qs(p.query, keep_blank_values=True).get('v', [''])[0]
        return 'fb:' + video if re.fullmatch(r'[0-9]{5,25}', video) else ''
    m = re.fullmatch(r'/(?:reel|watch|videos)/([0-9]{5,25})/?', p.path)
    if not m:
        m = re.fullmatch(r'/[^/]+/videos/(?:[^/]+/)?([0-9]{5,25})/?', p.path)
    return 'fb:' + m[1] if m else ''
