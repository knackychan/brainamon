"""Composer acceptance with disposable IndexedDB, Vite, Edge and an isolated desktop library.

Run: python -m tests.check_phone_compose_browser
Screenshots and results stay under local/phone-compose; no native/APK or device claims.
"""
import json
import re
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect
from PIL import Image
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone, PAIR, ROOT
from tests.helpers.shots import Run

ART = ROOT / 'local/phone-compose'
image = io.BytesIO()
Image.new('RGB', (90, 160), '#1f7a68').save(image, 'JPEG')
JPEG = image.getvalue()


def fixture_routes(page):
    # Vite's proxy must never reach an already-running personal backend.
    page.context.route('**/api/**', lambda route: route.abort())
    page.context.route('**/thumb/**', lambda route: route.fulfill(body=JPEG, content_type='image/jpeg'))
    page.context.route('**/files/**', lambda route: route.abort())
    page.context.route('**/thumbs-proxy.js', lambda route: route.fulfill(path=ROOT / 'web/public/thumbs-proxy.js'))
    page.context.route('**/wiskit/**', lambda route: route.abort())


def module(page, body, arg=None):
    return page.evaluate("async arg => { const {phone,source,refresh}=await import('/src/mobile/state.svelte.ts'); "
                         "const store=await import('/src/mobile/store.ts'); " + body + " }", arg)


def settle(page):
    page.wait_for_function('()=>{const e=document.querySelector(".m-cp-drawer");return e&&Math.abs(e.getBoundingClientRect().height-parseFloat(e.style.height))<.5}')


def seed(page, n=145):
    page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.loaded&&!phone.refreshing}")
    seeded = module(page, """
      const canvas=document.createElement('canvas');canvas.width=90;canvas.height=160;
      const ctx=canvas.getContext('2d');ctx.fillStyle='#1f7a68';ctx.fillRect(0,0,90,160);
      ctx.fillStyle='#FFF9C4';ctx.fillRect(20,20,50,50);
      const jpg=canvas.toDataURL('image/jpeg').split(',')[1], entries=[];
      for(let i=0;i<arg;i++) {
        const uid=(i+1).toString(16).padStart(32,'0');
        entries.push({op:'link',uid,url:'https://example.test/synthetic/'+i,note:'Synthetic '+i,category:i%2?'SPORT':'AI',at:100+i});
        entries.push({op:'details',uid,title:'Synthetic '+i,desc:'Fixture only',thumb:jpg,at:100+i});
      }
      await source.changes.addBatch(entries);await refresh();
      window.fixtureRows=phone.rows;
      return phone.rows.length;
    """, n)
    assert seeded == n, f'fixture library has {seeded} rows, expected {n}'


