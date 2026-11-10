"""Native startup reads use synthetic secrets, a fake clock, and no device/storage access."""
import json
import unittest

from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class PhoneStartupTest(unittest.TestCase):
    def test_app_info_uses_package_metadata_and_times_out(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>({});export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={getInfo:()=>globalThis.__getInfo()}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          const timers = new Map()
          let next = 0
          globalThis.setTimeout = (fn, ms) => { assert.equal(ms, 5000); timers.set(++next, fn); return next }
          globalThis.clearTimeout = id => timers.delete(id)
          const { appInfo } = await import('./web/src/mobile/native.ts')
          const installed = {name:'Brainamon',id:'app.brainamon.mobile',version:'1.0.1',build:'1000001'}
          globalThis.__getInfo = () => Promise.resolve(installed)
          assert.deepEqual(await appInfo(), installed)
          assert.equal(timers.size, 0)
          globalThis.__getInfo = () => Promise.reject(Error('bridge unavailable'))
          await assert.rejects(appInfo(), /bridge unavailable/)
          assert.equal(timers.size, 0)
          globalThis.__getInfo = () => new Promise(() => {})
          const pending = assert.rejects(appInfo(), /Could not read app info/)
          timers.values().next().value()
          await pending
          assert.equal(timers.size, 0)
        """)

    def test_google_timeout_and_late_native_callback_do_not_save_a_token(self):
        node(r"""
          import assert from 'node:assert/strict'
          import {register} from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            if(s.endsWith('.svelte'))return n(s+'.ts',c);
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          globalThis.$state=x=>x
          globalThis.window=new EventTarget()
          globalThis.localStorage=globalThis.sessionStorage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}}
          const timers=new Map();let seq=0,complete
          globalThis.setTimeout=(fn,ms)=>{timers.set(++seq,{fn,ms});return seq}
          globalThis.clearTimeout=id=>timers.delete(id)
          globalThis.__plugin={googleToken:()=>new Promise(resolve=>complete=resolve),secretSet:async()=>{}}
          const {signIn}=await import('./web/src/mobile/mirror/pairing.ts')
          const {secrets,secretsSaved}=await import('./web/src/mobile/native.ts')
          for(const silent of [false,true]) {
            const run=assert.rejects(signIn({g:'fixture@example.com'},silent),silent?/20 seconds/:/2 minutes/)
            const timer=[...timers.values()].find(t=>t.ms===(silent?20000:120000))
            assert.ok(timer);timer.fn();await run
            complete({token:'late-synthetic',expiresIn:3600})
            await Promise.resolve();await Promise.resolve()
            assert.equal(secrets.get('bp-gtoken'),null)
          }
          const retry=signIn({g:'fixture@example.com'})
          complete({token:'synthetic-retry',expiresIn:3600})
          assert.equal(await retry,true)
          await secretsSaved()
          assert.equal(JSON.parse(secrets.get('bp-gtoken')).access,'synthetic-retry')
        """)

    def test_protected_save_failure_is_reported_and_retry_can_finish(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          let fail = true
          globalThis.__plugin = {secretSet: async () => {if(fail) throw Error('synthetic secure storage failure')}}
          const {secrets, secretsSaved} = await import('./web/src/mobile/native.ts')
          secrets.set('bp-pair', 'synthetic')
          secrets.set('bp-gtoken', 'synthetic-token')
          await assert.rejects(secretsSaved(), /could not be saved securely/)
          fail = false
          secrets.set('bp-pair', 'synthetic')
          secrets.set('bp-gtoken', 'synthetic-token')
          await secretsSaved()
        """)

    def test_language_switch_keeps_failed_secret_keys_blocked_until_retried(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          const failures = new Set(['bp-pair', 'bp-gtoken'])
          globalThis.__plugin = {secretSet: async ({key}) => { if (failures.has(key)) throw Error('synthetic failure') }}
          const { secrets, secretsSaved, secretsHaveFailures } = await import('./web/src/mobile/native.ts')
          const { switchLanguage } = await import('./web/src/mobile/language-switch.ts')
          secrets.set('bp-pair', 'synthetic'); secrets.set('bp-gtoken', 'synthetic')
          await assert.rejects(secretsSaved())
          failures.delete('bp-pair'); secrets.set('bp-pair', 'synthetic'); await secretsSaved()
          assert.equal(secretsHaveFailures(), true)
          const result = await switchLanguage('fr', 'en', async () => {
            await secretsSaved(); if (secretsHaveFailures()) throw Error('pending')
          }, {setItem(){throw Error('must not write')}}, () => {throw Error('must not reload')})
          assert.equal(result.status, 'blocked')
          failures.delete('bp-gtoken'); secrets.set('bp-gtoken', 'synthetic'); await secretsSaved()
          assert.equal(secretsHaveFailures(), false)
          let reloaded = false
          assert.equal((await switchLanguage('fr', 'en', secretsSaved, {setItem(){}}, () => {reloaded = true})).status, 'reloaded')
          assert.equal(reloaded, true)
        """)

    def test_secret_retry_before_failure_is_observed_does_not_latch_reload(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          let fail = true
          globalThis.__plugin = {secretSet: async () => {if(fail) throw Error('synthetic failure')}}
          const {secrets, secretsSaved, secretsHaveFailures} = await import('./web/src/mobile/native.ts')
          const {switchLanguage} = await import('./web/src/mobile/language-switch.ts')
          secrets.set('bp-pair', 'synthetic')
          while (!secretsHaveFailures()) await new Promise(resolve => setTimeout(resolve, 0))
          fail = false
          secrets.set('bp-pair', 'synthetic')
          await secretsSaved()
          assert.equal(secretsHaveFailures(), false)
          assert.equal((await switchLanguage('fr', 'en', secretsSaved, {setItem() {}}, () => {})).status, 'reloaded')
        """)

    def test_browser_wrap_key_commits_before_legacy_secret_is_removed(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>false};export const registerPlugin=()=>({});export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          const writes = [], legacy = new Map([['bp-pair', 'synthetic-legacy']])
          const request = value => { const r = {}; queueMicrotask(() => { r.result = value; r.onsuccess() }); return r }
          const db = {transaction: () => {
            const tx = {error:null, objectStore: () => ({
              get: () => request(undefined), put: () => { writes.push(tx); return {} }, delete: () => { writes.push(tx); return {} },
            })}
            return tx
          }}
          globalThis.indexedDB = {open: () => request(db)}
          globalThis.localStorage = {getItem: key => legacy.get(key) ?? null, setItem: (key, value) => legacy.set(key, value), removeItem: key => legacy.delete(key)}
          const { initNative } = await import('./web/src/mobile/native.ts')
          let settled = false
          const first = initNative().then(() => { settled = true })
          while (!writes.length) await new Promise(resolve => setTimeout(resolve, 0))
          assert.equal(settled, false)
          assert.equal(legacy.get('bp-pair'), 'synthetic-legacy')
          writes.shift().onabort()
          await first
          assert.equal(legacy.get('bp-pair'), 'synthetic-legacy')
          const retry = initNative()
          while (!writes.length) await new Promise(resolve => setTimeout(resolve, 0))
          writes.shift().oncomplete()
          while (!writes.length) await new Promise(resolve => setTimeout(resolve, 0))
          assert.equal(legacy.get('bp-pair'), 'synthetic-legacy')
          writes.shift().oncomplete()
          await retry
          assert.equal(legacy.has('bp-pair'), false)
        """)

    def test_browser_secret_write_waits_for_transaction_commit(self):
        node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,export const Capacitor={isNativePlatform:()=>false};export const registerPlugin=()=>({});export const CapacitorHttp={}',shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\\.\\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          const key = await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt'])
          const writes = []
          const request = value => { const r = {}; queueMicrotask(() => { r.result = value; r.onsuccess() }); return r }
          const db = {transaction: (_name, mode) => {
            const tx = {error:null, objectStore: () => ({
              get: keyName => request(keyName === 'wrap' ? key : undefined),
              put: () => { writes.push(tx); return {} }, delete: () => { writes.push(tx); return {} },
            })}
            return tx
          }}
          globalThis.indexedDB = {open: () => request(db)}
          globalThis.localStorage = {getItem: () => null, setItem(){}, removeItem(){}}
          const { initNative, secrets, secretsSaved, secretsHaveFailures } = await import('./web/src/mobile/native.ts')
          await initNative()
          secrets.set('bp-pair', 'synthetic')
          let settled = false
          const first = secretsSaved().then(() => {settled = true}, () => {settled = true; throw Error('aborted')})
          while (!writes.length) await new Promise(resolve => setTimeout(resolve, 0))
          assert.equal(settled, false)
          writes.shift().onabort()
          await assert.rejects(first, /aborted/)
          assert.equal(secretsHaveFailures(), true)
          secrets.set('bp-pair', 'synthetic')
          const retry = secretsSaved()
          while (!writes.length) await new Promise(resolve => setTimeout(resolve, 0))
          writes.shift().oncomplete()
          await retry
          assert.equal(secretsHaveFailures(), false)
        """)

    def test_atomic_bounded_reads_rejection_retry_and_late_callbacks(self):
        result = json.loads(node(r"""
          import assert from 'node:assert/strict'
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,'+encodeURIComponent('export const Capacitor={isNativePlatform:()=>true};export const registerPlugin=()=>globalThis.__plugin;export const CapacitorHttp={}'),shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\.\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          const timers = new Map()
          let next = 0, reads = []
          globalThis.setTimeout = (fn, ms) => { assert.equal(ms, 10000); timers.set(++next, fn); return next }
          globalThis.clearTimeout = id => timers.delete(id)
          globalThis.__plugin = {
            secretGet: ({key}) => new Promise((resolve, reject) => reads.push({key, resolve, reject})),
            secretSet: () => { throw Error('startup wrote a secret') },
          }
          const { initNative, secrets } = await import('./web/src/mobile/native.ts')
          const flush = async () => { for(let i=0;i<12;i++) await Promise.resolve() }
          const complete = values => reads.splice(0).forEach(r => r.resolve({value:values[r.key]}))
          const first = {'bp-pair':'synthetic-pair-one', 'bp-gtoken':'synthetic-token-one'}
          let run = initNative()
          complete(first); await run
          const cached = () => Object.fromEntries(Object.keys(first).map(k => [k,secrets.get(k)]))
          assert.deepEqual(cached(), first)
          assert.equal(timers.size, 0)

          // Neither the successful half nor the late half may publish on timeout.
          run = initNative()
          const expired = assert.rejects(run, /10 seconds/)
          assert.equal(reads.length, 2)
          const late = reads.splice(0)
          late[0].resolve({value:'stale-pair'})
          await flush()
          assert.deepEqual(cached(), first)
          timers.values().next().value()
          await expired
          assert.equal(timers.size, 0)
          const second = {'bp-pair':'synthetic-pair-two', 'bp-gtoken':'synthetic-token-two'}
          run = initNative(); complete(second); await run
          late[1].resolve({value:'stale-token'}); await flush()
          assert.deepEqual(cached(), second)

          // Rejection of either read retains both old secrets, including when its sibling is late.
          for(const key of Object.keys(first)) {
            run = initNative()
            const rejected = assert.rejects(run, /synthetic read failure/)
            const attempt = reads.splice(0)
            attempt.find(r => r.key === key).reject(Error('synthetic read failure'))
            await rejected
            assert.deepEqual(cached(), second)
            run = initNative(); complete(first); await run
            attempt.find(r => r.key !== key).resolve({value:'stale-value'})
            await flush()
            assert.deepEqual(cached(), first)
            run = initNative(); complete(second); await run
          }
          // A late rejection is handled too; a confirmed empty store still means unpaired.
          run = initNative()
          const lateFailure = assert.rejects(run, /10 seconds/)
          const stale = reads.splice(0)
          timers.values().next().value(); await lateFailure
          run = initNative(); complete(second); await run
          stale.forEach(r => r.reject(Error('late native failure'))); await flush()
          assert.deepEqual(cached(), second)
          run = initNative(); complete({'bp-pair':null, 'bp-gtoken':null}); await run
          assert.deepEqual(cached(), {'bp-pair':null, 'bp-gtoken':null})
          assert.equal(timers.size, 0)
          console.log(JSON.stringify({timeout:true, rejectedReads:2, retries:true, lateCallbacks:true, confirmedEmpty:true}))
        """))
        self.assertEqual(result['rejectedReads'], 2)
        self.assertTrue(all(result.values()))
