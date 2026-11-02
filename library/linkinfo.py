"""What a link's own page says: a title, the creator, the caption and a picture address, read with the
standard library (no LLM, no package). A Python copy of web/src/mobile/linkinfo.ts, the phone's link
details (projects/mobile-app/plans/09-link-details.md): the same per-site rules (YouTube and Reddit
oEmbed, Instagram and Facebook og: tags read with a plain User-Agent, every other site's og: tags and
<title>), checked against the same recorded pages by tests/test_linkinfo.py. Change a rule in both files.

The PC adds what the phone does not need (projects/link-preview/PLAN.md): the fetch itself
(fetch_text), which refuses addresses on this PC or the home network (the Brainamon API on 127.0.0.1
has no login) before the request and on every redirect; the picture download (image); the page's
visible text for Describe (page_text); which tool Fetch link info tries first (ytdlp_first); the
thumbnail format (to_jpeg).

Nothing here raises for a bad page or a network problem: read() answers None, image() b'',
page_text() ''. Not covered: DNS rebinding (a name that changes address between the check and the
request)."""
import http.client
import io
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from library.public_http import HTTPConnection, HTTPSConnection, SecurityRefusal

UA = 'Brainamon/1.0 (link preview)'   # = web/src/mobile/native.ts LINK_UA: Facebook answers a browser's with HTTP 400
TIMEOUT = 10                         # seconds per request
MAX_PAGE = 1024 * 1024               # bytes of a page read (the og: tags are in its head)
MAX_IMAGE = 8 * 1024 * 1024
MAX_TEXT = 4000                      # characters of visible text kept for Describe
NONE = {'title': '', 'creator': '', 'desc': '', 'image': ''}

# Fetch link info: yt-dlp first on these (full captions, cookies), the page reader first everywhere else
YTDLP_FIRST = ('facebook.com', 'fb.watch', 'fb.com', 'instagram.com', 'youtube.com', 'youtu.be', 'tiktok.com',
               'reddit.com', 'redd.it', 'x.com', 'twitter.com', 'vimeo.com')

_ENT = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': ' '}


# ── the rules (linkinfo.ts) ────────────────────────────────────────────────────
def unescape(s: str) -> str:
    def one(m):
        e = m.group(1)
        if e[0] != '#':
            return _ENT.get(e.lower(), m.group(0))
        try:
            return chr(int(e[2:], 16) if e[1] in 'xX' else int(e[1:]))
        except (ValueError, OverflowError):
            return ''
    return re.sub(r'&(#[xX][0-9a-fA-F]+|#\d+|[a-zA-Z]+);', one, s, flags=re.A)


def meta(html: str, key: str) -> str:
    """One <meta property|name="key" content="..."> value, attributes in either order."""
    tag = re.search(r'<meta\b[^>]*?\b(?:property|name)\s*=\s*["\']' + re.escape(key) + r'["\'][^>]*>', html, re.I)
    if not tag:
        return ''
    v = re.search(r'\bcontent\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag.group(0), re.I)
    if not v:
        return ''
    return unescape(v.group(1) if v.group(1) is not None else (v.group(2) or '')).strip()


def host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url or '').hostname or '').lower()
    except ValueError:
        return ''


def _on(h: str, *names: str) -> bool:
    return any(h == n or h.endswith('.' + n) for n in names)


def _str(j, key: str) -> str:
    v = j.get(key) if isinstance(j, dict) else None
    return v.strip() if isinstance(v, str) else ''


def _json(status: int, text: str):
    if status != 200:
        return None
    try:
        j = json.loads(text)
    except ValueError:
        return None
    return j if isinstance(j, dict) else None


def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe="-_.!~*'()")      # = encodeURIComponent


def youtube_id(url: str) -> str:
    try:
        u = urllib.parse.urlsplit(url or '')
        h = (u.hostname or '').lower()
    except ValueError:
        return ''
    if not h:
        return ''
    if _on(h, 'youtu.be'):
        parts = u.path.split('/')
        i = parts[1] if len(parts) > 1 else ''
    else:
        i = (urllib.parse.parse_qs(u.query).get('v') or [''])[0]
        if not i:
            m = re.match(r'/(?:shorts|embed|live)/([\w-]+)', u.path, re.A)
            i = m.group(1) if m else ''
    return i if re.fullmatch(r'[\w-]{6,20}', i or '', re.A) else ''


def instagram_code(url: str) -> str:
    m = re.search(r'instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)', url or '', re.I | re.A)
    return m.group(1) if m else ''


def image_url(url: str) -> str:
    """A picture's address that needs no page: YouTube and Instagram; '' for every other site."""
    h = host(url)
    if _on(h, 'youtube.com', 'youtu.be'):
        i = youtube_id(url)
        return f'https://i.ytimg.com/vi/{i}/hqdefault.jpg' if i else ''
    if _on(h, 'instagram.com'):
        c = instagram_code(url)
        return f'https://www.instagram.com/p/{c}/media/?size=m' if c else ''
    return ''


def instagram_text(og_desc: str, og_title: str) -> dict:
    """og:description `60 likes, 5 comments - handle on May 23, 2021: "caption". `,
    og:title `Name on Instagram: "caption"`."""
    m = re.search(r':\s*"([\s\S]*)"\s*\.?\s*\Z', og_desc) or re.search(r':\s*"([\s\S]*)"\s*\Z', og_title)
    desc = m.group(1) if m else ''
    c = re.match(r'(.+?) on Instagram\b', og_title) or re.search(r' - ([\w.]+) on ', og_desc, re.A)
    return {'creator': (c.group(1) if c else '').strip(), 'desc': desc.strip()}


