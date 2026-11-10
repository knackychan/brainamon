"""Describe on synthetic phone items; model calls and changes stay in memory."""
import unittest

from tests.test_mobile_info_browser import mobile_browser, synthetic_phone


class PhoneDescribeBrowser(unittest.TestCase):
    def test_evidence_and_sentinel(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 780, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            result = page.evaluate("""async () => {
              const {MirrorSource} = await import('/src/mobile/source/mirror.ts');
              const {Changes} = await import('/src/mobile/mirror/changes.ts');
              const {setFetch} = await import('/src/mobile/ai/providers.ts');
              let reply = 'A real description', calls = [], edits = [], current, thumb = false;
              setFetch(async (url, init) => {
                calls.push(JSON.parse(init.body));
                return new Response(JSON.stringify({content:[{type:'text',text:reply}]}), {status:200});
              });
              const s = Object.create(MirrorSource.prototype);
              s.byId = new Map([[1, {id:1,uid:'synthetic'}]]); s.texts = new Map();
              s.ready = async () => {}; s.item = async () => current;
              s.thumbBlob = async () => thumb ? new Blob(['x'], {type:'image/jpeg'}) : null;
              s.itemAi = () => ({p:'anthropic',key:'fake',model:'fixture',cap:n=>n});
              s.endpoints = () => ({anthropic:'https://api.anthropic.com',openai:'https://api.openai.com'});
              s.changes = {add: async edit => edits.push(edit)}; s.setRows = () => {}; s.flushSoon = () => {};
              const empty = {id:1,url:'https://test.com/',description:'test.com',notes:'',ai_desc:''};
              const run = async (fields={}, image=false, answer='A real description') => {
                current = {...empty,...fields}; thumb = image; reply = answer;
                s.texts.set(1, {report:fields.report || '',transcript:fields.transcript || '',notes:current.notes});
                const beforeCalls = calls.length, beforeEdits = edits.length;
                const text = await s.describe(1);
                return {text,calls:calls.length-beforeCalls,edits:edits.length-beforeEdits,
                        prompt:calls.length>beforeCalls ? JSON.stringify(calls.at(-1)) : ''};
              };
              const results = [await run(), await run({description:'https://test.com/ A useful caption'}),
                await run({},true), await run({description:'A caption'},false,'NO_CONTENT'),
                await run({report:'Specific report'}), await run({notes:'A user note'}),
                await run({transcript:'A spoken detail'})];
              const changes = new Changes();
              changes.list = [{op:'edit',uid:'synthetic',fields:{ai_desc:' NO_CONTENT '}}];
              const overlay = changes.overlay([{id:1,uid:'synthetic',url:'https://test.com/',ai:true,desc:'Old text'}])[0];
              return {results,overlay};
            }""")
            self.assertFalse(result['overlay']['ai'])
            self.assertEqual(result['overlay']['desc'], '')
            result = result['results']
            self.assertEqual([(r['text'], r['calls'], r['edits']) for r in result[:4]], [
                (None, 0, 0), ('A real description', 1, 1),
                ('A real description', 1, 1), (None, 1, 0)])
            for item in result[4:]:
                self.assertEqual((item['text'], item['calls'], item['edits']), ('A real description', 1, 1))
            self.assertIn('Specific report', result[4]['prompt'])
            self.assertIn('A user note', result[5]['prompt'])
            self.assertIn('A spoken detail', result[6]['prompt'])
            self.assertEqual(errors, [])

    def test_processing_reports_each_outcome(self):
        from playwright.sync_api import expect

        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 780, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            page.evaluate("""async () => {
              const {phone,source} = await import('/src/mobile/state.svelte.ts');
              const rows = [1,2,3].map(id => ({id,title:'Item '+id,creator:'',type:'Post',cat:'Art',tags:'',desc:'',
                url:'https://example.com/'+id,src:'web',thumb:false,ai:false,an:false,nd:2,fav:false,created:id,tv:0}));
              phone.rows = rows; phone.loaded = true; phone.cat = 'all';
              source.ai = () => ({provider:'fixture',model:'fixture',label:'Fixture AI'});
              source.rowsByIds = async ids => rows.filter(r => ids.includes(r.id));
              source.rows = async () => ({rows,cats:[]});
              source.describe = async id => { if (id===2) return null; if (id===3) throw Error('Synthetic failure'); return 'Described'; };
            }""")
            page.get_by_role('button', name='Tools', exact=True).click()
            panel = page.get_by_role('dialog', name='Tools', exact=True)
            # projects/phone-processing-flow: one tap on the step row runs it; the finished ledger gives each reason
            panel.get_by_role('button', name='Describe', exact=True).click()
            expect(panel.locator('.m-runbar')).to_contain_text('1 described · 1 skipped · 1 failed')
            expect(panel).to_contain_text('Nothing to describe yet: open it online once or add a note')
            expect(panel).to_contain_text('Synthetic failure')
            page.keyboard.press('Escape')
            hello = page.evaluate("""async () => {
              const {source} = await import('/src/mobile/state.svelte.ts');
              const {DesktopSource} = await import('/src/mobile/source/desktop.ts');
              const {pcResult} = await import('/src/mobile/work.svelte.ts');
              source.kind = 'desktop';
              const events = new EventTarget(); new DesktopSource().watchJob(events);
              const snap = {id:42,kind:'describe',state:'finished',done:1,skipped:2,err:1,detail:'Add an AI key on the PC.'};
              events.dispatchEvent(new MessageEvent('hello', {data:JSON.stringify({jobs:{current:null,last:snap}})}));
              const seen = {...pcResult};
              events.dispatchEvent(new MessageEvent('job', {data:JSON.stringify({current:null,last:{...snap,id:43}})}));
              return seen;
            }""")
            self.assertEqual((hello['job'], hello['done'], hello['skipped'], hello['err']), (42, 1, 2, 1))
            page.get_by_role('button', name='Tools', exact=True).click()
            expect(panel.get_by_role('status')).to_contain_text('Last PC Describe: 1 described · 2 skipped · 1 failed')
            expect(panel.get_by_role('status')).to_contain_text('Nothing to describe yet: open it online once or add a note')
            expect(panel.get_by_role('alert')).to_contain_text('Add an AI key on the PC.')
            self.assertEqual(errors, [])
