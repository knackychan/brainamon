"""Phone backup management against synthetic storage and Drive; no real accounts or files."""
import unittest

from tests.test_phone_js import TS_RESOLVE, node


PRELUDE = TS_RESOLVE + r"""
import assert from 'node:assert/strict'
import { registerHooks } from 'node:module'
globalThis.__rows = new Map(); globalThis.__kv = new Map(); globalThis.__id = 0
registerHooks({load(url, c, next) {
  if (url.endsWith('/mobile/store.ts')) return {format:'module', shortCircuit:true, source:`
    const rows=globalThis.__rows, data=globalThis.__kv;
    export const changes={all:async()=>structuredClone([...rows.values()]),add:async e=>{const id=++globalThis.__id;rows.set(id,structuredClone({...e,id}));return id},put:async e=>rows.set(e.id,structuredClone(e)),del:async id=>rows.delete(id)};
    export const kv={get:async k=>structuredClone(data.get(k)),set:async(k,v)=>data.set(k,structuredClone(v)),del:async k=>data.delete(k)};
    export async function journal(entries, drop=[], values={}) {for(const e of entries)await changes.put(e);for(const id of drop)rows.delete(id);for(const [k,v]of Object.entries(values))await kv.set(k,v)}
    export const updateCanvasChange=async()=>{};
  `}
  return next(url,c)
}})
const mem=new Map(), sess=new Map()
globalThis.localStorage={getItem:k=>mem.get(k)??null,setItem:(k,v)=>mem.set(k,String(v)),removeItem:k=>mem.delete(k)}
globalThis.sessionStorage={getItem:k=>sess.get(k)??null,setItem:(k,v)=>sess.set(k,String(v)),removeItem:k=>sess.delete(k)}
globalThis.window=new EventTarget(); globalThis.document=new EventTarget()
Object.defineProperty(navigator,'onLine',{value:true})
Object.defineProperty(navigator,'connection',{value:Object.assign(new EventTarget(),{type:'wifi'})})
const P=await import('./web/src/mobile/mirror/pairing.ts')
const N=await import('./web/src/mobile/native.ts')
const G=await import('./web/src/mobile/mirror/gate.ts')
const B=await import('./web/src/mobile/mirror/phone-backup.ts')
const {MirrorKey}=await import('./web/src/mobile/mirror/crypto.ts')
const {Drive}=await import('./web/src/mobile/mirror/drive.ts')
const {Changes}=await import('./web/src/mobile/mirror/changes.ts')
const Net=await import('./web/src/mobile/network.svelte.ts')
await P.startSolo('A'.repeat(43)); const pair=P.pairing(); P.confirmAccount(pair,'fixture@example.com')
N.secrets.set('bp-gtoken',JSON.stringify({access:'synthetic',exp:Date.now()+3600000}))
const files=new Map(), removed=[], posts=[], requests=[]
let afterPost=null, beforeGet=null, deleteError=false, who='fixture@example.com', seq=0
globalThis.fetch=async(url, init={})=>{
  const u=new URL(url), method=init.method||'GET'; requests.push([method,u.pathname])
  if(u.pathname.endsWith('/about'))return Response.json({user:{emailAddress:who}})
  if(method==='POST') {
    const bytes=Buffer.from(init.body), boundary=init.headers['Content-Type'].split('boundary=')[1]
    const parts=bytes.toString('latin1').split('\r\n\r\n')
    const meta=JSON.parse(parts[1].split('\r\n--')[0])
    const body=Buffer.from(parts.slice(2).join('\r\n\r\n').split('\r\n--'+boundary)[0],'latin1')
    const id='new-'+(++seq);files.set(id,{name:meta.name,data:body});posts.push(id)
    if(afterPost)await afterPost(id)
    return Response.json({id})
  }
  if(u.pathname==='/drive/v3/files')return Response.json({files:[...files].map(([id,f])=>({id,name:f.name,size:String(f.data.length)}))})
  const id=u.pathname.split('/').at(-1)
  if(method==='DELETE'){if(deleteError)return Response.json({error:{message:'synthetic delete failure'}},{status:403});removed.push(id);files.delete(id);return new Response(null,{status:204})}
  if(beforeGet)await beforeGet(id)
  return files.has(id)?new Response(files.get(id).data):new Response(null,{status:404})
}
const key=await MirrorKey.fromText(pair.k), old=await MirrorKey.fromText(Buffer.alloc(32,7).toString('base64url'))
const prefix=await old.soloPrefix(), own=await key.soloPrefix(), enc=new TextEncoder()
files.set('old-1',{name:prefix+'1'.repeat(32),data:enc.encode('unreadable old copy')})
files.set('old-2',{name:prefix+'2'.repeat(32),data:enc.encode('unreadable old copy')})
files.set('unrelated-phone',{name:own+'3'.repeat(32),data:enc.encode('another retained copy')})
files.set('desktop',{name:'a'.repeat(32),data:enc.encode('desktop library')})
files.set('paired-edits',{name:'chg-'+'b'.repeat(32),data:enc.encode('paired library edits')})
files.set('recovery',{name:'vi-phone-recovery-'+'c'.repeat(32)+'-'+'d'.repeat(32)+'.json',data:enc.encode('recovery envelope')})
const journal=new Changes()
await journal.add({op:'link',uid:'e'.repeat(32),url:'https://example.com/kept',note:'local',category:''})
await journal.add({op:'note',file:'kept.md',body:'before',title:'Kept'})
const protectedFiles=()=>{for(const id of ['unrelated-phone','desktop','paired-edits','recovery'])assert.ok(files.has(id),id)}
"""