def facebook_creator(og_title: str) -> str:
    """og:title "<views> · <reactions> | caption | Creator" (the numbers in the viewer's language)."""
    parts = og_title.split(' | ')
    return parts[-1].strip() if len(parts) >= 3 else ''


def read(url: str, get=None):
    """linkInfo: {'title', 'creator', 'desc', 'image'} or None. `get(url) -> (status, text)`;
    fetch_text when not given (tests pass recorded pages)."""
    get = get or fetch_text
    h = host(url)
    if not h:
        return None
    if _on(h, 'youtube.com', 'youtu.be'):
        i = youtube_id(url)
        if not i:
            return None
        j = _json(*get('https://www.youtube.com/oembed?format=json&url=' + _enc('https://www.youtube.com/watch?v=' + i)))
        return {**NONE, 'title': _str(j, 'title'), 'creator': _str(j, 'author_name'),
                'image': f'https://i.ytimg.com/vi/{i}/hqdefault.jpg'}
    if _on(h, 'reddit.com', 'redd.it'):
        j = _json(*get('https://www.reddit.com/oembed?url=' + _enc(url)))
        return {**NONE, 'title': _str(j, 'title'), 'creator': _str(j, 'author_name')} if j is not None else None
    status, text = get(url)
    page = text if status == 200 else ''
    if _on(h, 'instagram.com'):
        code = instagram_code(url)
        t = instagram_text(meta(page, 'og:description'), meta(page, 'og:title'))
        if not (code or t['desc']):
            return None
        return {**NONE, **t, 'image': f'https://www.instagram.com/p/{code}/media/?size=m' if code else ''}
    if not page:
        return None
    title, desc, image = meta(page, 'og:title'), meta(page, 'og:description'), meta(page, 'og:image')
    if _on(h, 'facebook.com', 'fb.watch'):
        return {'title': '', 'creator': facebook_creator(title), 'desc': desc, 'image': image} if desc or image else None
    m = re.search(r'<title[^>]*>([^<]*)</title>', page, re.I)
    out = {'title': title or unescape(m.group(1) if m else '').strip(), 'creator': meta(page, 'og:site_name'),
           'desc': desc, 'image': image}
    return out if out['title'] or out['desc'] or out['image'] else None


# ── the PC's additions ─────────────────────────────────────────────────────────
def ytdlp_first(url: str) -> bool:
    return _on(host(url), *YTDLP_FIRST)


def absolute(base: str, link: str) -> str:
    """A picture address from a page, made absolute; '' unless http(s)."""
    link = (link or '').strip()
    if not link:
        return ''
    u = urllib.parse.urljoin(base or '', link)
    return u if urllib.parse.urlsplit(u).scheme in ('http', 'https') else ''


def public(url: str) -> bool:
    """True when `url` is http(s) and every address its host resolves to is a public one."""
    try:
        p = urllib.parse.urlsplit(url or '')
        port = p.port
    except ValueError:
        return False
    if p.scheme not in ('http', 'https') or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, port or (443 if p.scheme == 'https' else 80), proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError):
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split('%')[0])
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            return False
    return bool(infos)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public(newurl):
            raise SecurityRefusal('Private redirect refused.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(HTTPConnection, req)


class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects, _HTTP, _HTTPS)


def _get(url: str, limit: int):
    """(status, body, charset, content type) or None (refused or no answer). At most `limit` bytes."""
    if not public(url):
        raise SecurityRefusal('Private or invalid destination refused.')
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en'})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            return r.status, r.read(limit), r.headers.get_content_charset(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        return e.code, b'', None, ''
    except SecurityRefusal:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        return None


def fetch_text(url: str):
    """The `get` read() uses on the PC: (status, text); (0, '') when refused or unreachable."""
    got = _get(url, MAX_PAGE)
    if not got:
        return 0, ''
    status, body, charset, _ = got
    try:
        return status, body.decode(charset or 'utf-8', errors='replace')
    except LookupError:                  # an unknown charset name
        return status, body.decode('utf-8', errors='replace')


def image(url: str) -> bytes:
    """The picture at `url` (absolute), or b'' when it cannot be read or is not a picture."""
    got = _get(url, MAX_IMAGE) if url else None
    if not got or got[0] != 200 or not (got[3].startswith('image/') or got[3] == 'application/octet-stream'):
        return b''
    return got[1]


# not visible text: skipped by page_text
_SKIP = {'script', 'style', 'noscript', 'svg', 'template', 'head', 'nav', 'header', 'footer', 'form', 'iframe',
         'select', 'button'}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.parts, self.n = 0, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and self.n < MAX_TEXT:
            s = data.strip()
            if s:
                self.parts.append(s)
                self.n += len(s) + 1


def text_of(html: str) -> str:
    """The visible text of an HTML page, one line, MAX_TEXT characters at most."""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass                             # a broken page keeps what was read before the break
    return ' '.join(' '.join(p.parts).split())[:MAX_TEXT]


def page_text(url: str, get=None) -> str:
    """The page's visible text for Describe; '' when it cannot be read."""
    status, text = (get or fetch_text)(url)
    return text_of(text) if status == 200 and text else ''


def to_jpeg(raw: bytes) -> bytes:
    """A thumbnail as the app stores them (Qt _upload_thumb: RGB, 600 px box, JPEG 82)."""
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    img.thumbnail((600, 600))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=82)
    return buf.getvalue()
