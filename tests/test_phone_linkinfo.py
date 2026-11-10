"""Link details read on the phone with no PC (projects/mobile-app/plans/09-link-details.md): the
per-site rules over recorded pages, the overlay that shows them on a phone link, and the PC applying
a `details` change (fills only what is empty)."""
import base64
import io
import json
import unittest

from tests import test_phone_js
from tests.test_phone_mirror import ChangeIntakeTest

IG = ('<meta property="og:title" content="Kushank Aggarwal on Instagram: &quot;#passiveincome #sidehustle&quot;" />'
      '<meta property="og:description" content="60 likes, 5 comments - digitalsamaritan on May 23, 2021: '
      '&quot;#passiveincome #sidehustle&quot;. " />')
FB = ('<meta property="og:title" content="51&#xa0;k views &#xb7; 6.9&#xa0;k reactions | The amount of cool stuff | Daniel Shaw Comedy" />'
      '<meta property="og:description" content="The amount of cool stuff my kid misses on drives is astronomical." />'
      '<meta content="https://scontent.example/fb.jpg?a=1&amp;b=2" property="og:image" />')
WEB = "<html><head><title>A plain page &amp; more</title><meta name=\"og:description\" content='Single quoted'></head></html>"
PAGES = {
    'https://www.youtube.com/oembed?format=json&url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DBZWNXoNac6o':
        [200, '{"title":"TrueDepth - Blender Addon Overview","author_name":"Lewis Martin"}'],
    'https://www.instagram.com/digitalsamaritan/reel/CPO5dlEj8F7/': [200, IG],
    'https://www.facebook.com/reel/1649152786903188/': [200, FB],
    'https://www.reddit.com/oembed?url=https%3A%2F%2Fwww.reddit.com%2Fr%2Foddlysatisfying%2Fcomments%2F1rk3cj1%2Fhomemade_slingshot%2F':
        [200, '{"title":"Homemade slingshot .","author_name":"gex109"}'],
    'https://example.com/post': [200, WEB],
}
LINKS = ['https://youtu.be/BZWNXoNac6o?si=share', 'https://www.instagram.com/digitalsamaritan/reel/CPO5dlEj8F7/',
         'https://www.facebook.com/reel/1649152786903188/',
         'https://www.reddit.com/r/oddlysatisfying/comments/1rk3cj1/homemade_slingshot/',
         'https://example.com/post', 'https://example.com/gone']


