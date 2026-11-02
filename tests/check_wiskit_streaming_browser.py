"""Isolated browser: real source orchestration, streaming barriers and IndexedDB saves."""
import os
import subprocess
import tempfile
import socket
import time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
from tests import phone_ai_fixture as F

ROOT = Path(__file__).resolve().parents[1]

def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='wiskit-browser-') as td:
        log = open(Path(td) / 'vite.log', 'w')
        proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT/'web', stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    urlopen(f'http://127.0.0.1:{port}/src/lib/sse.ts', timeout=1).close(); break
                except OSError: time.sleep(.1)
            else: raise AssertionError('isolated Vite did not start')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge')
                page = browser.new_page()
                page.route('**/__wiskit_check', lambda r: r.fulfill(body='<!doctype html><title>Wiskit isolated check</title>', content_type='text/html'))
                page.route('**/api/**', lambda r: r.abort())
                page.route('https://**/*', lambda r: r.abort())
                page.goto(f'http://127.0.0.1:{port}/__wiskit_check')
                result = page.evaluate(r"""async fx => {
                  const {MirrorSource}=await import('/src/mobile/source/mirror.ts')
                  const {PhoneLibrary,noteOf}=await import('/src/mobile/ai/library.ts')
                  const {setFetch}=await import('/src/mobile/ai/providers.ts')
                  const {changes:db,kv,putCanvasPending}=await import('/src/mobile/store.ts')
                  const lib=new PhoneLibrary(fx.items.map(r=>({id:r.id,s:r.short_desc||'',d:r.description||'',a:r.ai_desc||'',t:r.transcript||'',c:r.creator||'',g:r.tags||'',k:''})),fx.items.map(r=>({id:r.id,cat:r.category,url:r.url,created:0,type:r.type||'Reel'})),fx.notes.map(n=>noteOf(n.file,n.text)))
                  const iid=fx.items[0].id, enc=new TextEncoder()
                  const assert=(v,m)=>{if(!v)throw Error(m)}
                  const frame=e=>`event: ${e.type}\r\ndata: ${JSON.stringify(e)}\r\n\r\n`
                  function round(p,text,tool) {
                    if(p==='openai')return [{type:'response.output_text.delta',delta:text},{type:'response.completed',response:{status:'completed',output:tool?[{type:'reasoning',encrypted_content:'fake'}, {type:'function_call',name:tool[0],call_id:crypto.randomUUID(),arguments:JSON.stringify(tool[1]),status:'completed'}]:[{type:'message',status:'completed',content:[{type:'output_text',text}]}]}}]
                    const blocks=[{type:'text',text},...(tool?[{type:'tool_use',id:crypto.randomUUID(),name:tool[0],input:tool[1]}]:[])]
                    const out=[{type:'message_start',message:{}}]
                    blocks.forEach((b,index)=>{out.push({type:'content_block_start',index,content_block:b.type==='text'?{type:'text',text:''}:b});if(b.type==='text')out.push({type:'content_block_delta',index,delta:{type:'text_delta',text:b.text}});out.push({type:'content_block_stop',index})})
                    return [...out,{type:'message_delta',delta:{stop_reason:tool?'tool_use':'end_turn'}},{type:'message_stop'}]
                  }
                  function source(p,solo=true){
                    const s=new MirrorSource({v:1,k:'A'.repeat(43),c:'',e:'',f:'browser',ai:{[p]:'fake'},at:0,solo})
                    s.manifest={files:{},published:0};s.man=async()=>s.manifest
                    s.ai=()=>({provider:p,model:'fake-model',label:'Fake'})
                    s.keys=()=>({[p]:'fake'});s.settings=()=>({cloud_min_tokens:8000,agent_max_rounds:8,agent_max_tokens:16000})
                    s.library=async()=>lib;s.vectors=async()=>null;s.noteTexts=async()=>fx.notes.map(n=>[n.file,n.text])
                    s.canvases=async()=>[];s.ready=async()=>{};s.flushSoon=()=>{}
                    s.cats=()=>[{name:'Reviewed',color:'#123456'}]
                    s.byId=new Map(fx.items.map(r=>[r.id,{id:r.id,uid:r.id.toString(16).padStart(32,'0'),cat:r.category,title:r.description}]))
                    s.report=async(_,id)=>fx.items.find(r=>r.id===id)?.report||''
                    return s
                  }
                  let scenarios=0
                  const schemas={}
                  for(const p of ['anthropic','openai'])for(const mode of ['quick','deep'])for(const solo of [true,false]){
                    await db.clear();await kv.del('wiskit-category-proposal:browser')
                    const s=source(p,solo),events=[]
                    let requests=0,release,firstResolve
                    const first=new Promise(ok=>firstResolve=ok)
                    setFetch(async(url,init)=>{
                      if(url.endsWith('/embeddings')){const input=JSON.parse(init.body).input;return new Response(JSON.stringify({data:input.map((_,index)=>({index,embedding:[1,0,0,0]}))}))}
                      const body=JSON.parse(init.body),tools=body.tools.map(t=>t.name)
                      const k=p+':'+solo
                      if(schemas[k])assert(JSON.stringify(tools)===schemas[k],'mode tool schemas differ');else schemas[k]=JSON.stringify(tools)
                      const n=requests++
                      const tool=n===0?['search_library',{query:'knee'}]:n===1?['read_items',{ids:[iid]}]:n===2?['propose_category',{ids:[iid],category:'Reviewed'}]:null
                      const es=round(p,tool?'Preparing':`Final 😀 [id ${iid}]`,tool)
                      return new Response(new ReadableStream({start(c){
                        const abort=()=>c.error(init.signal.reason);init.signal.addEventListener('abort',abort,{once:true})
                        const finish=()=>{c.enqueue(enc.encode(frame(es.at(-1))));c.close();init.signal.removeEventListener('abort',abort)}
                        for(const e of es.slice(0,-1))c.enqueue(enc.encode(frame(e)))
                        if(n===3)release=finish;else finish()
                      }}))
                    })
                    const pending=s.ask('Make me a collage of these', '', e=>{events.push(e);if(e.ev==='chunk'&&e.text.startsWith('Final'))firstResolve()},new AbortController().signal,mode)
                    await Promise.race([first,pending.then(()=>{throw Error('completed before held delta')})])
                    assert(!events.some(e=>e.ev==='done'),'done before provider completion')
                    assert(requests===4,'read proposal answer rounds')
                    release();await pending
                    const done=events.find(e=>e.ev==='done'),saved=(await db.all()).find(e=>e.op==='chat')
                    assert(done?.text===saved?.history.at(-1).content,'display/save mismatch')
                    assert(events.filter(e=>e.ev==='reset').length===3,'reset count')
                    assert(events.some(e=>e.ev==='category_proposal'),'no explicit review')
                    assert(!(await db.all()).some(e=>e.op==='category_batch'),'proposal applied itself')
                    assert((await s.chat(done.chat.slug)).history.at(-1).content===done.text,'reload mismatch')
                    scenarios++
                  }
                  // A prepared proposal survives Stop; the answer and an Apply change do not.
                  for(const p of ['anthropic','openai'])for(const mode of ['quick','deep']){
                    await db.clear();await kv.del('wiskit-category-proposal:browser')
                    const s=source(p),ctl=new AbortController(),events=[]
                    let n=0
                    setFetch(async(url,init)=>{
                      if(url.endsWith('/embeddings')){const input=JSON.parse(init.body).input;return new Response(JSON.stringify({data:input.map((_,index)=>({index,embedding:[1,0,0,0]}))}))}
                      const tool=n++===0?['read_items',{ids:[iid]}]:['propose_category',{ids:[iid],category:'Reviewed'}]
                      return new Response(enc.encode(round(p,'Preparing',tool).map(frame).join('')))
                    })
                    await s.ask('Please do it','',e=>{events.push(e);if(e.ev==='category_proposal')ctl.abort()},ctl.signal,mode).then(()=>{throw Error('stopped proposal saved answer')},e=>assert(e.name==='AbortError','proposal Stop did not propagate'))
                    assert(await kv.get('wiskit-category-proposal:browser'),'Stop discarded prepared review')
                    assert(!(await db.all()).length&&!events.some(e=>e.ev==='done'),'Stop saved/applied proposal')
                  }
                  await db.clear()
                  // Hold the asynchronous pre-save load; Stop wins before a transaction exists.
                  const s=source('anthropic'), ctl=new AbortController(), events=[]
                  let entered,release
                  const barrier=new Promise(ok=>entered=ok), gate=new Promise(ok=>release=ok)
                  s.changes.load=async()=>{entered();await gate}
                  const saving=s.finish('q','answer',[],null,[],{provider:'anthropic',model:'fake',label:'Fake'},e=>events.push(e),ctl.signal)
                  await barrier;ctl.abort();release()
                  await saving.then(()=>{throw Error('precommit Stop saved')},e=>assert(e.name==='AbortError','wrong stop'))
                  assert(!(await db.all()).length&&!s.changes.list.length&&!events.length,'precommit state changed')
                  // Abort immediately after the real write has been enqueued: the commit must survive.
                  const original=IDBObjectStore.prototype.put, late=new AbortController()
                  IDBObjectStore.prototype.put=function(...args){const r=original.apply(this,args);if(this.name==='changes')late.abort();return r}
                  const lateSource=source('anthropic'), lateEvents=[]
                  try{await lateSource.finish('q','committed',[],null,[],{provider:'anthropic',model:'fake',label:'Fake'},e=>lateEvents.push(e),late.signal)}finally{IDBObjectStore.prototype.put=original}
                  assert(late.signal.aborted&&lateEvents[0]?.ev==='done','late Stop relabeled commit')
                  const prior=JSON.stringify(await db.all()),mem=JSON.stringify(lateSource.changes.list)
                  IDBObjectStore.prototype.put=function(){throw new DOMException('quota','QuotaExceededError')}
                  try{await lateSource.finish('q','must fail',[],null,[],{provider:'anthropic',model:'fake',label:'Fake'},()=>{throw Error('false done')},new AbortController().signal).then(()=>{throw Error('quota accepted')},e=>assert(e.name==='QuotaExceededError','quota missing'))}finally{IDBObjectStore.prototype.put=original}
                  assert(JSON.stringify(await db.all())===prior&&JSON.stringify(lateSource.changes.list)===mem,'failed save altered state')
                  const transaction=IDBDatabase.prototype.transaction
                  IDBDatabase.prototype.transaction=function(name,mode,...args){if(name==='changes'&&mode==='readonly')throw Error('queue read failed');return transaction.call(this,name,mode,...args)}
                  try{await lateSource.finish('q','must fail read',[],null,[],{provider:'anthropic',model:'fake',label:'Fake'},()=>{throw Error('false done')},new AbortController().signal).then(()=>{throw Error('read failure accepted')},e=>assert(e.message==='queue read failed','queue failure missing'))}finally{IDBDatabase.prototype.transaction=transaction}
                  assert(JSON.stringify(await db.all())===prior&&JSON.stringify(lateSource.changes.list)===mem,'failed read altered chat state')
                  const stopped=new AbortController();stopped.abort()
                  await putCanvasPending('abort-proposal',{x:1},stopped.signal).then(()=>{throw Error('pending abort accepted')},e=>assert(e.name==='AbortError','proposal stop'))
                  assert(!await kv.get('abort-proposal'),'aborted pending write exists')
                  return {scenarios,storage:'precommit stop, late stop, quota failure, pending stop'}
                }""", F.load())
                print('PASS:', result)
                browser.close()
        finally:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
            else: proc.terminate()
            proc.wait(timeout=10);log.close()

if __name__ == '__main__': main()
