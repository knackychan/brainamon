"""Shared budget/evidence scenarios over temporary copies of the existing phone library."""
import json
import tempfile
import unittest
from pathlib import Path
from knowledge import librarian
from library import search
from tests import phone_ai_fixture as F
from tests.test_phone_js import node, _node_ok

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests/fixtures/wiskit_agent_cases.json').read_text(encoding='utf-8'))

@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class WiskitBudgetTest(unittest.TestCase):
    def test_reads_and_admission_match_phone(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = F.build(Path(td))
            self.addCleanup(db.close)
            outputs = {}
            for mode in ('quick', 'deep'):
                b = librarian.PROMPTS['agent_budgets'][mode]
                lib = librarian.Librarian(db, search.EmbeddingIndex([]), [], lambda _: None, budget=b)
                ids = [r['id'] for r in F.load()['items']]
                result = lib.run_tool('read_items', {'ids': ids + ids})
                outputs[mode] = {'ids': sorted(lib.evidence), 'admitted': sorted(lib.admitted), 'chars': lib.chars, 'text': result}
                self.assertLessEqual(len(lib.evidence), b['read_max_ids'])
                self.assertLessEqual(lib.chars, b['result_chars'])
                self.assertEqual(lib.evidence, lib.admitted)
                old = set(lib.evidence)
                lib.run_tool('search_library', {'query': 'knee'})
                self.assertEqual(lib.evidence, old)
                lib.chars = b['research_chars'] - librarian.PROMPTS['agent_budgets']['control_chars']
                self.assertIn('exhausted', lib.run_tool('read_items', {'ids': ids}))
                receipt = lib.admit_result('propose_canvas', 'Prepared for review.')
                self.assertEqual(receipt, 'Prepared for review.')
            phone = json.loads(node(r"""
                import fs from 'node:fs'
                import { PhoneLibrary, noteOf } from './web/src/mobile/ai/library.ts'
                import { Librarian } from './web/src/mobile/ai/deep.ts'
                const fx=JSON.parse(fs.readFileSync('tests/fixtures/phone_ai_library.json','utf8'))
                const P=JSON.parse(fs.readFileSync('knowledge/prompts/ask_deep.json','utf8'))
                const lib=new PhoneLibrary(fx.items.map(r=>({id:r.id,s:r.short_desc||'',d:r.description||'',a:r.ai_desc||'',t:r.transcript||'',c:r.creator||'',g:r.tags||'',k:''})),fx.items.map(r=>({id:r.id,cat:r.category,url:r.url,created:0,type:r.type||'Reel'})),fx.notes.map(n=>noteOf(n.file,n.text)))
                const out={}
                for(const mode of ['quick','deep']){
                  const L=new Librarian(P,lib,null,[],async()=>null,async id=>fx.items.find(r=>r.id===id)?.report||'')
                  L.budget=P.agent_budgets[mode]
                  const ids=fx.items.map(r=>r.id)
                  const text=await L.runTool('read_items',{ids:[...ids,...ids]})
                  out[mode]={ids:[...new Set(L.read)].sort((a,b)=>a-b),admitted:[...L.admitted].sort((a,b)=>a-b),chars:L.chars,text}
                }
                console.log(JSON.stringify(out))
            """))
            db.close()
            self.assertEqual(phone, outputs)

    def test_ordered_common_evidence_cases(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db = F.build(Path(td))
            try:
                expected = []
                for case in CASES['cases']:
                    for mode in case['modes']:
                        lib = librarian.Librarian(db, search.EmbeddingIndex([]), [], lambda _:None,
                            budget=librarian.PROMPTS['agent_budgets'][mode])
                        lib.evidence.update(r['id'] for r in db.get_items_by_ids(case['initial_ids']))
                        lib.admitted.update(lib.evidence)
                        for call in case.get('calls', []):
                            if not call['name'].startswith('propose_'):
                                lib.run_tool(call['name'], call['args'])
                        self.assertEqual(sorted(lib.evidence), case.get('expected_evidence', []))
                        expected.append(sorted(lib.evidence))
                phone = json.loads(node(r"""
                    import fs from 'node:fs'
                    import {PhoneLibrary,noteOf} from './web/src/mobile/ai/library.ts'
                    import {Librarian} from './web/src/mobile/ai/deep.ts'
                    const fx=JSON.parse(fs.readFileSync('tests/fixtures/phone_ai_library.json','utf8'))
                    const P=JSON.parse(fs.readFileSync('knowledge/prompts/ask_deep.json','utf8'))
                    const C=JSON.parse(fs.readFileSync('tests/fixtures/wiskit_agent_cases.json','utf8'))
                    const lib=new PhoneLibrary(fx.items.map(r=>({id:r.id,s:'',d:r.description||'',a:r.ai_desc||'',t:r.transcript||'',c:r.creator||'',g:r.tags||'',k:''})),fx.items.map(r=>({id:r.id,cat:r.category,url:r.url,created:0,type:r.type||'Reel'})),fx.notes.map(n=>noteOf(n.file,n.text)))
                    const out=[]
                    for(const c of C.cases)for(const mode of c.modes){
                      const L=new Librarian(P,lib,null,[],async()=>null,async id=>fx.items.find(r=>r.id===id)?.report||'')
                      L.budget=P.agent_budgets[mode]
                      for(const r of lib.getItemsByIds(c.initial_ids)){L.read.push(r.id);L.admitted.add(r.id)}
                      for(const call of c.calls||[])if(!call.name.startsWith('propose_'))await L.runTool(call.name,call.args)
                      out.push([...new Set(L.read)].sort((a,b)=>a-b))
                    }
                    console.log(JSON.stringify(out))
                """))
                self.assertEqual(phone, expected)
            finally: db.close()

    def test_unicode_json_trimming_grants_only_exposed_elements(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db=F.build(Path(td))
            try:
                view={'id':'board','name':'😀','count':8,'shown':8,'truncated':False,
                      'elements':[{'id':str(i),'text':'😀é'*600} for i in range(8)]}
                lib=librarian.Librarian(db,search.EmbeddingIndex([]),[],lambda _:None,budget=librarian.PROMPTS['agent_budgets']['quick'])
                text=lib.admit_result('read_canvas',json.dumps(view,ensure_ascii=False))
                data=json.loads(text)
                self.assertTrue(data['truncated'])
                self.assertLess(len(data['elements']),8)
                self.assertEqual(lib.canvases['board'],{e['id'] for e in data['elements']})
                phone=json.loads(node(r"""
                  import fs from 'node:fs'
                  import {Librarian} from './web/src/mobile/ai/deep.ts'
                  const P=JSON.parse(fs.readFileSync('knowledge/prompts/ask_deep.json','utf8'))
                  const L=new Librarian(P,{},null,[],async()=>null,async()=>''),view={id:'board',name:'😀',count:8,shown:8,truncated:false,elements:Array.from({length:8},(_,i)=>({id:String(i),text:'😀é'.repeat(600)}))}
                  L.budget=P.agent_budgets.quick
                  const text=L.admitResult('read_canvas',JSON.stringify(view))
                  console.log(JSON.stringify({text,chars:L.chars,ids:[...L.canvases.get('board')]}))
                """))
                self.assertEqual(phone,{'text':text,'chars':len(text),'ids':[e['id'] for e in data['elements']]})
            finally: db.close()

    def test_low_agent_caps_and_cloud_floor(self):
        from core import ai_client
        from knowledge import ask_core
        from unittest import mock
        with mock.patch.object(ai_client,'_AGENT_MAX_ROUNDS',1),mock.patch.object(ai_client,'_AGENT_MAX_TOKENS',100):
            for mode in ('quick','deep'):
                self.assertEqual(ask_core.agent_budget(mode)['max_rounds'],1)
                self.assertEqual(ask_core.agent_budget(mode)['max_tokens'],8000)
        with mock.patch.object(ai_client,'_ASK_CLOUD_MIN_TOKENS',20000):
            with self.assertRaisesRegex(ValueError,'Incompatible'): ask_core.agent_budget('quick')

    def test_common_cases_and_values_are_shared(self):
        self.assertEqual(CASES['library_fixture'], 'phone_ai_library.json')
        self.assertGreaterEqual(len(CASES['cases']), 3)
        b = librarian.PROMPTS['agent_budgets']
        self.assertEqual(b['quick']['max_rounds'], 4)
        self.assertEqual(b['quick']['max_tokens'], 8000)
        self.assertLess(b['quick']['max_items'], b['deep']['max_items'])

if __name__ == '__main__': unittest.main()
