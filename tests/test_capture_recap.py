"""The phone's Add recap rules (web/src/mobile/recap.ts, projects/phone-add-confirm), run under Node like
tests/test_capture.py: a new note goes to General (Inbox stays listed only while the source lists it), why the
Library cannot take a draft and in which order, where the recap stands, the lines under each destination, the
attachment's line, and the end of a note above an addition. The desktop's shared rules keep their Inbox. Skips
without Node 22.6+."""
import json
import unittest

from tests.test_phone_js import TS_RESOLVE, _node_ok, node


def run(body: str):
    return json.loads(node(TS_RESOLVE + "const c = await import('./web/src/lib/capture.ts')\n"
                           "const r = await import('./web/src/mobile/recap.ts')\n"
                           "const d = (text, over = {}) => ({ ...c.newDraft('typed', text), ...over })\n"
                           "const png = { name: 'a.png', type: 'image/png', blob: null }\n"
                           "const pdf = { name: 'menu.pdf', type: 'application/pdf', blob: null }\n"
                           "const txt = { name: 'list.txt', type: 'text/plain', blob: null }\n" + body))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class CaptureRecapTest(unittest.TestCase):
    def test_a_new_note_goes_to_general_and_inbox_stays_only_while_listed(self):
        out = run("""
            console.log(JSON.stringify([
              r.GENERAL,
              r.categoriesFor([]),
              r.categoriesFor(['Inbox', 'Reading', 'General']),
              r.categoriesFor(['Reading']),
              r.categoriesFor(['Reading'], 'Inbox'),
              c.verdict({ ...d('Keep this thought'), dest: r.phoneDest(d('Keep this thought')), category: r.GENERAL }, { thumb: false }).help,
              c.verdict(d('Keep this thought'), { thumb: false }).help,
            ]))
        """)
        self.assertEqual(out, ['General', ['General'], ['General', 'Inbox', 'Reading'], ['General', 'Reading'],
                               ['General', 'Reading', 'Inbox'], 'Creates a note in General.', 'Creates a note in Inbox.'])

    def test_why_the_library_cannot_take_a_draft_in_order(self):
        out = run("""
            console.log(JSON.stringify([
              r.libraryBlock(d('plain text')),
              r.libraryBlock(d('plain text', { pic: png })),
              r.libraryBlock(d('https://example.com/a'), 7),
              r.libraryBlock(d('https://example.com/a', { pic: png }), 7),
              r.libraryBlock(d('https://example.com/a', { pic: png })),
              r.libraryBlock(d('https://example.com/a', { pic: pdf })),
              r.libraryBlock(d('Look at this https://example.com/a')),
            ]))
        """)
        self.assertEqual(out, [
            'Library items need a web link.',
            'Library items need a web link.',
            'Already in your library as No. 7.',
            'Already in your library as No. 7.',
            'A picture can only go into a Library item from the PC app. Choose Note, or remove the picture.',
            '',
            '',
        ])

    def test_where_the_recap_stands(self):
        out = run("""
            console.log(JSON.stringify([
              r.phoneDest(d('https://www.instagram.com/reel/abc/')),                       // a lone link: Library
              r.phoneDest(d('https://www.instagram.com/reel/abc/', { dest: 'note' })),     // chosen Note
              r.phoneDest(d('Look at this https://example.com/a')),                       // text and a link: Note
              r.phoneDest(d('Look at this https://example.com/a', { dest: 'library' })),  // chosen Library
              r.phoneDest(d('plain text', { dest: 'library' })),                          // an old draft, no link left
              r.phoneDest(d('https://example.com/a', { dest: 'library', pic: png })),     // a picture: Note
              r.phoneDest(d('https://example.com/a'), 7),                                 // already a card: Note
            ]))
        """)
        self.assertEqual(out, ['library', 'note', 'note', 'library', 'note', 'note', 'note'])

    def test_the_lines_under_the_destinations_and_the_draft(self):
        out = run("""
            const page = { asked: 'https://example.com/a', url: 'https://example.com/a', found: true, title: 'A page', desc: 'Its caption', image: '', creator: '' }
            console.log(JSON.stringify([
              r.noteHint(d('https://example.com/a'), page),
              r.noteHint(d('https://example.com/a')),
              r.libraryHint(d('https://example.com/a')),
              r.libraryHint(d('Look at this https://example.com/a')),
              r.draftHelp(d('')),
              r.draftHelp(d('', { comment: 'only a comment' })),
              r.draftHelp(d('Keep this')),
              r.draftHelp(d('', { pic: png })),
            ]))
        """)
        self.assertEqual(out, [
            "The page's title and caption go under the link.",
            'The link is kept as text.',
            'A card from the link.',
            'A card from the link; the text goes into its note.',
            'Add a link, some text or a picture to save.',
            'Add a link, some text or a picture to save.',
            'Nothing is saved yet. Save shows what goes where.',
            'Nothing is saved yet. Save shows what goes where.',
        ])

    def test_the_attachment_line_names_it_and_says_what_happens(self):
        out = run("""
            console.log(JSON.stringify([
              r.attLine(d('', { pic: png })),
              r.attLine(d('Its words', { pic: png, read: 'digest' })),
              r.attLine(d('', { pic: pdf })),
              r.attLine(d('Its words', { pic: pdf, read: 'digest' })),
              [c.picKind(png), c.picKind(pdf), c.picKind(txt)].map(k => r.KIND_TAG[k]),
            ]))
        """)
        self.assertEqual(out, [
            '1 picture, not read yet. Brainamon keeps the text, not the picture.',
            '1 picture. Its text is in the preview above. The picture itself is not kept.',
            '1 document, not read yet. Brainamon keeps the text, not the document.',
            '1 document. Its text is in the preview above. The document itself is not kept.',
            ['IMG', 'PDF', 'TXT'],
        ])

    def test_a_library_item_starts_on_the_last_collection_never_pc_decides(self):
        out = run("""
            console.log(JSON.stringify([
              r.INTERESTING,
              r.startCollection(''),
              r.startCollection('COOKING'),
              r.startCollection('  '),
              r.collectionsFor(['COOKING', 'SPORT']),
              r.collectionsFor(['COOKING', 'INTERESTING', 'SPORT']),
              r.collectionsFor(['COOKING'], 'Knife skills'),
              r.collectionsFor(['COOKING'], 'COOKING'),
              r.collectionsFor([]),
              r.NAME_IT,
            ]))
        """)
        self.assertEqual(out, ['INTERESTING', 'INTERESTING', 'COOKING', 'INTERESTING', ['COOKING', 'SPORT', 'INTERESTING'],
                               ['COOKING', 'INTERESTING', 'SPORT'], ['COOKING', 'INTERESTING', 'Knife skills'],
                               ['COOKING', 'INTERESTING'], ['INTERESTING'], 'Name the new collection, or pick one.'])

    def test_what_suggest_says(self):
        out = run("""
            console.log(JSON.stringify([
              r.SUGGEST,
              r.pickedLine('COOKING', 'knives, technique'),
              r.pickedLine('INTERESTING', ''),
              r.suggestFailed('The AI did not answer with a category. Try again.'),
              r.suggestFailed('Failed to fetch'),
            ]))
        """)
        self.assertEqual(out, [
            {'name': 'Suggest', 'says': 'Wiskit reads the link and what its page says, then picks one of your collections and a few '
                                        'tags. It uses the AI key on this phone.'},
            'Wiskit picked COOKING and the tags knives, technique. Change them if you like.',
            'Wiskit picked INTERESTING. Change them if you like.',
            'Wiskit could not suggest a collection: The AI did not answer with a category. Try again. Pick one yourself.',
            'Wiskit could not suggest a collection: Failed to fetch. Pick one yourself.',
        ])

    def test_the_end_of_a_note_above_an_addition(self):
        out = run("""
            console.log(JSON.stringify([
              r.tailOf('first\\n\\nsecond\\n   \\nthird\\nfourth'),
              r.tailOf('first\\nsecond\\nthird', 2),
              r.tailOf(''),
            ]))
        """)
        self.assertEqual(out, ['second\nthird\nfourth', 'second\nthird', ''])


if __name__ == '__main__':
    unittest.main()