def mirror_ui(browser, base):
    with synthetic_phone(browser, base, 390, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_text('No canvases yet. Ask Wiskit to make one.').wait_for()
        p.get_by_role('button', name='New canvas', exact=True).click()
        expect(p.get_by_label('Canvas name', exact=True)).to_be_visible()
        expect(p.locator('.m-top,.m-dock,.m-abar')).to_have_count(0)
        expect(p.get_by_role('button', name='Add', exact=True)).to_be_disabled()
        p.get_by_role('button', name='Write a note', exact=True).click()
        p.get_by_label('Note text', exact=True).fill('A synthetic note')
        p.get_by_role('button', name=re.compile('^Add')).click()
        expect(p.get_by_role('alert')).to_contain_text('Name your canvas first.')
        p.get_by_label('Canvas name', exact=True).fill('Offline canvas')
        p.get_by_role('button', name='Resize drawer', exact=True).click()
        p.get_by_role('button', name=re.compile('^Add')).click()
        expect(p.locator('.m-cv-txt')).to_have_text('A synthetic note')
        expect(p.get_by_role('status').filter(has_text='Offline canvas created with 1.')).to_be_visible()
        cid = p.url.split('/')[-1]
        p.get_by_role('button', name='Add', exact=True).click()
        p.get_by_role('button', name='Write a note', exact=True).click()
        p.get_by_label('Note text', exact=True).fill('Second note')
        p.get_by_role('button', name='Back', exact=True).click()
        expect(p.get_by_role('dialog')).to_be_visible()
        p.get_by_role('button', name='Keep editing', exact=True).click()
        expect(p.get_by_label('Note text', exact=True)).to_have_value('Second note')
        p.get_by_role('button', name='Back', exact=True).click()
        p.get_by_role('button', name='Discard', exact=True).click()
        expect(p.locator('.m-cv-txt')).to_have_count(1)
        p.get_by_role('button', name='Add', exact=True).click()
        p.get_by_role('button', name='Write a note', exact=True).click()
        p.get_by_label('Note text', exact=True).fill('Second note')
        p.get_by_label('Colour 3', exact=True).click()
        p.get_by_role('button', name=re.compile('^Add')).click()
        expect(p.locator('.m-cv-txt')).to_have_count(2)
        expect(p).to_have_url(re.compile('/' + cid + '$'))
        p.reload()
        expect(p.locator('.m-cv-txt')).to_have_count(2)
        # Vite imports exercise the actual source, transaction, and journal modules in Edge.
        seed(p)
        module(p, "location.hash='#/canvas/new'")
        p.get_by_label('Canvas name', exact=True).fill('Images')
        p.get_by_role('button', name='Resize drawer', exact=True).click()
        expect(p.locator('.m-cp-tile')).to_have_count(120)
        p.locator('.m-cp-grid').evaluate('(e)=>e.scrollTop=e.scrollHeight')
        expect(p.locator('.m-cp-tile')).to_have_count(145)
        p.get_by_label('Search the library', exact=True).fill('Synthetic 1')
        expect(p.locator('.m-cp-grid')).to_have_js_property('scrollTop', 0)
        p.get_by_label('Clear search', exact=True).click()
        p.get_by_label('Search the library', exact=True).blur()
        p.get_by_role('button', name='Resize drawer', exact=True).click()  # full -> closed
        p.get_by_role('button', name='Resize drawer', exact=True).click()  # closed -> half
        p.locator('.m-cp-tile').nth(0).click()
        p.locator('.m-cp-tile').nth(1).click()
        expect(p.get_by_role('button', name='Add 2', exact=True)).to_be_enabled()
        assert p.locator('.m-cp-staged').count() == 2
        p.wait_for_function("()=>[...document.querySelectorAll('.m-cp-tile img')].slice(0,16).every(i=>i.complete&&i.naturalWidth)")
        p.screenshot(path=str(ART / 'compose-light-390.png'))
        p.emulate_media(color_scheme='dark')
        p.evaluate("document.documentElement.dataset.theme='dark'")
        p.screenshot(path=str(ART / 'compose-dark-390.png'))
        # Prepared blobs remain usable after the source cache is evicted.
        module(p, "await caches.delete('bp-thumbs-v1')")
        p.get_by_role('button', name='Add 2', exact=True).click()
        expect(p.locator('.m-cv-el')).to_have_count(2)
        expect(p.locator('.m-cp-view-add')).to_be_visible()
        image_id = p.url.split('/')[-1]
        module(p, "const {go}=await import('/src/mobile/shell.svelte.ts');go('#/canvas')")
        p.get_by_role('button', name='New canvas', exact=True).click()
        p.locator('.m-cp-tile').nth(0).click()
        p.locator('.m-cp-tile').nth(2).click()
        p.get_by_label('Canvas name', exact=True).fill('Images')
        p.get_by_role('button', name='Add 2', exact=True).click()
        p.get_by_role('button', name='Add to it', exact=True).click()
        expect(p).to_have_url(re.compile('/' + image_id + '/add$'))
        expect(p.get_by_role('button', name='Add 1', exact=True)).to_be_enabled()
        expect(p.get_by_role('status')).to_contain_text('1 pick is already on this canvas.')
        p.get_by_role('button', name='Add 1', exact=True).click()
        expect(p.locator('.m-cp-view-add')).to_be_visible()
        expect(p.locator('.m-cv-el')).to_have_count(3)
        # Refresh removes a staged pick that another local operation has just added.
        p.get_by_role('button', name='Add', exact=True).click()
        p.locator('.m-cp-tile').nth(3).click()
        expect(p.get_by_role('button', name='Add 1', exact=True)).to_be_enabled()
        module(p, """
          const row=phone.rows.slice().sort((a,b)=>b.created-a.created||b.id-a.id)[3];
          const blob=await source.thumbBlob(row), bitmap=await createImageBitmap(blob), size=[bitmap.width,bitmap.height];bitmap.close();
          const base=await source.canvas(arg);
          await source.applyCanvasDraft({canvas_id:arg,layout:'rows',elements:[{kind:'thumbnail',item_id:row.id}]},
            {opId:crypto.randomUUID().replaceAll('-',''),canvasId:arg,at:Date.now(),base,thumbs:[{id:row.id,uid:row.uid,version:String(row.tv||0),blob,size}]});
        """, image_id)
        expect(p.get_by_role('button', name='Add', exact=True)).to_be_disabled()
        expect(p.get_by_role('status')).to_contain_text('1 pick is already on this canvas.')
        assert not errors, errors
        print('Mirror UI: note/new/append/reload, leave Keep/Discard, 145-item chunking, retained images, retarget/refresh dedup passed')


def source_and_journal(browser, base):
    with synthetic_phone(browser, base, 390, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_role('button', name='New canvas', exact=True).wait_for()
        result = module(p, """
          const assert=(ok,text)=>{if(!ok)throw Error(text)}, hex=()=>crypto.randomUUID().replaceAll('-','');
          const context=(id=hex(),base=null)=>({opId:hex(),canvasId:id,at:Date.now(),base,thumbs:[]});
          const raw={new_name:'Manual beside Wiskit',layout:'rows',elements:[{kind:'text',text:'One',color:'#FFE0CC'}]};
          const canvasKey='wiskit-canvas-proposal:'+source.pair.f, categoryKey='wiskit-category-proposal:'+source.pair.f;
          await store.putCanvasPending(canvasKey,{token:'pending-canvas',raw:{new_name:'Wiskit',elements:[{kind:'text',text:'pending'}]},refs:{}});
          await store.putCanvasPending(categoryKey,{entries:[{id:1,title:'Pending',from:'A',category:'B'}]});
          const c=context(), first=await source.applyCanvasDraft(raw,c);
          assert(first===c.canvasId,'manual ID');
          assert((await store.kv.get(canvasKey)).token==='pending-canvas','canvas proposal retained');
          assert((await store.kv.get(categoryKey)).entries.length===1,'category retained');
          const before=source.changes.list.length;
          assert(await source.applyCanvasDraft(raw,c)===first&&source.changes.list.length===before,'repeat once');
          let rejected=false;try{await source.applyCanvasDraft({...raw,new_name:'different'},c)}catch{rejected=true}assert(rejected,'conflicting retry');
          // Required storage throws before publication and leaves Wiskit pending.
          const tx=IDBDatabase.prototype.transaction;
          const fail=context();IDBDatabase.prototype.transaction=function(...args){if(args[1]==='readwrite')throw Error('synthetic quota');return tx.apply(this,args)};
          rejected=false;try{await source.applyCanvasDraft({...raw,new_name:'Storage retry'},fail)}catch{rejected=true}
          finally{IDBDatabase.prototype.transaction=tx}
          assert(rejected&&!source.changes.list.some(e=>e.op_id===fail.opId),'failed storage unpublished');
          await source.applyCanvasDraft({...raw,new_name:'Storage retry'},fail);
          const saved=await store.changes.all();assert(saved.filter(e=>e.op_id===fail.opId).length===1,'durable retry');
          const local=source.changes.list.find(e=>e.op_id===fail.opId).canvasLocal.result;
          await store.kv.set('saved-canvases',[{id:fail.canvasId,name:local.name,doc:local,at:Date.now(),images:[],size:1}]);
          assert((await source.canvas(fail.canvasId)).items.length===1,'saved creation is not replayed over itself');
          const extra={canvas_id:fail.canvasId,layout:'rows',elements:[{kind:'text',text:'Second',color:'#D9F2E3'}]};
          const localBase=await source.canvas(fail.canvasId), appendContext=context(fail.canvasId,localBase);
          appendContext.at=fail.at-1;
          await source.applyCanvasDraft(extra,appendContext);
          const two=await source.canvas(fail.canvasId);
          await store.kv.set('saved-canvases',[{id:fail.canvasId,name:two.name,doc:two,at:Date.now(),images:[],size:1}]);
          const reloaded=await source.canvas(fail.canvasId);
          assert(reloaded.items.length===2&&new Set(reloaded.items.map(e=>e.id)).size===2,'saved append is not replayed twice');
          // Abort after requests have run is not transaction completion.
          IDBDatabase.prototype.transaction=function(...args){const t=tx.apply(this,args);if(args[1]==='readwrite')queueMicrotask(()=>{try{t.abort()}catch{}});return t};
          rejected=false;try{await source.applyCanvasDraft({...raw,new_name:'Aborted'},context())}catch{rejected=true}
          finally{IDBDatabase.prototype.transaction=tx}assert(rejected,'transaction abort refuses');
          // Replay remains possible after the journal is pruned into a canonical marker.
          const entry=source.changes.list.find(e=>e.op_id===c.opId), hash=await (await import('/src/mobile/ai/canvas.ts')).canvasHash(entry);
          const canonical={...entry.canvasLocal.result,phone_ops:{[c.opId]:hash}};
          const oldMirror=source.mirrorCanvas.bind(source);source.mirrorCanvas=async id=>id===c.canvasId?canonical:oldMirror(id);
          await source.changes.pruneCanvas(entry);
          assert(await source.applyCanvasDraft(raw,c)===c.canvasId,'canonical replay');
          source.mirrorCanvas=oldMirror;
          const {Changes}=await import('/src/mobile/mirror/changes.ts');
          for(const numbered of [false,true]) {
            await store.changes.clear();await store.kv.del('delivery');
            const journal=new Changes();await journal.load();
            const link=await journal.add({op:'link',uid:hex(),url:'https://example.test/order'});
            await journal.add({op:'details',uid:link.uid,title:'Earlier details'});
            const create={op:'canvas',op_id:hex(),canvas_id:hex(),at:1,state:'queued',proposal:raw,refs:{},sizes:{}};
            await journal.commitCanvas(create);
            let release, started;const held=new Promise(r=>release=r), began=new Promise(r=>started=r), batches=[];
            const flushing=journal.flush(async doc=>{batches.push(doc);if(batches.length===1){started();await held}return 'fixture-'+batches.length},'fixture',true,numbered);
            await began;
            const old=journal.list[0];
            const append={...create,op_id:hex(),at:2,proposal:{canvas_id:create.canvas_id,layout:'rows',elements:raw.elements}};
            await journal.commitCanvas(append);
            assert(journal.list[0]===old,'publication preserves old object');
            release();await flushing;
            assert(batches.length===2&&batches[0].changes[0].op==='link'&&batches[0].changes[1].op==='details'&&batches[0].changes[2].op_id===create.op_id&&batches[1].changes[0].op_id===append.op_id,'upload ordering');
            assert(journal.list.every(e=>e.state==='sent'),'no frozen entry lost');
            await journal.commitCanvas(append);assert(journal.list.length===4,'stored replay published once');
            const again=[];await journal.flush(async d=>{again.push(d);return 'bad'},'fixture',true,numbered);assert(!again.length,'old batch not replayed');
          }
          return 'required storage, replay, pending isolation, numbered/solo publication passed';
        """)
        assert not errors, errors
        print(result)


def session_contracts(browser, base):
    with synthetic_phone(browser, base, 390, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_role('button', name='New canvas', exact=True).wait_for()
        result = module(p, """
          const assert=(ok,text)=>{if(!ok)throw Error(text)}, delay=n=>new Promise(r=>setTimeout(r,n));
          const {Composer}=await import('/src/mobile/canvas/compose.svelte.ts');
          const {ApiError}=await import('/src/lib/api.ts');
          let calls=[], release;
          const s={kind:'desktop',canvases:async()=>[],applyCanvasDraft:async(raw,context)=>{
            calls.push({raw,context});if(calls.length===1)throw Error('lost response');return context.canvasId;
          }};
          const c=new Composer(s,false);c.name='Frozen';c.note='One';
          assert(await c.add(()=>[])===null&&c.uncertain&&c.locked&&c.canAdd,'unknown outcome frozen');
          const first=calls[0];const done=await c.add(()=>[]);
          assert(done&&calls[1].raw===first.raw&&calls[1].context===first.context,'identical frozen retry');c.destroy();
          const d=new Composer({...s,applyCanvasDraft:async()=>new Promise(r=>release=r)},false);d.name='Double';d.note='One';
          const saving=d.add(()=>[]);await delay(0);
          assert(d.busy&&await d.add(()=>[])===null,'double Add ignored');
          release('x');await saving;d.destroy();
          const refused=new Composer({...s,applyCanvasDraft:async()=>{throw new ApiError(400,'known refusal')}},false);
          refused.name='Refused';refused.note='Note';await refused.add(()=>[]);
          assert(!refused.locked&&refused.note==='Note'&&refused.error==='known refusal','known refusal editable');refused.destroy();
          const req=[], ranking=[];
          const find=new Composer({search:q=>new Promise((resolve,reject)=>req.push({q,resolve,reject})),smart:q=>new Promise(resolve=>ranking.push({q,resolve}))},true);
          find.q='old';find.search();await delay(160);find.q='new';find.search();await delay(160);
          req[1].resolve([2]);ranking[1].resolve([3]);await delay(0);req[0].resolve([9]);ranking[0].resolve([9]);await delay(0);
          assert(find.ids.has(2)&&!find.ids.has(9)&&find.rank.has(3),'late search ignored');
          find.q='third';find.search();await delay(160);find.smart=false;find.search();await delay(160);
          ranking[2].resolve([9]);req[3].resolve([]);await delay(0);
          assert(find.rank===null&&find.ids.size===0,'Smart-off invalidates and empty keyword stays empty');find.destroy();
          // A selected bitmap retains its stable UID across a negative-ID remap.
          const canvas=document.createElement('canvas');canvas.width=80;canvas.height=120;
          const blob=await new Promise(r=>canvas.toBlob(r));let active=0,max=0,held=[];
          const thumbnails={kind:'mirror',thumbBlob:async()=>{active++;max=Math.max(max,active);await new Promise(r=>held.push(r));active--;return blob}};
          const picks=new Composer(thumbnails,false), rows=Array.from({length:8},(_,i)=>({id:-(i+1),uid:String(i+1).padStart(32,'0'),tv:1,thumb:true,title:'Pick '+i}));
          rows.forEach(r=>picks.pick(r));await delay(0);assert(max===4&&held.length===4,'four-worker bound');
          held.splice(0).forEach(r=>r());await delay(50);held.splice(0).forEach(r=>r());await delay(50);
          assert(picks.picks.every(p=>p.state==='ready'),'all prepared');
          const key=picks.picks[1].key, original=picks.picks[1].blob;picks.selected=key;picks.remove(picks.picks[0].key);
          assert(picks.picks[0].key===key&&picks.selected===null,'selection never transfers');
          picks.reconcile(rows.slice(1).map(r=>({...r,id:-r.id+100})));
          assert(picks.picks[0].row.id===102&&picks.picks[0].blob===original,'UID remap retains blob');
          picks.reconcile(rows.slice(2));assert(picks.picks[0].state==='unavailable'&&!picks.canAdd,'removed item retained unavailable');
          picks.destroy();assert(max===4,'verification concurrency');
          let oldReject,fetches=0;
          const late=new Composer({kind:'mirror',thumbBlob:()=>++fetches===1?new Promise((_,reject)=>oldReject=reject):Promise.resolve(blob)},false);
          late.pick(rows[0]);late.remove(rows[0].uid);late.pick(rows[0]);await delay(50);
          oldReject(Error('obsolete'));await delay(0);assert(late.picks[0].state==='ready','obsolete failure cannot poison repick');late.destroy();
          const bad=new Composer({kind:'mirror',thumbBlob:async()=>new Blob(['corrupt'])},false);
          bad.pick(rows[0]);await delay(50);bad.note='Still one note';bad.noteMode=true;
          assert(bad.unavailable===1&&!bad.canAdd&&bad.n===2,'corrupt selected image blocks even in note mode');bad.destroy();
          return 'session double Add, uncertain retry, known refusal, search races, four-job bound and UID remap passed';
        """)
        assert not errors, errors
        print(result)


def targets_and_navigation(browser, base):
    with synthetic_phone(browser, base, 390, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_role('button', name='New canvas', exact=True).wait_for()
        print(module(p, """
          const assert=(ok,text)=>{if(!ok)throw Error(text)}, hex=()=>crypto.randomUUID().replaceAll('-','');
          const cid=hex(), raw={new_name:'Held creation',layout:'rows',elements:[{kind:'text',text:'Created',color:'#FFF9C4'}]};
          source.pair.solo=false;source.manifest={format:1,published:0,files:{}};
          await source.applyCanvasDraft(raw,{opId:hex(),canvasId:cid,at:10,base:null,thumbs:[]});
          assert((await source.canvasDraftProblem(cid))===null&&source.canvasStatus(cid).includes('Update the PC'),'old PC holds locally');
          source.manifest.canvas_change=1;assert(source.canvasSync&&source.canvasStatus(cid)==='Waiting to sync','capability upgrade');
          const created=source.changes.list.find(e=>e.canvas_id===cid);
          await source.changes.canvasResult(created,'refused','Creation refused');
          await source.changes.commitCanvas({op:'canvas',op_id:hex(),canvas_id:cid,at:11,state:'queued',proposal:{canvas_id:cid,layout:'rows',elements:raw.elements},refs:{},sizes:{},canvasLocal:{base:null,result:created.canvasLocal.result,assets:[],status:'pending'}});
          assert((await source.canvasDraftProblem(cid)).includes('Creation refused'),'later append never masks refused creation');
          const missing=hex();await source.changes.commitCanvas({op:'canvas',op_id:hex(),canvas_id:missing,at:12,state:'queued',proposal:{canvas_id:missing,layout:'rows',elements:raw.elements},refs:{},sizes:{}});
          assert((await source.canvasDraftProblem(missing)).includes('missing'),'missing creation refused');
          const missingEntry=source.changes.list.find(e=>e.canvas_id===missing);
          missingEntry.canvasLocal={base:null,result:{id:missing,name:'Unresolved copy',items:[{id:'copy',type:'note',text:'Kept',x:40,y:40,w:240,h:160}]},assets:[],status:'pending'};
          assert((await source.canvases()).find(e=>e.id===missing).name==='Canvas waiting for earlier backup','retained unresolved copy keeps waiting row');
          const saved=hex(), savedDoc={id:saved,name:'Saved only',created:20,modified:20,items:[{id:'note',type:'note',text:'Saved',x:40,y:40,w:240,h:160}]};
          await store.kv.set('saved-canvases',[{id:saved,doc:savedDoc,name:'Saved only',at:20,images:[],size:20}]);
          assert((await source.canvases()).some(e=>e.id===saved)&&(await source.canvasDraftProblem(saved))===null,'saved-only eligible');
          const op=hex(),{applyCanvasLocal,normalizeCanvas}=await import('/src/mobile/ai/canvas.ts');
          const appendRaw={canvas_id:saved,layout:'rows',elements:raw.elements};
          const refusedDoc=applyCanvasLocal(normalizeCanvas(appendRaw),savedDoc,new Map(),op,saved,22);
          const append={op:'canvas',op_id:op,canvas_id:saved,at:22,state:'queued',proposal:appendRaw,refs:{},sizes:{},canvasLocal:{base:savedDoc,result:refusedDoc,assets:[],status:'refused',reason:'Append refused',pc:20}};
          await source.changes.commitCanvas(append);assert((await source.canvasDraftProblem(saved)).includes('Append refused'),'retained refused overlay blocked');
          await store.kv.set('saved-canvases',[{id:saved,doc:{...refusedDoc,modified:100},name:'Saved only',at:100,images:[],size:20}]);
          assert((await source.canvasDraftProblem(saved)).includes('Append refused'),'saved refused overlay is not a newer PC version');
          savedDoc.modified=30;await store.kv.set('saved-canvases',[{id:saved,doc:savedDoc,name:'Saved only',at:30,images:[],size:20}]);
          assert((await source.canvasDraftProblem(saved))===null,'canonical supersedes refused append');
          source.pair.solo=true;return 'target eligibility: saved-only, old-PC hold/upgrade, missing/refused creation and superseded append passed';
        """))
        # Browser traversal is cancelled before the composer unmounts; dismissing keeps the draft.
        p.get_by_role('button', name='New canvas', exact=True).click()
        p.get_by_role('button', name='Write a note', exact=True).click()
        p.get_by_label('Note text', exact=True).fill('Keep through history')
        p.evaluate('history.back()')
        expect(p.get_by_role('dialog')).to_be_visible()
        assert p.url.endswith('/new')
        p.keyboard.press('Escape')
        expect(p.get_by_role('dialog')).not_to_be_visible()
        expect(p.get_by_label('Note text', exact=True)).to_have_value('Keep through history')
        # The shell path also goes through the same guard; the OwnerLine uses this exact API.
        module(p, "const {go}=await import('/src/mobile/shell.svelte.ts');go('#/backup')")
        expect(p.get_by_role('dialog')).to_be_visible()
        p.evaluate('history.back()')  # repeated Back must not replace the saved continuation
        p.get_by_role('button', name='Discard', exact=True).click()
        expect(p).to_have_url(re.compile('#/backup$'))
        # Cleanup cannot leave the guard on the next ordinary navigation.
        module(p, "const {go}=await import('/src/mobile/shell.svelte.ts');go('#/canvas')")
        p.get_by_role('button', name='New canvas', exact=True).click()
        p.get_by_label('Canvas name', exact=True).fill('Name alone')
        p.get_by_role('button', name='Back', exact=True).click()
        expect(p.get_by_role('button', name='New canvas', exact=True)).to_be_visible()
        assert not errors, errors
        print('Navigation API: traversal Keep/Escape, repeated Back, shell/OwnerLine continuation and cleanup passed')


def desktop_ui(browser, base):
    from core.db import Database
    with tempfile.TemporaryDirectory(prefix='brainamon-compose-pc-', ignore_cleanup_errors=True) as folder:
        root = Path(folder)
        db = Database(root / 'data/content_manager.db')
        for i in range(4):
            iid = db.add_item({'url': f'https://example.test/pc/{i}', 'short_desc': f'PC fixture {i}', 'description': 'Synthetic only', 'thumb_path': 'thumb.jpg'})
            directory = db.item_dir(iid); directory.mkdir(parents=True, exist_ok=True)
            (directory / 'thumb.jpg').write_bytes(JPEG)
        db.close()
        run = Run(SimpleNamespace(out=str(ART), only='', repo=str(ROOT), dist=None, port=0))
        run.start(root)
        try:
            run.api('PUT', '/api/onboarding', {'answer': 'links'})
            pending = run.api('POST', '/api/canvases/request', {'proposal': {'new_name': 'Pending PC Wiskit', 'elements': [{'kind': 'text', 'text': 'Do not consume'}]}})
            context = browser.new_context(viewport={'width': 390, 'height': 780}, is_mobile=True, has_touch=True, locale='en-US')
            context.add_init_script("localStorage.setItem('bp-lang','en')")
            errors, attempts = [], []
            lost = [True]

            def route(r):
                from urllib.parse import urlparse
                url = urlparse(r.request.url)
                if not r.request.url.startswith(base):
                    r.abort(); return
                if url.path.startswith(('/api/', '/thumb/', '/files/')):
                    if url.path == '/api/events':
                        r.fulfill(body='', content_type='text/event-stream'); return
                    if url.path == '/api/canvases/draft':
                        attempts.append(r.request.post_data_json)
                    headers = {k: v for k, v in r.request.headers.items() if k not in ('origin', 'host', 'referer')}
                    response = r.fetch(url=run.base + url.path + ('?' + url.query if url.query else ''),
                                       headers={**headers, 'Origin': run.base, 'Authorization': 'Bearer ' + run.token})
                    if url.path == '/api/canvases/draft' and lost[0]:
                        lost[0] = False; r.abort(); return
                    r.fulfill(response=response); return
                if url.path.startswith('/cards/'):
                    r.fulfill(path=ROOT / 'design/card-designs' / url.path.removeprefix('/cards/')); return
                r.continue_()

            context.route('**/*', route)
            p = context.new_page(); p.on('pageerror', lambda e: errors.append(str(e)))
            p.goto(base + '/mobile.html#/canvas/new')
            p.get_by_label('Canvas name', exact=True).fill('Direct canvas')
            p.get_by_role('button', name='Write a note', exact=True).click()
            p.get_by_label('Note text', exact=True).fill('Direct note')
            p.get_by_role('button', name='Add 1', exact=True).click()
            expect(p.get_by_role('alert')).to_contain_text('Could not confirm Add. Tap Add to check the same addition.')
            expect(p.get_by_label('Canvas name', exact=True)).to_be_disabled()
            expect(p.get_by_role('button', name='Add 1', exact=True)).to_be_enabled()
            p.get_by_role('button', name='Add 1', exact=True).click()
            expect(p.locator('.m-cp-view-add')).to_be_visible()
            assert attempts[0] == attempts[1]
            cid = attempts[0]['canvas_id']
            p.get_by_role('button', name='Add', exact=True).click()
            p.locator('.m-cp-tile').nth(0).click()
            p.locator('.m-cp-tile').nth(1).click()
            p.get_by_role('button', name='Columns', exact=True).click()
            expect(p.get_by_role('button', name='Add 2', exact=True)).to_be_enabled()
            changed_id = module(p, "return phone.rows.slice().sort((a,b)=>b.created-a.created||b.id-a.id)[0].id")
            run.api('PATCH', f'/api/items/{changed_id}', {'tags': 'changed during preview'})
            p.get_by_role('button', name='Add 2', exact=True).click()
            expect(p.get_by_role('alert')).to_contain_text('Canvas changed. Check the board and tap Add again.')
            expect(p.get_by_role('button', name='Add 2', exact=True)).to_be_enabled()
            p.get_by_role('button', name='Add 2', exact=True).click()
            expect(p.locator('.m-cp-view-add')).to_be_visible()
            saved = run.api('GET', '/api/canvases/' + cid)['canvas']
            assert len(saved['items']) == 3 and saved['items'][2]['y'] > saved['items'][1]['y']
            assert run.api('GET', '/api/jobs')['request']['id'] == pending['id']
            # A cold add route replaces itself with the viewer after success.
            p.goto(base + '/mobile.html#/canvas/' + cid + '/add')
            p.get_by_role('button', name='Write a note', exact=True).click()
            p.get_by_label('Note text', exact=True).fill('Cold add')
            p.get_by_role('button', name='Add 1', exact=True).click()
            expect(p).to_have_url(re.compile('/' + cid + '$'))
            expect(p.get_by_role('status').filter(has_text='Added 1 to Direct canvas.')).to_be_visible()
            p.reload()
            expect(p.locator('.m-cp-view-add')).to_be_visible()
            expect(p.locator('.m-cp-success')).to_have_count(0)
            assert not errors, errors
            context.close()
            print('Desktop: lost response/identical retry, columns, pending Wiskit, cold add and one-shot notice passed')
        finally:
            run.stop()


def fallback_and_native(browser, base):
    with synthetic_phone(browser, base, 360, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.add_init_script("Object.defineProperty(window,'navigation',{value:undefined})")
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_role('button', name='New canvas', exact=True).click()
        p.get_by_role('button', name='Write a note', exact=True).click()
        p.get_by_label('Note text', exact=True).fill('Fallback history')
        p.evaluate('history.back()')
        expect(p.get_by_role('dialog')).to_be_visible()
        expect(p.get_by_label('Note text', exact=True)).to_have_value('Fallback history')
        assert p.url.endswith('/new')
        p.get_by_role('button', name='Keep editing', exact=True).click()
        p.get_by_role('button', name='Back', exact=True).click()
        p.get_by_role('button', name='Discard', exact=True).click()
        expect(p.get_by_role('button', name='New canvas', exact=True)).to_be_visible()
        assert not errors, errors
    # This is a browser bridge simulation, not physical Android validation.
    context = browser.new_context(bypass_csp=True, viewport={'width': 390, 'height': 780}, locale='en-US')
    context.add_init_script("localStorage.setItem('bp-lang','en')")
    pair = json.dumps(json.dumps(PAIR))
    context.add_init_script("""
      window.androidBridge={};window.__listeners={};window.__secrets={'bp-pair':PAIR};
      localStorage.setItem('bp-wifi','off');
      window.Capacitor={
        PluginHeaders:['Brainamon','App'].map(name=>({name,methods:[{name:'secretGet',rtype:'promise'},{name:'secretSet',rtype:'promise'},
          {name:'networkStatus',rtype:'promise'},{name:'addListener',rtype:'callback'},{name:'removeListener',rtype:'promise'}]})),
        nativeCallback(plugin,method,options,callback){if(method==='addListener')__listeners[options.eventName]=callback;return 'fixture-listener'},
        nativePromise(plugin,method,options){
          if(method==='secretGet')return Promise.resolve({value:__secrets[options.key]||null});
          if(method==='secretSet')__secrets[options.key]=options.value;
          if(method==='networkStatus')return Promise.resolve({connected:true,type:'wifi'});
          return Promise.resolve({});
        }
      };
    """.replace('PAIR', pair))
    context.route('https://**/*', lambda r: r.abort())
    context.route(base + '/cards/**', lambda r: r.fulfill(path=ROOT / 'design/card-designs' / r.request.url.split('/cards/')[1].split('?')[0]))
    p = context.new_page(); fixture_routes(p)
    p.goto(base + '/mobile.html#/canvas/new')
    p.get_by_label('Canvas name', exact=True).fill('Native fixture')
    p.get_by_role('button', name='Write a note', exact=True).click()
    p.get_by_label('Note text', exact=True).fill('Keep these picks')
    p.wait_for_function('!!window.__listeners.shared && !!window.__listeners.sharedFile && !!window.__listeners.backButton')
    p.evaluate("__listeners.shared({text:'Synthetic shared text'})")
    expect(p.get_by_role('status')).to_contain_text('Shared to Add. Your picks are still here.')
    expect(p.get_by_label('Note text', exact=True)).to_have_value('Keep these picks')
    p.evaluate("__listeners.sharedFile({name:'synthetic.txt',type:'text/plain',data:btoa('File body')})")
    p.wait_for_function("async()=>{const {kv}=await import('/src/mobile/store.ts');return (await kv.get('drafts'))?.length===2}")
    assert p.url.endswith('/new')
    p.evaluate('__listeners.backButton({canGoBack:true})')
    expect(p.get_by_role('dialog')).to_be_visible()
    p.evaluate('__listeners.backButton({canGoBack:true})')
    expect(p.get_by_role('dialog')).not_to_be_visible()
    expect(p.get_by_label('Note text', exact=True)).to_have_value('Keep these picks')
    module(p, "const save=source.applyCanvasDraft.bind(source);source.applyCanvasDraft=async(...args)=>{await new Promise(r=>window.releaseCanvas=r);return save(...args)}")
    p.get_by_role('button', name='Add 1', exact=True).click()
    p.get_by_role('button', name='Adding…', exact=True).wait_for()
    module(p, """
      const put=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(value,key){const request=put.call(this,value,key),t=this.transaction;
        if(key==='drafts')queueMicrotask(()=>{const done=t.oncomplete;t.oncomplete=e=>{window.releaseShare=()=>done.call(t,e)}});
        return request};
    """)
    p.evaluate("__listeners.shared({text:'Shared during commit'})")
    p.wait_for_function("async()=>{const {kv}=await import('/src/mobile/store.ts');return (await kv.get('drafts'))?.length===3}")
    assert p.url.endswith('/new')
    p.evaluate('releaseCanvas()')
    expect(p.locator('.m-cp-view-add')).to_be_visible()
    p.wait_for_function('typeof releaseShare==="function"')
    p.evaluate('releaseShare()')
    expect(p.locator('.m-cp-view-add')).to_be_visible()
    expect(p.locator('.m-cv-txt')).to_have_count(1)
    context.close()
    print('Fallback history and simulated native Back/text/file Capture deferral passed')


def viewport_and_board(browser, base):
    for theme in ('light', 'dark'):
        with synthetic_phone(browser, base, 390, 780, theme) as (p, errors):
            fixture_routes(p)
            p.goto(base + '/mobile.html#/canvas')
            p.get_by_role('button', name='New canvas', exact=True).wait_for()
            seed(p, 16)
            p.get_by_role('button', name='New canvas', exact=True).click()
            p.get_by_label('Canvas name', exact=True).fill('Exercise references')
            p.get_by_role('button', name='Resize drawer', exact=True).click()
            p.locator('.m-cp-tile').nth(0).click()
            p.locator('.m-cp-tile').nth(1).click()
            expect(p.get_by_role('button', name='Add 2', exact=True)).to_be_enabled()
            # Keyboard selection and Remove affect the stable pick, then note clipping preserves full text.
            first = p.locator('.m-cp-staged').first
            first.focus(); p.keyboard.press('Enter')
            p.get_by_role('button', name='✕ Remove', exact=True).click()
            expect(p.get_by_role('button', name='Add 1', exact=True)).to_be_enabled()
            p.get_by_role('button', name='Write a note', exact=True).click()
            long = 'Full note text is retained.\n' * 30
            p.get_by_label('Note text', exact=True).fill(long)
            expect(p.get_by_role('button', name=long.strip(), exact=True)).to_be_visible()
            assert p.locator('.m-cp-staged.m-cv-txt').evaluate('(e)=>e.scrollHeight>e.clientHeight&&getComputedStyle(e).overflow==="hidden"')
            settle(p)
            p.screenshot(path=str(ART / f'note-{theme}-390.png'))
            p.get_by_label('Note text', exact=True).fill('x' * 1001)
            expect(p.get_by_role('button', name='Add 2', exact=True)).to_be_disabled()
            expect(p.get_by_role('alert')).to_contain_text('Use at most 1000 characters for the note.')
            p.get_by_label('Note text', exact=True).fill('Ask coach about hinge depth')
            p.get_by_role('button', name='Write a note', exact=True).click()
            for width, height in ((320, 780), (360, 780), (390, 780), (780, 360)):
                p.set_viewport_size({'width': width, 'height': height})
                p.wait_for_function('()=>Math.abs(document.querySelector(".m-cp-drawer").getBoundingClientRect().height-parseFloat(document.querySelector(".m-cp-drawer").style.height))<1')
                assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert p.locator('.m-cp-header .m-back').bounding_box()['height'] == 36
                p.screenshot(path=str(ART / f'compose-{theme}-{width}x{height}.png'))
            p.set_viewport_size({'width': 390, 'height': 780})
            p.get_by_label('Search the library', exact=True).focus()
            expect(p.get_by_role('button', name='Fit the board', exact=True)).to_have_count(0)
            settle(p)
            p.screenshot(path=str(ART / f'full-{theme}-390.png'))
            # Browser viewport resize approximates the available area with a keyboard, not a WebView keyboard.
            p.set_viewport_size({'width': 390, 'height': 460})
            p.wait_for_function('()=>document.querySelector(".m-cp-drawer").getBoundingClientRect().top>=document.querySelector(".m-cp-header").getBoundingClientRect().bottom+5')
            p.get_by_label('Canvas name', exact=True).focus()
            p.wait_for_function('()=>document.querySelector(".m-cp-drawer").getBoundingClientRect().height<80')
            p.set_viewport_size({'width': 390, 'height': 780})
            p.get_by_role('button', name='Resize drawer', exact=True).click()
            settle(p)
            prior = p.locator('.m-cp-drawer').bounding_box()['height']
            grip = p.get_by_role('button', name='Resize drawer', exact=True).bounding_box()
            p.mouse.move(grip['x'] + grip['width'] / 2, grip['y'] + grip['height'] / 2)
            p.mouse.down(); p.mouse.move(grip['x'] + grip['width'] / 2, grip['y'] - 80)
            p.locator('.m-cp-grip').dispatch_event('pointercancel', {'pointerId': 1})
            p.mouse.up(); settle(p)
            assert abs(p.locator('.m-cp-drawer').bounding_box()['height'] - prior) < 1
            p.emulate_media(reduced_motion='reduce')
            assert p.locator('.m-cp-drawer').evaluate('(e)=>getComputedStyle(e).transitionDuration') == '0s'
            p.emulate_media(reduced_motion='no-preference')
            module(p, "const {setMotionOff}=await import('/src/mobile/state.svelte.ts');setMotionOff(true)")
            expect(p.locator('.m-cp-page')).to_have_class(re.compile('m-cp-still'))
            assert p.locator('.m-cp-drawer').evaluate('(e)=>getComputedStyle(e).transitionDuration') == '0s'
            # Make the real OwnerLine appear, then verify its measured space and guarded link.
            module(p, "source.pair.solo=false;source.pair.g='synthetic@example.test';phone.signIn=true;phone.tokenAt++")
            p.locator('.m-strip-owner').wait_for()
            p.get_by_label('Search the library', exact=True).focus()
            p.wait_for_function('()=>document.querySelector(".m-cp-drawer").getBoundingClientRect().top>=document.querySelector(".m-cp-header").getBoundingClientRect().bottom+5')
            settle(p)
            p.screenshot(path=str(ART / f'owner-{theme}-390.png'))
            p.get_by_role('link', name=re.compile('Backup & phones')).click()
            expect(p.get_by_role('dialog')).to_be_visible()
            p.get_by_role('button', name='Keep editing', exact=True).click()
            p.locator('.m-cp-page input,.m-cp-page textarea,.m-cp-page button').evaluate_all('(els)=>els.forEach(e=>e.style.fontSize=parseFloat(getComputedStyle(e).fontSize)*1.4+"px")')
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
            p.screenshot(path=str(ART / f'large-text-{theme}-390.png'))
            assert not errors, errors
    print('Board keyboard Remove/long-note clipping; light/dark 320/360/390/landscape, viewport resizing, OwnerLine and both motion preferences passed')


def interrupted_storage(browser, base):
    for mode in ('unavailable', 'blocked', 'before', 'after'):
        with synthetic_phone(browser, base, 360, 780, 'light') as (p, errors):
            fixture_routes(p)
            if mode in ('unavailable', 'blocked'):
                p.add_init_script("""const open=indexedDB.open.bind(indexedDB);indexedDB.open=(name,...args)=>{
                  if(name!=='brainamon-phone')return open(name,...args);
                  if(MODE==='unavailable')throw Error('synthetic unavailable');
                  const request={};queueMicrotask(()=>request.onblocked?.({target:request}));return request;
                }""".replace('MODE', json.dumps(mode)))
            p.goto(base + '/mobile.html#/canvas/new')
            p.get_by_label('Canvas name', exact=True).fill('Interrupted ' + mode)
            p.get_by_role('button', name='Write a note', exact=True).click()
            p.get_by_label('Note text', exact=True).fill('Never partial')
            if mode == 'before':
                module(p, """
                  const add=IDBObjectStore.prototype.add;
                  IDBObjectStore.prototype.add=function(value,...rest){const r=add.call(this,value,...rest),t=this.transaction;
                    if(value.op==='canvas')r.addEventListener('success',()=>{window.beforeCommit=true;
                      const hold=()=>{t.objectStore('changes').get(0).onsuccess=hold};hold()});return r};
                """)
            elif mode == 'after':
                module(p, """
                  const descriptor=Object.getOwnPropertyDescriptor(IDBTransaction.prototype,'oncomplete');
                  Object.defineProperty(IDBTransaction.prototype,'oncomplete',{...descriptor,set(fn){descriptor.set.call(this,event=>{
                    if(this.mode==='readwrite'&&this.objectStoreNames.contains('changes')){window.afterCommit=true;return}
                    fn.call(this,event)
                  })}});
                """)
            p.get_by_role('button', name='Add 1', exact=True).click()
            if mode in ('unavailable', 'blocked'):
                expect(p.get_by_role('alert')).to_contain_text('storage')
                expect(p.get_by_label('Note text', exact=True)).to_have_value('Never partial')
            else:
                p.wait_for_function('window.' + ('beforeCommit' if mode == 'before' else 'afterCommit') + '===true')
                context = p.context
                p.close()
                q = context.new_page()
                q.goto(base + '/mobile.html#/canvas')
                if mode == 'before':
                    q.get_by_text('No canvases yet. Ask Wiskit to make one.').wait_for()
                else:
                    q.get_by_role('button', name=re.compile('Interrupted after')).click()
                    expect(q.locator('.m-cv-txt')).to_have_text('Never partial')
                    assert module(q, "return (await store.changes.all()).filter(e=>e.op==='canvas').length") == 1
                q.close()
    print('Unavailable/blocked storage and page termination before/after transaction completion passed')


def viewer_contracts(browser, base):
    with synthetic_phone(browser, base, 390, 780, 'light') as (p, errors):
        fixture_routes(p)
        p.goto(base + '/mobile.html#/canvas')
        p.get_by_role('button', name='New canvas', exact=True).wait_for()
        seed(p, 3)
        cid = module(p, """
          const row=phone.rows[0],blob=await source.thumbBlob(row),bitmap=await createImageBitmap(blob),size=[bitmap.width,bitmap.height];bitmap.close();
          const id=crypto.randomUUID().replaceAll('-','');
          await source.applyCanvasDraft({new_name:'Viewer fixture',layout:'rows',elements:[{kind:'thumbnail',item_id:row.id},{kind:'text',text:'Full viewer note',color:'#FFF9C4'}]},
            {opId:crypto.randomUUID().replaceAll('-',''),canvasId:id,at:Date.now(),base:null,thumbs:[{id:row.id,uid:row.uid,version:String(row.tv||0),blob,size}]});
          const {go}=await import('/src/mobile/shell.svelte.ts');go('#/canvas/'+id);return id;
        """)
        p.locator('.m-cv-el').wait_for()
        initial = p.locator('.m-cv-board').get_attribute('style')
        transform = p.locator('.m-cv-board').evaluate('(e)=>{const m=new DOMMatrix(getComputedStyle(e).transform);return {x:m.e,y:m.f,s:m.a}}')
        host = p.locator('.m-cv').bounding_box()
        p.get_by_role('button', name='Zoom in', exact=True).click()
        assert p.locator('.m-cv-board').get_attribute('style') != initial
        zoomed = p.locator('.m-cv-board').evaluate('(e)=>{const m=new DOMMatrix(getComputedStyle(e).transform);return {x:m.e,y:m.f,s:m.a}}')
        k = zoomed['s'] / transform['s']
        assert abs(zoomed['x'] - (host['width'] / 2 - (host['width'] / 2 - transform['x']) * k)) < .02
        assert abs(zoomed['y'] - (host['height'] / 2 - (host['height'] / 2 - transform['y']) * k)) < .02
        p.get_by_role('button', name='Fit', exact=True).click()
        assert p.locator('.m-cv-board').get_attribute('style') == initial
        box = p.locator('.m-cv-el').bounding_box()
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        p.mouse.move(x, y); p.mouse.down(); p.mouse.move(x + 30, y + 30, steps=3); p.mouse.up()
        assert p.url.endswith(cid)
        cdp = p.context.new_cdp_session(p)
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': 100, 'y': 200, 'id': 1}, {'x': 200, 'y': 200, 'id': 2}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': 80, 'y': 210, 'id': 1}, {'x': 220, 'y': 210, 'id': 2}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
        assert p.url.endswith(cid)
        cdp.detach()
        p.get_by_role('button', name='Fit', exact=True).click()
        p.locator('.m-cv-el').click()
        expect(p).to_have_url(re.compile('#/item/-[0-9]+$'))
        p.evaluate('history.back()')
        p.get_by_role('button', name='Save for offline', exact=True).click()
        expect(p.get_by_role('button', name='✓ Saved', exact=True)).to_be_visible()
        module(p, "source.canvas=async()=>{throw Error('synthetic offline')};const {go}=await import('/src/mobile/shell.svelte.ts');go('#/canvas');go('#/canvas/'+arg)", cid)
        expect(p.locator('.m-cv-txt')).to_have_text('Full viewer note')
        # File images retry after 3 and 6 seconds; missing library rows keep their placeholder.
        p.clock.install()
        p.context.route('**/thumb/**', lambda route: route.abort())
        module(p, """
          phone.rows=phone.rows.map(row=>({...row,tv:row.tv+100000}));
          source.canvas=async()=>({id:'fixture',name:'Missing viewer',items:[
            {id:'missing-row',type:'image',source:'db',item_id:999999,x:40,y:40,w:220,h:165},
            {id:'missing-file',type:'image',source:'file',file_path:'missing.jpg',x:340,y:40,w:200,h:150},
            {id:'retry-library',type:'image',source:'db',item_id:phone.rows[0].id,x:40,y:250,w:220,h:165}]});
          const {go}=await import('/src/mobile/shell.svelte.ts');go('#/canvas/fixture');
        """)
        expect(p.get_by_text('Image unavailable', exact=True)).to_be_visible()
        p.wait_for_function('()=>{const images=[...document.querySelectorAll(".m-cv-el img")];return images.length===2&&images.every(e=>e.dataset.tries==="1")}')
        p.clock.fast_forward(3100)
        p.wait_for_function('()=>[...document.querySelectorAll(".m-cv-el img")].every(e=>e.dataset.tries==="2")')
        p.clock.fast_forward(6100)
        expect(p.locator('.m-cv-el.file')).to_have_attribute('data-missing', '1')
        expect(p.locator('.m-cv-el[data-missing="1"]')).to_have_count(2)
        assert not errors, errors
    print('Viewer fit/zoom, drag versus tap, tap-to-open, Save/offline fallback, missing rows and 3s/6s file retries passed')


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with mobile_browser() as (browser, base):
        mirror_ui(browser, base)
        source_and_journal(browser, base)
        session_contracts(browser, base)
        targets_and_navigation(browser, base)
        desktop_ui(browser, base)
        fallback_and_native(browser, base)
        viewport_and_board(browser, base)
        interrupted_storage(browser, base)
        viewer_contracts(browser, base)


if __name__ == '__main__':
    main()
