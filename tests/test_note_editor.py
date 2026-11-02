"""Pure editor preservation/geometry checks. Node must run; a skipped adapter check is not a pass."""
import json
import unittest
from pathlib import Path

from tests.test_note_format import node

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/note_editor.json').read_text(encoding='utf-8'))


class NoteEditorTest(unittest.TestCase):
    def test_supported_round_trip_and_stability(self):
        node(f"""
          import assert from 'node:assert/strict'
          import {{ parseMarkdown, serializeMarkdown }} from './web/src/lib/note-editor.ts'
          const cases = {json.dumps(CASES['supported'])}
          for (const source of cases) {{
            const parsed = parseMarkdown(source)
            assert.ok(parsed.ok, 'supported: ' + source)
            const saved = serializeMarkdown(parsed.blocks)
            const reopened = parseMarkdown(saved)
            assert.ok(reopened.ok, 'reopen: ' + saved)
            assert.equal(serializeMarkdown(reopened.blocks), saved, 'stable: ' + source)
            const meaning = blocks => blocks.map(b => ({{ ...b, runs: b.runs.map(r => ({{ ...r, marks: r.marks.map(m => m === 'mark:sun' ? 'mark:sun' : m).sort() }})) }}))
            assert.deepEqual(meaning(reopened.blocks), meaning(parsed.blocks), 'meaning: ' + source)
          }}
        """)

    def test_unsupported_is_explicit_and_keeps_source(self):
        node(f"""
          import assert from 'node:assert/strict'
          import {{ parseMarkdown }} from './web/src/lib/note-editor.ts'
          for (const source of {json.dumps(CASES['unsupported'])}) {{
            assert.equal(parseMarkdown(source).ok, false, source)
          }}
        """)

    def test_typed_delimiters_are_literal_and_empty_marks_merge(self):
        node("""
          import assert from 'node:assert/strict'
          import { parseMarkdown, serializeMarkdown } from './web/src/lib/note-editor.ts'
          const text = '2 * 3 **literal** _literal_ ==literal== <script> [id 1]'
          const source = serializeMarkdown([{kind:'p',runs:[{text,marks:[]}]}])
          const parsed = parseMarkdown(source)
          assert.ok(parsed.ok)
          assert.equal(parsed.blocks[0].runs[0].text, text)
          assert.deepEqual(parsed.blocks[0].runs[0].marks, [])
          assert.equal(serializeMarkdown([{kind:'p',runs:[{text:'a',marks:['b']},{text:'',marks:['u']},{text:'b',marks:['b']}]}]), '**ab**')
        """)

    def test_anchor_geometry_and_inverse(self):
        node(f"""
          import assert from 'node:assert/strict'
          import {{ anchorRow, headingName, stampPosition, stampFromPoint }} from './web/src/lib/note-editor.ts'
          const g = {json.dumps(CASES['geometry'])}
          const st = {{ k:'sun', at:'Duplicate', x:-4, y:1, s:3, c:'sun', r:0 }}
          assert.equal(anchorRow('Duplicate',g),144)
          assert.equal(anchorRow('orphan',g),600)
          assert.equal(anchorRow('top',g),48)
          assert.equal(anchorRow('end',g),600)
          assert.deepEqual(stampPosition(st,g),{{left:704,top:168}})
          assert.deepEqual(stampPosition({{...st,x:2}},g),{{left:120,top:168}})
          assert.deepEqual(stampFromPoint(st,704,168,g),st)
          assert.equal(stampFromPoint(st,120,168,g).x,2)
          assert.equal(stampFromPoint(st,72,60,g).at,'top')
          const narrow = {{...g,width:120,textRight:96}}
          assert.equal(stampPosition(st,narrow).left,24)
          assert.equal(st.x,-4) // display clamp never changes stored coordinates
          assert.equal(headingName('  a \\n b  '),'a b')
          assert.equal(Array.from(headingName('😀'.repeat(125))).length,120)
        """)


if __name__ == '__main__':
    unittest.main()