class MobileRecoveryRemediation(unittest.TestCase):
    def test_pause_during_key_installation_survives_until_cleanup(self):
        node(PRELUDE + r"""
          await B.beginBackupTask('replace',prefix)
          const set=N.secrets.set;let pausing,interrupted=false
          N.secrets.set=(name,value)=>{
            set(name,value)
            if(name==='bp-pair' && JSON.parse(value).k!==pair.k && !interrupted){
              interrupted=true;pausing=B.pauseBackupTask(true)
            }
          }
          await assert.rejects(B.runBackupTask(journal,()=>{}),/paused/);await pausing
          assert.notEqual(P.pairing().k,pair.k);assert.equal(B.backupTask().paused,true)
          assert.equal(removed.length,0);assert.ok(files.has('old-1'));protectedFiles()
          await B.pauseBackupTask(false);await B.runBackupTask(journal,()=>{})
          assert.deepEqual(removed,['old-1','old-2']);assert.equal(B.backupTask(),undefined)
        """)

    def test_restart_reverifies_replacement_before_resuming_old_copy_deletion(self):
        node(PRELUDE + r"""
          await B.beginBackupTask('replace',prefix);deleteError=true
          await assert.rejects(B.runBackupTask(journal,()=>{}),/synthetic delete failure/)
          assert.equal(B.backupTask().phase,'delete');assert.notEqual(P.pairing().k,pair.k)
          assert.equal(removed.length,0);files.delete(posts[0]);deleteError=false
          await assert.rejects(B.runBackupTask(new Changes(),()=>{}))
          assert.ok(files.has('old-1'));assert.ok(files.has('old-2'));assert.equal(removed.length,0)
        """)

    def test_incomplete_drive_listing_cannot_start_deletion(self):
        node(PRELUDE + r"""
          const original=fetch
          globalThis.fetch=(url,init)=>new URL(url).pathname==='/drive/v3/files'
            ?Promise.resolve(Response.json({files:[],incompleteSearch:true})):original(url,init)
          await assert.rejects(B.beginBackupTask('delete',prefix),/incomplete listing/)
          assert.equal(B.backupTask(),undefined);assert.equal(removed.length,0);protectedFiles()
        """)

    def test_replace_pauses_restarts_verifies_and_preserves_new_edits(self):
        node(PRELUDE + r"""
          const choices=await B.listPhoneBackups(); assert.equal(choices.length,2)
          await B.beginBackupTask('replace',prefix)
          afterPost=async()=>{await journal.add({op:'note',file:'kept.md',body:'edited during upload',title:'Kept'});await B.pauseBackupTask(true)}
          await assert.rejects(B.runBackupTask(journal,()=>{}),/paused/)
          assert.equal(P.pairing().k,pair.k);assert.equal(removed.length,0);assert.equal(posts.length,1)
          // New journal instance models a restarted page. Resume re-lists the uncertain upload.
          afterPost=null;await B.pauseBackupTask(false)
          const resumed=new Changes();await B.runBackupTask(resumed,()=>{})
          assert.notEqual(P.pairing().k,pair.k);assert.equal(B.backupTask(),undefined)
          assert.equal(posts.length,1);assert.deepEqual(removed,['old-1','old-2']);protectedFiles()
          assert.equal(resumed.list.find(e=>e.op==='link').state,'sent')
          assert.equal(resumed.list.find(e=>e.op==='note').state,'queued')
          assert.equal(resumed.list.find(e=>e.op==='note').body,'edited during upload')
          const replacement=files.get(posts[0]), fresh=await MirrorKey.fromText(P.pairing().k)
          assert.equal(JSON.parse(N.secrets.get('bp-pair-before-replace-'+replacement.name)).k,pair.k)
          const restored=await fresh.openJSON(replacement.name,replacement.data)
          assert.equal(restored.changes.length,2);assert.equal(restored.changes[1].body,'before')
        """)

    def test_retry_relists_manual_deletion_and_deletes_only_selected_backup(self):
        node(PRELUDE + r"""
          await B.beginBackupTask('delete',prefix)
          files.delete('old-1');await B.runBackupTask(journal,()=>{})
          assert.deepEqual(removed,['old-2']);protectedFiles()
          assert.equal(P.token(P.pairing()),null);assert.equal(journal.list.length,2)
          assert.equal(journal.unsent,2);assert.equal(B.backupTask(),undefined)
        """)

    def test_wrong_account_and_failed_verification_never_delete_old_copy(self):
        node(PRELUDE + r"""
          await B.beginBackupTask('replace',prefix)
          who='other@example.com';await assert.rejects(B.runBackupTask(journal,()=>{}),/account/)
          assert.equal(posts.length,0);who='fixture@example.com'
          afterPost=async id=>{files.get(id).data=new Uint8Array(40)}
          await assert.rejects(B.runBackupTask(journal,()=>{}))
          assert.equal(removed.length,0);assert.equal(P.pairing().k,pair.k);protectedFiles()
          await B.disconnectPhoneBackup()
          assert.equal(P.token(P.pairing()),null);assert.equal(B.backupTask(),undefined)
          assert.equal(journal.unsent,2)
        """)

    def test_paired_phone_and_unlisted_ids_cannot_delete_backups(self):
        node(PRELUDE + r"""
          const drive=new Drive(P.GOOGLE_DRIVE,()=>P.token(pair),P.dropToken)
          await drive.list()
          await assert.rejects(drive.removeSolo('desktop',prefix),/standalone/)
          await assert.rejects(drive.removeSolo('unrelated-phone',prefix),/standalone/)
          N.secrets.set('bp-pair',JSON.stringify({...pair,solo:false,l:'a'.repeat(122)}))
          await assert.rejects(B.beginBackupTask('delete',prefix),/PC backup/)
          await assert.rejects(drive.removeSolo('old-1',prefix),/standalone/)
          assert.equal(removed.length,0)
        """)

    def test_disconnect_waits_for_send_and_late_completion_cannot_ack_changes(self):
        node(PRELUDE + r"""
          const drive=new Drive(P.GOOGLE_DRIVE,()=>P.token(pair),P.dropToken)
          let release, entered;const started=new Promise(r=>entered=r)
          afterPost=()=>new Promise(r=>{release=r;entered()})
          G.beginCloudChange()
          const send=journal.flush(async doc=>{const [name,blob]=await key.sealChange(doc,true);await drive.create(name,blob);return name},'fixture').finally(G.endCloudChange)
          await started;const failed=assert.rejects(send,/stopped/)
          let done=false;const disconnect=B.disconnectPhoneBackup().then(()=>done=true)
          await new Promise(r=>setTimeout(r,10));assert.equal(done,false)
          release();await failed;await disconnect
          assert.equal(journal.unsent,2);assert.equal(P.token(P.pairing()),null)
          await assert.rejects(drive.list(),/stopped/)
        """)

    def test_old_auth_failure_does_not_remove_new_token_and_keys_save_independently(self):
        node(PRELUDE + r"""
          const drive=new Drive(P.GOOGLE_DRIVE,()=>P.token(pair),P.dropToken)
          globalThis.fetch=async()=>{N.secrets.set('bp-gtoken',JSON.stringify({access:'renewed',exp:Date.now()+3600000}));return new Response(null,{status:401})}
          await assert.rejects(drive.about(),/stopped/);assert.equal(P.token(pair),'renewed')
          P.setAiKey(pair,'openai',' openai-synthetic ')
          assert.deepEqual(P.pairing().ai,{openai:'openai-synthetic'})
          P.setAiKey(pair,'anthropic','anthropic-synthetic')
          assert.deepEqual(P.pairing().ai,{openai:'openai-synthetic',anthropic:'anthropic-synthetic'})
          Net.setSyncPaused(true);assert.equal(Net.syncPaused(),true);assert.equal(mem.get('bp-sync-paused'),'on')
          Net.setSyncPaused(false);assert.equal(mem.get('bp-sync-paused'),'off')
        """)
