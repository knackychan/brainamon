"""Wiskit, Smart search and Synthesize on the phone (projects/mobile-app/PLAN.md Phase 5): the
TypeScript ports in web/src/mobile/ai/ against the desktop's Python on the same library
(tests/fixtures/phone_ai_library.json, built by tests/phone_ai_fixture.py).

- keyword ranking: the phone's bm25 gives the same ids in the same order as SQLite FTS5
  (db.fts_ids, db.search_notes), from the mirror's search text, not the database;
- Smart search: the same top items as server/routes/smart.py, from the mirror's int8 vectors;
- Wiskit Quick: the same messages and info line as ask_core.build_turn (fresh question, a
  follow-up, list mode), and the same fallback rows;
- Synthesize: the same source blocks and fold prompts as synth.py;
- the shared prompt files are what both sides read; the stopword lists agree.

Embeddings are fakes (tests/phone_ai_fixture.fake_vec), and no AI provider is called. Runs under
Node 22.6+ type stripping (skips without it), like tests/test_phone_js.py."""
import base64
import gzip
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from core import db as core_db
from knowledge import ask_core, synth
from library import export, mirror, search
from tests import phone_ai_fixture as F
from tests.test_phone_js import _node_ok, node

MODEL = 'text-embedding-3-small'

# one source with every part (the labels, the per-part caps and the trim: 1200 + 600 + 800 + 400 + 400 is over 3000, so
# the report is cut to 800), a link saved on the phone (title, caption, note; no report), a bare link (its description
# is only its url: no block). The same dicts go through both twins.
RICH = {'id': 7, 'url': 'https://example.com/7', 'short_desc': 'Knee prehab', 'creator': 'Coach', 'category': 'SPORT',
        'tags': ' knee ,prehab,, ', 'report': 'R' * 1500, 'ai_desc': 'A' * 700, 'transcript': 'T' * 900,
        'description': 'D' * 500, 'notes': 'N' * 450}
PHONE_LINK = {'id': -7, 'url': 'https://example.com/p7', 'short_desc': 'Knee wall sits', 'creator': '', 'category': 'Inbox',
              'tags': '', 'ai_desc': '', 'description': 'Hold 45 s, three rounds.', 'notes': 'Try on Monday'}
BARE = {'id': -8, 'url': 'https://example.com/p8', 'description': 'https://example.com/p8', 'short_desc': '', 'notes': ''}
SENTINEL = {'id': -9, 'url': 'https://example.com/p9', 'description': 'NO_CONTENT', 'ai_desc': '  NO_CONTENT\n', 'notes': ''}


