"""The phone without a PC (projects/mobile-app/plans/08-phone-solo.md): the bundled AI settings match
core/ai_client.py, a second phone rebuilds the library from the change files, and a solo phone that
pairs with a PC sends its whole journal, which the PC applies like any phone change."""
import json
import unittest

from knowledge import prompt_files
from tests import test_phone_js
from tests.test_phone_mirror import ChangeIntakeTest


class PhoneAiFileTest(unittest.TestCase):
    def test_the_bundled_settings_match_ai_client(self):
        got = json.loads((prompt_files.DIR / 'phone_ai.json').read_text(encoding='utf-8'))
        self.assertEqual(got, prompt_files.phone_ai(),
                         'knowledge/prompts/phone_ai.json is stale: run py -m knowledge.prompt_files')


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class SoloJournalTest(ChangeIntakeTest):
    def test_read_back_on_a_second_phone_then_handed_to_a_pc(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const uid = 'ef'.repeat(16)
            // phone A, no PC: a link, its favourite, a note, sent as one change file
            const a = new Changes(), sentA = []
            await a.add({ op: 'link', uid, url: 'https://www.youtube.com/watch?v=solo1', note: 'from the bus', category: '' })
            await a.add({ op: 'fav', uid, on: true })
            await a.add({ op: 'note', file: 'solo-idea-abc123.md', title: 'Solo idea', category: 'General', body: 'Written with no PC.', was: '' })
            await a.flush(async doc => { sentA.push(JSON.parse(JSON.stringify(doc))); return 'chg-a' }, 'pS')
            // phone B on the same recovery code reads that file back
            const b = new Changes()
            const n = await b.merge([{ name: 'chg-a', doc: sentA[0] }])
            const rows = b.overlay([])
            const again = await b.merge([])
            // B pairs with a PC: everything goes again, in one file
            await b.requeue()
            const queued = b.unsent, sentB = []
            await b.flush(async doc => { sentB.push(JSON.parse(JSON.stringify(doc))); return 'chg-b' }, 'pS')
            console.log(JSON.stringify({ n, again, known: [...b.known()], rows: rows.map(r => [r.url, r.fav, r.desc]), unsentAfterMerge: 0, queued, sentB }))
        """))
        self.assertEqual((out['n'], out['again'], out['queued']), (3, 0, 3))
        self.assertEqual(out['rows'], [['https://www.youtube.com/watch?v=solo1', True, 'from the bus']])
        self.assertEqual(out['known'], ['chg-b'])
        doc = out['sentB'][0]
        self.assertEqual([c['op'] for c in doc['changes']], ['link', 'fav', 'note'])
        name, blob = self.key.seal_change(doc)
        self.drive.put(name, blob)
        self.assertTrue(self.svc._intake())
        row = self.writer.read(lambda db: dict(db.conn.execute(
            "SELECT * FROM items WHERE url = 'https://www.youtube.com/watch?v=solo1'").fetchone()))
        self.assertEqual((row['notes'], row['favourite'], row['uid']), ('from the bus', 1, 'ef' * 16))
        self.assertIn('Written with no PC.', (self.data / 'notes' / 'solo-idea-abc123.md').read_text(encoding='utf-8'))


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+')
class SoloBackupTransportTest(unittest.TestCase):
    def test_unlicensed_backup_restore_and_same_account_isolation(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + r"""
            import assert from 'node:assert/strict'
            const mem = new Map(), session = new Map()
            globalThis.localStorage = {getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}
            globalThis.sessionStorage = {getItem:k=>session.get(k)??null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)}
            globalThis.window = new EventTarget(); globalThis.document = new EventTarget()
            Object.defineProperty(navigator,'onLine',{value:true})
            Object.defineProperty(navigator,'connection',{value:Object.assign(new EventTarget(),{type:'wifi'})})
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            const { secrets } = await import('./web/src/mobile/native.ts')
            const { MirrorKey } = await import('./web/src/mobile/mirror/crypto.ts')
            const { Drive } = await import('./web/src/mobile/mirror/drive.ts')
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const code = P.newKeyText(), pc = await MirrorKey.fromText(P.newKeyText())
            await P.startSolo(code)
            const key = await MirrorKey.fromText(code)
            assert.notEqual(key.fingerprint,pc.fingerprint)
            const files = new Map([['desktop',{name:await pc.name('manifest.json'), data:await pc.seal('manifest.json',new TextEncoder().encode('private desktop'))}]])
            const original = Buffer.from(files.get('desktop').data)
            const [legacyName,legacyBlob] = await key.sealChange({format:1,device:'old',at:1,changes:[{op:'note',file:'old.md',body:'Old phone backup',at:1}]})
            files.set('legacy',{name:legacyName,data:legacyBlob})
            let requests=0, retry=false, attempt=0
            globalThis.fetch = async (url,init) => {
              requests++
              if (init.method === 'POST') {
                if(retry) {
                  attempt++
                  await P.startSolo(P.newKeyText())
                  return new Response('',{status:503})
                }
                const body=Buffer.from(init.body), start=body.indexOf('\r\n\r\n')+4
                const meta=JSON.parse(body.subarray(start,body.indexOf('\r\n--',start)).toString())
                const marker=Buffer.from('Content-Type: application/octet-stream\r\n\r\n')
                const data=body.subarray(body.indexOf(marker)+marker.length,body.lastIndexOf('\r\n--'))
                const id='backup'+files.size
                files.set(id,{name:meta.name,data})
                return Response.json({id})
              }
              if(url.includes('/files?')) return Response.json({files:[...files].map(([id,f])=>({id,name:f.name,size:f.data.length}))})
              const id=decodeURIComponent(new URL(url).pathname.split('/').pop())
              assert.equal(init.method,undefined,'No desktop deletion is allowed')
              return new Response(files.get(id).data)
            }
            const drive=new Drive(P.GOOGLE_DRIVE,()=> 'synthetic',()=>{})
            const a=new Changes()
            await a.add({op:'link',uid:'ef'.repeat(16),url:'https://example.com/phone',note:'Phone only'})
            await a.flush(async doc=>{const [name,blob]=await key.sealChange(doc,true);await drive.create(name,blob);return name},'phone')
            const prefix=await key.soloPrefix()
            assert.ok(a.list[0].chg.startsWith(prefix))
            assert.equal(a.unsent,0)
            const before=requests
            for(const action of [()=>drive.create('chg-'+'a'.repeat(32),new Uint8Array([1])),()=>drive.remove('desktop'),()=>drive.get('desktop'),()=>drive.authorize()])
              await assert.rejects(action)
            assert.equal(requests,before)
            await P.startSolo(code) // replacement phone with its saved recovery code
            const restored=new Drive(P.GOOGLE_DRIVE,()=> 'synthetic',()=>{}), b=new Changes()
            const listed=await restored.list(), docs=[]
            for(const f of listed.filter(f=>f.name.startsWith(prefix)||f.name.startsWith('chg-')))
              docs.push({name:f.name,doc:await key.openJSON(f.name,await restored.get(f.id))})
            await b.merge(docs)
            assert.equal(b.overlay([])[0].url,'https://example.com/phone')
            assert.ok(b.list.some(e=>e.op==='note'&&e.body==='Old phone backup'))
            await assert.rejects(()=>restored.get('desktop'))
            await P.startSolo(P.newKeyText())
            const other=new Drive(P.GOOGLE_DRIVE,()=> 'synthetic',()=>{})
            await other.list()
            const ours=[...files].find(([,f])=>f.name.startsWith(prefix))[0]
            const held=requests
            await assert.rejects(()=>other.get(ours))
            assert.equal(requests,held)
            assert.deepEqual(Buffer.from(files.get('desktop').data),original)
            await P.startSolo(code)
            const late=new Drive(P.GOOGLE_DRIVE,()=> 'synthetic',()=>{}), queued=new Changes()
            await queued.add({op:'fav',uid:'ef'.repeat(16),on:true})
            retry=true
            await assert.rejects(()=>queued.flush(async doc=>{const [name,blob]=await key.sealChange(doc,true);await late.create(name,blob);return name},'phone'))
            assert.equal(attempt,1,'A retry must not upload under a replaced phone identity')
            assert.equal(queued.unsent,1)
            assert.equal(queued.list[0].state,'sending')
            console.log(JSON.stringify({restored:b.list.length,desktopUnchanged:true,queued:queued.unsent}))
        """))
        self.assertEqual(out, {'restored': 2, 'desktopUnchanged': True, 'queued': 1})


def load_tests(loader, tests, pattern):
    # only this module's tests: SoloJournalTest borrows ChangeIntakeTest's set-up, not its tests
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(PhoneAiFileTest))
    suite.addTests(loader.loadTestsFromTestCase(SoloBackupTransportTest))
    suite.addTest(SoloJournalTest('test_read_back_on_a_second_phone_then_handed_to_a_pc'))
    return suite
