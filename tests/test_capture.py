"""Add to Brainamon's shared rules (web/src/lib/capture.ts, projects/note-organic-ui/plans/09-add-to-brainamon.md),
run under Node like tests/test_phone_js.py: where a capture starts, when Save is allowed and why not, what
a note gets (the section matches knowledge/filing.py), one picture at a time, the note picker. Skips
without Node 22.6+."""
import json
import re
import unittest
from pathlib import Path

from knowledge import filing, inbox
from tests.test_phone_js import TS_RESOLVE, _node_ok, node

SHARE_CASES = json.loads((Path(__file__).parent / 'fixtures' / 'share_links.json').read_text(encoding='utf-8'))['cases']


def run(body: str):
    return json.loads(node(TS_RESOLVE + "const c = await import('./web/src/lib/capture.ts')\n" + body))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class CaptureRulesTest(unittest.TestCase):
    def test_note_category_defaults_and_selected_category_help(self):
        self.assertEqual(run("""
            const d = c.newDraft('typed', 'Keep this thought')
            console.log(JSON.stringify([
              c.verdict(d, { thumb: false }).help,
              c.verdict({ ...d, category: 'Reading' }, { thumb: false }).help,
              c.verdict({ ...d, category: 'Reading', target: 'existing.md' }, { thumb: false }).help,
            ]))
        """), ['Creates a note in Inbox.', 'Creates a note in Reading.',
                 'Adds a section at the end of the note. Nothing already there changes.'])

    def test_a_lone_link_starts_on_library_everything_else_on_note(self):
        out = run("""
            const d = (text, over = {}) => ({ ...c.newDraft('share', text), ...over })
            const pic = { name: 'a.png', type: 'image/png', blob: null }
            console.log(JSON.stringify([
              c.defaultDest(d('https://www.instagram.com/reel/abc/?igsh=zzz')),
              c.defaultDest(d('Look at this https://example.com/a')),
              c.defaultDest(d('Remember to read this')),
              c.defaultDest(d('notes.md')),
              c.defaultDest(d('https://example.com/a', { pic })),
              c.destOf(d('https://example.com/a', { dest: 'note' })),
            ]))
        """)
        self.assertEqual(out, ['library', 'note', 'note', 'note', 'note', 'note'])

    def test_save_is_allowed_only_with_what_the_destination_needs(self):
        out = run("""
            const d = (text, over = {}) => ({ ...c.newDraft('typed', text), ...over })
            const png = { name: 'a.png', type: 'image/png', blob: null }
            const v = (x, caps = { thumb: false }) => { const r = c.verdict(x, caps); return [r.ok, r.help] }
            console.log(JSON.stringify([
              v(d('')),                                                          // 0 empty
              v(d('', { comment: 'only a comment' })),                           // 1 a comment alone is empty
              v(d('plain text', { dest: 'library' })),                           // 2 library needs a link
              v(d('Look https://example.com/a', { dest: 'library' })),           // 3 share text with a link works
              v(d('https://example.com/a', { dest: 'library' }), { thumb: false, known: 7 }), // 4 duplicate
              v(d('plain text')),                                                // 5 new note
              v(d('plain text', { target: 'x.md' })),                            // 6 append
              v(d('', { pic: png })),                                            // 7 picture, nothing read yet
              v(d('read text', { pic: png })),                                   // 8 picture + text to a note
              v(d('https://example.com/a', { pic: png, dest: 'library' })),      // 9 picture to Library, phone
              v(d('https://example.com/a', { pic: png, dest: 'library' }), { thumb: true }), // 10 ... PC
              v(d('https://example.com/a', { dest: 'note' })),                   // 11 a link in a note
              v(d('https://example.com/a', { pic: { name: 'a.pdf', type: 'application/pdf', blob: null }, dest: 'library' })), // 12 a PDF is read, not kept: no block
            ]))
        """)
        ok = [o[0] for o in out]
        self.assertEqual(ok, [False, False, False, True, False, True, True, False, True, False, True, True, True])
        self.assertIn('Library items need a web link', out[2][1])
        self.assertIn('Already in your library as No. 7', out[4][1])
        self.assertIn('Nothing already there changes', out[6][1])
        self.assertIn('Read the picture', out[7][1])
        self.assertIn("text around it goes into the card's note", out[3][1])
        self.assertIn('Creates a note in Inbox', out[11][1])

    def test_a_shared_link_with_only_its_title_is_a_lone_link_and_text_around_a_link_is_kept(self):
        out = run("""
            const d = (text, comment = '') => ({ ...c.newDraft('typed', text), comment })
            console.log(JSON.stringify({
              parts: [c.shareParts('https://www.youtube.com/watch?v=abc&si=zz\\nKnife skills'), c.shareParts('Knife skills\\nhttps://a.com/x'),
                      c.shareParts('https://a.com/x?igsh=1'), c.shareParts('Look at this https://a.com/x'), c.shareParts('https://a.com/x\\nhttps://b.com/y'),
                      c.shareParts('one\\ntwo\\nhttps://a.com/x'), c.shareParts('plain words')],
              around: [c.around('Look at this https://a.com/x?igsh=1 please'), c.around('https://a.com/x'), c.around('no link here'), c.around('Line one\\nhttps://a.com/x\\nLine two')],
              note: [c.libraryNote(d('Look https://a.com/x', 'mine')), c.libraryNote(d('https://a.com/x', 'mine')), c.libraryNote(d('Look https://a.com/x'))],
              dest: c.defaultDest({ ...c.newDraft('share', c.shareParts('https://a.com/x\\nA title').text) }),
            }))
        """)
        self.assertEqual(out['parts'], [
            {'text': 'https://www.youtube.com/watch?v=abc', 'title': 'Knife skills'}, {'text': 'https://a.com/x', 'title': 'Knife skills'},
            {'text': 'https://a.com/x', 'title': ''}, {'text': 'Look at this https://a.com/x', 'title': ''},
            {'text': 'https://a.com/x\nhttps://b.com/y', 'title': ''}, {'text': 'one\ntwo\nhttps://a.com/x', 'title': ''},
            {'text': 'plain words', 'title': ''}])
        self.assertEqual(out['around'], ['Look at this please', '', '', 'Line one\nLine two'])
        self.assertEqual(out['note'], ['Look\n\nmine', 'mine', 'Look'])
        self.assertEqual(out['dest'], 'library')

    def test_share_text_with_a_link_goes_through_the_one_link_parser(self):
        cases = [t for t, want in SHARE_CASES if want]
        out = run(f"console.log(JSON.stringify({json.dumps(cases)}.map(t => c.linkOf(t))))")
        for text, got in zip(cases, out):
            self.assertEqual(got, inbox.link(text), text)

    def test_the_note_section_is_the_filing_section(self):
        out = run("""
            const d = { ...c.newDraft('typed', 'Visit the shop.'), comment: 'for Saturday' }
            const shot = { ...c.newDraft('file', 'Weekend ideas'), pic: { name: 'a.png', type: 'image/png', blob: null }, read: 'digest' }
            console.log(JSON.stringify({
              label: [c.label(d), c.label({ ...d, text: 'https://example.com/x' }), c.label(shot)],
              body: c.newBody(d), section: c.section(d, '2026-10-18 10:01'),
              appended: c.appended('First line.', d, '2026-10-18 10:01'),
              empty: c.appended('', d, '2026-10-18 10:01'),
              titles: [c.titleFor(d), c.titleFor({ ...d, title: '  Mine  ' }), c.titleFor({ ...d, text: 'https://www.example.com/x' }),
                       c.titleFor({ ...shot, text: '' }), c.titleFor(c.newDraft())],
            }))
        """)
        self.assertEqual(out['label'], ['Note', 'Link', 'Screenshot digest'])
        self.assertEqual(out['body'], 'Visit the shop.\n\nfor Saturday\n')
        head = filing.heading('append', 'Note', '2026-10-18 10:01')
        self.assertEqual(out['section'], head + '\n\nVisit the shop.\n\nfor Saturday')
        self.assertEqual(out['appended'], 'First line.\n\n' + head + '\n\nVisit the shop.\n\nfor Saturday\n')
        self.assertEqual(out['empty'], head + '\n\nVisit the shop.\n\nfor Saturday\n')
        self.assertEqual(out['titles'], ['Visit the shop.', 'Mine', 'Link from example.com', 'a', 'Quick note'])

    def test_one_picture_or_file_at_a_time(self):
        out = run("""
            const f = (name, type, size = 1000) => ({ name, type, size })
            const k = r => (r.ok ? r.kind : r.msg)
            console.log(JSON.stringify([
              k(c.checkFiles([f('a.png', 'image/png')])), k(c.checkFiles([f('a.pdf', '')])), k(c.checkFiles([f('a.md', '')])),
              k(c.checkFiles([f('a.png', 'image/png'), f('b.png', 'image/png')])), k(c.checkFiles([f('a.exe', 'application/x-msdownload')])),
              k(c.checkFiles([f('a.png', 'image/png', 11 * 1024 * 1024)])), k(c.checkFiles([])),
              c.joinText('', ' read '), c.joinText('typed\\n', 'read'),
            ]))
        """)
        self.assertEqual(out[:3], ['image', 'pdf', 'text'])
        for msg in out[3:7]:
            self.assertTrue(msg.endswith('Your capture has been kept.'), msg)
        self.assertIn('one picture or file at a time', out[3])
        self.assertIn('over 10 MB', out[5])
        self.assertEqual(out[7:], ['read', 'typed\n\nread'])

    def test_the_note_picker_shows_recent_notes_or_the_search(self):
        out = run("""
            const n = (file, title, updated, head = '') => ({ file, title, updated, head, category: 'Inbox' })
            const notes = [n('a.md', 'Alpha', '2026-10-01'), n('b.md', 'Bravo kettlebell', '2026-10-05'), n('c.md', 'Charlie', '2026-10-03'),
                           n('d.md', 'Delta', '2026-10-04'), n('e.md', 'Echo', '2026-10-02'), n('f.md', 'Foxtrot', '2026-10-06', 'swing and squat')]
            const files = l => l.map(x => x.file)
            console.log(JSON.stringify([
              files(c.pickNotes(notes, '')), files(c.pickNotes(notes, '', 'a.md')), files(c.pickNotes(notes, 'kettle')),
              files(c.pickNotes(notes, 'SWING squat')), files(c.pickNotes(notes, 'nothing')),
              c.suggestNote('kettlebell swings today', notes),
            ]))
        """)
        self.assertEqual(out[0], ['f.md', 'b.md', 'd.md', 'c.md', 'e.md'])
        self.assertEqual(out[1], ['a.md', 'f.md', 'b.md', 'd.md', 'c.md'])        # the suggestion comes first
        self.assertEqual(out[2], ['b.md'])
        self.assertEqual(out[3], ['f.md'])
        self.assertEqual(out[4], [])
        self.assertEqual(out[5], 'b.md')

    def test_new_drafts_have_the_shape_the_service_worker_writes(self):
        keys = run("console.log(JSON.stringify(Object.keys(c.newDraft('share', 'x')).sort()))")
        self.assertEqual(keys, sorted(['id', 'at', 'origin', 'text', 'comment', 'dest', 'target', 'title', 'collection',
                                       'type', 'tags', 'made', 'pic', 'read']))
        self.assertTrue(re.match(r'^[a-z0-9]{8,}$', run("console.log(JSON.stringify(c.newDraft().id))")))

    def test_a_lone_links_page_titles_the_note_and_goes_under_the_link(self):
        out = run("""
            const d = c.newDraft('typed', 'https://isoglow.dev/')
            const p = { asked: 'https://isoglow.dev/', url: 'https://isoglow.dev/', found: true, title: 'iso-glow', creator: '',
                        desc: 'Isometric drawings that glow', image: 'https://iso-glow.vercel.app/img/tower.jpg' }
            const ig = { ...p, title: '', desc: 'First line of a caption\\nsecond line' }
            console.log(JSON.stringify([
              c.titleFor(d, p),                                         // 0 the page title
              c.newBody(d, p),                                          // 1 link, then title and caption
              c.titleFor(d, { ...p, asked: 'https://other.dev/' }),     // 2 an answer for another link is ignored
              c.newBody(d, null),                                       // 3 no page: as before
              c.titleFor({ ...d, title: 'Mine' }, p),                   // 4 a typed title wins
              c.noteText({ ...d, text: 'Look https://isoglow.dev/' }, p),  // 5 not a lone link: no page lines
              c.sourceHelp({ ...d, dest: 'note' }, p),                  // 6
              c.titleFor(d, ig),                                        // 7 no title: the caption's first line
              c.titleFor(d, { ...p, found: false }),                    // 8 not found
              c.section({ ...d, comment: 'why' }, '2026-10-19 10:00', p), // 9 an addition carries the page too
              c.siteOf('https://www.isoglow.dev/a'), c.siteOf('nope'),  // 10, 11
            ]))
        """)
        self.assertEqual(out[0], 'iso-glow')
        self.assertEqual(out[1], 'https://isoglow.dev/\n\niso-glow\nIsometric drawings that glow\n')
        self.assertEqual(out[2], 'Link from isoglow.dev')
        self.assertEqual(out[3], 'https://isoglow.dev/\n')
        self.assertEqual(out[4], 'Mine')
        self.assertEqual(out[5], 'Look https://isoglow.dev/')
        self.assertIn('title and caption', out[6])
        self.assertEqual(out[7], 'First line of a caption')
        self.assertEqual(out[8], 'Link from isoglow.dev')
        self.assertEqual(out[9], '## From Link - 2026-10-19 10:00\n\nhttps://isoglow.dev/\n\niso-glow\nIsometric drawings that glow\n\nwhy')
        self.assertEqual((out[10], out[11]), ('isoglow.dev', ''))


if __name__ == '__main__':
    unittest.main()