def tiny_jpeg_b64() -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 80, 40)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue()).decode('ascii')


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class LinkInfoTest(unittest.TestCase):
    def test_site_rules_over_recorded_pages(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const {{ linkInfo, youtubeId, instagramCode, imageUrl }} = await import('./web/src/mobile/linkinfo.ts')
            const pages = {json.dumps(PAGES)}
            const asked = []
            const get = async u => {{ asked.push(u); const p = pages[u]; return p ? {{ status: p[0], text: p[1] }} : {{ status: 404, text: '' }} }}
            const out = {{}}
            for (const u of {json.dumps(LINKS)}) out[u] = await linkInfo(u, get)
            console.log(JSON.stringify({{ out, asked,
              pics: ['https://www.instagram.com/reel/DeZwNTwCCsj/', 'https://youtu.be/BZWNXoNac6o', 'https://example.com/post', 'https://www.instagram.com/'].map(imageUrl),
              ids: [youtubeId('https://www.youtube.com/shorts/abcDEF12345'), youtubeId('https://www.youtube.com/watch?v=x')],
              codes: [instagramCode('https://www.instagram.com/reel/NEW1/?igsh=zz'), instagramCode('https://www.instagram.com/p/Cx_9-a/')] }}))
        """))
        got = out['out']
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
        self.assertEqual(out['asked'], [list(PAGES)[0], LINKS[1], LINKS[2], list(PAGES)[3], LINKS[4], LINKS[5]])
        self.assertEqual(out['ids'], ['abcDEF12345', ''])
        self.assertEqual(out['codes'], ['NEW1', 'Cx_9-a'])
        self.assertEqual(out['pics'], ['https://www.instagram.com/p/DeZwNTwCCsj/media/?size=m',
                                       'https://i.ytimg.com/vi/BZWNXoNac6o/hqdefault.jpg', '', ''])

    def test_overlay_shows_details_on_phone_links_only(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes(), uid = 'ab'.repeat(16), pc = 'cd'.repeat(16)
            const l = await c.add({ op: 'link', uid, url: 'https://www.instagram.com/reel/X1/', note: 'mine', category: '' })
            l.id = 5                                 // Node has no IndexedDB: give the entry its id by hand
            const d = await c.add({ op: 'details', uid, title: '', creator: 'Kushank', desc: 'First line\\nsecond', thumb: 'AAAA' })
            await c.add({ op: 'details', uid: pc, title: 'Not a phone link', creator: 'X', desc: '', thumb: 'AAAA' })
            const pcRow = { id: 7, uid: pc, title: 'PC title', creator: 'PC', type: 'Reel', cat: 'X', tags: '', desc: '',
              url: 'https://x.test/7', src: 'web', thumb: false, ai: true, an: false, nd: 0, fav: false, created: 1, tv: 3 }
            const rows = c.overlay([pcRow])
            console.log(JSON.stringify({ rows: rows.map(r => [r.id, r.title, r.creator, r.thumb, r.desc]), tv: rows[0].tv === d.at, pcTv: rows[1].tv }))
        """))
        # the card's description is the caption, as the PC's row (description), not the link's note
        self.assertEqual(out['rows'], [[-5, 'First line', 'Kushank', True, 'First line\nsecond'], [7, 'PC title', 'PC', False, '']])
        self.assertTrue(out['tv'])
        self.assertEqual(out['pcTv'], 3)

    def test_overlay_card_text_follows_the_pc_row(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const c = new Changes(), a = 'ab'.repeat(16), b = 'ef'.repeat(16), d = '12'.repeat(16), pc = 'cd'.repeat(16)
            for (const [i, uid, url] of [[1, a, 'https://x.test/a'], [2, b, 'https://x.test/b'], [3, d, 'https://x.test/d']]) {
              const l = await c.add({ op: 'link', uid, url, note: 'my note', category: '' }); l.id = i
            }
            await c.add({ op: 'details', uid: a, title: '', creator: '', desc: 'first caption', thumb: '' })
            await c.add({ op: 'details', uid: d, title: '', creator: '', desc: 'x'.repeat(300), thumb: '' })      // cut to the snippet
            await c.add({ op: 'details', uid: b, title: '', creator: '', desc: '', thumb: '' })       // no caption: the note stays
            await c.add({ op: 'edit', uid: a, fields: { ai_desc: 'AI summary' }, was: { ai_desc: '' } })
            await c.add({ op: 'details', uid: a, title: '', creator: '', desc: 'late caption', thumb: '' })   // never beats the AI text
            await c.add({ op: 'edit', uid: pc, fields: { ai_desc: 'Phone made this' }, was: { ai_desc: '' } })
            const pcRow = { id: 7, uid: pc, title: 'PC', creator: 'PC', type: 'Reel', cat: 'X', tags: '', desc: 'old',
              url: 'https://x.test/7', src: 'web', thumb: true, ai: false, an: false, nd: 0, fav: false, created: 1, tv: 3 }
            const rows = c.overlay([pcRow])
            console.log(JSON.stringify(rows.map(r => [r.id, r.desc.length > 100 ? r.desc.length : r.desc, r.ai])))
        """))
        self.assertEqual(out, [[-3, 200, False], [-2, 'my note', False], [-1, 'AI summary', True], [7, 'Phone made this', True]])


class DetailsIntakeTest(ChangeIntakeTest):
    def test_details_fill_empties_and_write_the_thumbnail(self):
        new_uid = 'ef' * 16
        url = 'https://www.instagram.com/reel/DETAILS1/'
        self.phone([
            {'op': 'link', 'uid': new_uid, 'url': url, 'note': '', 'category': ''},
            {'op': 'details', 'uid': new_uid, 'title': '', 'creator': 'Kushank Aggarwal', 'desc': 'Caption from the phone',
             'thumb': tiny_jpeg_b64()},
        ])
        self.assertTrue(self.svc._intake())
        row = self.writer.read(lambda db: dict(db.conn.execute('SELECT * FROM items WHERE uid = ?', (new_uid,)).fetchone()))
        self.assertEqual((row['description'], row['creator'], row['thumb_path'], row['thumb_source']),
                         ('Caption from the phone', 'Kushank Aggarwal', 'thumb.jpg', 'phone'))
        self.assertTrue((self.data / 'items' / str(row['id']) / 'thumb.jpg').is_file())

    def test_details_never_overwrite(self):
        i = self.ids[0]
        before = self.item(i)
        self.phone([{'op': 'details', 'uid': self.uid[i], 'title': 'Phone title', 'creator': 'Phone', 'desc': 'Phone caption', 'thumb': ''}])
        self.assertTrue(self.svc._intake())
        after = self.item(i)
        for k in ('creator', 'thumb_path'):
            if before[k]:
                self.assertEqual(after[k], before[k])
        if before['description'] not in ('', before['url']):
            self.assertEqual(after['description'], before['description'])

    def test_a_damaged_thumbnail_skips_only_that_change(self):
        new_uid = 'aa' * 16
        self.phone([
            {'op': 'link', 'uid': new_uid, 'url': 'https://example.com/damaged', 'note': '', 'category': ''},
            {'op': 'details', 'uid': new_uid, 'title': 'T', 'creator': '', 'desc': '', 'thumb': 'not base64 at all!'},
        ])
        self.assertTrue(self.svc._intake())
        row = self.writer.read(lambda db: dict(db.conn.execute('SELECT * FROM items WHERE uid = ?', (new_uid,)).fetchone()))
        self.assertEqual(row['url'], 'https://example.com/damaged')
        self.assertEqual(row['thumb_path'], '')


def load_tests(loader, tests, pattern):
    # only this module's tests: DetailsIntakeTest borrows ChangeIntakeTest's set-up, not its tests
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(LinkInfoTest))
    for name in ('test_details_fill_empties_and_write_the_thumbnail', 'test_details_never_overwrite',
                 'test_a_damaged_thumbnail_skips_only_that_change'):
        suite.addTest(DetailsIntakeTest(name))
    return suite
