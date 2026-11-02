"""Phone connection boundaries with synthetic native/browser answers; no account or device."""
import unittest
from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node with type stripping')
class PhoneConnection(unittest.TestCase):
    def test_authorization_account_storage_and_refresh_are_separate(self):
        node(r"""
          import assert from 'node:assert/strict'
          import fs from 'node:fs'
          import {registerHooks, stripTypeScriptTypes} from 'node:module'
          const memory = new Map()
          globalThis.localStorage = globalThis.sessionStorage = {getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}
          globalThis.window = new EventTarget()
          globalThis.location = {hash:'#/more',hostname:'fixture.invalid'}
          Object.defineProperty(navigator,'onLine',{value:true})
          globalThis.$state = Object.assign(x=>x,{raw:x=>x})
          globalThis.$derived = Object.assign(x=>x,{by:f=>f()})
          globalThis.__pair = {e:'pc@example.com',g:'',l:'synthetic-verifier'}
          globalThis.__test = {signed:false,redirect:false,saveFail:false,wrong:false,cancel:false,rows:0,accountSaves:0}
          const modules = {
            '../lib/md': 'export const setCardLookup=()=>{}',
            './source/desktop': 'export class DesktopSource {}',
            './source/mirror': `export class MirrorSource {constructor(pair){this.pair=pair;this.kind='mirror'} async rows(){globalThis.__test.rows++;throw globalThis.__readError} } export class NeedsSignIn extends Error {} export class NoMirror extends Error {} export class PhoneTooOld extends Error {} export const tooOld={}`,
            './mirror/drive': 'export class DriveError extends Error {} export class NeedsSignIn extends DriveError {}',
            './mirror/pairing': `const t=globalThis.__test; export const pairing=()=>globalThis.__pair; export const token=p=>t.signed&&p.g?'synthetic-token':null; export const signIn=async()=>{if(t.cancel)throw Error('Google chooser cancelled');if(t.redirect)return false;t.signed=true;return true};export const whoSignedIn=async()=>t.wrong?'wrong@example.com':'pc@example.com';export const confirmAccount=(p,g)=>{t.accountSaves++;p.g=g};export const disconnectDrive=p=>{t.signed=false;delete p.g}; export const triedSilent=()=>true; export const unconfirmedToken=()=>false;export const acceptLink=()=>'';export const newKeyText=()=>'';export const startSolo=()=>{};export const takeFromUrl=()=>{}`,
            './native': `export const isApp=true;export const scanQr=()=>'';export const secretsSaved=async()=>{if(globalThis.__test.saveFail)throw Error('Sign-in could not be saved securely')}`,
            './store': `export const changes={};export const drafts={};export const items={};export const outbox={};export const kv={};export const trimItems=()=>{};export const wipe=()=>{}`,
            './network.svelte': `export const network={licenseLocked:false,licenseProblem:''};export class SyncPaused extends Error{};export const syncPaused=()=>false;export const syncPauseReason=()=>''`,
          }
          registerHooks({resolve(s,c,next){
            if(c.parentURL?.endsWith('/mobile/state.svelte.ts') && modules[s])return {url:'data:text/javascript,'+encodeURIComponent(modules[s]),shortCircuit:true}
            if(c.parentURL?.endsWith('/mobile/mirror/status.ts')&&s==='./drive')return {url:'data:text/javascript,'+encodeURIComponent(modules['./mirror/drive']),shortCircuit:true}
            try{return next(s,c)}catch(e){if(s.startsWith('.')&&!/\.\w+$/.test(s))return next(s+'.ts',c);throw e}
          },load(url,c,next){
            if(url.endsWith('/mobile/state.svelte.ts'))return {format:'module',shortCircuit:true,source:stripTypeScriptTypes(fs.readFileSync(new URL(url),'utf8').replace('import.meta.env.DEV','false'))}
            return next(url,c)
          }})
          const S = await import('./web/src/mobile/state.svelte.ts')
          const {network} = await import('data:text/javascript,'+encodeURIComponent(modules['./network.svelte']))
          const {LicenseRequired,LICENSE_REQUIRED} = await import('./web/src/mobile/mirror/license.ts')
          const t=globalThis.__test,p=globalThis.__pair
          globalThis.__readError=Error('synthetic refresh failure')
          await S.connectDrive()
          assert.match(S.phone.note,/Google Drive connected/)
          assert.equal(S.driveLinked(),true)
          assert.equal(t.rows,1)
          assert.match(S.phone.error,/synthetic refresh failure/)
          t.wrong=true
          await S.connectDrive(true)
          assert.match(S.phone.note,/Choose pc@example.com/)
          assert.equal(S.driveLinked(),false)
          assert.equal(t.rows,1)
          t.wrong=false;t.cancel=true
          await S.connectDrive()
          assert.match(S.phone.note,/chooser cancelled/)
          assert.equal(S.phone.connecting,false)
          t.cancel=false;t.saveFail=true
          await S.connectDrive()
          assert.match(S.phone.note,/could not be saved securely/)
          assert.equal(t.rows,1)
          t.saveFail=false;t.redirect=true
          await S.connectDrive()
          assert.equal(t.rows,1) // browser redirects before account/refresh completion
          t.redirect=false
          globalThis.__readError=new LicenseRequired(LICENSE_REQUIRED)
          network.licenseLocked=true;network.licenseProblem=LICENSE_REQUIRED
          await S.connectDrive()
          assert.match(S.phone.note,/Google Drive connected/)
          assert.equal(S.phone.error,LICENSE_REQUIRED)
          assert.equal(S.driveStatus().lamp,'access pending')
          assert.ok(t.accountSaves>=3) // retries persist confirmation even when memory already holds it
          delete p.g;t.signed=false
          assert.equal(S.driveStatus().lamp,'sign in') // authorization takes precedence over access state
          assert.equal(S.phone.connecting,false)
        """)
