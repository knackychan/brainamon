"""Voice notes on the phone (projects/voice-notes/plans/02-phone.md): the section text agrees with the PC,
and providers.transcribe builds the file-transcription request. Runs under Node 22.6+ (skips without it)."""
import json
import re
import unittest

from core import ai_client
from knowledge import my_notes
from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneVoiceTest(unittest.TestCase):
    def test_enqueue_waits_for_commit_and_reports_abort(self):
        out = json.loads(node("""
            import { enqueue } from './web/src/mobile/voice.ts'
            let tx, closed = 0
            const db = { close: () => closed++, transaction: () => {
              tx = { error: null, objectStore: () => ({ add: () => ({}) }) }
              return tx
            } }
            globalThis.indexedDB = { open: () => {
              const request = {}; queueMicrotask(() => { request.result = db; request.onsuccess() }); return request
            } }
            let settled = false
            const save = enqueue('synthetic.md', new Blob(['voice'])).finally(() => { settled = true })
            await Promise.resolve(); await Promise.resolve()
            const beforeCommit = settled
            tx.oncomplete(); await save
            const aborted = enqueue('synthetic.md', new Blob(['voice'])).then(() => false, () => true)
            await Promise.resolve(); await Promise.resolve()
            tx.error = Error('synthetic abort'); tx.onabort()
            console.log(JSON.stringify({ beforeCommit, aborted: await aborted, closed }))
        """))
        self.assertEqual(out, {'beforeCommit': False, 'aborted': True, 'closed': 2})

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
            setFetch(async (url, init) => {{ seen = {{ url, auth: init.headers.authorization, model: init.body.get('model'), name: init.body.get('file').name, format: init.body.get('response_format'), fields: [...init.body.keys()] }}
              return new Response(JSON.stringify({{ text: ' buy milk ' }}), {{ status: 200 }}) }})
            const text = await transcribe(CLOUD, 'sk-x', {json.dumps(ai_client.TRANSCRIPTION_MODEL)}, new Blob(['a'], {{ type: 'audio/webm' }}))
            console.log(JSON.stringify([text, seen]))
        """)
        text, seen = json.loads(out)
        self.assertEqual(text, 'buy milk')
        self.assertEqual(seen, {'url': 'https://api.openai.com/v1/audio/transcriptions', 'auth': 'Bearer sk-x',
                                'model': ai_client.TRANSCRIPTION_MODEL, 'name': 'voice.webm', 'format': 'json',
                                'fields': ['model', 'response_format', 'file']})

    def test_current_phone_ignores_stale_transcription_metadata(self):
        out = node(r"""
            import fs from 'node:fs'
            import { stripTypeScriptTypes } from 'node:module'
            import { AiError, CLOUD, setFetch, transcribe } from './web/src/mobile/ai/providers.ts'
            const PHONE_AI = JSON.parse(fs.readFileSync('knowledge/prompts/phone_ai.json', 'utf8'))
            const src = fs.readFileSync('web/src/mobile/source/mirror.ts', 'utf8').replace(/\r\n/g, '\n')
            const body = src.match(/  canTranscribe\(\)[\s\S]*?\n  }\n/)[0]
            const Source = new Function('PHONE_AI', 'AiError', 'transcribe',
              stripTypeScriptTypes('class Source {\n' + body + '\n}') + ';return Source')(PHONE_AI, AiError, transcribe)
            const seen = []
            setFetch(async (url, init) => { seen.push(init.body.get('model')); return Response.json({text:'hello'}) })
            let key = 'synthetic'
            const s = Object.assign(new Source(), { keys: () => ({openai:key}), endpoints: () => CLOUD,
              settings: () => ({transcription_model:'whisper-1'}) })
            const available = s.canTranscribe()
            await s.transcribe(new Blob(['a']))
            s.settings = () => null
            await s.transcribe(new Blob(['a']))
            key = ''
            const refused = await s.transcribe(new Blob(['a'])).then(() => false, e => e instanceof AiError)
            console.log(JSON.stringify({available, seen, refused, missingKey:s.canTranscribe()}))
        """)
        self.assertEqual(json.loads(out), {'available': True, 'seen': [ai_client.TRANSCRIPTION_MODEL] * 2,
                                          'refused': True, 'missingKey': False})

    def test_abort_and_provider_failure_still_propagate(self):
        out = node(f"""
            import {{ AiError, CLOUD, setFetch, transcribe }} from './web/src/mobile/ai/providers.ts'
            const signal = new AbortController().signal
            let calls = 0, forwarded = false
            setFetch(async (url, init) => {{ calls++; forwarded = init.signal === signal; throw new DOMException('Stopped', 'AbortError') }})
            const abort = await transcribe(CLOUD, 'sk-x', {json.dumps(ai_client.TRANSCRIPTION_MODEL)}, new Blob(['a']), signal).catch(e => e.name)
            setFetch(async () => {{ calls++; return Response.json({{error:{{message:'Invalid key'}}}}, {{status:401}}) }})
            const error = await transcribe(CLOUD, 'sk-x', {json.dumps(ai_client.TRANSCRIPTION_MODEL)}, new Blob(['a'])).catch(e => e instanceof AiError)
            console.log(JSON.stringify({{abort, error, calls, forwarded}}))
        """)
        self.assertEqual(json.loads(out), {'abort': 'AbortError', 'error': True, 'calls': 2, 'forwarded': True})

    def test_no_model_id_in_phone_code(self):
        from pathlib import Path
        src = '\n'.join(p.read_text(encoding='utf-8') for p in Path('web/src/mobile').rglob('*') if p.suffix in ('.ts', '.svelte'))
        self.assertIsNone(re.search(r'whisper-1|gpt-(?:live-)?transcribe', src))


if __name__ == '__main__':
    unittest.main()
