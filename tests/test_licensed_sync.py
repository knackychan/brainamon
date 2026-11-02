"""Licensed pairing, worker races and authenticated phone grants, with disposable keys/data."""
import base64
import json
import threading
import time
import unittest
from unittest import mock

from core import license, sync_license
from library import drive_client, mirror
from tests import test_server_license, test_sync, test_phone_js


class Routes(test_server_license.LicenseRoutesTest):
    def test_pairing_and_receipt_changes_keep_the_same_security_identity(self):
        svc = self.c.app.state.sync
        fp = None
        for receipt in ('', 'damaged'):
            if receipt:
                license.LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
                license.LICENSE_PATH.write_text(receipt)
            response = self.c.post('/api/cloud/pair', headers=test_server_license.W)
            self.assertEqual(response.status_code, 200)
            data = json.loads(base64.urlsafe_b64decode(response.json()['code'] + '=' * (-len(response.json()['code']) % 4)))
            self.assertEqual(len(data['l']), 122)
            fp = fp or data['f']
            self.assertEqual(data['f'], fp)
        self.assertEqual(self.c.put('/api/license', json={'key': self.key}, headers=test_server_license.W).status_code, 200)
        self.assertEqual(self.c.put('/api/license', json={'key': 'bad'}, headers=test_server_license.W).status_code, 400)
        self.assertEqual(self.c.delete('/api/license', headers=test_server_license.W).status_code, 200)
        self.assertTrue(svc.status()['licensed'])
        self.assertEqual(mirror.MirrorKey.load(svc.key_path).fingerprint, fp)
        self.assertEqual(self.c.post('/api/cloud/pair', headers=test_server_license.W).status_code, 200)
        self.assertNotIn(self.key, response.text)
        self.assertNotIn('Test Buyer', response.text)

    def test_direct_phone_still_requires_the_local_credential_but_no_receipt(self):
        self.assertEqual(self.c.get('/api/items', headers={'X-Brainamon-Phone': '1'}).status_code, 200)
        self.assertEqual(self.c.post('/api/cloud/pair', headers={'X-Brainamon-Phone': '1'}).status_code, 403)
        self.assertEqual(self.c.post('/api/cloud/pair', headers=test_server_license.W).status_code, 200)


