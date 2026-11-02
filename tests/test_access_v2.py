"""New access grants do not contain a receipt; legacy signatures remain tested separately."""
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from core import license, sync_license
from library import drive_client, mirror
from tests import test_phone_js, test_sync


class AccessProtocolTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='access-v2-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.key = mirror.MirrorKey.generate()
        self.private = sync_license.signer(self.root / 'control.pem', create=True)
        self.public = sync_license.public(self.private)
        self.now = int(time.time())

    def envelope(self, enabled=True):
        with mock.patch.object(sync_license.time, 'time', return_value=self.now):
            return json.loads(sync_license.access_record(self.key, self.private, enabled))

    def test_v2_signature_schema_clock_and_no_payment_payload(self):
        good, disabled = self.envelope(), self.envelope(False)
        body = json.loads(good['body'])
        self.assertEqual(set(body), {'v', 'fp', 'issued', 'expires', 'enabled'})
        self.assertNotIn('license', body)
        with self.assertRaises(ValueError):
            self.envelope('false')
        wrong = sync_license.signer(self.root / 'wrong.pem', create=True)
        cases = [(disabled, self.key.fingerprint, self.public, self.now),
                 (good, 'wrong-fingerprint', self.public, self.now),
                 (good, self.key.fingerprint, sync_license.public(wrong), self.now),
                 (good, self.key.fingerprint, self.public, self.now - 1),
                 (good, self.key.fingerprint, self.public, self.now + 3600),
                 ({**good, 'body': good['body'] + ' '}, self.key.fingerprint, self.public, self.now),
                 ({**good, 'publicKey': sync_license.public(wrong)}, self.key.fingerprint, self.public, self.now)]
        for change in ({'v': 1}, {'enabled': 'true'}, {'issued': True}, {'expires': body['expires'] + 1},
                       {'expires': body['issued']}, {'issued': -1}, {'license': 'not-allowed'}):
            cases.append((json.loads(sync_license._signed({**body, **change}, self.private)),
                          self.key.fingerprint, self.public, self.now))
        result = json.loads(test_phone_js.node(f"""
            import {{ verifyAccess }} from './web/src/mobile/mirror/license.ts'
            const good = {json.dumps(good)}, cases = {json.dumps(cases)}
            let refused = 0
            for (const args of cases) {{ try {{ await verifyAccess(...args) }} catch {{ refused++ }} }}
            const expires = await verifyAccess(good, {json.dumps(self.key.fingerprint)}, {json.dumps(self.public)}, {self.now})
            console.log(JSON.stringify({{refused, expires}}))
        """))
        self.assertEqual(result, {'refused': len(cases), 'expires': self.now + 3600})

    def test_stale_settings_and_first_key_transfer_preserve_verified_v2(self):
        pair = {'v': 2, 'k': self.key.text(), 'f': self.key.fingerprint, 'l': self.public,
                'c': '', 'e': '', 'ai': {}, 'g': 'synthetic@example.invalid',
                't': self.key.text(), 'tx': self.now + 1800, 'at': 1}
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem = new Map()
            globalThis.localStorage = {{getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,v),removeItem:k=>mem.delete(k)}}
            globalThis.sessionStorage = {{getItem:()=>null,setItem:()=>{{}},removeItem:()=>{{}}}}
            globalThis.window=new EventTarget();globalThis.document=new EventTarget()
            const P=await import('./web/src/mobile/mirror/pairing.ts')
            const {{secrets,secretsSaved}}=await import('./web/src/mobile/native.ts')
            const stale={json.dumps(pair)}
            secrets.set('bp-pair',JSON.stringify(stale));await P.validateStoredPairing()
            const note=await P.takeKeys(stale,{{find:async()=>{{await P.confirmAccessV2(P.pairing());return null}}}})
            if(note!=='')throw Error('First v2 confirmation cancelled key transfer')
            for(const edit of [()=>P.setAiKeys(stale,{{openai:'synthetic'}}),()=>P.confirmAccount(stale,'synthetic@example.invalid'),
                               ()=>P.forgetKeys(stale),()=>P.disconnectDrive(stale)]){{
              delete stale.accessVersion // each caller can have a pre-confirmation snapshot
              edit();await secretsSaved()
              if(P.pairing().accessVersion!==2||JSON.parse(mem.get('bp-pair')).accessVersion!==2)throw Error('Settings erased watermark')
            }}
            const qr={{...stale}};delete qr.accessVersion
            await P.acceptLink('#pair='+Buffer.from(JSON.stringify(qr)).toString('base64url'))
            console.log(JSON.stringify({{note,watermark:P.pairing().accessVersion}}))
        """))
        self.assertEqual(result, {'note': '', 'watermark': 2})

    def test_transport_no_fallback_after_invalid_or_seen_v2_and_storage_failure(self):
        from tests.license_fixture import activate
        activate(self, self.root)
        legacy = sync_license.record(self.key, self.private)
        seal = lambda logical, raw: base64.b64encode(self.key.seal(logical, raw)).decode()
        v2 = seal(sync_license.ACCESS_LOGICAL, json.dumps(self.envelope()).encode())
        disabled = seal(sync_license.ACCESS_LOGICAL, json.dumps(self.envelope(False)).encode())
        v1 = seal(sync_license.LOGICAL, legacy)
        pair = {'v': 2, 'k': self.key.text(), 'f': self.key.fingerprint, 'l': self.public,
                'c': '', 'e': '', 'ai': {}, 'g': 'synthetic@example.invalid'}
        result = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + f"""
            const mem = new Map(), session = new Map()
            let failStorage = false
            globalThis.localStorage = {{getItem:k=>mem.get(k)??null,setItem:(k,v)=>{{if(failStorage)throw Error('Synthetic storage full');mem.set(k,v)}},removeItem:k=>mem.delete(k)}}
            globalThis.sessionStorage = {{getItem:k=>session.get(k)??null,setItem:(k,v)=>session.set(k,v),removeItem:k=>session.delete(k)}}
            globalThis.window=new EventTarget();globalThis.document=new EventTarget()
            Object.defineProperty(navigator,'onLine',{{value:true}})
            Object.defineProperty(navigator,'connection',{{value:Object.assign(new EventTarget(),{{type:'wifi'}})}})
            globalThis.__LICENSE_PUBLIC_KEYS__={json.dumps(list(license.PUBLIC_KEYS))}
            const P=await import('./web/src/mobile/mirror/pairing.ts')
            const {{secrets}}=await import('./web/src/mobile/native.ts')
            const {{MirrorKey}}=await import('./web/src/mobile/mirror/crypto.ts')
            const {{Drive}}=await import('./web/src/mobile/mirror/drive.ts')
            const pair={json.dumps(pair)}, key=await MirrorKey.fromText(pair.k)
            const v2name=await key.name('control/access-v2.json')
            const v2='{v2}', disabled='{disabled}', legacy='{v1}'
            let state='absent', content=0, legacyReads=0, v2Reads=0
            globalThis.fetch=async url=>{{
              if(url.includes('/files?')){{
                const isV2=new URL(url).searchParams.get('q').includes(v2name)
                if(isV2){{v2Reads++; if(state==='incomplete')return Response.json({{files:[],incompleteSearch:true}});if(state==='page')return Response.json({{files:[],nextPageToken:'more'}});return Response.json({{files:state==='absent'?[]:[{{id:'v2',size:'10000'}}]}})}}
                legacyReads++;return Response.json({{files:[{{id:'legacy',size:'10000'}}]}})
              }}
              if(url.includes('/files/legacy?'))return new Response(Buffer.from(legacy,'base64'))
              if(url.includes('/files/v2?'))return new Response(state==='broken'?new Uint8Array([1]):Buffer.from(state==='disabled'?disabled:v2,'base64'))
              content++;return new Response('synthetic content')
            }}
            async function reset(){{secrets.set('bp-pair',JSON.stringify(pair));await P.validateStoredPairing()}}
            await reset()
            const drive=()=>new Drive('https://www.googleapis.com',()=> 'synthetic',()=>{{}})
            await drive().get('content') // old PC: authenticated v2 absence permits genuine legacy v1
            if(content!==1||legacyReads!==1)throw Error('Legacy compatibility failed')
            let refused=0
            for(state of ['broken','disabled','incomplete','page']){{
              const before=legacyReads
              try{{await drive().get('content')}}catch{{refused++}}
              if(legacyReads!==before||content!==1)throw Error('Invalid v2 fell back')
            }}
            state='valid';failStorage=true
            try{{await drive().get('content')}}catch{{refused++}}
            if(content!==1)throw Error('Unsaved v2 was granted')
            failStorage=false
            await drive().get('content')
            if(P.pairing().accessVersion!==2||JSON.parse(mem.get('bp-pair')).accessVersion!==2)throw Error('Watermark not durable')
            const saved=secrets.get('bp-pair'), before=legacyReads
            secrets.set('bp-pair',saved);await P.validateStoredPairing() // fresh Drive reads the persisted pairing
            state='absent'
            try{{await drive().get('content')}}catch{{refused++}}
            if(legacyReads!==before||content!==2)throw Error('Seen v2 downgraded')
            console.log(JSON.stringify({{refused,content,legacyReads}}))
        """))
        self.assertEqual(result, {'refused': 6, 'content': 2, 'legacyReads': 1})


class AccessPublicationTest(unittest.TestCase):
    def setUp(self):
        self.fx = test_sync.ServiceTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(self.fx.tearDown)
        self.svc, self.drive = self.fx.svc, self.fx.drive
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})

    def test_v2_renewal_survives_receipt_removal_and_legacy_failure_bound_is_honest(self):
        key = self.svc.mirror_key()
        license.remove()
        self.svc.publish_license_control()
        raw = key.open(sync_license.ACCESS_LOGICAL, self.drive.by_name(key.name(sync_license.ACCESS_LOGICAL)))
        body = json.loads(json.loads(raw)['body'])
        self.assertTrue(body['enabled'])
        self.assertEqual(self.svc._grant, (key.fingerprint, body['expires'] * 1000))
        old = json.loads(json.loads(key.open(sync_license.LOGICAL, self.drive.by_name(key.name(sync_license.LOGICAL))))['body'])
        self.assertEqual(old['license'], '')
        upload = self.drive.upload

        def fail_legacy(name, *args, **kwargs):
            if name == key.name(sync_license.LOGICAL):
                raise drive_client.DriveError('Synthetic legacy upload failed')
            return upload(name, *args, **kwargs)

        future = body['issued'] + 300
        self.drive.upload = fail_legacy
        with mock.patch.object(sync_license.time, 'time', return_value=future):
            with self.assertRaises(drive_client.DriveError):
                self.svc.publish_license_control()
        self.assertEqual(self.svc._grant[1], (future + 3600) * 1000)

    def test_receipt_change_does_not_enable_or_disable_saved_sync_switches(self):
        self.svc.mirror_key()
        before = self.svc.writer.read(lambda db: [db.get_setting(k, '') for k in ('cloud_upload', 'cloud_vault')])
        license.remove()
        with mock.patch.object(self.svc, 'start') as start, mock.patch.object(self.svc, 'start_vault') as vault, \
                mock.patch.object(self.svc, '_end_mirror') as end_mirror, mock.patch.object(self.svc, '_end_vault') as end_vault:
            self.svc.license_changed()
            for action in (start, vault, end_mirror, end_vault):
                action.assert_not_called()
        self.assertFalse(self.svc.running)
        self.assertFalse(self.svc.vault_running)
        self.assertEqual(self.svc.writer.read(lambda db: [db.get_setting(k, '') for k in ('cloud_upload', 'cloud_vault')]), before)

    def test_explicit_unpair_locks_out_both_protocols(self):
        old = self.svc.mirror_key()
        self.svc.publish_license_control()
        names = {old.name(path) for path in sync_license.CONTROL_LOGICALS}
        self.assertTrue(names <= {name for name, _ in self.drive.files.values()})
        self.svc.unpair()
        self.assertTrue(self.fx.wait(lambda: bool(self.svc.status()['rotation_locked_at'])))
        self.assertFalse(names & {name for name, _ in self.drive.files.values()})


if __name__ == '__main__':
    unittest.main()
