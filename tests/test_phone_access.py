"""Phone access reasons and local access history. Synthetic grants and storage only."""
import base64
import json
import unittest

from core import license, sync_license
from library import mirror
from tests import test_phone_js


class PhoneAccess(unittest.TestCase):
    def test_refusals_say_why_and_a_restored_pc_is_told_apart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            from tests.license_fixture import activate
            activate(self, Path(folder))
            key = mirror.MirrorKey.generate()
            private = sync_license.signer(Path(folder) / 'control.pem', create=True)
            other = sync_license.signer(Path(folder) / 'other.pem', create=True)     # the same library on a restored PC
            good, moved = json.loads(sync_license.record(key, private)), json.loads(sync_license.record(key, other))
            license.remove()
            locked, lost = json.loads(sync_license.record(key, private)), json.loads(sync_license.record(key, other))
            out = json.loads(test_phone_js.node(f"""
                import {{ ACCESS_INVALID, LICENSE_REQUIRED, LicenseRequired, PC_REPLACED, verifyGrant }} from './web/src/mobile/mirror/license.ts'
                const good = {json.dumps(good)}, moved = {json.dumps(moved)}, locked = {json.dumps(locked)}, lost = {json.dumps(lost)}
                const keys = {json.dumps(list(license.PUBLIC_KEYS))}, fp = {json.dumps(key.fingerprint)}, pc = {json.dumps(sync_license.public(private))}
                const why = async (g, f = fp, now = JSON.parse(g.body).issued, issuers = keys) => {{
                  try {{ await verifyGrant(g, f, pc, issuers, now); return 'granted' }} catch (e) {{ return [e.kind, e.at, e.message] }}
                }}
                const out = {{
                  good: await why(good), moved: await why(moved), expired: await why(good, fp, JSON.parse(good.body).issued + 3600),
                  locked: await why(locked), lost: await why(lost), otherLibrary: await why(moved, 'wrong'), unlicensed: await why(moved, fp, undefined, []),
                  missing: new LicenseRequired(LICENSE_REQUIRED).kind, plain: [new LicenseRequired().kind, new LicenseRequired().message === ACCESS_INVALID],
                }}
                const importKey = crypto.subtle.importKey.bind(crypto.subtle)
                crypto.subtle.importKey = (format, data, alg, ...rest) => alg === 'Ed25519' ? Promise.reject(new DOMException('no Ed25519', 'NotSupportedError')) : importKey(format, data, alg, ...rest)
                out.webview = (await why(good))[0]
                out.replacedWords = out.moved[2] === PC_REPLACED
                for (const k of ['moved', 'expired', 'locked', 'lost', 'otherLibrary', 'unlicensed']) out[k] = out[k].slice(0, 2)
                console.log(JSON.stringify(out))
            """))
            issued = {name: json.loads(g['body'])['issued'] * 1000 for name, g in (('good', good), ('moved', moved))}
            self.assertEqual(out, {
                'good': 'granted', 'moved': ['replaced', issued['moved']], 'expired': ['expired', issued['good']],
                'locked': ['inactive', 0], 'lost': ['invalid', 0], 'otherLibrary': ['invalid', 0], 'unlicensed': ['invalid', 0],
                'missing': 'missing', 'plain': ['invalid', True], 'webview': 'webview', 'replacedWords': True})

    def test_drive_says_why_access_was_refused_and_remembers_the_last_access(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            from tests.license_fixture import activate
            activate(self, Path(folder))
            key = mirror.MirrorKey.generate()
            private = sync_license.signer(Path(folder) / 'control.pem', create=True)
            other = sync_license.signer(Path(folder) / 'other.pem', create=True)
            p = {'v': 2, 'k': key.text(), 'f': key.fingerprint, 'l': sync_license.public(private), 'c': '', 'e': '', 'ai': {}}
            sealed = lambda grant: base64.b64encode(key.seal(sync_license.LOGICAL, grant)).decode()
            valid, moved = sealed(sync_license.record(key, private)), sealed(sync_license.record(key, other))
            out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
                const mem = new Map(), session = new Map()
                globalThis.localStorage = {{ getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k) }}
                globalThis.sessionStorage = {{ getItem:k=>session.get(k)??null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k) }}
                globalThis.window = new EventTarget(); globalThis.document = new EventTarget()
                Object.defineProperty(navigator, 'onLine', {{ value: true }})
                Object.defineProperty(navigator, 'connection', {{ value: Object.assign(new EventTarget(), {{ type: 'wifi' }}) }})
                globalThis.__LICENSE_PUBLIC_KEYS__ = {json.dumps(list(license.PUBLIC_KEYS))}
                const P = await import('./web/src/mobile/mirror/pairing.ts')
                const {{ secrets }} = await import('./web/src/mobile/native.ts')
                const {{ Drive }} = await import('./web/src/mobile/mirror/drive.ts')
                const {{ network }} = await import('./web/src/mobile/network.svelte.ts')
                const {{ lastAccess }} = await import('./web/src/mobile/mirror/license.ts')
                const pair = {json.dumps(p)}
                secrets.set('bp-pair', JSON.stringify({{...pair,g:'fixture@example.com'}}))
                await P.validateStoredPairing()
                let control = ''
                globalThis.fetch = async url => {{
                  if (url.includes('/files?') && new URL(url).searchParams.get('q').includes('{key.name(sync_license.ACCESS_LOGICAL)}')) return Response.json({{ files: [] }})
                  if (url.includes('/files?')) return Response.json({{ files: control ? [{{ id:'control',size:'10000' }}] : [] }})
                  if (url.includes('/files/control?')) return new Response(Buffer.from(control, 'base64'))
                  return new Response('local fixture content')
                }}
                const drive = new Drive('https://www.googleapis.com', ()=>'synthetic', ()=>{{}})
                const seen = []
                const step = async () => {{
                  try {{ await drive.get('content'); seen.push(['granted', network.licenseKind, network.licenseLocked, network.licenseAt]) }}
                  catch (e) {{ seen.push([e.kind, network.licenseKind, network.licenseLocked, network.licenseAt > 0]) }}
                }}
                await step()                                            // the PC has not confirmed this phone yet
                const before = lastAccess(pair.f)
                control = '{valid}'; await step()                       // confirmed
                const after = lastAccess(pair.f)
                control = '{moved}'; await step()                       // the same library, signed by a restored PC
                const now = Date.now; Date.now = () => now() + 3601000
                control = '{valid}'; await step()                       // an hour without a renewal
                Date.now = now
                console.log(JSON.stringify({{ seen, before, after: !!after && after.f === pair.f && Math.abs(after.at - Date.now()) < 60000, other: lastAccess('another') }}))
            """))
            self.assertEqual(out, {'seen': [['missing', 'missing', True, False], ['granted', '', False, 0], ['replaced', 'replaced', True, True],
                                            ['expired', 'expired', True, True]], 'before': None, 'after': True, 'other': None})

    def test_missing_access_history_never_claims_a_removal(self):
        out = json.loads(test_phone_js.node("""
            import { lastAccess, noteAccess } from './web/src/mobile/mirror/license.ts'
            const mem = new Map()
            globalThis.localStorage = {
              getItem: k => mem.get(k) ?? null,
              setItem: (k, v) => mem.set(k, v),
            }
            noteAccess('fixture', 1000)
            const kept = lastAccess('fixture')
            const other = lastAccess('other')
            mem.set('bp-access', 'broken json')
            const broken = lastAccess('fixture')
            globalThis.localStorage = {
              getItem() { throw new Error('storage unavailable') },
              setItem() { throw new Error('storage unavailable') },
            }
            noteAccess('private', 100000)
            console.log(JSON.stringify({kept, other, broken, unavailable: lastAccess('private')}))
        """))
        self.assertEqual(out, {'kept': {'f': 'fixture', 'at': 1000}, 'other': None,
                               'broken': None, 'unavailable': None})