class Workers(unittest.TestCase):
    def setUp(self):
        self.fx = test_sync.ServiceTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.addCleanup(self.fx.tearDown)
        self.svc, self.drive = self.fx.svc, self.fx.drive
        drive_client.save_token(self.svc.token_path, {'refresh_token': 'synthetic'})
        self.saved = license.LICENSE_PATH.read_text()

    def test_boot_honors_saved_switches_without_requiring_a_receipt(self):
        license.remove()
        self.svc.writer.call(lambda db: (db.set_setting('cloud_upload', 'on'), db.set_setting('cloud_vault', 'on')))
        with mock.patch.object(self.svc, 'start_vault') as vault:
            self.svc.boot()
            vault.assert_called_once()
            self.assertTrue(self.fx.wait(lambda: self.svc.status()['last_publish']))
        self.assertTrue(self.svc.running)
        self.assertIsNone(sync_license.signer(self.svc.control_key_path), 'Backup alone must not silently pair a phone')
        key = self.svc.mirror_key()       # explicit pairing is available with no receipt
        self.assertIsNotNone(key)
        self.assertIsNotNone(sync_license.signer(self.svc.control_key_path))

    def test_removal_during_signin_keeps_explicit_vault_request(self):
        drive_client.private_storage.remove(self.svc.token_path)
        entered, release = threading.Event(), threading.Event()
        def signin(*args, **kwargs):
            entered.set(); release.wait(3)
            return {'refresh_token': 'late'}
        self.svc._sign_in = signin
        with mock.patch('core.config.google_client', return_value=('fixture', 'fixture')), \
                mock.patch.object(self.svc, 'start_vault') as vault:
            self.svc.connect()
            self.svc.connect('vault')
            self.assertTrue(entered.wait(2))
            license.remove()
            self.svc.license_changed()
            release.set()
            self.svc._signin_thread.join(5)
            vault.assert_called_once()
        self.assertTrue(self.svc.signed_in())
        self.assertTrue(self.svc.running)

    def test_removal_does_not_interrupt_shared_worker_or_resume_saved_switches(self):
        entered, release = threading.Event(), threading.Event()
        upload = self.drive.upload
        def blocked(name, *args, **kwargs):
            entered.set(); release.wait(3)
            return upload(name, *args, **kwargs)
        self.drive.upload = blocked
        self.svc.start()
        self.assertTrue(entered.wait(2))
        before_options = self.svc.writer.read(lambda db: [db.get_setting(k, '') for k in ('cloud_upload', 'cloud_vault')])
        license.remove()
        self.svc.license_changed()
        self.assertTrue(self.svc.running)
        release.set()
        self.assertTrue(self.fx.wait(lambda: self.svc.status()['last_publish']))
        self.assertEqual(self.svc.writer.read(lambda db: [db.get_setting(k, '') for k in ('cloud_upload', 'cloud_vault')]), before_options)
        self.svc._factory({'refresh_token': 'synthetic'}, phone=True).upload('synthetic-free-phone', b'x')
        self.assertIn('upload synthetic-free-phone', self.drive.calls)

    def test_queued_phone_work_survives_receipt_removal_but_rechecks_stopping(self):
        entered, release = threading.Event(), threading.Event()
        self.svc.writer.submit(lambda db: (entered.set(), release.wait(3)))
        self.assertTrue(entered.wait(2))
        completed = []
        thread = threading.Thread(target=lambda: (self.svc._licensed_call(lambda db: db.set_setting('free-phone', 'yes')), completed.append(True)))
        thread.start()
        license.remove(); release.set(); thread.join(3)
        self.assertEqual(completed, [True])
        self.assertEqual(self.svc.writer.read(lambda db: db.get_setting('free-phone', '')), 'yes')
        self.svc._closing = True
        try:
            with self.assertRaisesRegex(drive_client.DriveError, 'stopping'):
                self.svc._licensed_call(lambda db: db.set_setting('must-not-run', 'yes'))
        finally:
            self.svc._closing = False
        self.assertFalse(self.svc.writer.read(lambda db: db.get_setting('must-not-run', '')))

    def test_control_is_signed_private_and_locks_then_renews_without_rotating_pairing(self):
        key = self.svc.mirror_key()
        self.svc.publish_license_control()
        private = sync_license.signer(self.svc.control_key_path)
        good = json.loads(key.open(sync_license.LOGICAL, self.drive.by_name(key.name(sync_license.LOGICAL))))
        license.remove()
        self.svc.publish_license_control()
        locked = json.loads(key.open(sync_license.LOGICAL, self.drive.by_name(key.name(sync_license.LOGICAL))))
        license.save(self.saved)
        self.svc.publish_license_control()
        renewed = json.loads(key.open(sync_license.LOGICAL, self.drive.by_name(key.name(sync_license.LOGICAL))))
        public = sync_license.public(private)
        out = json.loads(test_phone_js.node(f"""
            import {{ verifyGrant }} from './web/src/mobile/mirror/license.ts'
            const good = {json.dumps(good)}, locked = {json.dumps(locked)}, renewed = {json.dumps(renewed)}
            const keys = {json.dumps(list(license.PUBLIC_KEYS))}, fp = {json.dumps(key.fingerprint)}, pc = {json.dumps(public)}
            const issued = JSON.parse(good.body).issued
            let refused = 0
            for (const [g, f, k, pubs, now] of [
              [locked, fp, pc, keys, issued], [good, fp, pc, [], issued],
              [good, fp, pc, keys, issued + 3600], [good, fp, pc, keys, issued - 1],
              [good, 'wrong', pc, keys, issued], [{{...good, body: good.body + ' '}}, fp, pc, keys, issued],
              [{{...good, sig: 'A'.repeat(86)}}, fp, pc, keys, issued]
            ]) {{ try {{ await verifyGrant(g, f, k, pubs, now) }} catch {{ refused++ }} }}
            try {{ await verifyGrant(good, fp, pc, keys, issued + 3600) }} catch(e) {{ if(!e.message.includes('expired')) throw e }}
            try {{ await verifyGrant(locked, fp, pc, keys, issued) }} catch(e) {{ if(!e.message.includes('older phone access')) throw e }}
            const expires = await verifyGrant(good, fp, pc, keys, issued)
            await verifyGrant(renewed, fp, pc, keys, JSON.parse(renewed.body).issued)
            console.log(JSON.stringify({{ refused, life: expires - issued }}))
        """))
        self.assertEqual(out, {'refused': 7, 'life': 3600})
        self.assertEqual(len([n for n, _ in self.drive.files.values() if n == key.name(sync_license.LOGICAL)]), 1)


