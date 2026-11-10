"""library/linkinfo.py (projects/link-preview/plans/01-reader.md): the Python copy of the phone's link
rules (web/src/mobile/linkinfo.ts) over the same recorded pages, the two copies compared under Node, the
refusal of addresses on this PC or the home network, the page text for Describe and the thumbnail
format. No network: every fetch is a recorded page or a stub.
Run: py -m unittest tests.test_linkinfo -v"""
import io
import json
import socket
import unittest
import urllib.error
import urllib.request
from unittest import mock
import tempfile
from pathlib import Path
from types import SimpleNamespace

from library import linkinfo
from tests import test_phone_js
from tests.test_phone_linkinfo import LINKS, PAGES
from server import job_kinds
from knowledge import tasks
from tests.auth_client import TestClient

from server.app import create_app


def recorded(asked=None):
    def get(url):
        if asked is not None:
            asked.append(url)
        p = PAGES.get(url)
        return (p[0], p[1]) if p else (404, '')
    return get


def png(w=1200, h=630) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (20, 20, 200)).save(buf, 'PNG')
    return buf.getvalue()


class RulesTest(unittest.TestCase):
    """The same expectations as tests/test_phone_linkinfo.py LinkInfoTest, on the Python copy."""

    def test_site_rules_over_recorded_pages(self):
        asked = []
        got = {u: linkinfo.read(u, recorded(asked)) for u in LINKS}
        self.assertEqual(got[LINKS[0]], {'title': 'TrueDepth - Blender Addon Overview', 'creator': 'Lewis Martin', 'desc': '',
                                         'image': 'https://i.ytimg.com/vi/BZWNXoNac6o/hqdefault.jpg'})
        self.assertEqual(got[LINKS[1]], {'title': '', 'creator': 'Kushank Aggarwal', 'desc': '#passiveincome #sidehustle',
                                         'image': 'https://www.instagram.com/p/CPO5dlEj8F7/media/?size=m'})
        self.assertEqual(got[LINKS[2]], {'title': '', 'creator': 'Daniel Shaw Comedy',
                                         'desc': 'The amount of cool stuff my kid misses on drives is astronomical.',
                                         'image': 'https://scontent.example/fb.jpg?a=1&b=2'})
        self.assertEqual(got[LINKS[3]], {'title': 'Homemade slingshot .', 'creator': 'gex109', 'desc': '', 'image': ''})
        self.assertEqual(got[LINKS[4]], {'title': 'A plain page & more', 'creator': '', 'desc': 'Single quoted', 'image': ''})
        self.assertIsNone(got[LINKS[5]])
        self.assertEqual(asked, [list(PAGES)[0], LINKS[1], LINKS[2], list(PAGES)[3], LINKS[4], LINKS[5]])

    def test_ids_codes_and_pictures(self):
        self.assertEqual([linkinfo.youtube_id('https://www.youtube.com/shorts/abcDEF12345'),
                          linkinfo.youtube_id('https://www.youtube.com/watch?v=x')], ['abcDEF12345', ''])
        self.assertEqual([linkinfo.instagram_code('https://www.instagram.com/reel/NEW1/?igsh=zz'),
                          linkinfo.instagram_code('https://www.instagram.com/p/Cx_9-a/')], ['NEW1', 'Cx_9-a'])
        self.assertEqual([linkinfo.image_url(u) for u in ('https://www.instagram.com/reel/DeZwNTwCCsj/', 'https://youtu.be/BZWNXoNac6o',
                                                          'https://example.com/post', 'https://www.instagram.com/')],
                         ['https://www.instagram.com/p/DeZwNTwCCsj/media/?size=m',
                          'https://i.ytimg.com/vi/BZWNXoNac6o/hqdefault.jpg', '', ''])

    def test_no_host_and_unknown_entities(self):
        self.assertIsNone(linkinfo.read('not a link', recorded()))
        self.assertEqual(linkinfo.unescape('a &amp; b &bogus; &#x41;&#66;'), 'a & b &bogus; AB')

    def test_ytdlp_first_and_absolute(self):
        self.assertTrue(linkinfo.ytdlp_first('https://www.facebook.com/reel/1'))
        self.assertTrue(linkinfo.ytdlp_first('https://m.youtube.com/watch?v=abcdefgh'))
        self.assertTrue(linkinfo.ytdlp_first('https://old.reddit.com/r/a'))
        self.assertFalse(linkinfo.ytdlp_first('https://isoglow.dev/'))
        self.assertFalse(linkinfo.ytdlp_first('https://notfacebook.com/'))
        self.assertEqual(linkinfo.absolute('https://isoglow.dev/a/b', '/og.png'), 'https://isoglow.dev/og.png')
        self.assertEqual(linkinfo.absolute('https://isoglow.dev/', 'javascript:alert(1)'), '')
        self.assertEqual(linkinfo.absolute('https://isoglow.dev/', ''), '')


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class ParityTest(unittest.TestCase):
    """linkinfo.py and linkinfo.ts give the same answer for the same pages."""

    def test_both_copies_agree(self):
        ts = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const {{ linkInfo, imageUrl }} = await import('./web/src/mobile/linkinfo.ts')
            const pages = {json.dumps(PAGES)}
            const get = async u => {{ const p = pages[u]; return p ? {{ status: p[0], text: p[1] }} : {{ status: 404, text: '' }} }}
            const out = {{}}
            for (const u of {json.dumps(LINKS)}) out[u] = await linkInfo(u, get)
            const pics = {{}}
            for (const u of {json.dumps(LINKS)}) pics[u] = imageUrl(u)
            console.log(JSON.stringify({{ out, pics }}))
        """))
        py = {u: linkinfo.read(u, recorded()) for u in LINKS}
        self.assertEqual(ts['out'], py)
        self.assertEqual(ts['pics'], {u: linkinfo.image_url(u) for u in LINKS})


class LocalAddressTest(unittest.TestCase):
    def test_this_pc_and_the_home_network_are_refused(self):
        for url in ('http://127.0.0.1:18765/api/items', 'http://localhost/', 'http://192.168.1.10/', 'http://10.0.0.1/',
                    'http://172.16.0.1/', 'http://[::1]/', 'http://[::ffff:127.0.0.1]/', 'http://169.254.169.254/',
                    'http://0.0.0.0/', 'http://100.64.0.1/', 'file:///C:/Windows/win.ini', 'ftp://example.com/', 'not a link', ''):
            self.assertFalse(linkinfo.public(url), url)

    def test_a_public_address_is_allowed(self):
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        with mock.patch.object(linkinfo.socket, 'getaddrinfo', return_value=fake):
            self.assertTrue(linkinfo.public('https://example.com/'))

    def test_a_name_with_one_local_address_is_refused(self):
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with mock.patch.object(linkinfo.socket, 'getaddrinfo', return_value=fake):
            self.assertFalse(linkinfo.public('https://example.com/'))

    def test_a_redirect_to_this_pc_is_refused(self):
        req = urllib.request.Request('https://example.com/')
        with self.assertRaises(linkinfo.SecurityRefusal):
            linkinfo._Redirects().redirect_request(req, None, 302, 'Found', {}, 'http://127.0.0.1:18765/api/items')

    def test_a_refused_address_is_never_requested(self):
        with mock.patch.object(linkinfo._OPENER, 'open') as op:
            with self.assertRaises(linkinfo.SecurityRefusal):
                linkinfo.fetch_text('http://127.0.0.1:18765/api/items')
            with self.assertRaises(linkinfo.SecurityRefusal):
                linkinfo.image('http://192.168.1.1/a.png')
        op.assert_not_called()


class FetchTest(unittest.TestCase):
    def _answer(self, status=200, body=b'', ctype='text/html; charset=utf-8'):
        r = mock.MagicMock()
        r.status = status
        r.read.side_effect = lambda n=-1: body[:n] if n and n > 0 else body
        msg = mock.Mock()
        msg.get_content_charset.return_value = ctype.split('charset=')[1] if 'charset=' in ctype else None
        msg.get_content_type.return_value = ctype.split(';')[0]
        r.headers = msg
        r.__enter__.return_value = r
        return r

    def test_fetch_text_sends_the_plain_user_agent(self):
        with mock.patch.object(linkinfo, 'public', return_value=True), \
             mock.patch.object(linkinfo._OPENER, 'open', return_value=self._answer(body='<title>é</title>'.encode())) as op:
            self.assertEqual(linkinfo.fetch_text('https://example.com/'), (200, '<title>é</title>'))
        req = op.call_args[0][0]
        self.assertEqual(req.get_header('User-agent'), 'Brainamon/1.0 (link preview)')

    def test_an_http_error_gives_its_status(self):
        err = urllib.error.HTTPError('https://example.com/', 404, 'Not Found', {}, None)
        with mock.patch.object(linkinfo, 'public', return_value=True), mock.patch.object(linkinfo._OPENER, 'open', side_effect=err):
            self.assertEqual(linkinfo.fetch_text('https://example.com/'), (404, ''))

    def test_image_only_takes_pictures(self):
        with mock.patch.object(linkinfo, 'public', return_value=True), \
             mock.patch.object(linkinfo._OPENER, 'open', return_value=self._answer(body=b'<html>', ctype='text/html')):
            self.assertEqual(linkinfo.image('https://example.com/og.png'), b'')
        with mock.patch.object(linkinfo, 'public', return_value=True), \
             mock.patch.object(linkinfo._OPENER, 'open', return_value=self._answer(body=png(), ctype='image/png')):
            self.assertTrue(linkinfo.image('https://example.com/og.png').startswith(b'\x89PNG'))


class PageTextTest(unittest.TestCase):
    PAGE = ('<html><head><title>T</title><script>var x = "no";</script><style>p{}</style></head><body>'
            '<nav>Menu Home</nav><header>Logo</header><main><h1>Make icons glow</h1><p>Pick a shape &amp; a colour.</p>'
            '<button>Buy</button></main><footer>Copyright</footer></body></html>')

    def test_visible_text_only(self):
        self.assertEqual(linkinfo.text_of(self.PAGE), 'Make icons glow Pick a shape & a colour.')

    def test_page_text_needs_a_page(self):
        self.assertEqual(linkinfo.page_text('https://e.com/', lambda u: (200, self.PAGE)), 'Make icons glow Pick a shape & a colour.')
        self.assertEqual(linkinfo.page_text('https://e.com/', lambda u: (404, '')), '')
        self.assertEqual(linkinfo.page_text('https://e.com/', lambda u: (0, '')), '')

    def test_the_text_is_capped(self):
        long = '<p>' + 'word ' * 5000 + '</p>'
        self.assertLessEqual(len(linkinfo.text_of(long)), linkinfo.MAX_TEXT)

    def test_to_jpeg_fits_600(self):
        from PIL import Image
        img = Image.open(io.BytesIO(linkinfo.to_jpeg(png())))
        self.assertEqual((img.format, max(img.size)), ('JPEG', 600))


def _job(data_dir, force=True):
    return SimpleNamespace(ctx={'data_dir': str(data_dir), 'lookups': []}, force=force, step=mock.Mock())


SITE = {'title': 'iso-glow', 'creator': '', 'desc': 'A Claude skill for isometric drawings.', 'image': '/img/tower.jpg'}
YT_OK = {'filename': 'thumb.jpg', 'source': 'yt-dlp', 'caption': 'Reel text', 'error': ''}


class FetchLinkInfoTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)

    def run_item(self, url, read=None, image=b'', yt=None, available=True):
        yt = yt or mock.Mock(return_value=dict(job_kinds._NO_INFO))
        read = read if isinstance(read, mock.Mock) else mock.Mock(return_value=read)
        with mock.patch.object(linkinfo, 'read', read), mock.patch.object(linkinfo, 'image', return_value=image) as img, \
             mock.patch.object(job_kinds.ytdlp, 'fetch_thumbnail', yt), \
             mock.patch.object(job_kinds.ytdlp, 'available', return_value=available):
            r = job_kinds._thumb_run(_job(self.data), {'id': 5, 'url': url})
        return r, read, yt, img

    def test_an_ordinary_site_uses_its_page_and_skips_yt_dlp(self):
        r, _, yt, img = self.run_item('https://isoglow.dev/', SITE, png())
        yt.assert_not_called()
        img.assert_called_once_with('https://isoglow.dev/img/tower.jpg')        # made absolute
        self.assertEqual((r['filename'], r['source'], r['title'], r['caption']),
                         ('thumb.jpg', 'web', 'iso-glow', 'A Claude skill for isometric drawings.'))
        self.assertTrue((self.data / 'items' / '5' / 'thumb.jpg').is_file())

    def test_fetch_reports_the_page_step(self):
        job = _job(self.data)
        with mock.patch.object(job_kinds, '_web_info', return_value={**job_kinds._NO_INFO, 'title': 'Page'}):
            job_kinds._thumb_run(job, {'id': 5, 'url': 'https://example.com/'})
        job.step.assert_called_once_with(5, 'Reading the page and its preview image…')

    def test_an_ordinary_site_does_not_enter_generic_downloader(self):
        yt = mock.Mock(return_value={'filename': 'thumb.jpg', 'source': 'yt-dlp', 'caption': '', 'error': ''})
        r, _, yt, _ = self.run_item('https://isoglow.dev/', dict(SITE, image=''), b'', yt)
        yt.assert_not_called()
        self.assertEqual((r['source'], r['caption'], r['title']), ('', SITE['desc'], 'iso-glow'))

    def test_facebook_tries_yt_dlp_first_and_stops_when_it_has_everything(self):
        r, read, yt, _ = self.run_item('https://www.facebook.com/reel/1', SITE, b'', mock.Mock(return_value=YT_OK))
        read.assert_not_called()
        self.assertEqual((r['source'], r['caption']), ('yt-dlp', 'Reel text'))

    def test_without_yt_dlp_a_reel_still_gets_the_page(self):
        fb = {'title': '', 'creator': 'Daniel Shaw Comedy', 'desc': 'Kid misses stuff', 'image': 'https://scontent.example/fb.jpg'}
        r, _, yt, _ = self.run_item('https://www.facebook.com/reel/1', fb, png(), available=False)
        yt.assert_not_called()
        self.assertEqual((r['source'], r['creator'], r['error']), ('web', 'Daniel Shaw Comedy', job_kinds.ytdlp.NOT_FOUND))

    def test_youtube_falls_back_to_the_page_when_yt_dlp_fails(self):
        bad = mock.Mock(return_value={'filename': '', 'source': '', 'caption': '', 'error': 'yt-dlp timed out'})
        yt_info = {'title': 'TrueDepth', 'creator': 'Lewis Martin', 'desc': '', 'image': 'https://i.ytimg.com/vi/x/hqdefault.jpg'}
        r, _, _, _ = self.run_item('https://youtu.be/BZWNXoNac6o', yt_info, png(), bad)
        self.assertEqual((r['source'], r['title'], r['error']), ('web', 'TrueDepth', 'yt-dlp timed out'))

    def test_nothing_anywhere_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.run_item('https://isoglow.dev/', None, b'', available=False)

    def test_prepare_no_longer_needs_yt_dlp(self):
        db = mock.Mock(data_dir=self.data)
        db.get_setting.return_value = ''
        db.get_items_by_ids.return_value = [{'id': 1, 'url': 'https://www.facebook.com/reel/1', 'thumb_path': ''}]
        with mock.patch.object(job_kinds.ytdlp, 'available', return_value=False):
            self.assertEqual(len(job_kinds._thumb_prepare(db, SimpleNamespace(ctx={}, ids=[1], force=False))), 1)

    def test_persist_follows_the_phone_rule(self):
        db = mock.Mock()
        r = dict(job_kinds._NO_INFO, filename='thumb.jpg', source='web', caption='Caption', title='Title', creator='Site')
        db.get_item.return_value = {'url': 'https://isoglow.dev/', 'description': 'https://isoglow.dev/', 'short_desc': '', 'creator': ''}
        job_kinds._thumb_persist(db, {'id': 5}, r, _job(self.data, force=False))
        db.update_item.assert_called_once_with(5, {'thumb_path': 'thumb.jpg', 'thumb_source': 'web', 'description': 'Caption',
                                                   'short_desc': 'Title', 'creator': 'Site'})
        db.reset_mock()
        db.get_item.return_value = {'url': 'https://isoglow.dev/', 'description': 'Mine', 'short_desc': 'My title', 'creator': 'Me'}
        job_kinds._thumb_persist(db, {'id': 5}, r, _job(self.data, force=False))
        db.update_item.assert_called_once_with(5, {'thumb_path': 'thumb.jpg', 'thumb_source': 'web'})   # nothing typed is replaced
        db.reset_mock()
        job_kinds._thumb_persist(db, {'id': 5}, r, _job(self.data, force=True))
        db.update_item.assert_called_once_with(5, {'thumb_path': 'thumb.jpg', 'thumb_source': 'web', 'description': 'Caption'})

    def test_persist_without_a_picture_saves_the_text_and_reports(self):
        db = mock.Mock()
        db.get_item.return_value = {'url': 'https://isoglow.dev/', 'description': '', 'short_desc': '', 'creator': ''}
        with self.assertRaises(RuntimeError):
            job_kinds._thumb_persist(db, {'id': 5}, dict(job_kinds._NO_INFO, caption='C', error='The page has no picture'), _job(self.data))
        db.update_item.assert_called_once_with(5, {'description': 'C'})


class DescribeFromThePageTest(unittest.TestCase):
    def prompt(self, item, text):
        got = {}

        def fake(provider, model, prompt='', images=None, max_tokens=0, **kw):
            got['prompt'] = prompt
            return 'ok'

        job = SimpleNamespace(ctx={'provider': 'anthropic', 'model': 'm', 'data_dir': ''})
        page_text = mock.Mock(return_value=text)
        with mock.patch.object(tasks.ai_client, 'complete_vision', fake), mock.patch.object(linkinfo, 'page_text', page_text):
            job_kinds._describe_run(job, item)
        return got['prompt'], page_text

    def test_an_ordinary_site_sends_its_text_as_quoted_data(self):
        p, page_text = self.prompt({'id': 1, 'url': 'https://isoglow.dev/', 'description': 'https://isoglow.dev/'},
                                   'Isometric figures that light up.')
        page_text.assert_called_once_with('https://isoglow.dev/')
        self.assertIn('"""\nIsometric figures that light up.\n"""', p)
        self.assertIn('not instructions to you', p)

    def test_social_links_and_analyzed_items_do_not_read_the_page(self):
        _, page_text = self.prompt({'id': 2, 'url': 'https://www.facebook.com/reel/1', 'description': 'A caption'}, 'x')
        page_text.assert_not_called()
        _, page_text = self.prompt({'id': 3, 'url': 'https://isoglow.dev/', 'analysis_done': 1, 'transcript': 'words'}, 'x')
        page_text.assert_not_called()

    def test_an_unreadable_page_keeps_todays_prompt(self):
        item = {'id': 4, 'url': 'https://isoglow.dev/', 'description': 'd'}
        p, _ = self.prompt(item, '')
        got = {}

        def fake(provider, model, prompt='', images=None, max_tokens=0, **kw):
            got['prompt'] = prompt
            return 'ok'

        with mock.patch.object(tasks.ai_client, 'complete_vision', fake):
            tasks.describe_item(item, 'anthropic', 'm', '')
        self.assertEqual(p, got['prompt'])
        self.assertIn('This is a web link.', p)

    def test_the_page_text_is_capped_at_3000(self):
        p, _ = self.prompt({'id': 5, 'url': 'https://isoglow.dev/'}, 'a' * 5000)
        self.assertIn('a' * 3000 + '\n"""', p)
        self.assertNotIn('a' * 3001, p)


class PreviewRouteTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        data = Path(td.name)
        app = create_app(data_dir=data, cloud_dir=data / 'test-cloud', port=8765, web_dist=data / 'nope', cards_dir=data / 'nope')
        self.cl = TestClient(app, base_url='http://127.0.0.1:8765')
        self.cl.__enter__()
        self.addCleanup(self.cl.__exit__, None, None, None)

    def post(self, url, headers=None):
        return self.cl.post('/api/link/preview', json={'url': url}, headers={'X-CM': '1'} if headers is None else headers)

    def test_a_page_is_read_and_its_picture_made_absolute(self):
        with mock.patch.object(linkinfo, 'read', return_value=dict(SITE)) as read:
            r = self.post('isoglow.dev')
        read.assert_called_once_with('https://isoglow.dev')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {**SITE, 'image': 'https://isoglow.dev/img/tower.jpg', 'asked': 'isoglow.dev',
                                    'url': 'https://isoglow.dev', 'found': True})

    def test_a_silent_page_is_not_found(self):
        with mock.patch.object(linkinfo, 'read', return_value=None):
            r = self.post('https://isoglow.dev/')
        self.assertEqual(r.json()['found'], False)
        self.assertEqual(r.json()['title'], '')

    def test_facebook_is_read_too(self):
        with mock.patch.object(linkinfo, 'read', return_value=None) as read:
            self.post('https://www.facebook.com/reel/1')
        read.assert_called_once()

    def test_no_link_and_no_header(self):
        self.assertEqual(self.post('hello there').status_code, 400)
        self.assertEqual(self.post('https://isoglow.dev/', headers={}).status_code, 403)
