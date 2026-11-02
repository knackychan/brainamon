"""Voice notes on the phone (projects/voice-notes/plans/02-phone.md): the section text agrees with the PC,
and providers.transcribe builds the request Whisper expects. Runs under Node 22.6+ (skips without it)."""
import json
import re
import unittest

from core import ai_client
from knowledge import my_notes
from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneVoiceTest(unittest.TestCase):
    def test_section_text_matches_the_pc(self):
        out = node("""
            import { appendVoice, stamp } from './web/src/mobile/voice.ts'
            console.log(JSON.stringify([appendVoice('', ' hello ', '2026-10-12 09:30'), appendVoice('Intro\\n', 'hi', '2026-10-12 09:30'), stamp(new Date(2026, 9, 12, 9, 5))]))
        """)
        a, b, s = json.loads(out)
        self.assertEqual(a, my_notes.append_voice('', ' hello ', '2026-10-12 09:30'))
        self.assertEqual(b, my_notes.append_voice('Intro\n', 'hi', '2026-10-12 09:30'))
        self.assertEqual(s, '2026-10-12 09:05')

    def test_transcribe_request(self):
        out = node(f"""
            import {{ setFetch, transcribe, CLOUD }} from './web/src/mobile/ai/providers.ts'
            let seen
            setFetch(async (url, init) => {{ seen = {{ url, auth: init.headers.authorization, model: init.body.get('model'), name: init.body.get('file').name }}
              return new Response(JSON.stringify({{ text: ' buy milk ' }}), {{ status: 200 }}) }})
            const text = await transcribe(CLOUD, 'sk-x', {json.dumps(ai_client.WHISPER_MODEL)}, new Blob(['a'], {{ type: 'audio/webm' }}))
            console.log(JSON.stringify([text, seen]))
        """)
        text, seen = json.loads(out)
        self.assertEqual(text, 'buy milk')
        self.assertEqual(seen, {'url': 'https://api.openai.com/v1/audio/transcriptions', 'auth': 'Bearer sk-x',
                                'model': ai_client.WHISPER_MODEL, 'name': 'voice.webm'})

    def test_no_model_id_in_phone_code(self):
        from pathlib import Path
        src = '\n'.join(p.read_text(encoding='utf-8') for p in Path('web/src/mobile').rglob('*') if p.suffix in ('.ts', '.svelte'))
        self.assertIsNone(re.search(r'whisper-1', src))


if __name__ == '__main__':
    unittest.main()
