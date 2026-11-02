"""Stamps and markup survive every write path and stay out of search (projects/note-organic-ui/plans/
03-store-search.md): the autosave keeps or replaces the `stamps:` line, the appenders (voice, summary,
screenshot digest) and the Knowledge save / rename keep it byte-identical, GET returns the stamps, and
notes_fts holds the words without the tags."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.auth_client import TestClient

from core import ai_client
from core import note_format
from core.db import Database
from knowledge import knowledge
from knowledge import my_notes
from server.app import create_app
from server.jobs import KINDS

BASE = 'http://127.0.0.1:8765'
W = {'X-CM': '1'}
LINE = '[{"k":"kettlebell","at":"The sequence","x":-4,"y":1,"s":3,"c":"indigo","r":0}]'
BODY = ('Ten minutes. <span data-ink="ember">16 kg</span> swings.\n\n## The sequence\n\n'
        '- [x] cat-cow\n- [ ] dead hang with <mark data-mark="mint">chalk</mark> and ==grip==\n')


def stamps_line(path: Path) -> str:
    meta, _body = knowledge.split_frontmatter(path.read_text(encoding='utf-8'))
    return meta.get('stamps', '')


class StampsCoreTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name) / 'notes'
        self.p = my_notes.create_note(self.dir, 'Morning routine', 'General')
        my_notes.save_note(self.p, 'Morning routine', 'General', BODY, note_format.parse_stamps(LINE))

    def test_save_sets_keeps_and_clears(self):
        self.assertEqual(stamps_line(self.p), LINE)
        my_notes.save_note(self.p, 'Morning routine', 'Work', BODY + 'more\n')         # stamps=None: kept
        self.assertEqual(stamps_line(self.p), LINE)
        my_notes.save_note(self.p, 'Morning routine', 'Work', BODY, [{'k': 'sun', 'at': 'top'}])
        self.assertEqual(note_format.parse_stamps(stamps_line(self.p))[0]['k'], 'sun')
        my_notes.save_note(self.p, 'Morning routine', 'Work', BODY, [])
        self.assertNotIn('stamps', knowledge.split_frontmatter(self.p.read_text(encoding='utf-8'))[0])

    def test_appenders_and_rename_keep_the_line(self):
        my_notes.add_voice(self.p, 'spoken words')
        self.assertEqual(stamps_line(self.p), LINE)
        meta, body = knowledge.split_frontmatter(self.p.read_text(encoding='utf-8'))
        my_notes.save_note(self.p, meta['topic'], meta['category'], my_notes.replace_summary(body, '- short'))
        my_notes.save_note(self.p, meta['topic'], meta['category'], my_notes.append_digest(body, 'shot text'))
        self.assertEqual(stamps_line(self.p), LINE)
        new = knowledge.rename_note(self.dir, self.p, 'Morning routine v4')
        self.assertEqual(stamps_line(new), LINE)

    def test_markup_stays_in_the_file(self):
        _meta, body = knowledge.split_frontmatter(self.p.read_text(encoding='utf-8'))
        self.assertEqual(body, BODY)


class StampsServerTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        Database(self.data / 'content_manager.db').close()
        p = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'OPENAI_API_KEY': 'k'})
        p.start()
        self.addCleanup(p.stop)
        for k in KINDS.values():
            p = mock.patch.multiple(k, gap=0.0, error_gap=0.0)
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(create_app(data_dir=self.data, cloud_dir=self.data / 'test-cloud', port=8765, web_dist=self.data / 'x', cards_dir=self.data / 'x'), base_url=BASE)
        self.c.__enter__()
        self.addCleanup(self.c.__exit__, None, None, None)
        self.c.post('/api/my-notes', json={'title': 'Morning routine', 'category': 'General'}, headers=W)
        self.file = 'morning-routine.md'
        self.path = self.data / 'notes' / self.file

    def put(self, **extra):
        r = self.c.put(f'/api/my-notes/{self.file}', json={'title': 'Morning routine', 'category': 'General', 'body': BODY, **extra}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)

    def wait(self):
        end = time.time() + 10
        while time.time() < end:
            s = self.c.get('/api/jobs').json()
            if s['current'] is None and s['last']:
                return s['last']
            time.sleep(0.03)
        self.fail('job did not finish')

    def test_autosave_get_and_keep(self):
        self.put(stamps=note_format.parse_stamps(LINE))
        got = self.c.get(f'/api/my-notes/{self.file}').json()
        self.assertEqual(got['stamps'], note_format.parse_stamps(LINE))
        self.assertEqual(got['body'], BODY.strip('\n'))
        self.put()                                       # an autosave without stamps keeps them
        self.assertEqual(stamps_line(self.path), LINE)
        self.put(stamps='not a list')                    # junk is ignored, not written
        self.assertEqual(stamps_line(self.path), LINE)

    def test_summary_and_knowledge_save_keep_the_line(self):
        self.put(stamps=note_format.parse_stamps(LINE))
        with mock.patch.object(ai_client, 'complete_text', lambda *a, **k: '- short'):
            self.assertEqual(self.c.post(f'/api/my-notes/{self.file}/summarize', headers=W).status_code, 200)
            self.wait()
        self.assertEqual(stamps_line(self.path), LINE)
        r = self.c.put(f'/api/notes/{self.file}', json={'body': BODY + '\nedited in Knowledge\n'}, headers=W)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(stamps_line(self.path), LINE)

    def test_search_sees_words_not_markup(self):
        self.put(stamps=note_format.parse_stamps(LINE))
        db = Database(self.data / 'content_manager.db')
        self.addCleanup(db.close)
        self.assertEqual([n['filename'] for n in db.search_notes('chalk grip', 5)], [self.file])
        for word in ('span', 'ember', 'mark', 'data', 'mint'):
            self.assertEqual(db.search_notes(word, 5), [], word)
        self.assertNotIn('<span', db.search_notes('swings', 5)[0]['body'])


if __name__ == '__main__':
    unittest.main()
