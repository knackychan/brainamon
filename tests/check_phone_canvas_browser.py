"""Isolated 360px solo canvas review and offline reload; no AI or Drive credentials."""
import os
import re
import json
import subprocess
import sys
import tempfile
import time
from threading import Event, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
from PIL import Image
from core import app_paths, local_auth

PAIR = dict(v=2, k='FxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxcXFxc', f='e0f475838db8', c='', e='', ai={}, at=0, solo=True)


def main():
    held = Event()
    class SlowAsk(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'event: start\ndata: {"run":"browser-check"}\n\n')
            self.wfile.flush()
            held.wait(10)
            self.wfile.write(b'event: stopped\ndata: {}\n\n')
            self.wfile.flush()
        def log_message(self, *args):
            pass
    ask = ThreadingHTTPServer(('127.0.0.1', 18798), SlowAsk)
    Thread(target=ask.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='phone-canvas-', ignore_cleanup_errors=True) as temp:
        env = dict(os.environ, CM_DATA_DIR=temp, CM_PORT='18799', PYTHONUTF8='1', BRAINAMON_HOME=temp)
        log = open(Path(temp) / 'server.log', 'w')
        proc = subprocess.Popen([sys.executable, '-m', 'server'], env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    urlopen('http://127.0.0.1:18799/api/health', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('isolated server did not start')
            app_paths.LOCAL = Path(temp) / 'local'
            auth = local_auth.headers(18799)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge')
                ctx = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True, locale='en-US')
                ctx.add_init_script("localStorage.setItem('bp-lang','en')")
                ctx.add_init_script("if (!sessionStorage.getItem('solo-fixture')) { sessionStorage.setItem('solo-fixture', '1'); "
                                    "localStorage.setItem('bp-pair', " + json.dumps(json.dumps(PAIR)) + "); }")
                page = ctx.new_page()
                page.set_default_timeout(5000)
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                resp = page.goto('http://127.0.0.1:18799/mobile.html#/more')
                assert resp and resp.status == 200
                page.locator('.m-ws').wait_for()
                page.evaluate('''async fingerprint => {
                  const key = 'wiskit-canvas-proposal:' + fingerprint;
                  const preview = {target:{id:null,name:'Offline practice',new:true,count:0},layout:'rows',arrange:false,
                    counts:{thumbnail:0,frame:0,text:1,sections:0,moves:0},sections:[{title:null,elements:[{kind:'text',text:'Stretch gently'}]}],explicit:[]};
                  const db = await new Promise((ok,bad) => { const r=indexedDB.open('brainamon-phone',2); r.onsuccess=()=>ok(r.result); r.onerror=()=>bad(r.error) });
                  await new Promise((ok,bad) => { const t=db.transaction('kv','readwrite');
                    t.objectStore('kv').put({token:'browser-check',raw:{new_name:'Offline practice',elements:[{kind:'text',text:'Stretch gently'}]},refs:{},quick:true,preview},key);
                    t.oncomplete=ok; t.onerror=()=>bad(t.error) });
                }''', PAIR['f'])
                page.goto('http://127.0.0.1:18799/mobile.html#/jv')
                page.get_by_role('heading', name='New canvas: Offline practice').wait_for()
                assert page.get_by_role('button', name='Apply', exact=True).evaluate('(e) => e.getBoundingClientRect().height >= 44')
                page.get_by_role('button', name='Apply', exact=True).click()
                page.get_by_role('button', name='Open canvas').click()
                page.get_by_text('Stretch gently').wait_for()
                page.reload()
                page.get_by_text('Stretch gently').wait_for()
                ctx.set_offline(True)
                page.reload()
                page.get_by_text('Stretch gently').wait_for()
                ctx.set_offline(False)
                restored = page.evaluate('''async () => {
                  const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  const rows=await new Promise((ok,bad)=>{const r=db.transaction('changes').objectStore('changes').getAll();r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  if(rows.filter(x=>x.op==='canvas').length!==1)throw Error('Apply created duplicate canvas operations');
                  const c={...rows.find(x=>x.op==='canvas')};for(const k of ['id','state','canvasLocal','sentAt','chg'])delete c[k];
                  const vault=await new Promise((ok,bad)=>{const r=indexedDB.open('bp-secrets',1);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  const get=k=>new Promise((ok,bad)=>{const r=vault.transaction('kv').objectStore('kv').get(k);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  const key=await get('wrap'), rec=await get('bp-pair');
                  const pair=new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:rec.iv,additionalData:new TextEncoder().encode('bp-pair')},key,rec.ct));
                  return {pair,wire:c};
                }''')
                second = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True, locale='en-US')
                second.add_init_script("localStorage.setItem('bp-lang','en')")
                second.add_init_script(script=f"localStorage.setItem('bp-pair', {json.dumps(restored['pair'])})")
                other = second.new_page()
                other.goto('http://127.0.0.1:18799/mobile.html#/canvas')
                other.get_by_text('No canvases yet. Ask Wiskit to make one.').wait_for()
                other.evaluate('''async wire => {
                  const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  await new Promise((ok,bad)=>{const t=db.transaction('changes','readwrite');t.objectStore('changes').add({...wire,state:'sent',sentAt:wire.at,chg:'restored'});t.oncomplete=ok;t.onerror=()=>bad(t.error)});
                }''', restored['wire'])
                other.reload()
                other.get_by_role('button', name=re.compile('Offline practice')).click()
                other.get_by_text('Stretch gently').wait_for()
                missing = 'd' * 32
                other.evaluate('''async cid => {
                  const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  const wire={op:'canvas',op_id:'e'.repeat(32),canvas_id:cid,at:201,
                    proposal:{canvas_id:cid,elements:[{kind:'text',text:'After creation'}]},refs:{},sizes:{}};
                  await new Promise((ok,bad)=>{const t=db.transaction('changes','readwrite');t.objectStore('changes').add({...wire,state:'sent',sentAt:201,chg:'early'});t.oncomplete=ok;t.onerror=()=>bad(t.error)});
                }''', missing)
                other.goto('http://127.0.0.1:18799/mobile.html#/canvas')
                other.reload()
                other.get_by_text('Canvas waiting for earlier backup').wait_for()
                other.evaluate('''async cid => {
                  const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  const wire={op:'canvas',op_id:'f'.repeat(32),canvas_id:cid,at:200,
                    proposal:{new_name:'Late creation',elements:[{kind:'text',text:'Before append'}]},refs:{},sizes:{}};
                  await new Promise((ok,bad)=>{const t=db.transaction('changes','readwrite');t.objectStore('changes').add({...wire,state:'sent',sentAt:200,chg:'late'});t.oncomplete=ok;t.onerror=()=>bad(t.error)});
                }''', missing)
                other.reload()
                other.get_by_role('button', name=re.compile('Late creation')).click()
                other.get_by_text('Before append').wait_for()
                other.get_by_text('After creation').wait_for()
                second.close()
                page.evaluate('''async fingerprint => {
                  const key='wiskit-canvas-proposal:'+fingerprint;
                  const preview={target:{id:null,name:'Storage case',new:true,count:0},layout:'rows',arrange:false,
                    counts:{thumbnail:0,frame:0,text:1,sections:0,moves:0},sections:[{title:null,elements:[{kind:'text',text:'Never committed'}]}],explicit:[]};
                  const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
                  await new Promise((ok,bad)=>{const t=db.transaction('kv','readwrite');
                    t.objectStore('kv').put({token:'quota-check',raw:{new_name:'Storage case',elements:[{kind:'text',text:'Never committed'}]},refs:{},quick:true,preview},key);
                    t.oncomplete=ok;t.onerror=()=>bad(t.error)});
                }''', PAIR['f'])
                page.goto('http://127.0.0.1:18799/mobile.html#/jv')
                page.get_by_role('heading', name='New canvas: Storage case').wait_for()
                page.evaluate('''() => {
                  const original=IDBDatabase.prototype.transaction;
                  IDBDatabase.prototype.transaction=function(names, mode, options) {
                    if (Array.isArray(names) && names.includes('changes')) throw new DOMException('Quota exceeded', 'QuotaExceededError');
                    return original.call(this,names,mode,options)
                  }
                }''')
                page.get_by_role('button', name='Apply', exact=True).click()
                page.get_by_role('alert').filter(has_text='Quota exceeded').wait_for()
                assert page.get_by_role('heading', name='New canvas: Storage case').is_visible()
                page.reload()
                page.get_by_role('heading', name='New canvas: Storage case').wait_for()
                page.get_by_role('button', name='Decline').click()
                page.get_by_role('heading', name='New canvas: Storage case').wait_for(state='detached')
                assert not errors, errors
                print('Solo browser: 360x800 Apply, offline reload, wire-only restore, late creation, storage failure and Decline passed')
                pc = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True, extra_http_headers=auth, locale='en-US')
                pc.add_init_script("localStorage.setItem('bp-lang','en')")
                direct = pc.new_page()
                direct.goto('http://127.0.0.1:18799/mobile.html#/jv')
                def request_canvas(name):
                    body = json.dumps({'proposal': {'new_name': name, 'elements': [{'kind': 'text', 'text': 'From PC'}]}}).encode()
                    req = Request('http://127.0.0.1:18799/api/canvases/request', data=body,
                                  headers={**auth, 'X-CM': '1', 'Content-Type': 'application/json'})
                    with urlopen(req) as response:
                        return json.load(response)
                pc.route('**/api/ask', lambda route: route.continue_(url='http://127.0.0.1:18798/api/ask'))
                direct.get_by_placeholder('Ask your library…').fill('Make a canvas')
                direct.get_by_role('button', name='Send', exact=True).click()
                direct.get_by_role('button', name='Stop', exact=True).wait_for()
                request_canvas('While asking')
                direct.get_by_role('heading', name='New canvas: While asking').wait_for(timeout=7000)
                assert direct.get_by_role('button', name='Stop').is_visible()
                direct.get_by_role('button', name='Decline').click()
                direct.get_by_role('heading', name='New canvas: While asking').wait_for(state='detached')
                held.set()
                pc.unroute('**/api/ask')
                request_canvas('Direct review')
                direct.get_by_role('heading', name='New canvas: Direct review').wait_for(timeout=5000)
                direct.get_by_role('button', name='Apply', exact=True).click()
                direct.get_by_role('button', name='Open canvas').click()
                direct.get_by_text('From PC').wait_for()
                request_canvas('Declined PC')
                direct.goto('http://127.0.0.1:18799/mobile.html#/jv')
                direct.get_by_role('heading', name='New canvas: Declined PC').wait_for(timeout=5000)
                direct.get_by_role('button', name='Decline').click()
                direct.get_by_role('heading', name='New canvas: Declined PC').wait_for(state='detached')
                body = json.dumps({'url': 'https://example.com/frame', 'description': 'Frame source'}).encode()
                req = Request('http://127.0.0.1:18799/api/items', data=body, headers={**auth, 'X-CM': '1', 'Content-Type': 'application/json'})
                with urlopen(req) as response:
                    item_id = json.load(response)['id']
                frames = Path(temp) / 'items' / str(item_id) / 'frames'
                frames.mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (80, 50), '#5588aa').save(frames / 'scene.jpg')
                body = json.dumps({'proposal': {'new_name': 'Frame review', 'elements': [
                    {'kind': 'frame', 'item_id': item_id, 'frame': 'scene.jpg'}]}}).encode()
                req = Request('http://127.0.0.1:18799/api/canvases/request', data=body,
                              headers={**auth, 'X-CM': '1', 'Content-Type': 'application/json'})
                with urlopen(req) as response:
                    json.load(response)
                direct.goto('http://127.0.0.1:18799/mobile.html#/jv')
                direct.get_by_role('heading', name='New canvas: Frame review').wait_for()
                direct.locator('.m-review-element img').wait_for()
                direct.wait_for_function("() => { const e = document.querySelector('.m-review-element img'); return e?.complete && e.naturalWidth > 0 }")
                assert direct.locator('.m-review-element img').evaluate('(e)=>e.complete&&e.naturalWidth>0')
                direct.get_by_role('button', name='Apply', exact=True).click()
                direct.get_by_role('button', name='Open canvas').click()
                direct.locator('.m-cv-el img').wait_for()
                print('Direct PC browser: review while Ask ran, frame preview, Apply and Decline passed')
                pc.close()
                browser.close()
        finally:
            held.set()
            ask.shutdown()
            ask.server_close()
            proc.terminate()
            proc.wait(timeout=10)
            log.close()


if __name__ == '__main__':
    main()
