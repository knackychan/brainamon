"""Phone site reader (projects/phone-site-reader/plans/02-runner-facebook.md): the page scripts' pure helpers
(scrapers/sites/*.js, under Node with no page, as the app joins them) and the phone's checks
(web/src/mobile/sites.ts), on made-up links and cards in tests/fixtures/site_cards/ (no personal data). Every
site with a page script has a fixture <site>.json; common.json holds the runner and picture cases. Skips
without Node 22.6+."""
import hashlib
import json
import unittest
from pathlib import Path

from tests import test_phone_js

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'scrapers' / 'sites'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'site_cards'
COMMON = json.loads((FIXTURES / 'common.json').read_text(encoding='utf-8'))
SITES = sorted(p.stem for p in FIXTURES.glob('*.json') if p.stem != 'common')

# plain page scripts in a Node vm context, joined as SiteReader.script joins them (no page: nothing boots)
LOAD = """
    import fs from 'node:fs'
    import vm from 'node:vm'
    const load = (...files) => {
      const ctx = vm.createContext({ URL, URLSearchParams, TextEncoder, crypto: globalThis.crypto, console })
      for (const f of files) vm.runInContext(fs.readFileSync('scrapers/sites/' + f, 'utf8'), ctx, { filename: f })
      return ctx
    }
    const S = await import('./web/src/mobile/sites.ts')
"""


def fixture(site: str) -> dict:
    return json.loads((FIXTURES / f'{site}.json').read_text(encoding='utf-8'))


def run(script: str):
    return json.loads(test_phone_js.node(test_phone_js.TS_RESOLVE + LOAD + script))


