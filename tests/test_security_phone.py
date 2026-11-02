"""Production phone trust boundaries, under Node with synthetic browser storage."""
import base64
import hashlib
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from library import mirror
from tests import test_phone_js


@unittest.skipUnless(test_phone_js._node_ok(), 'requires installed Node with type stripping')
class PhoneSecurity(unittest.TestCase):
    def test_pairing_override_fingerprint_version_and_cancel_are_inert(self):
        key = mirror.MirrorKey.generate()
        p = {'v': 2, 'l': 'A' * 122, 'k': key.text(), 'c': '', 'e': '', 'f': key.fingerprint}
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem = new Map(), session = new Map()
            globalThis.localStorage = {{getItem: k => mem.get(k) ?? null, setItem: (k,v) => mem.set(k,v), removeItem: k => mem.delete(k)}}
            globalThis.sessionStorage = {{getItem: k => session.get(k) ?? null, setItem: (k,v) => session.set(k,v), removeItem: k => session.delete(k)}}
            globalThis.fetch = () => {{ throw Error('No network authorized') }}
            const P = await import('./web/src/mobile/mirror/pairing.ts')
            const good = {json.dumps(p)}
            const link = p => '#pair=' + Buffer.from(JSON.stringify(p)).toString('base64url')
            const bad = [{{...good,d:'http://127.0.0.1:18766'}}, {{...good,x:{{openai:'https://evil.invalid'}}}}, {{...good,v:99}}, {{...good,f:'000000000000'}}, {{...good,ai:{{openai:'synthetic'}}}}]
            for (const p of bad) {{ await P.acceptLink(link(p)); if(mem.size) throw Error('Rejected pairing changed storage') }}
            mem.set('bp-pair', JSON.stringify({{...good,d:'https://evil.invalid',ai:{{}}}}))
            await P.validateStoredPairing()
            if(P.pairing()) throw Error('Stored override survived')
            mem.clear()
            await P.startSolo(P.newKeyText())
            const before = JSON.stringify([...mem])
            globalThis.confirm = () => false
            await P.acceptLink(link(good))
            if(JSON.stringify([...mem]) !== before || mem.has('bp-requeue')) throw Error('Cancel changed state')
            globalThis.confirm = () => true
            await P.acceptLink(link(good))
            console.log(JSON.stringify({{ paired: P.pairing()?.f === good.f, requeue: P.takeRequeue() }}))
        """))
        self.assertEqual(result, {'paired': True, 'requeue': True})

    def test_transfer_expiry_before_network_and_after_download(self):
        one, expiry, name, blob = mirror.pair_drop({'openai': 'synthetic-key'})
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem = new Map()
            globalThis.localStorage = {{getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}}
            const {{takeKeys}} = await import('./web/src/mobile/mirror/pairing.ts')
            let calls=0
            const late={{t:{json.dumps(one.text())},tx:1,ai:{{}}}}
            const never={{find:async()=>{{calls++;throw Error('Expired transfer requested')}}}}
            await takeKeys(late,never)
            const missing={{t:{json.dumps(one.text())},ai:{{}}}}
            await takeKeys(missing,never)
            const p={{t:{json.dumps(one.text())},tx:{expiry},ai:{{}}}}
            const oldNow=Date.now
            const drive={{find:async()=>({{id:'synthetic'}}),get:async()=>{{Date.now=()=>({expiry}+1)*1000;return Uint8Array.from(Buffer.from({json.dumps(base64.b64encode(blob).decode())},'base64'))}},remove:async()=>{{throw Error('should not delete')}}}}
            await takeKeys(p,drive)
            Date.now=oldNow
            console.log(JSON.stringify({{calls,kept:Object.keys(p.ai).length,cleared:!p.t&&!late.t&&!missing.t}}))
        """))
        self.assertEqual(result, {'calls': 0, 'kept': 0, 'cleared': True})

    def test_late_transfer_cannot_restore_a_replaced_pairing(self):
        one, expiry, _, blob = mirror.pair_drop({'openai': 'synthetic-key'})
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem=new Map()
            globalThis.localStorage={{getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}}
            const P=await import('./web/src/mobile/mirror/pairing.ts')
            const {{secrets}}=await import('./web/src/mobile/native.ts')
            const p={{t:{json.dumps(one.text())},tx:{expiry},ai:{{}}}}
            secrets.set('bp-pair',JSON.stringify(p))
            let removed=false
            const drive={{find:async()=>({{id:'synthetic'}}),get:async()=>{{secrets.set('bp-pair','replacement');return Uint8Array.from(Buffer.from({json.dumps(base64.b64encode(blob).decode())},'base64'))}},remove:async()=>{{removed=true}}}}
            await P.takeKeys(p,drive)
            console.log(JSON.stringify({{pair:secrets.get('bp-pair'),removed,keys:Object.keys(p.ai).length}}))
        """))
        self.assertEqual(result, {'pair': 'replacement', 'removed': False, 'keys': 0})

    def test_valid_transfer_survives_best_effort_remote_delete_failure(self):
        one, expiry, _, blob = mirror.pair_drop({'openai': 'synthetic-key'})
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem=new Map()
            globalThis.localStorage={{getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}}
            const P=await import('./web/src/mobile/mirror/pairing.ts')
            const p={{t:{json.dumps(one.text())},tx:{expiry},ai:{{}}}}
            const drive={{find:async()=>({{id:'synthetic'}}),get:async()=>Uint8Array.from(Buffer.from({json.dumps(base64.b64encode(blob).decode())},'base64')),remove:async()=>{{throw Error('synthetic failure')}}}}
            const note=await P.takeKeys(p,drive)
            console.log(JSON.stringify({{kept:p.ai.openai==='synthetic-key',cleared:!p.t,warning:note.includes('could not be confirmed')}}))
        """))
        self.assertEqual(result, {'kept': True, 'cleared': True, 'warning': True})

    def test_zip_stream_caps_actual_inflation_and_validates_lengths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            normal = json.dumps([{'label_values': [{'label': 'URL', 'value': 'https://www.instagram.com/reel/synthetic/'}]}]).encode()
            for name, payload in [('normal', normal), ('cap', normal + b' ' * (2048 - len(normal))), ('bomb', normal + b' ' * 2048)]:
                with zipfile.ZipFile(root / (name + '.zip'), 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('saved_posts.json', payload)
            dishonest = bytearray((root / 'bomb.zip').read_bytes())
            central = dishonest.index(b'PK\x01\x02')
            struct.pack_into('<I', dishonest, central + 24, 1)
            (root / 'dishonest.zip').write_bytes(dishonest)
            # A lower test cap keeps all payloads bounded while exercising the exact production code.
            code = (Path(__file__).resolve().parents[1] / 'web/src/mobile/imports.ts').read_text().replace('60 * 1024 * 1024', '2048')
            (root / 'imports.ts').write_text(code)
            result = json.loads(test_phone_js.node(f"""
                import fs from 'node:fs'
                const I=await import({json.dumps((root / 'imports.ts').as_uri())})
                const names=['normal','cap','bomb','dishonest'], out=[]
                for(const n of names){{try{{await I.readExport(new Uint8Array(fs.readFileSync({json.dumps(str(root))}+'/'+n+'.zip')));out.push('ok')}}catch(e){{out.push(e.message===I.TOO_BIG?'size':'format')}}}}
                console.log(JSON.stringify(out))
            """))
            self.assertEqual(result, ['ok', 'ok', 'size', 'size'])

    def test_video_python_typescript_complete_digest_parity(self):
        key = mirror.MirrorKey.generate()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = b'first---second--end'
            with unittest.mock.patch.object(mirror, 'VIDEO_CHUNK', 8):
                src = root / 'video'
                src.write_bytes(data)
                key.seal_file('videos/u.bin', src, root / 'sealed')
            integrity = {'integrity': 2, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            blob = base64.b64encode((root / 'sealed').read_bytes()).decode()
            result = json.loads(test_phone_js.node(f"""
                import {{MirrorKey}} from './web/src/mobile/mirror/crypto.ts'
                const key=await MirrorKey.fromText({json.dumps(key.text())}), blob=Uint8Array.from(Buffer.from({json.dumps(blob)},'base64')), expected={json.dumps(integrity)}
                const out=await key.openVideo('videos/u.bin',blob,expected)
                let refused=0
                for(const [b,e] of [[blob.slice(0,44),expected],[blob,{{}}],[blob,{{...expected,sha256:'0'.repeat(64)}}]] ){{try{{await key.openVideo('videos/u.bin',b,e)}}catch{{refused++}}}}
                console.log(JSON.stringify({{text:Buffer.concat(out).toString(),refused}}))
            """))
            self.assertEqual(result, {'text': data.decode(), 'refused': 3})

    def test_zip_stored_bounds_malformed_and_stream_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            module = Path(folder) / 'imports.ts'
            source = Path(__file__).resolve().parents[1] / 'web/src/mobile/imports.ts'
            module.write_text(source.read_text(encoding='utf-8').replace('60 * 1024 * 1024', '2048'), encoding='utf-8')
            result = json.loads(test_phone_js.node(f"""
                const I=await import({json.dumps(module.as_uri())})
                const bytes=new Uint8Array(31);bytes.set([0x50,0x4b,3,4])
                const entry={{at:0,packed:1,size:1,method:0,name:'saved_posts.json'}}, out=[]
                out.push((await I.unzipEntry(bytes,entry)).length)
                for(const z of [{{...entry,size:2}},{{...entry,packed:999}},{{...entry,method:8}}]){{
                  try{{await I.unzipEntry(bytes,z);out.push('accepted')}}catch(e){{out.push(e.message===I.NOT_SAVED?'format':'other')}}
                }}
                let cancelled=0,released=0
                globalThis.Blob=class{{stream(){{return{{pipeThrough(){{return{{getReader(){{return{{read:async()=>({{done:false,value:new Uint8Array(2049)}}),cancel:async()=>{{cancelled++}},releaseLock:()=>{{released++}}}}}}}}}}}}}}}}
                try{{await I.unzipEntry(bytes,{{...entry,method:8}})}}catch(e){{out.push(e.message===I.TOO_BIG?'size':'other')}}
                console.log(JSON.stringify({{out,cancelled,released}}))
            """))
            self.assertEqual(result, {'out': [1, 'format', 'format', 'format', 'size'], 'cancelled': 1, 'released': 1})
