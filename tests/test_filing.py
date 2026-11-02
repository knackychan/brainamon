"""Wiskit files (projects/wiskit-files plan 01): PDF attachments, knowledge/filing.py and
/api/filing/*. Temp data only, model calls stubbed.
Run:  py -m unittest tests.test_filing -v
"""
import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import ai_defaults
from core.db import Database
from knowledge import attachments as att
from knowledge import filing
from knowledge import knowledge
from knowledge import my_notes
from knowledge import tasks
from server.app import create_app

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF whose text layer is `text` (Helvetica, hand-built xref)."""
    content = f'BT /F1 18 Tf 20 50 Td ({text}) Tj ET'.encode()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R '
            b'/Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offs = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    for o in offs:
        out += b'%010d 00000 n \n' % o
    out += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    return bytes(out)


def blank_pdf() -> bytes:
    from pypdf import PdfWriter
    w, buf = PdfWriter(), io.BytesIO()
    w.add_blank_page(100, 100)
    w.write(buf)
    return buf.getvalue()


class PdfTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)

    def test_kind(self):
        self.assertEqual(att.kind_of('Book.PDF'), 'pdf')

    def test_text_layer(self):
        self.assertIn('Hello PDF', att.pdf_text(tiny_pdf('Hello PDF')))

    def test_scan_and_garbage(self):
        with self.assertRaisesRegex(ValueError, 'no text layer'):
            att.pdf_text(blank_pdf())
        with self.assertRaisesRegex(ValueError, 'could not be read'):
            att.pdf_text(b'%PDF-nope')

    def test_save_keeps_the_text_beside_the_copy(self):
        d = att.save(self.data, 'guide.pdf', tiny_pdf('Hip airplanes'), describe=None)
        self.assertEqual(d['kind'], 'pdf')
        name, text = att.resolve(self.data, d['id'])
        self.assertIn('Hip airplanes', text)
        self.assertTrue((self.data / 'inbox' / (d['id'] + '.txt')).is_file())

    def test_scan_files_nothing(self):
        with self.assertRaises(ValueError):
            att.save(self.data, 'scan.pdf', blank_pdf(), describe=None)
        self.assertFalse((self.data / 'inbox').exists() and any((self.data / 'inbox').iterdir()))

    def test_image_bytes(self):
        d = att.save(self.data, 'shot.png', b'png-bytes', describe=lambda m, raw: 'a shot')
        name, media, b64 = att.image_bytes(self.data, d['id'])
        self.assertEqual((media, base64.b64decode(b64)), ('image/png', b'png-bytes'))
        with self.assertRaises(att.Unsupported):
            att.image_bytes(self.data, 'notes.md')
        with self.assertRaises(att.Gone):
            att.image_bytes(self.data, 'missing.png')


class FilingModuleTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        self.db = Database(self.data / 'content_manager.db')
        self.addCleanup(self.db.close)
        self.wiki, _meta = knowledge.save_new_note(self.db.notes_dir, 'Knee rehab', [4, 9], 'Hip airplanes help knees.')
        self.db.reindex_notes()

    def test_plain_title(self):
        self.assertEqual(filing.plain_title('2026-10-13-knee_rehab-plan.pdf'), 'knee rehab plan')
        self.assertEqual(filing.plain_title(''), 'From a file')

    def test_candidates_skip_topic_digests(self):
        c = filing.candidates(self.db, self.db.notes_dir, 'knee.md', 'knee rehab airplanes', set())
        self.assertEqual([x['file'] for x in c], [self.wiki.name])
        self.assertEqual(c[0]['kind'], 'Synthesized')
        self.assertEqual(filing.candidates(self.db, self.db.notes_dir, 'knee.md', 'knee rehab', {self.wiki.name}), [])

    def test_suggest_uses_the_model_pick(self):
        cands = [{'file': self.wiki.name, 'title': 'Knee rehab', 'kind': 'Synthesized', 'excerpt': ''}]
        answer = f'Sure: {{"best": "[{self.wiki.name}]", "why": "Same exercise.", "title": "Knee drills"}}'
        with mock.patch.object(ai_client, 'complete_text', return_value=answer):
            s = filing.suggest('knee.md', 'text', cands, 'anthropic', 'm')
        self.assertEqual((s['best'], s['title'], s['ai']), (self.wiki.name, 'Knee drills', True))

    def test_suggest_falls_back(self):
        cands = [{'file': self.wiki.name, 'title': 'Knee rehab', 'kind': 'Synthesized', 'excerpt': ''}]
        with mock.patch.object(ai_client, 'complete_text', side_effect=RuntimeError('no key')):
            s = filing.suggest('2026-10-13-knee.md', 'text', cands, 'anthropic', 'm')
        self.assertEqual((s['best'], s['title'], s['ai']), (self.wiki.name, 'knee', False))
        with mock.patch.object(ai_client, 'complete_text', return_value='{"best": "other.md", "title": ""}'):
            s = filing.suggest('x.md', 'text', cands, 'anthropic', 'm')
        self.assertEqual((s['best'], s['title']), ('', 'x'))

    def test_options_order(self):
        cands = [{'file': 'a.md', 'title': 'A', 'kind': 'Personal', 'excerpt': ''},
                 {'file': 'b.md', 'title': 'B', 'kind': 'Synthesized', 'excerpt': ''}]
        o = filing.options({'best': 'b.md', 'why': 'w', 'title': 'T', 'ai': True}, cands)
        self.assertEqual([(x['action'], x['file']) for x in o], [('append', 'b.md'), ('extend', 'b.md'), ('new', ''), ('append', 'a.md')])
        self.assertEqual(sum(x['best'] for x in o), 1)
        o = filing.options({'best': '', 'why': '', 'title': 'T', 'ai': False}, [])
        self.assertEqual([(x['action'], x['best']) for x in o], [('new', True)])

    def test_new_note_is_personal_in_inbox(self):
        p = filing.file_text(self.db, 'new', 'plan.md', 'deadlift day', title='Lifting')
        meta, body = knowledge.split_frontmatter(p.read_text(encoding='utf-8'))
        self.assertEqual((meta['topic'], meta['kind'], meta['category']), ('Lifting', 'personal', 'Inbox'))
        self.assertIn('## From plan.md - ', body)
        self.assertIn('deadlift day', body)

    def test_append_keeps_a_wiki_note_a_wiki_note(self):
        filing.file_text(self.db, 'append', 'more.md', 'Copenhagen planks', file=self.wiki.name)
        meta, body = knowledge.split_frontmatter(self.wiki.read_text(encoding='utf-8'))
        self.assertNotIn('kind', meta)
        self.assertEqual(meta['sources'], '4,9')
        self.assertIn('updated', meta)
        self.assertLess(body.index('Hip airplanes'), body.index('Copenhagen planks'))
        self.assertTrue(self.db.search_notes('copenhagen', 5))

    def test_errors(self):
        with self.assertRaises(LookupError):
            filing.file_text(self.db, 'append', 'x', 'text', file='gone.md')
        with self.assertRaises(ValueError):
            filing.file_text(self.db, 'new', 'x', '   ')
        with self.assertRaises(ValueError):
            filing.file_text(self.db, 'delete', 'x', 'text')


class FilingRouteTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.wiki, _meta = knowledge.save_new_note(db.notes_dir, 'Knee rehab', [4], 'Hip airplanes help knees.')
        self.topic_note, _meta = knowledge.save_new_note(db.notes_dir, 'topic knees', [], 'Knees digest.')
        db.update_topic(db.add_topic('knees', 'knee'), note_path=self.topic_note.name)
        db.reindex_notes()
        db.close()
        for p in (mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'}),
                  mock.patch.object(ai_defaults, 'embed_credentials', lambda db: ('', None))):
            p.start()
            self.addCleanup(p.stop)
        self.app = create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x')
        self.c = TestClient(self.app, base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)

    def attach(self, name, raw):
        r = self.c.post(f'/api/ask/attach?name={name}', content=raw, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['id']

    def test_pdf_attaches(self):
        r = self.c.post('/api/ask/attach?name=guide.pdf', content=tiny_pdf('Knee airplanes'), headers=W)
        self.assertEqual((r.status_code, r.json()['kind']), (200, 'pdf'))
        self.assertEqual(self.c.post('/api/ask/attach?name=scan.pdf', content=blank_pdf(), headers=W).status_code, 400)

    def test_suggest_without_a_key_still_offers_choices(self):
        aid = self.attach('knee.md', b'knee rehab with hip airplanes')
        with mock.patch.object(ai_client, 'complete_text', side_effect=RuntimeError('no key')):
            d = self.c.post('/api/filing/suggest', json={'id': aid}, headers=W).json()
        self.assertFalse(d['ai'])
        self.assertEqual(d['options'][0], {'action': 'append', 'file': self.wiki.name, 'title': 'Knee rehab',
                                           'label': 'Add to "Knee rehab"', 'why': 'Shares the most words with this file.', 'best': True})
        self.assertNotIn(self.topic_note.name, [o['file'] for o in d['options']])
        self.assertEqual(self.c.post('/api/filing/suggest', json={'id': 'gone.md'}, headers=W).status_code, 404)

    def test_file_new_and_append(self):
        aid = self.attach('plan.md', b'deadlift day')
        seen = []
        with mock.patch.object(self.app.state.hub, 'publish', lambda k, d: seen.append((k, d))):
            d = self.c.post('/api/filing/file', json={'id': aid, 'action': 'new', 'title': 'Lifting'}, headers=W).json()
            self.assertTrue(d['personal'])
            body = (self.data / 'notes' / d['file']).read_text(encoding='utf-8')
            self.assertIn(f'Source file: `data/inbox/{aid}`', body)
            r = self.c.post('/api/filing/file', json={'text': 'Line one', 'name': 'Screenshot digest',
                                                      'action': 'append', 'file': self.wiki.name}, headers=W)
        self.assertEqual(r.json(), {'file': self.wiki.name, 'title': 'Knee rehab', 'personal': False})
        self.assertIn('## From Screenshot digest - ', self.wiki.read_text(encoding='utf-8'))
        self.assertEqual([k for k, _d in seen], ['notes_changed', 'notes_changed'])

    def test_file_refusals(self):
        bad = [({'text': 'x', 'action': 'move'}, 400), ({'text': ' ', 'action': 'new'}, 400),
               ({'text': 'x', 'action': 'append', 'file': 'gone.md'}, 404),
               ({'text': 'x', 'action': 'append', 'file': self.topic_note.name}, 400)]
        for body, code in bad:
            self.assertEqual(self.c.post('/api/filing/file', json=body, headers=W).status_code, code, body)

    def test_extend_writes_the_ai_section(self):
        with mock.patch.object(ai_client, 'complete_text', return_value='- Copenhagen planks add adductor work.') as ct:
            d = self.c.post('/api/filing/file', json={'text': 'Copenhagen planks', 'name': 'clip notes',
                                                      'action': 'extend', 'file': self.wiki.name}, headers=W).json()
        self.assertIn('Hip airplanes help knees.', ct.call_args.kwargs['prompt'])
        body = self.wiki.read_text(encoding='utf-8')
        self.assertIn('## Extended from clip notes - ', body)
        self.assertIn('adductor work', body)
        self.assertEqual(d['file'], self.wiki.name)

    def test_digest_returns_text_in_order(self):
        a = self.attach_image('one.png')
        b = self.attach_image('two.png')

        def fake(media_type, b64, provider, model):
            if base64.b64decode(b64) == b'bad':
                raise RuntimeError('blurry')
            return f'text of {base64.b64decode(b64).decode()}'
        with mock.patch.object(tasks, 'transcribe_screenshot', fake):
            d = self.c.post('/api/filing/digest', json={'ids': [a, b]}, headers=W).json()
            self.assertEqual(d['failed'], 0)
            self.assertLess(d['text'].index('one.png'), d['text'].index('two.png'))
            bad = self.c.post('/api/filing/digest', json={'images': [{'name': 'x.png', 'type': 'image/png',
                                                                      'data': base64.b64encode(b'bad').decode()}]}, headers=W)
        self.assertEqual(bad.status_code, 400)
        self.assertIn('blurry', bad.json()['detail'])
        self.assertEqual(self.c.post('/api/filing/digest', json={}, headers=W).status_code, 400)

    def attach_image(self, name):
        with mock.patch.object(tasks, 'describe_attachment', lambda *a: 'a picture'):
            return self.attach(name, name.encode())

    def test_read_keeps_nothing(self):
        md = self.c.post('/api/filing/read?name=a.md', content='# Hi'.encode(), headers=W).json()
        self.assertEqual((md['kind'], md['text']), ('text', '# Hi'))
        pdf = self.c.post('/api/filing/read?name=a.pdf', content=tiny_pdf('Page words'), headers=W).json()
        self.assertIn('Page words', pdf['text'])
        with mock.patch.object(tasks, 'transcribe_screenshot', lambda *a: 'verbatim'), \
                mock.patch.object(tasks, 'describe_attachment', lambda *a: 'described'), \
                mock.patch('core.config.key_for_provider', lambda provider: 'k'):
            dig = self.c.post('/api/filing/read?name=s.png&how=digest', content=b'png', headers=W).json()
            des = self.c.post('/api/filing/read?name=s.png&how=describe', content=b'png', headers=W).json()
        self.assertEqual((dig['text'], des['text']), ('verbatim', 'described'))
        self.assertEqual(self.c.post('/api/filing/read?name=a.mp4', content=b'x', headers=W).status_code, 415)
        self.assertFalse((self.data / 'inbox').exists() and any(p.suffix == '.pdf' for p in (self.data / 'inbox').iterdir()))


if __name__ == '__main__':
    unittest.main()