def h16(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


@unittest.skipUnless(test_phone_js._node_ok(), 'needs Node 22.6+ (type stripping)')
class SiteScriptsTest(unittest.TestCase):
    def test_every_fixture_site_has_a_script_and_a_rule(self):
        self.assertTrue((SCRIPTS / '_runner.js').is_file())
        self.assertIn('facebook', SITES)
        out = run(f"""
            const sites = {json.dumps(SITES)}
            console.log(JSON.stringify(sites.map(s => [load(s + '.js').SITE.id, !!S.RULES[s], S.SITES.some(x => x.id === s)])))
        """)
        for site, (sid, rule, listed) in zip(SITES, out):
            self.assertTrue((SCRIPTS / f'{site}.js').is_file(), site)
            self.assertEqual(sid, site)
            self.assertTrue(rule, site)
            self.assertTrue(listed, site)

    def test_joined_scripts_compile_in_strict_mode(self):
        # the text SiteReader.script builds, with no page and no channel: it must load and stay idle
        out = run(f"""
            const sites = {json.dumps(SITES)}
            const runner = fs.readFileSync('scrapers/sites/_runner.js', 'utf8')
            console.log(JSON.stringify(sites.map(s => {{
              const code = "(function () {{\\n'use strict';\\n" + fs.readFileSync('scrapers/sites/' + s + '.js', 'utf8') + '\\n' + runner + '\\n}})();\\n'
              vm.runInContext(code, vm.createContext({{ URL, TextEncoder, crypto: globalThis.crypto }}))
              return s
            }})))
        """)
        self.assertEqual(out, SITES)

    def test_links_agree_between_the_page_and_the_phone(self):
        for site in SITES:
            links = fixture(site)['links']
            out = run(f"""
                const ctx = load('{site}.js'), links = {json.dumps([x[0] for x in links])}
                console.log(JSON.stringify(links.map(u => {{
                  const c = ctx.SITE.canon(u)
                  return [c, c ? ctx.SITE.key(c) : '', S.canonical('{site}', u), S.siteKey('{site}', u)]
                }})))
            """)
            for (link, canon, key), (js_canon, js_key, ts_canon, ts_key) in zip(links, out):
                self.assertEqual(js_canon, canon, f'{site}.js canon {link}')
                self.assertEqual(js_key, key, f'{site}.js key {link}')
                self.assertEqual(ts_canon, canon, f'sites.ts canon {link}')
                self.assertEqual(ts_key, key, f'sites.ts key {link}')

    def test_hashes_match_python(self):
        texts = COMMON['hashes']
        out = run(f"""
            const ctx = load('_runner.js'), texts = {json.dumps(texts)}
            const page = [], phone = []
            for (const t of texts) {{ page.push(await ctx.hashOf(t)); phone.push(await S.hash16(t)) }}
            console.log(JSON.stringify([page, phone]))
        """)
        want = [h16(t) for t in texts]
        self.assertEqual(out, [want, want])

    def test_known_hashes_are_the_site_keys_only(self):
        for site in SITES:
            links = fixture(site)['links']
            out = run(f"""
                console.log(JSON.stringify(await S.knownHashes('{site}', {json.dumps([x[0] for x in links])})))
            """)
            self.assertEqual(sorted(out), sorted({h16(key) for _, _, key in links if key}), site)

    def test_runner_hashes_cards_with_the_site_key(self):
        for site in SITES:
            links = [x for x in fixture(site)['links'] if x[1]][:3]
            cards = [{'url': canon, 'kind': 'Reel', 'caption': 'c', 'creator': '', 'pic': ''} for _, canon, _ in links]
            cards += [{'url': 'https://example.com/other', 'kind': 'Other'}, {'url': 'https://example.com/x', 'kind': 'Reel'}, {'kind': 'Reel'}]
            out = run(f"""
                const ctx = load('{site}.js', '_runner.js')
                console.log(JSON.stringify((await ctx.hashCards({json.dumps(cards)})).map(c => [c.url, c.h])))
            """)
            want = [[canon, h16(key)] for _, canon, key in links] + [['https://example.com/other', 'other:https://example.com/other']]
            self.assertEqual(out, want, site)

    def test_runner_steps(self):
        out = run(f"""
            const ctx = load('_runner.js'), cases = {json.dumps(COMMON['steps'])}
            const names = s => {{ const m = /^(\\w+?)(\\d+)-(\\d+)$/.exec(s); if (!m) return [s]; const o = []; for (let i = +m[2]; i <= +m[3]; i++) o.push(m[1] + i); return o }}
            const card = s => {{ const [k, n] = s.split(':'); return names(n).map(x => ({{ url: 'https://example.com/' + x, kind: k === 'O' ? 'Other' : 'Reel', caption: '', creator: '', pic: '', h: x }})) }}
            console.log(JSON.stringify(cases.map(c => {{
              const run = Object.assign(ctx.newRun('r'), c.start || {{}})
              const opt = {{ known: Object.fromEntries(c.known.flatMap(names).map(h => [h, 1])), full: c.full, complete: c.complete }}
              let doc = ctx.newDoc()
              const got = []
              for (const p of c.passes) {{
                if (p === 'reload') {{ doc = ctx.newDoc(); continue }}
                const r = ctx.step(run, doc, p.flatMap(card), opt)
                got.push({{ send: r.send.map(x => x.url.slice('https://example.com/'.length)), stop: r.stop }})
              }}
              return {{ got, run: {{ read: run.read, known: run.known, other: run.other }} }}
            }})))
        """)
        for case, got in zip(COMMON['steps'], out):
            self.assertEqual(got['got'], case['want'], case['name'])
            self.assertEqual(got['run'], case['run'], case['name'])

    def test_where_the_page_is(self):
        cases = COMMON['where']
        out = run(f"""
            const ctx = load('_runner.js')
            console.log(JSON.stringify({json.dumps(cases)}.map(c => ctx.where(c[0], c[1], c[2], c[3]))))
        """)
        for case, got in zip(cases, out):
            self.assertEqual(got, case[4], case)

    def test_site_helpers(self):
        # each fixture's "calls": [helper name, [arguments], expected answer] on that site's SITE object
        for site in SITES:
            cases = fixture(site).get('calls', [])
            out = run(f"""
                const ctx = load('{site}.js')
                console.log(JSON.stringify({json.dumps(cases)}.map(c => ctx.SITE[c[0]](...c[1]))))
            """)
            for case, got in zip(cases, out):
                self.assertEqual(got, case[2], f'{site}: {case}')

    def test_check_items(self):
        for site in SITES:
            items = fixture(site)['items']
            long = {'url': items['posts'][0], 'kind': 'Reel', 'caption': 'x' * 6000, 'creator': 'y' * 200, 'pic': ''}
            out = run(f"""
                const r = S.checkItems('{site}', {json.dumps(items['raw'])})
                const long = S.checkItems('{site}', [{json.dumps(long)}]).posts[0]
                console.log(JSON.stringify({{ posts: r.posts.map(p => p.url), at: r.posts.map(p => p.at + p.tags), pics: r.pics,
                  dropped: r.dropped, long: [long.caption.length, long.creator.length], none: S.checkItems('{site}', null).dropped }}))
            """)
            self.assertEqual(out['posts'], items['posts'], site)
            self.assertEqual(set(out['at']), {'0'}, site)
            self.assertEqual(out['pics'], items['pics'], site)
            self.assertEqual(out['dropped'], items['dropped'], site)
            self.assertEqual(out['long'], [5000, 120], site)
            self.assertEqual(out['none'], 0, site)

    def test_picture_plan(self):
        cases = COMMON['pictures']
        out = run(f"""
            console.log(JSON.stringify({json.dumps(cases)}.map(c => S.picturePlan(c.url, c.hint ?? undefined, c.now))))
        """)
        for case, got in zip(cases, out):
            self.assertEqual(got, case['want'], case['url'])

    def test_hostile_authorities_and_exact_keys(self):
        out = run("""
            const c = load('facebook.js')
            const urls = ['https://user:secret@www.facebook.com/reel/1234567890/',
              'https://www.facebook.com:8443/reel/1234567890/']
            console.log(JSON.stringify([urls.map(u => [c.SITE.canon(u), S.canonical('facebook', u)]),
              c.SITE.key('https://www.facebook.com/reel/1234567890/extra'),
              S.RULES.facebook.key('https://www.facebook.com/watch/?v=1234567890evil')]))
        """)
        self.assertEqual(out, [[['', ''], ['', '']], '', ''])

    def test_whole_run_validation_and_bounded_pending(self):
        out = run("""
            const item = n => ({url:'https://www.facebook.com/reel/'+n+'/',kind:'Reel'})
            const raw = Array.from({length:501},(_,i)=>item(100000+i))
            raw[500]={url:'https://www.facebook.com/watch/?v=100000',kind:'Video'}
            const offsets=[]
            const result=await S.readPending('facebook',async(offset,max)=>{
              offsets.push([offset,max]); return {total:raw.length,items:raw.slice(offset,offset+max)}
            })
            const bad=[]
            for(const page of [{items:[],total:20001},{items:[],total:-1},{items:null,total:1}]) {
              try { await S.readPending('facebook',async()=>page); bad.push(false) } catch { bad.push(true) }
            }
            const empty=await S.readPending('facebook',async(offset)=>({total:501,items:offset? [item(999999)]:[]}))
            console.log(JSON.stringify({offsets,count:result.posts.length,bad,empty:empty.posts.length,corrupt:empty.dropped}))
        """)
        self.assertEqual(out, {'offsets': [[0, 500], [500, 500]], 'count': 500,
                               'bad': [True, True, True], 'empty': 1, 'corrupt': 500})

    def test_item_cap_does_not_refuse_a_duplicate(self):
        out = run("""
            const raw=Array.from({length:20000},(_,i)=>({url:'https://www.facebook.com/reel/'+(100000+i)+'/',kind:'Reel'}))
            raw.push(raw[0])
            const r=S.checkItems('facebook',raw)
            console.log(JSON.stringify([r.posts.length,r.dropped]))
        """)
        self.assertEqual(out, [20000, 0])

    def test_unique_cap_includes_known_and_other_items(self):
        out = run("""
            const c=load('_runner.js'), r=c.newRun('r'), d=c.newDoc()
            r.known=19999
            const x=c.step(r,d,[{url:'https://example.com/a',h:'a',kind:'Other'},
              {url:'https://example.com/b',h:'b',kind:'Reel'}],{known:{},complete:false,full:false})
            console.log(JSON.stringify([x.stop,r.read,r.other,r.known]))
        """)
        self.assertEqual(out, ['cap', 0, 1, 19999])

    def test_untrusted_session_storage_is_not_a_run(self):
        out = run("""
            const c=load('_runner.js')
            c.sessionStorage={getItem:()=>JSON.stringify({id:'r',seen:{},read:-10,known:0,other:0,streak:0,opens:0})}
            console.log(JSON.stringify(c.loadRun('r').read))
        """)
        self.assertEqual(out, 0)

    def test_runner_runtime_navigation_pause_batches_and_end(self):
        out = run("""
            const c=load('facebook.js','_runner.js'), sent=[], phases=[]
            let tick=0, waits=0, listener, storage=null
            c.Date={now:()=>tick}
            c.sessionStorage={getItem:()=>storage,setItem:(_,value)=>storage=value}
            c.document={visibilityState:'visible',querySelectorAll:()=>[]}
            c.navigator={onLine:true}; c.location={pathname:'/',assign:()=>{c.location.pathname='/saved/'}}
            c.window={scrollBy(){},scrollTo(){},innerHeight:800}
            c.scroll=()=>{};
            c.sleep=async ms=>{tick+=ms; if(++waits===2)c.document.visibilityState='hidden';
              else if(waits===3){c.document.visibilityState='visible';c.navigator.onLine=false}
              else if(waits===4)c.navigator.onLine=true}
            c.SITE.read=()=>Array.from({length:60},(_,i)=>({url:'https://www.facebook.com/reel/'+(100000+i)+'/',kind:'Reel'}))
            const port={addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
              const m=JSON.parse(data); sent.push(m)
              if(m.t==='hello')listener({data:JSON.stringify({t:'init',run:'r',known:[],signed:true})})
              if(m.t==='ping')listener({data:JSON.stringify({t:'signed',on:true})})
              if(m.t==='status')phases.push(m.phase)
            }}
            await c.main(port)
            console.log(JSON.stringify({phases,batches:sent.filter(m=>m.t==='batch').map(m=>m.items.length),
              end:sent.at(-1),state:JSON.parse(storage).read}))
        """)
        self.assertIn('open', out['phases'])
        self.assertIn('wait', out['phases'])
        self.assertEqual(out['batches'], [25, 25, 10])
        self.assertEqual(out['state'], 60)
        self.assertEqual(out['end'], {'t': 'end', 'reason': 'end'})

    def test_runner_waits_through_signin_and_challenge(self):
        out = run("""
            const c=load('facebook.js','_runner.js'), sent=[]
            let tick=0,n=0,listener
            c.Date={now:()=>tick}; c.sessionStorage={getItem:()=>null,setItem(){}}
            c.document={visibilityState:'visible',querySelectorAll:()=>[]}
            c.navigator={onLine:true}; c.location={pathname:'/login/'}; c.window={};c.scroll=()=>{}
            c.sleep=async ms=>{tick+=ms;if(++n===1)listener({data:JSON.stringify({t:'signed',on:true})});
              if(n===2)c.location.pathname='/saved/'}
            let reads=0;c.SITE.read=()=>{reads++;return []}
            const port={addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
              const m=JSON.parse(data);sent.push(m)
              if(m.t==='hello')listener({data:JSON.stringify({t:'init',run:'r',known:[],signed:false})})
            }}
            await c.main(port)
            console.log(JSON.stringify([sent.filter(m=>m.t==='status').map(m=>m.phase),reads,sent.at(-1)]))
        """)
        self.assertEqual(out, [['signin', 'check', 'read'], 3, {'t': 'end', 'reason': 'empty'}])

    def test_unsave_requires_matching_durable_receipt_and_stops_on_failure(self):
        out = run("""
            const results=[]
            for (const mode of ['off','ok','missing','partial','wrong-batch','paused','native-paused','native-silent','refused']) {
              const c=load('facebook.js','_runner.js'), removed=[], sent=[]
              let listener, tick=0, reply=null
              c.Date={now:()=>tick}; c.sessionStorage={getItem:()=>null,setItem(){}}
              c.document={visibilityState:'visible',querySelectorAll:()=>[]};c.navigator={onLine:true}
              c.location={pathname:'/saved/'};c.window={};c.scroll=()=>{}
              c.sleep=async ms=>{tick+=ms;if(reply){const m=reply;reply=null;listener({data:JSON.stringify(m)})}}
              c.SITE.read=()=>[100000,100001,100002].map(n=>({url:'https://www.facebook.com/reel/'+n+'/',kind:'Reel'}))
              c.SITE.unsave=async(doc,url,allowed)=>{if(!await allowed())return false;removed.push(url);return mode!=='refused'}
              const known=[await c.hashOf('fb:100000')]
              await c.main({addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
                const m=JSON.parse(data);sent.push(m)
                if(m.t==='hello')listener({data:JSON.stringify({t:'init',run:'r',known,signed:true,unsave:mode!=='off'})})
                if(m.t==='ping' && mode!=='native-silent')listener({data:JSON.stringify({t:'signed',on:true,active:mode!=='native-paused'||!sent.some(x=>x.t==='batch')})})
                if(m.t==='batch' && mode!=='missing') {
                  reply={t:'stored',batch:m.batch+(mode==='wrong-batch'?1:0),urls:m.items.map(x=>x.url)}
                  if(mode==='partial')reply.urls.pop()
                  if(mode==='paused')c.document.visibilityState='hidden'
                }
              }})
              results.push([mode,removed.map(u=>c.SITE.key(u)),sent.at(-1).reason])
            }
            console.log(JSON.stringify(results))
        """)
        self.assertEqual(out, [
            ['off', [], 'end'], ['ok', ['fb:100001', 'fb:100002'], 'end'],
            ['missing', [], 'failure'], ['partial', [], 'failure'],
            ['wrong-batch', [], 'failure'], ['paused', [], 'stop'],
            ['native-paused', [], 'unsave-failed'], ['native-silent', [], 'unsave-failed'],
            ['refused', ['fb:100001'], 'unsave-failed'],
        ])

    def test_native_background_signal_pauses_a_visible_webview(self):
        out = run("""
            const c=load('facebook.js','_runner.js'), phases=[]
            let tick=0,listener,reads=0
            c.Date={now:()=>tick};c.sessionStorage={getItem:()=>null,setItem(){}}
            c.document={visibilityState:'visible',querySelectorAll:()=>[]};c.navigator={onLine:true}
            c.location={pathname:'/saved/'};c.window={};c.scroll=()=>{}
            c.sleep=async ms=>{tick+=ms;listener({data:JSON.stringify({t:'signed',on:true,active:true})})}
            c.SITE.read=()=>{reads++;return []}
            await c.main({addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
              const m=JSON.parse(data)
              if(m.t==='hello')listener({data:JSON.stringify({t:'init',run:'r',known:[],signed:true,active:false})})
              if(m.t==='status')phases.push(m.phase)
            }})
            console.log(JSON.stringify([phases,reads]))
        """)
        self.assertEqual(out, [['wait', 'read'], 3])

    def test_instagram_runner_navigation_and_known_stop(self):
        out = run("""
            const results=[]
            for(const [complete,full] of [[false,false],[true,false],[true,true]]) {
              const c=load('instagram.js','_runner.js'), sent=[], routes=[]
              let listener,tick=0
              c.Date={now:()=>tick};c.sessionStorage={getItem:()=>null,setItem(){}}
              c.document={visibilityState:'visible',querySelectorAll:()=>[]};c.navigator={onLine:true}
              c.SITE.user=()=> 'sam.example'
              c.location={pathname:'/',assign:url=>{routes.push(url);c.location.pathname=new URL(url).pathname}}
              c.window={};c.scroll=()=>{};c.sleep=async ms=>{tick+=ms}
              c.SITE.read=()=>Array.from({length:26},(_,i)=>({url:'https://www.instagram.com/p/Synthetic'+i+'/',kind:'Post'}))
              const known=await Promise.all(Array.from({length:25},(_,i)=>c.hashOf('ig:Synthetic'+i)))
              await c.main({addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
                const m=JSON.parse(data);sent.push(m)
                if(m.t==='hello')listener({data:JSON.stringify({t:'init',run:'r',known,signed:true,complete,full})})
              }})
              results.push([routes,sent.at(-1).reason,sent.filter(m=>m.t==='batch').flatMap(m=>m.items).length,
                sent.filter(m=>m.t==='status').at(-1).known])
            }
            console.log(JSON.stringify(results))
        """)
        route = ['https://www.instagram.com/sam.example/saved/all-posts/']
        self.assertEqual(out, [[route, 'end', 1, 25], [route, 'known', 0, 20], [route, 'end', 1, 25]])

    def test_instagram_picture_boundaries_and_paged_dedupe(self):
        out = run("""
            const pics=['https://cdninstagram.com/a.jpg','https://xx.fbcdn.net/a.jpg',
              'https://cdninstagram.com.evil.example/a.jpg','http://xx.cdninstagram.com/a.jpg',
              'https://synthetic@xx.cdninstagram.com/a.jpg','https://xx.cdninstagram.com:8443/a.jpg']
            const items=Array.from({length:500},(_,i)=>({url:'https://www.instagram.com/p/Synthetic'+i+'/',kind:'Post'}))
            items.push({url:'https://www.instagram.com/reel/Synthetic0/',kind:'Reel'})
            const r=await S.readPending('instagram',async(offset,max)=>({total:items.length,items:items.slice(offset,offset+max)}))
            console.log(JSON.stringify([pics.map(p=>S.picOk('instagram',p)),r.posts.length,r.dropped,
              S.picturePlan(items[0].url,{u:pics[0],at:1000},432001000).hint]))
        """)
        self.assertEqual(out, [[True, True, False, False, False, False], 500, 0, ''])

    def test_threads_stop_paging_and_shared_import_keys(self):
        out = run("""
            const c=load('threads.js','_runner.js');
            const item=i=>({url:'https://www.threads.com/@sam.example/post/Synthetic'+i,kind:'Post'});
            const cards=await c.hashCards(Array.from({length:26},(_,i)=>item(i)));
            const known=Object.fromEntries(cards.slice(0,25).map(x=>[x.h,1]));
            const results=[[false,false],[true,false],[true,true]].map(([complete,full])=>{
              const r=c.newRun('r'),x=c.step(r,c.newDoc(),cards,{known,complete,full});
              return [x.stop,x.send.length,r.known];
            });
            const raw=Array.from({length:500},(_,i)=>item(i));
            raw.push({...item(0),url:'https://www.threads.com/@renamed.user/post/Synthetic0'});
            const checked=await S.readPending('threads',async(o,n)=>({items:raw.slice(o,o+n),total:raw.length}));
            console.log(JSON.stringify([results,checked.posts.length,checked.dropped,
              S.postKey('https://www.threads.net/@renamed.user/post/Synthetic0/?xmt=synthetic'),
              S.postPicOk(item(0).url,'https://xx.fbcdn.net/pic.jpg'),
              S.postPicOk(item(0).url,'https://fbcdn.net.evil.example/pic.jpg')]));
        """)
        self.assertEqual(out, [[['', 1, 25], ['known', 0, 20], ['', 1, 25]], 500, 0, 'th:Synthetic0', True, False])


if __name__ == '__main__':
    unittest.main()