def _mirror_texts(db, data_dir: Path) -> tuple[list, list]:
    """The search text and card rows exactly as the mirror carries them."""
    payload = export.build_export_payload(db, None, {}, mirror=True, vectors_model=MODEL)
    texts, rows, vec = [], [], None
    for f in mirror.build_files(payload, data_dir, mirror.Options(videos='off', canvases=False)):
        if f.name.startswith('search/text-'):
            texts += json.loads(gzip.decompress(f.data()))
        elif f.name.startswith('library/part-'):
            rows += json.loads(f.data())
        elif f.name == 'vectors.bin':
            vec = f.data()
    return texts, rows, vec


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneAiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.db = F.build(cls.tmp, MODEL)
        cls.fx = F.load()
        cls.texts, cls.rows, vec = _mirror_texts(cls.db, cls.tmp)
        cls.index = search.EmbeddingIndex.from_db(cls.db, MODEL)
        notes = [{'file': p.name, 'text': p.read_text(encoding='utf-8')} for p in sorted(cls.db.notes_dir.glob('*.md'))]
        hist = [{'role': 'user', 'content': 'knee?'}, {'role': 'assistant', 'content': 'See [id 102] and [id 104].'}]
        cls.cases = []
        for q in cls.fx['questions'] + ['tell me more about the second one', 'more on these']:
            depth = ask_core.effective_depth(q, 25)
            rows = ask_core.rank_rows(cls.db, q, depth, '', cls.index, F.fake_vec(q))
            cls.cases.append({'q': q, 'vec': F.fake_vec(q), 'depth': depth, 'ids': [r['id'] for r in rows]})
        src = {'texts': cls.texts, 'rows': cls.rows, 'notes': notes, 'vec': base64.b64encode(vec).decode(),
               'cases': cls.cases, 'hist': hist,
               'ask': json.loads((ask_core.prompt_files.DIR / 'ask_quick.json').read_text(encoding='utf-8')),
               'synth': json.loads((ask_core.prompt_files.DIR / 'synth.json').read_text(encoding='utf-8')),
               'synth_ids': [it['id'] for it in cls.fx['items']],
               'rich': RICH, 'phone_link': PHONE_LINK, 'bare': BARE, 'sentinel': SENTINEL}
        (cls.tmp / 'in.json').write_text(json.dumps(src), encoding='utf-8')
        cls.out = json.loads(node(f"""
            import fs from 'node:fs'
            import {{ PhoneLibrary, noteOf }} from './web/src/mobile/ai/library.ts'
            import {{ Quick, citedIds, autoName }} from './web/src/mobile/ai/quick.ts'
            import {{ Synth, clean }} from './web/src/mobile/ai/synth.ts'
            import {{ hybridRank, topk, SMART_LIMIT }} from './web/src/mobile/ai/search.ts'
            import {{ ftsTerms, STOPWORDS }} from './web/src/mobile/ai/text.ts'
            import {{ readVectors }} from './web/src/mobile/mirror/crypto.ts'
            const S = JSON.parse(fs.readFileSync({json.dumps(str(cls.tmp / 'in.json'))}, 'utf8'))
            const lib = new PhoneLibrary(S.texts, S.rows, S.notes.map(n => noteOf(n.file, n.text)))
            const Q = new Quick(S.ask), Y = new Synth(S.synth)
            const v = readVectors(Uint8Array.from(Buffer.from(S.vec, 'base64')))
            const out = {{ cases: [], stop: [...STOPWORDS].sort() }}
            for (const c of S.cases) {{
              const smart = hybridRank(lib.ftsIds(c.q, SMART_LIMIT), topk(v, c.vec, SMART_LIMIT), SMART_LIMIT)
              const mine = Q.rankRows(lib, c.q, c.depth, '', k => topk(v, c.vec, k)).map(r => r.id)
              const rows = lib.getItemsByIds(c.ids)
              const fresh = Q.buildTurn(lib, c.q, rows, [], 'keyword + semantic search')
              const hist = Q.buildTurn(lib, c.q, rows, S.hist, '')
              out.cases.push({{
                terms: ftsTerms(c.q), fts: lib.ftsIds(c.q, 200), ftsAll: lib.ftsIds(c.q, 200, true), notes: lib.searchNotes(c.q, 9).map(n => n.filename),
                smart, mine, cat: Q.rankRows(lib, c.q, 25, 'SPORT', k => topk(v, c.vec, k)).map(r => r.id),
                fb: Q.fallbackRows(lib, c.q, 25, '', lib.all).map(r => r.id),
                fresh: {{ messages: fresh.messages, info: fresh.info, sources: fresh.sources.map(r => r.id), list: fresh.listMode, max: fresh.maxTokens }},
                hist: {{ messages: hist.messages, info: hist.info, sources: hist.sources.map(r => r.id) }},
                name: autoName(c.q),
              }})
            }}
            const items = lib.getItemsByIds(S.synth_ids)
            out.blocks = items.map(s => Y.sourceBlock(s))
            out.batches = Y.batches(items).map(b => b.map(s => s.id))
            const b0 = Y.batches(items)[0]
            out.fold = [Y.batchPrompt('Knee prehab', '', b0), Y.batchPrompt('Knee prehab', '## Note', b0), Y.batchPrompt('Knee prehab', '## Note', b0, 'append')]
            out.clean = clean('```markdown\\n# Hi\\n```')
            out.rich = Y.sourceBlock(S.rich); out.phoneLink = Y.sourceBlock(S.phone_link); out.bare = Y.sourceBlock(S.bare)
            out.richParts = Y.parts(S.rich)
            out.sentinel = [Y.hasText(S.sentinel), Y.sourceBlock(S.sentinel), Y.batches([S.sentinel]).length,
              Y.sourceBlock({{ ...S.sentinel, notes: 'Read later' }}), Y.hasText({{ ...S.sentinel, ai_desc: ' no_content ' }})]
            out.bareVariants = ['example.com/p8/', 'HTTPS://WWW.EXAMPLE.COM/p8/', 'example.com/p8 caption'].map(description => Y.hasText({{ ...S.bare, description }}))
            out.cited = citedIds('Try [id 12] and [ids 3, 4] or [id 5, id 6]; see [note: knee.md]. Not [12].')
            console.log(JSON.stringify(out))
        """, timeout=120))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def each(self):
        for c, o in zip(self.cases, self.out['cases']):
            with self.subTest(q=c['q']):
                yield c, o

    def test_keyword_ranking_matches_sqlite_fts5(self):
        for c, o in self.each():
            self.assertEqual(o['terms'], core_db.fts_terms(c['q']))
            self.assertEqual(o['fts'], self.db.fts_ids(c['q'], 200))
            self.assertEqual(o['notes'], [n['filename'] for n in self.db.search_notes(c['q'], 9)])

    def test_every_word_search_matches_the_library_box(self):
        """E-phone-fixes item 10: the phone's keyword box finds the ids the PC's box finds."""
        for c, o in self.each():
            self.assertEqual(o['ftsAll'], self.db.fts_ids(c['q'], 200, match_all=True))

    def test_smart_search_top_items_match_the_desktop(self):
        """server/routes/smart.py on float32 vectors vs the phone on the mirror's int8 ones."""
        for c, o in self.each():
            want = search.hybrid_rank(self.db.fts_ids(c['q'], 150), self.index.topk(c['vec'], 150), limit=150)
            self.assertEqual(o['smart'][:10], want[:10])
            self.assertEqual(o['mine'][:10], c['ids'][:10])
            cat = [r['id'] for r in ask_core.rank_rows(self.db, c['q'], 25, 'SPORT', self.index, c['vec'])]
            self.assertEqual(o['cat'][:10], cat[:10])

    def test_wiskit_quick_builds_the_same_turn(self):
        hist = [{'role': 'user', 'content': 'knee?'}, {'role': 'assistant', 'content': 'See [id 102] and [id 104].'}]
        for c, o in self.each():
            rows = self.db.get_items_by_ids(c['ids'])
            for key, h, retrieval in (('fresh', [], 'keyword + semantic search'), ('hist', hist, '')):
                t = ask_core.build_turn(self.db, c['q'], rows, h, retrieval)
                self.assertEqual(o[key]['messages'], t['messages'], key)
                self.assertEqual(o[key]['info'], t['info'], key)
                self.assertEqual(o[key]['sources'], [r['id'] for r in t['sources']], key)
            self.assertEqual(o['fresh']['list'], ask_core.is_list(c['q']))
            self.assertEqual(o['fresh']['max'] or None, ask_core.build_turn(self.db, c['q'], rows, [])['max_tokens'])
            self.assertEqual(o['fb'], [r['id'] for r in ask_core.fallback_rows(self.db, c['q'], 25, '')])
            self.assertEqual(o['name'], ask_core.auto_name(c['q']))
        self.assertEqual(self.out['cited'], [12, 3, 4, 5, 6])

    def test_synthesize_builds_the_same_prompts(self):
        srcs = self.db.get_items_by_ids([it['id'] for it in self.fx['items']])
        self.assertEqual(self.out['blocks'], [synth.source_block(s) for s in srcs])
        self.assertEqual(self.out['batches'], [[s['id'] for s in b] for b in synth.batches(srcs)])
        b0 = synth.batches(srcs)[0]
        text = '\n\n'.join(b for b in (synth.source_block(s) for s in b0) if b)
        self.assertEqual(self.out['fold'], [synth.fold_prompt('Knee prehab', 'reorganize', '', text),
                                            synth.fold_prompt('Knee prehab', 'reorganize', '## Note', text),
                                            synth.fold_prompt('Knee prehab', 'append', '## Note', text)])
        self.assertEqual(self.out['clean'], synth.clean('```markdown\n# Hi\n```'))
        self.assertEqual(synth.PHONE_MAX_SOURCES, 36)

    def test_synthesize_sends_every_part_of_a_source(self):
        # projects/phone-solo-synthesize: labelled parts, per-part caps, the report trimmed first, tags and category
        self.assertEqual(self.out['rich'], synth.source_block(RICH))
        self.assertEqual(self.out['phoneLink'], synth.source_block(PHONE_LINK))
        self.assertEqual(self.out['bare'], synth.source_block(BARE))
        self.assertEqual(self.out['richParts'], [list(p) for p in synth.parts(RICH)])
        block = synth.source_block(RICH)
        for line in ('### Source 7 — Knee prehab', 'Creator: Coach', 'URL: https://example.com/7', 'Tags: knee, prehab', 'Category: SPORT',
                     'Report:\n' + 'R' * 800, 'AI description:\n' + 'A' * 600, 'Transcript:\n' + 'T' * 800, 'Caption:\n' + 'D' * 400, 'My note:\n' + 'N' * 400):
            self.assertIn(line, block)
        self.assertEqual({k: len(t) for k, t in synth.parts(RICH)}, {'report': 800, 'ai_desc': 600, 'transcript': 800, 'description': 400, 'notes': 400})
        self.assertEqual([k for k, _ in synth.parts(RICH)], ['report', 'ai_desc', 'transcript', 'description', 'notes'])
        phone = synth.source_block(PHONE_LINK)
        for line in ('### Source -7 — Knee wall sits', 'Category: Inbox', 'Caption:\nHold 45 s, three rounds.', 'My note:\nTry on Monday'):
            self.assertIn(line, phone)
        for gone in ('Report:', 'Creator:', 'Tags:', 'Transcript:', 'AI description:'):
            self.assertNotIn(gone, phone)
        self.assertEqual(synth.source_block(BARE), '')
        self.assertFalse(synth.has_text(BARE))
        variants = [{**BARE, 'description': text} for text in ('example.com/p8/', 'HTTPS://WWW.EXAMPLE.COM/p8/', 'example.com/p8 caption')]
        self.assertEqual(self.out['bareVariants'], [synth.has_text(s) for s in variants])
        self.assertEqual(self.out['bareVariants'], [False, False, True])
        self.assertEqual(synth.batches([RICH, BARE, PHONE_LINK]), [[RICH, PHONE_LINK]])
        self.assertFalse(synth.has_text(SENTINEL))
        self.assertEqual(synth.batches([SENTINEL]), [])
        with_note = {**SENTINEL, 'notes': 'Read later'}
        self.assertFalse(synth.has_text({**SENTINEL, 'ai_desc': ' no_content '}))
        self.assertEqual(self.out['sentinel'], [False, '', 0, synth.source_block(with_note), False])
        self.assertIn('My note:\nRead later', synth.source_block(with_note))
        self.assertNotIn('NO_CONTENT', synth.source_block(with_note))
        self.assertEqual((synth.EXCERPT_LIMIT, synth.TITLE_LIMIT, synth.PHONE_MAX_SOURCES), (3000, 200, 36))
        self.assertIn("'My note' is what the owner wrote", synth.RULES)

    def test_stopwords_agree(self):
        self.assertEqual(self.out['stop'], sorted(core_db._FTS_STOPWORDS))

    def test_mirror_search_text_and_ai_settings(self):
        t = {r['id']: r for r in self.texts}
        it = next(i for i in self.fx['items'] if i.get('report'))
        self.assertEqual(t[it['id']]['k'], export.report_section(it['report'], 'Key information')[:mirror.KEYINFO])
        self.assertEqual(t[it['id']]['t'], it.get('transcript', ''))
        from core import ai_client
        s = ai_client.phone_settings('anthropic', 'gpt-4.1-mini')
        self.assertEqual(s['synth']['model'], ai_client.current_model('gpt-4.1-mini'))
        self.assertEqual(set(s['ask']['models']), {'anthropic', 'openai'})
        self.assertEqual(s['embedding_model'], ai_client.EMBEDDING_MODEL)
        self.assertTrue(re.match(r'^\d+$', str(s['cloud_min_tokens'])))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class ProviderHistoryTest(unittest.TestCase):
    def test_phone_provider_strips_review_metadata(self):
        out = json.loads(node(f"""
            import {{ setFetch, askAgent, chatStream }} from './web/src/mobile/ai/providers.ts'
            const EP = {{ anthropic: 'https://api.anthropic.com', openai: 'https://api.openai.com' }}
            const requests = []
            setFetch(async (url, init) => {{
              requests.push({{ url, body: JSON.parse(init.body) }})
              if (url.includes('/v1/messages')) {{
                return new Response(JSON.stringify({{ stop_reason: 'end_turn', content: [{{ type: 'text', text: 'ok' }}] }}), {{ status: 200, headers: {{ 'content-type': 'application/json' }} }})
              }}
              const stream = new ReadableStream({{ start(c) {{ c.enqueue(new TextEncoder().encode('data: [DONE]\\n\\n')); c.close() }} }})
              return new Response(stream, {{ status: 200, headers: {{ 'content-type': 'text/event-stream' }} }})
            }})
            const hist = [{{ role: 'user', content: 'hi' }}, {{ role: 'assistant', content: 'yo', review: {{ kind: 'weekly', start: 'x', end: 'y', timezone: 'UTC', through: 'z' }} }}]
            await askAgent(EP, 'anthropic', 'k', 'm', 'sys', hist, [], async () => '', () => {{}}, 1, 100)
            for await (const _ of chatStream(EP, 'openai', 'k', 'm', 'sys', hist, 100)) {{}}
            console.log(JSON.stringify(requests))
        """, timeout=120))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['body']['messages'], [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'yo'}])
        self.assertEqual(out[1]['body']['messages'], [{'role': 'system', 'content': 'sys'}, {'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'yo'}])


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class AgentStreamProtocolTest(unittest.TestCase):
    def test_fragmented_streams_completion_replay_and_eof(self):
        out = json.loads(node(r"""
            import { askAgent, setFetch } from './web/src/mobile/ai/providers.ts'
            const ep = { anthropic: 'https://api.anthropic.com', openai: 'https://api.openai.com' }, enc = new TextEncoder()
            const frame = e => `event: ${e.type}\r\ndata: ${JSON.stringify(e)}\r\n\r\n`
            const a = [
              {type:'message_start',message:{role:'assistant',content:[]}},
              {type:'content_block_start',index:0,content_block:{type:'thinking',thinking:'',signature:''}},
              {type:'content_block_delta',index:0,delta:{type:'thinking_delta',thinking:'private'}},
              {type:'content_block_delta',index:0,delta:{type:'signature_delta',signature:'sig'}},
              {type:'content_block_stop',index:0},
              {type:'content_block_start',index:1,content_block:{type:'text',text:''}},
              {type:'content_block_delta',index:1,delta:{type:'text_delta',text:'Hi 😀'}},
              {type:'content_block_stop',index:1},
              {type:'content_block_start',index:2,content_block:{type:'tool_use',id:'c1',name:'read_items',input:{}}},
              {type:'content_block_delta',index:2,delta:{type:'input_json_delta',partial_json:'{"ids":'}},
              {type:'content_block_delta',index:2,delta:{type:'input_json_delta',partial_json:'[101]}' }},
              {type:'content_block_stop',index:2},
              {type:'message_delta',delta:{stop_reason:'tool_use'}},{type:'message_stop'}]
            const output = [{type:'reasoning',encrypted_content:'secret'}, {type:'function_call',name:'read_items',call_id:'c1',arguments:'{"ids":[101]}',status:'completed'}]
            const o = [{type:'response.output_text.delta',delta:'Hi 😀'}, {type:'response.completed',response:{status:'completed',output}}]
            let checks = 0
            for (const p of ['anthropic','openai']) {
              const events = p === 'anthropic' ? a : o, bytes = enc.encode(events.map(frame).join(''))
              for (let boundary = 0; boundary <= bytes.length; boundary++) {
                let calls=0, requests=0, reset=0, delivered=false
                setFetch(async (_, init) => {
                  requests++
                  if (requests === 2) {
                    const body=JSON.parse(init.body), replay=p==='anthropic'?body.messages:body.input
                    if (!JSON.stringify(replay).includes(p==='anthropic'?'sig':'secret')) throw Error('lost replay')
                    return new Response(JSON.stringify(p==='anthropic'?{stop_reason:'end_turn',content:[{type:'text',text:'Done'}]}:{status:'completed',output:[{type:'message',status:'completed',content:[{type:'output_text',text:'Done'}]}]}))
                  }
                  return new Response(new ReadableStream({start(c){c.enqueue(bytes.slice(0,boundary));c.enqueue(bytes.slice(boundary));c.close()}}))
                })
                // The second round can return a whole stream too; use a streamed terminal answer.
                const sendFinal = p==='anthropic' ? [
                  {type:'message_start',message:{}},{type:'content_block_start',index:0,content_block:{type:'text',text:''}},
                  {type:'content_block_delta',index:0,delta:{type:'text_delta',text:'Done'}},{type:'content_block_stop',index:0},
                  {type:'message_delta',delta:{stop_reason:'end_turn'}},{type:'message_stop'}]
                  : [{type:'response.output_text.delta',delta:'Done'},{type:'response.completed',response:{status:'completed',output:[{type:'message',status:'completed',content:[{type:'output_text',text:'Done'}]}]}}]
                let n=0
                setFetch(async(_,init)=>{
                  const body=JSON.parse(init.body)
                  const b=n++ ? enc.encode(sendFinal.map(frame).join('')) : bytes
                  if(n===2 && !JSON.stringify(p==='anthropic'?body.messages:body.input).includes(p==='anthropic'?'sig':'secret')) throw Error('lost replay')
                  return new Response(new ReadableStream({start(c){c.enqueue(b.slice(0,boundary));c.enqueue(b.slice(boundary));c.close()}}))
                })
                const text=await askAgent(ep,p,'k','m','sys',[],[{name:'read_items',description:'d',parameters:{}}],async(n,a)=>{if(!delivered||!reset||a.ids[0]!==101)throw Error('order');calls++;return 'ok'},()=>{},2,100,undefined,{onText:()=>{delivered=true},onReset:()=>reset++})
                if(text!=='Done'||calls!==1||reset!==1) throw Error('result')
                checks++
              }
              let calls=0
              const incomplete=enc.encode(events.slice(0,-1).map(frame).join(''))
              setFetch(async()=>new Response(incomplete))
              try { await askAgent(ep,p,'k','m','sys',[],[],async()=>{calls++;return ''},()=>{},2,100,undefined,{onText:()=>{}}); throw Error('accepted EOF') }
              catch(e){if(!e.message.includes('without successful completion'))throw e}
              if(calls)throw Error('EOF dispatch')
            }
            console.log(JSON.stringify({checks}))
        """, timeout=120))
        self.assertGreater(out['checks'], 1000)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class SharedSseTest(unittest.TestCase):
    def test_multiline_frames_utf8_and_cleanup(self):
        result = json.loads(node(r"""
            import {sse} from './web/src/lib/sse.ts'
            const bytes=new TextEncoder().encode(': comment\r\nevent: custom\rdata: 😀\r\ndata: second\r\n\r\n')
            let count=0,cancelled=0
            for(let i=0;i<=bytes.length;i++){
              const r=new Response(new ReadableStream({start(c){c.enqueue(bytes.slice(0,i));c.enqueue(bytes.slice(i));c.close()}}))
              const out=[];for await(const e of sse(r))out.push(e)
              if(JSON.stringify(out)!==JSON.stringify([['custom','😀\nsecond']]))throw Error('multiline framing')
              count++
            }
            const r=new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: first\n\n'))},cancel(){cancelled++}}))
            for await(const e of sse(r))break
            console.log(JSON.stringify({count,cancelled}))
        """))
        self.assertGreater(result['count'],40)
        self.assertEqual(result['cancelled'],1)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class PhoneAgentOutcomeTest(unittest.TestCase):
    def test_outcomes_call_budget_and_stop(self):
        result=json.loads(node(r"""
          import {askAgent,setFetch} from './web/src/mobile/ai/providers.ts'
          const ep={anthropic:'https://api.anthropic.com',openai:'https://api.openai.com'},tools=[{name:'read_items',description:'d',parameters:{}}]
          let cases=0
          for(const p of ['anthropic','openai'])for(const kind of ['refusal','empty','incomplete','final_calls','budget','stop']){
            let calls=0,requests=[],ctl=new AbortController()
            const tool=i=>p==='anthropic'?{type:'tool_use',id:'c'+i,name:'read_items',input:{ids:[102]}}:{type:'function_call',call_id:'c'+i,name:'read_items',arguments:'{"ids":[102]}',status:'completed'}
            setFetch(async(_,init)=>{
              requests.push(JSON.parse(init.body))
              let j
              if(requests.length>1)j=p==='anthropic'?{stop_reason:'end_turn',content:[{type:'text',text:'Done'}]}:{status:'completed',output:[{type:'message',status:'completed',content:[{type:'output_text',text:'Done'}]}]}
              else if(kind==='refusal')j=p==='anthropic'?{stop_reason:'refusal',content:[]}:{status:'completed',output:[{type:'message',status:'completed',content:[{type:'refusal',refusal:'Declined'}]}]}
              else if(kind==='empty')j=p==='anthropic'?{stop_reason:'end_turn',content:[]}:{status:'completed',output:[]}
              else j=p==='anthropic'?{stop_reason:kind==='incomplete'?'max_tokens':'tool_use',content:[tool(0),tool(1),tool(2),tool(3)]}:{status:kind==='incomplete'?'incomplete':'completed',output:[tool(0),tool(1),tool(2),tool(3)]}
              return new Response(JSON.stringify(j))
            })
            try{
              const text=await askAgent(ep,p,'fake','fake','s',[],tools,async()=>{calls++;if(kind==='stop')ctl.abort();return 'ok'},()=>{},kind==='final_calls'?1:4,8000,ctl.signal,{maxToolCalls:2})
              if(!['refusal','budget'].includes(kind)||!text)throw Error('invalid success')
              if(kind==='budget'&&(calls!==2||requests.length!==2))throw Error('call budget')
              if(kind==='budget'){
                const last=requests[1],results=p==='anthropic'?last.messages.at(-1).content:last.input.filter(x=>x.type==='function_call_output')
                if(results.length!==4||(p==='anthropic'?last.tool_choice.type:last.tool_choice)!=='none')throw Error('final-only results')
              }
            }catch(e){if(['refusal','budget'].includes(kind))throw e;if(kind==='stop'&&(e.name!=='AbortError'||calls!==1||requests.length!==1))throw e}
            if(!['budget','stop'].includes(kind)&&calls)throw Error('invalid outcome dispatched tools')
            cases++
          }
          console.log(JSON.stringify({cases}))
        """))
        self.assertEqual(result['cases'],12)


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class PhoneInterleavedCallsTest(unittest.TestCase):
    def test_multiple_fragmented_calls_and_invalid_sibling(self):
        result=json.loads(node(r"""
          import {askAgent,setFetch} from './web/src/mobile/ai/providers.ts'
          const ep={anthropic:'https://api.anthropic.com',openai:'https://api.openai.com'},tools=[{name:'read_items',description:'d',parameters:{}}]
          const enc=new TextEncoder(),frame=e=>`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`
          let providers=0
          for(const p of ['anthropic','openai']){
            const seen=[],requests=[]
            setFetch(async(_,init)=>{
              const b=JSON.parse(init.body);requests.push(b)
              let events=[]
              if(requests.length===1&&p==='anthropic'){
                events=[{type:'message_start',message:{content:[]}}]
                for(let i=0;i<3;i++)events.push({type:'content_block_start',index:i,content_block:{type:'tool_use',id:'c'+i,name:'read_items',input:{}}})
                for(const i of [1,0,2])events.push({type:'content_block_delta',index:i,delta:{type:'input_json_delta',partial_json:i===2?'nu':'{"ids":'}})
                for(const i of [0,2,1])events.push({type:'content_block_delta',index:i,delta:{type:'input_json_delta',partial_json:i===2?'ll':`[${102+i}]}`}})
                for(let i=0;i<3;i++)events.push({type:'content_block_stop',index:i})
                events.push({type:'message_delta',delta:{stop_reason:'tool_use'}},{type:'message_stop'})
              }else if(requests.length===1){
                for(const i of [1,0,2])events.push({type:'response.output_item.added',output_index:i,item:{type:'function_call'}})
                for(const i of [1,0,2])events.push({type:'response.function_call_arguments.delta',output_index:i,delta:'{"ids":'})
                const output=[0,1,2].map(i=>({type:'function_call',call_id:'c'+i,name:'read_items',arguments:i===2?'null':JSON.stringify({ids:[102+i]})}))
                for(const i of [2,0,1])events.push({type:'response.output_item.done',output_index:i,item:output[i]})
                events.push({type:'response.completed',response:{status:'completed',output}})
              }else if(p==='anthropic')events=[{type:'message_start',message:{}},{type:'content_block_start',index:0,content_block:{type:'text',text:''}},{type:'content_block_delta',index:0,delta:{type:'text_delta',text:'Done'}},{type:'content_block_stop',index:0},{type:'message_delta',delta:{stop_reason:'end_turn'}},{type:'message_stop'}]
              else events=[{type:'response.output_text.delta',delta:'Done'},{type:'response.completed',response:{status:'completed',output:[{type:'message',status:'completed',content:[{type:'output_text',text:'Done'}]}]}}]
              return new Response(enc.encode(events.map(frame).join('')))
            })
            const text=await askAgent(ep,p,'fake','fake','s',[],tools,async(n,a)=>{seen.push(a.ids[0]);return 'read'},()=>{},2,8000,undefined,{onText:()=>{},onReset:()=>{}})
            const final=requests[1],results=p==='anthropic'?final.messages.at(-1).content:final.input.filter(x=>x.type==='function_call_output')
            if(text!=='Done'||seen.join()!=='102,103'||results.length!==3||!(p==='anthropic'?results[2].content:results[2].output).startsWith('Error:'))throw Error('interleaved call protocol')
            providers++
          }
          console.log(JSON.stringify({providers}))
        """))
        self.assertEqual(result['providers'],2)
