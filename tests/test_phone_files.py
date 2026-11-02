"""Add a picture or file on the phone (projects/wiskit-files plan 04), run under Node like
tests/test_phone_js.py: the prompts equal knowledge/tasks.py, the note section equals
knowledge/filing.py, the file rules, bestNote, and the vision / PDF requests both providers get.
Skips without Node 22.6+."""
import json
import tempfile
import unittest
from pathlib import Path

from knowledge import filing
from knowledge import knowledge
from knowledge import tasks
from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneFilesTest(unittest.TestCase):
    def test_prompts_equal_the_pc(self):
        out = json.loads(node("""
            import { DIGEST_PROMPT, ATTACH_PROMPT } from './web/src/mobile/files.ts'
            console.log(JSON.stringify([DIGEST_PROMPT, ATTACH_PROMPT]))"""))
        self.assertEqual(out, [tasks.DIGEST_PROMPT, tasks.ATTACH_PROMPT])

    def test_section_equals_filing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'n.md'
            knowledge.write_front(p, {'topic': 'N'}, 'Body line\n')
            filing.add_section(p, filing.heading('append', 'shot.png', '2026-10-13 09:05'), ' text \n')
            _meta, py_body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        ts = json.loads(node("""
            import { withSection } from './web/src/mobile/files.ts'
            console.log(JSON.stringify([withSection('Body line\\n', 'shot.png', ' text \\n', '2026-10-13 09:05'),
                                        withSection('', 'a.md', 'x', '2026-10-13 09:05')]))"""))
        self.assertEqual(ts[0], py_body)
        self.assertEqual(ts[1], '## From a.md - 2026-10-13 09:05\n\nx\n')

    def test_kinds_names_best_note(self):
        out = json.loads(node("""
            import { kindOf, fileName, bestNote } from './web/src/mobile/files.ts'
            console.log(JSON.stringify({
              kinds: [kindOf('a.PNG', ''), kindOf('x', 'application/pdf'), kindOf('n.md', ''), kindOf('c.heic', 'image/heic')],
              names: [fileName('', 'image/jpeg'), fileName('IMG_1', 'image/png'), fileName('doc.pdf', 'application/pdf'), fileName('notes', 'text/markdown')],
              best: bestNote('Knee rehab with hip airplanes', [{ file: 'a.md', title: 'Lifting' }, { file: 'k.md', title: 'Knee rehab' }]),
              none: bestNote('nothing shared', [{ file: 'a.md', title: 'Lifting' }]),
            }))"""))
        self.assertEqual(out['kinds'], ['image', 'pdf', 'text', ''])
        self.assertEqual(out['names'], ['shared.jpg', 'IMG_1.png', 'doc.pdf', 'notes.md'])
        self.assertEqual((out['best'], out['none']), ('k.md', ''))

    def test_vision_and_pdf_requests(self):
        out = json.loads(node("""
            import { setFetch, vision, pdfText, CLOUD } from './web/src/mobile/ai/providers.ts'
            const sent = []
            setFetch(async (url, init) => {
              sent.push({ url, body: JSON.parse(init.body) })
              const j = url.includes('anthropic') ? { content: [{ type: 'text', text: 'A' }] }
                : { output: [{ type: 'message', content: [{ type: 'output_text', text: 'O' }] }] }
              return new Response(JSON.stringify(j), { status: 200 })
            })
            const r = [await vision(CLOUD, 'anthropic', 'k', 'm', 'P', 'image/png', 'QUJD', 100),
                       await vision(CLOUD, 'openai', 'k', 'm', 'P', 'image/png', 'QUJD', 100),
                       await pdfText(CLOUD, 'anthropic', 'k', 'm', 'P', 'a.pdf', 'UERG', 100),
                       await pdfText(CLOUD, 'openai', 'k', 'm', 'P', 'a.pdf', 'UERG', 100)]
            console.log(JSON.stringify({ r, sent }))"""))
        self.assertEqual(out['r'], ['A', 'O', 'A', 'O'])
        s = out['sent']
        self.assertTrue(s[0]['url'].endswith('/v1/messages'))
        self.assertEqual(s[0]['body']['messages'][0]['content'][0]['source'], {'type': 'base64', 'media_type': 'image/png', 'data': 'QUJD'})
        self.assertTrue(s[1]['url'].endswith('/v1/responses'))
        self.assertEqual(s[1]['body']['input'][0]['content'][1], {'type': 'input_image', 'image_url': 'data:image/png;base64,QUJD'})
        self.assertEqual(s[2]['body']['messages'][0]['content'][0]['type'], 'document')
        self.assertEqual(s[3]['body']['input'][0]['content'][0],
                         {'type': 'input_file', 'filename': 'a.pdf', 'file_data': 'data:application/pdf;base64,UERG'})


if __name__ == '__main__':
    unittest.main()
