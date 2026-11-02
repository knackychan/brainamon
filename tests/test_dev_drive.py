"""server/dev_drive.py: the stand-in Google Drive answers the calls library/drive_client.py makes
(list, multipart and resumable upload, download, delete), so `py -m server.dev_drive` can stand in
for Google while the sign-in app is not registered. With fake_ai it also stands in for Anthropic and
OpenAI, which the phone's own client (web/src/mobile/ai/providers.ts) reads unchanged."""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from library import drive_client
from server import dev_drive
from tests.test_phone_js import _node_ok, node


class DevDriveTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.srv = dev_drive.serve(self.root / 'drive', port=0)
        base = f'http://127.0.0.1:{self.srv.server_address[1]}'
        p = mock.patch.multiple(drive_client, API=base + '/drive/v3', UPLOAD=base + '/upload/drive/v3')
        p.start()
        self.addCleanup(p.stop)
        self.c = drive_client.DriveClient('dev', 'dev', {'access_token': 'dev', 'expires_at': time.time() + 3600})

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_drive_check_passes_against_the_fake_and_leaves_nothing(self):
        from server import drive_check
        lines = []
        self.assertEqual(drive_check.run(self.c, say=lines.append), 0, lines)
        self.assertEqual(len([l for l in lines if l.startswith('ok')]), 8)      # about, 2 up, list, 2 down, 2 delete
        self.assertEqual(self.c.list(), [])

    def test_round_trip(self):
        small = self.c.upload('abc', data=b'small file')
        big_body = bytes(range(256)) * (drive_client.MULTIPART_MAX // 256 + 10)   # over the multipart limit: resumable
        big = self.c.upload('big', data=big_body)
        self.assertEqual({(f['id'], f['name']) for f in self.c.list()}, {(small, 'abc'), (big, 'big')})
        self.assertEqual(self.c.download(small), b'small file')
        self.assertEqual(self.c.download(big), big_body)
        self.assertEqual(self.c.upload('abc', data=b'v2', file_id=small), small)
        self.assertEqual(self.c.download(small), b'v2')
        self.c.delete(small)
        self.assertEqual([f['name'] for f in self.c.list()], ['big'])
        # kept on disk: a restart sees the same files
        self.assertEqual(dev_drive.FakeDrive(self.root / 'drive').files(), [{'id': big, 'name': 'big', 'size': str(len(big_body))}])


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class FakeAiTest(unittest.TestCase):
    """providers.ts streams, completes and embeds against the stand-ins (no real provider)."""
    def test_phone_client_reads_both_providers(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        srv = dev_drive.serve(root, port=0, fake_ai=True, fake_dim=8)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f'http://127.0.0.1:{srv.server_address[1]}/ai'
        out = json.loads(node(f"""
            import {{ chatStream, complete, embed }} from './web/src/mobile/ai/providers.ts'
            const ep = {{ anthropic: '{base}/anthropic', openai: '{base}/openai' }}
            const ask = 'Context [id 7] [note: knee.md]\\nAnswer this question:\\nQuestion: knees?'
            const out = {{}}
            for (const p of ['anthropic', 'openai']) {{
              const parts = []
              for await (const t of chatStream(ep, p, 'k', 'm', 'sys', [{{ role: 'user', content: ask }}], 100)) parts.push(t)
              out[p] = {{ n: parts.length, text: parts.join(''),
                whole: await complete(ep, p, 'k', 'm', 'on the topic: "Knees"\\n\\n### Source 7\\nx', 100) }}
            }}
            out.vec = await embed(ep, 'k', 'm', ['knee pain', 'knee'])
            console.log(JSON.stringify(out))
        """, development=True))
        for p in ('anthropic', 'openai'):
            self.assertGreater(out[p]['n'], 3, p)
            self.assertIn('[id 7]', out[p]['text'])
            self.assertIn('[note: knee.md]', out[p]['text'])
            self.assertEqual(out[p]['text'], dev_drive.fake_answer('Context [id 7] [note: knee.md]\nAnswer this question:\nQuestion: knees?'))
            self.assertIn('## Knees', out[p]['whole'])
            self.assertIn('- 7', out[p]['whole'])
        self.assertEqual(out['vec'], [dev_drive.fake_vec('knee pain', 8), dev_drive.fake_vec('knee', 8)])


if __name__ == '__main__':
    unittest.main()