class PhoneTransport(unittest.TestCase):
    def test_restored_solo_and_retries_check_current_grant_before_content(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            from tests.license_fixture import activate
            activate(self, Path(folder))
            key = mirror.MirrorKey.generate()
            private = sync_license.signer(Path(folder) / 'control.pem', create=True)
            p = {'v': 2, 'k': key.text(), 'f': key.fingerprint, 'l': sync_license.public(private), 'c': '', 'e': '', 'ai': {}}
            grant = sync_license.record(key, private)
            valid = base64.b64encode(key.seal(sync_license.LOGICAL, grant)).decode()
            license.remove()
            locked = base64.b64encode(key.seal(sync_license.LOGICAL, sync_license.record(key, private))).decode()
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
                const {{ MirrorKey }} = await import('./web/src/mobile/mirror/crypto.ts')
                const v2name = await (await MirrorKey.fromText({json.dumps(p['k'])})).name('control/access-v2.json')
                const pair = {json.dumps(p)}
                secrets.set('bp-pair', JSON.stringify({{...pair,g:'fixture@example.com'}}))
                await P.validateStoredPairing()
                let control = '{valid}', content = 0, requests = 0, retry = false
                const fetcher = async (url, init) => {{
                  requests++
                  if (url.includes('/files?')) return Response.json({{ files: new URL(url).searchParams.get('q').includes(v2name) ? [] : [{{ id:'control',size:'10000' }}] }})
                  if (url.includes('/files/control?')) return new Response(Buffer.from(control, 'base64'))
                  content++
                  if (retry) {{ control = '{locked}'; return new Response('', {{status:503}}) }}
                  return new Response('local fixture content')
                }}
                globalThis.fetch = fetcher
                const drive = new Drive('https://www.googleapis.com', ()=>'synthetic', ()=>{{}})
                await drive.get('content')
                control = '{locked}'
                let refused=0
                try {{ await drive.create('queued-edit',new Uint8Array([1])) }} catch {{refused++}}
                if(content !== 1) throw Error('Locked content was transferred')
                control = '{valid}'; retry=true
                try {{ await drive.get('content') }} catch {{refused++}}
                if(content !== 2) throw Error('Retry skipped entitlement check')
                const saved = secrets.get('bp-pair')
                secrets.set('bp-pair',JSON.stringify({{...pair,solo:true}})); await P.validateStoredPairing()
                const beforeSolo=requests
                try {{ await new Drive('https://www.googleapis.com',()=>'synthetic',()=>{{}}).get('content') }} catch {{refused++}}
                if(requests!==beforeSolo) throw Error('Solo cloud bypass')
                secrets.set('bp-pair',saved); await P.validateStoredPairing(); control='{valid}'; retry=false
                await new Drive('https://www.googleapis.com',()=>'synthetic',()=>{{}}).get('content')
                const old={{...pair}};delete old.l
                secrets.set('bp-pair',JSON.stringify(old));await P.validateStoredPairing()
                const beforeOld=requests
                try {{ await new Drive('https://www.googleapis.com',()=>'synthetic',()=>{{}}).list() }} catch {{refused++}}
                if(requests!==beforeOld) throw Error('Old pairing bypass')
                console.log(JSON.stringify({{refused,content}}))
            """))
            self.assertEqual(out, {'refused': 4, 'content': 3})


class QueuedEdits(unittest.TestCase):
    def test_locked_upload_retains_batch_and_reactivation_sends_same_edit(self):
        out = json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + """
            const { Changes } = await import('./web/src/mobile/mirror/changes.ts')
            const changes = new Changes()
            await changes.add({op:'fav',uid:'fixture',on:true})
            try {await changes.flush(async()=>{throw Error('license_required')},'fixture-phone')} catch {}
            const held = changes.list.map(x=>[x.uid,x.state,x.on])
            let doc
            await changes.flush(async d=>{doc=d;return 'fixture-change'},'fixture-phone')
            console.log(JSON.stringify({held,sent:doc.changes[0].uid,state:changes.list[0].state}))
        """))
        self.assertEqual(out,{'held':[['fixture','sending',True]],'sent':'fixture','state':'sent'})
