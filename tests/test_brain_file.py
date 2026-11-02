"""brain.py notes / file (projects/wiskit-files plan 03). Temp data only; the running app is faked.
Run:  py -m unittest tests.test_brain_file -v
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

with mock.patch.dict(os.environ):   # brain loads the real .env at import: keep its keys out of later tests
    import brain
from core.db import Database
from knowledge import knowledge


class BrainFileTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        self.data = Path(td.name)
        db = Database(self.data / 'content_manager.db')
        self.wiki, _meta = knowledge.save_new_note(db.notes_dir, 'Knee rehab', [4], 'Hip airplanes help knees.')
        db.reindex_notes()
        db.close()
        for p in (mock.patch.object(brain, 'DB_PATH', self.data / 'content_manager.db'),
                  mock.patch.object(brain, 'DATA_DIR', self.data)):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, argv, stdin=''):
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(stdin)), mock.patch('sys.stdout', out), mock.patch('sys.stderr', out):
            code = brain.main(argv)
        return code, out.getvalue()

    def test_notes_reads_only(self):
        code, out = self.run_cli(['notes', '--query', 'knee airplanes'])
        self.assertEqual(code, 0)
        self.assertIn(self.wiki.name, out)
        code, out = self.run_cli(['notes', '--json'])
        self.assertEqual(json.loads(out)[0]['file'], self.wiki.name)

    def test_file_without_the_app_writes_directly(self):
        shot = self.data / 'shot.png'
        shot.write_bytes(b'png')
        refused = urllib.error.URLError('refused')
        with mock.patch('urllib.request.urlopen', side_effect=refused):
            code, out = self.run_cli(['file', 'append', '--note', self.wiki.name, '--attach', str(shot)], 'Line from a shot')
        self.assertEqual(code, 0, out)
        self.assertIn('directly', out)
        body = self.wiki.read_text(encoding='utf-8')
        self.assertIn('## From shot.png - ', body)
        self.assertIn('Source file: `data/inbox/', body)
        self.assertTrue(any(p.name.endswith('-shot.png') for p in (self.data / 'inbox').iterdir()))

    @mock.patch.object(brain.local_auth, 'headers', side_effect=lambda port, extra=None: {**(extra or {}), 'Authorization': 'Bearer synthetic'})
    def test_file_goes_through_the_running_app(self, _auth):
        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=0):
            sent.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data))
            return Resp(json.dumps({'file': 'lifting.md', 'title': 'Lifting', 'personal': True}).encode())
        with mock.patch('urllib.request.urlopen', fake):
            code, out = self.run_cli(['file', 'new', '--title', 'Lifting', '--name', 'plan.md'], 'deadlift day')
        self.assertEqual(code, 0, out)
        self.assertIn('through the running app', out)
        self.assertTrue(sent['url'].endswith('/api/filing/file'))
        self.assertEqual(sent['headers'].get('X-cm'), '1')
        self.assertEqual((sent['body']['action'], sent['body']['title'], sent['body']['text']), ('new', 'Lifting', 'deadlift day'))
        self.assertFalse((self.data / 'notes' / 'lifting.md').exists())

    def test_refusals(self):
        code, out = self.run_cli(['file', 'append'], 'text')
        self.assertEqual(code, 1)
        self.assertIn('--note', out)
        code, out = self.run_cli(['file', 'new'], '')
        self.assertEqual(code, 1)
        code, out = self.run_cli(['file', 'new', '--attach', str(self.data / 'nope.png')], 'x')
        self.assertEqual(code, 1)
        self.assertIn('Not a file', out)


if __name__ == '__main__':
    unittest.main()
