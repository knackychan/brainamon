"""Native bridge adapter exercised with fake plugin events and real byte/SSE parsing."""
import json
import unittest
from tests.test_phone_js import _node_ok, node

@unittest.skipUnless(_node_ok(), 'needs Node 22.6+')
class PhoneAiTransportTest(unittest.TestCase):
    def test_native_stream_delivery_ack_cancel_and_no_retry(self):
        out = json.loads(node(r"""
          import { register } from 'node:module'
          register('data:text/javascript,'+encodeURIComponent(`export async function resolve(s,c,n){
            if(s==='@capacitor/core')return {url:'data:text/javascript,'+encodeURIComponent('export const Capacitor={isNativePlatform:()=>true}; export const registerPlugin=()=>globalThis.__plugin; export const CapacitorHttp={request:()=>{throw Error("buffered fallback")}}'),shortCircuit:true};
            if(s==='@capacitor/app')return {url:'data:text/javascript,export const App={}',shortCircuit:true};
            try{return await n(s,c)}catch(e){if(s.startsWith('.')&&!/\.\w+$/.test(s))return n(s+'.ts',c);throw e}}`),import.meta.url)
          let fn, id, starts=0, cancelled=0, removed=0, acks=[]
          globalThis.__plugin={
            async addListener(ev,f){fn=f;return {remove:async()=>{removed++}}},
            async aiStreamStart(o){id=o.id;starts++;fn({id,kind:'headers',status:200,headers:{'content-type':'text/event-stream'}})},
            async aiStreamCancel(){cancelled++},async aiStreamAck(o){acks.push(o.seq)}
          }
          globalThis.fetch=async()=>{throw new TypeError('CORS')}
          const {aiFetch}=await import('./web/src/mobile/native.ts')
          const {sse}=await import('./web/src/lib/sse.ts')
          const init={method:'POST',body:'{"stream":true}',headers:{'content-type':'application/json'}}
          const r=await aiFetch('https://api.openai.com/v1/responses',init)
          if(starts!==1)throw Error('headers did not resolve response')
          const bytes=new TextEncoder().encode('event: message\r\ndata: 😀\r\n\r\n')
          const at=bytes.indexOf(240)+2
          fn({id:'another',kind:'chunk',seq:99,data:'AA=='})
          fn({id,kind:'chunk',seq:0,data:Buffer.from(bytes.slice(0,at)).toString('base64')})
          if(acks.length)throw Error('ACK before consumption')
          const reader=r.body.getReader()
          const one=await reader.read()
          await Promise.resolve()
          if(acks.join()!=='0')throw Error('missing consume ACK')
          fn({id,kind:'chunk',seq:1,data:Buffer.from(bytes.slice(at)).toString('base64')})
          const two=await reader.read()
          await Promise.resolve()
          fn({id,kind:'done'})
          if(!(await reader.read()).done)throw Error('not closed')
          const joined=new Response(new ReadableStream({start(c){c.enqueue(one.value);c.enqueue(two.value);c.close()}}))
          const parsed=[];for await(const e of sse(joined))parsed.push(e)
          if(parsed[0][1]!=='😀'||acks.join()!=='0,1'||removed!==1)throw Error('bytes/cleanup')
          const ctl=new AbortController()
          const stopped=await aiFetch('https://api.openai.com/v1/responses',{...init,signal:ctl.signal})
          const wait=stopped.body.getReader().read()
          ctl.abort()
          await wait.then(()=>{throw Error('abort accepted')},e=>{if(e.name!=='AbortError')throw e})
          if(!cancelled||removed!==2)throw Error('abort cleanup')
          const bad=await aiFetch('https://api.openai.com/v1/responses',init)
          const badread=bad.body.getReader().read()
          fn({id,kind:'chunk',seq:9,data:'AA=='})
          await badread.then(()=>{throw Error('out of order accepted')},()=>{})
          const before=starts
          globalThis.fetch=async()=>new Response(new ReadableStream({start(c){c.error(Error('body broke'))}}))
          const browser=await aiFetch('https://api.openai.com/v1/responses',init)
          await browser.text().then(()=>{throw Error('body failure accepted')},()=>{})
          if(starts!==before)throw Error('retried delivered response')
          globalThis.fetch=async()=>{throw new TypeError('CORS')}
          globalThis.__plugin.aiStreamStart=async()=>{throw Object.assign(Error('not implemented'),{code:'UNIMPLEMENTED'})}
          await aiFetch('https://api.openai.com/v1/responses',init).then(()=>{throw Error('old APK accepted')},e=>{if(e.message!=='This Android app needs an update to stream Wiskit through native HTTP.')throw e})
          const early=new AbortController();early.abort()
          const count=starts
          await aiFetch('https://api.openai.com/v1/responses',{...init,signal:early.signal}).catch(()=>{})
          if(starts!==count)throw Error('started aborted stream')
          console.log(JSON.stringify({acks,removed,cancelled,starts}))
        """))
        self.assertEqual(out['acks'], [0, 1])
        self.assertGreaterEqual(out['cancelled'], 3)
        self.assertGreaterEqual(out['removed'], 4)
