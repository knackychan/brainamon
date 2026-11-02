"""The My Notes format (projects/note-organic-ui/plans/01-note-format-agents.md): core/note_format.py
and web/src/lib/note-format.ts agree on tests/fixtures/note_format.json, the TypeScript renderer keeps
anything outside the contract as text, and the contract text the models read names every value.
The TypeScript half runs under Node (type stripping, the tests/test_phone_js.py way); it skips
without Node 22.6+."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from core import note_format

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / 'tests' / 'fixtures' / 'note_format.json').read_text(encoding='utf-8'))


def node(script: str, timeout: float = 60) -> str:
    r = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', '--input-type=module', '-e', script],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return r.stdout


def _node_ok() -> bool:
    if not shutil.which('node'):
        return False
    try:
        node("import { plain } from './web/src/lib/note-format.ts'; console.log(plain('x'))")
        return True
    except Exception:
        return False


class NoteFormatPythonTest(unittest.TestCase):
    def test_plain(self):
        for body, words in CASES['plain']:
            self.assertEqual(note_format.plain(body), words, body)

    def test_head(self):
        for body, top in CASES['head']:
            self.assertEqual(note_format.head(body), top, body)

    def test_head_stops_at_the_character_budget(self):
        # 300-character lines: the second line brings it past HEAD_CHARS, so two lines
        self.assertEqual(note_format.head(('x' * 300 + '\n') * 3), 'x' * 300 + '\n' + 'x' * 300)

    def test_word_count(self):
        for body, n in CASES['words']:
            self.assertEqual(note_format.word_count(body), n, body)

    def test_stamps_round_trip(self):
        for value, dumped in CASES['stamps']:
            self.assertEqual(note_format.dump_stamps(note_format.parse_stamps(value)), dumped, value)

    def test_dump_is_one_line_and_parses_back(self):
        items = note_format.parse_stamps(CASES['stamps'][0][0])
        line = note_format.dump_stamps(items)
        self.assertNotIn('\n', line)
        self.assertEqual(note_format.parse_stamps(line), items)

    def test_set_stamps_adds_and_removes_the_key(self):
        meta = {'topic': 'T'}
        note_format.set_stamps(meta, [{'k': 'sun'}])
        self.assertEqual(meta[note_format.KEY], '[{"k":"sun","at":"end","x":-4,"y":0,"s":2,"c":"indigo","r":0}]')
        note_format.set_stamps(meta, [])
        self.assertNotIn(note_format.KEY, meta)

    def test_at_most_max_stamps(self):
        self.assertEqual(len(note_format.clean_stamps([{'k': 'sun'}] * 100)), note_format.MAX_STAMPS)

    def test_contract_names_every_value(self):
        text = note_format.contract()
        for name in note_format.INKS + note_format.MARKS + note_format.STAMPS:
            self.assertIn(name, text)
        for snippet in ('<u>', '<mark data-mark=', '<span data-ink=', '- [x]', '==', 'stamps: [', 'top', 'end'):
            self.assertIn(snippet, text)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class NoteFormatTypeScriptTest(unittest.TestCase):
    def test_typescript_agrees_with_python(self):
        out = json.loads(node(f"""
            import {{ plain, parseStamps, dumpStamps, blocksHTML, marksInline, head, wordCount, INKS, MARKS, STAMPS, MAX_STAMPS }} from './web/src/lib/note-format.ts'
            const C = {json.dumps(CASES)}
            const ESC = {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}
            const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c])
            console.log(JSON.stringify({{
              plain: C.plain.map(([b]) => plain(b)),
              stamps: C.stamps.map(([v]) => dumpStamps(parseStamps(v))),
              render: C.render.map(([md, exact]) => blocksHTML(esc(md), marksInline, exact)),
              head: C.head.map(([b]) => head(b)),
              words: C.words.map(([b]) => wordCount(b)),
              long: head(('x'.repeat(300) + '\\n').repeat(3)),
              names: [INKS, MARKS, STAMPS, MAX_STAMPS],
            }}))
        """))
        self.assertEqual(out['plain'], [w for _b, w in CASES['plain']])
        self.assertEqual(out['stamps'], [d for _v, d in CASES['stamps']])
        self.assertEqual(out['render'], [h for _m, _e, h in CASES['render']])
        self.assertEqual(out['head'], [t for _b, t in CASES['head']])
        self.assertEqual(out['words'], [n for _b, n in CASES['words']])
        self.assertEqual(out['long'], note_format.head(('x' * 300 + '\n') * 3))
        self.assertEqual(out['names'], [list(note_format.INKS), list(note_format.MARKS), list(note_format.STAMPS), note_format.MAX_STAMPS])

    def test_phone_sees_the_same_words_as_the_pc(self):
        """Deep's note sections and profile, and the notes search text, are the plain words on both sides
        (plans/03-store-search.md): the phone's ports in web/src/mobile/ai/ use note-format.ts plain."""
        import tempfile
        from knowledge import librarian
        notes = {
            'about-me.md': '---\ntopic: About me\n---\n\nI train with a <span data-ink="sky">16 kg</span> bell, ==mornings== only.\n',
            'morning.md': ('---\ntopic: Morning\nkind: personal\nstamps: [{"k":"sun","at":"top","x":-4,"y":0,"s":2,"c":"sun","r":0}]\n---\n\n'
                           'Ten minutes before coffee, <u>every day</u>, keep it short enough.\n\n## The sequence\n\n'
                           '- [x] cat-cow and thoracic rotations, two minutes\n- [ ] dead hang with <mark data-mark="mint">chalk</mark>\n'),
        }
        with tempfile.TemporaryDirectory() as td:
            for name, text in notes.items():
                (Path(td) / name).write_text(text, encoding='utf-8')
            py_sections = [[s['key'], s['text'], s['payload']] for s in librarian._note_sections(Path(td))]
            py_profile = librarian.read_profile(Path(td))
        out = json.loads(node(f"""
            import {{ noteSections, profileOf }} from './web/src/mobile/ai/deep.ts'
            import {{ noteOf }} from './web/src/mobile/ai/library.ts'
            const N = {json.dumps(list(notes.items()))}
            console.log(JSON.stringify({{
              sections: noteSections(N, {librarian._SECTION_MAX}).map(s => [s.key, s.text, s.payload]),
              profile: profileOf(N[0][1], {librarian._PROFILE_MAX}),
              body: noteOf(N[1][0], N[1][1]).body,
            }}))
        """))
        self.assertEqual(out['sections'], py_sections)
        self.assertEqual(out['profile'], py_profile)
        self.assertNotIn('<', out['profile'] + out['body'] + json.dumps(py_sections))
        self.assertIn('- cat-cow', out['body'])


if __name__ == '__main__':
    unittest.main()
