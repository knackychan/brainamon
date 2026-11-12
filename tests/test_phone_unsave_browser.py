"""Unsave against synthetic site DOM and phone storage; never touches an account."""
import unittest

from playwright.sync_api import expect
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone
from tests.test_phone_import_browser import ROOT, OUT, FACEBOOK_NATIVE, reader_test, show, settle_import


class PhoneUnsaveBrowser(unittest.TestCase):
    def test_facebook_unsave_keeps_scrolling_after_rows_are_removed(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('https://www.facebook.com/saved/', lambda route: route.fulfill(
                body='<div id="saved"></div>', content_type='text/html'))
            page.goto('https://www.facebook.com/saved/')
            page.evaluate('''() => {
                document.body.style.overflow='hidden';
                const list=document.querySelector('#saved');
                list.style.cssText='position:fixed;width:300px;height:300px;overflow-y:auto';
                let count=0;window.removed=[];
                function load() {
                    list.replaceChildren();
                    for(let i=0;i<10&&count<25;i++) {
                        const id=100000+count++,row=document.createElement('article');
                        row.style.height='100px';
                        row.innerHTML=`<a href="https://www.facebook.com/reel/${id}/">Caption ${id}</a><span>Add to collection</span><button aria-label="More options">More</button>`;
                        row.querySelector('button').onclick=()=>{
                            const menu=document.createElement('div');menu.setAttribute('role','menu');
                            menu.innerHTML='<button role="menuitem">Unsave</button>';
                            menu.firstChild.onclick=()=>{window.removed.push(id);row.remove();menu.remove()};
                            document.body.append(menu);
                        };
                        list.append(row);
                    }
                    const tail=document.createElement('div');tail.style.height='600px';list.append(tail);
                    list.scrollTop=0;
                }
                load();
                list.addEventListener('scroll',()=>{
                    if(count<25&&list.scrollTop+list.clientHeight>=list.scrollHeight-4)load();
                });
                const timer=window.setTimeout;
                window.setTimeout=(fn,ms)=>timer(fn,Math.min(ms,20));
            }''')
            scripts = '\n'.join((ROOT / 'scrapers/sites' / name).read_text(encoding='utf-8')
                                for name in ('facebook.js', '_runner.js'))
            result = page.evaluate('async () => {' + scripts + ''';
                const sent=[];let listener;
                await main({addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
                    const m=JSON.parse(data);sent.push(m);
                    const reply=m.t==='hello'?{t:'init',run:'fixture',known:[],signed:true,unsave:true}:
                        m.t==='ping'?{t:'signed',on:true,active:true}:
                        m.t==='batch'?{t:'stored',batch:m.batch,urls:m.items.map(x=>x.url)}:null;
                    if(reply)listener({data:JSON.stringify(reply)});
                }});
                return {urls:sent.filter(m=>m.t==='batch').flatMap(m=>m.items.map(x=>x.url)),
                    removed:window.removed,end:sent.at(-1)};
            }''')
            self.assertEqual(len(set(result['urls'])), 25)
            self.assertEqual(len(set(result['removed'])), 25)
            self.assertEqual(result['end'], {'t': 'end', 'reason': 'end'})
            self.assertEqual(errors, [])

    def test_instagram_failed_unsave_returns_to_saved_and_stays_disabled_after_reload(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            saved = 'https://www.instagram.com/sam.example/saved/all-posts/'
            page.route(saved, lambda route: route.fulfill(body='<main></main>', content_type='text/html'))
            page.goto(saved)
            scripts = '\n'.join((ROOT / 'scrapers/sites' / name).read_text(encoding='utf-8')
                                for name in ('instagram.js', '_runner.js'))
            result = page.evaluate('async saved => {' + scripts + ''';
                let listener,failed=false,clicks=0,reloads=0;
                const sent=[],mainEl=document.querySelector('main');
                // Simulate a document reload while keeping the native Activity and run storage.
                var location={href:saved,pathname:new URL(saved).pathname,assign(url){
                    reloads++;this.href=url;this.pathname=new URL(url).pathname;
                    document.querySelectorAll('[role="dialog"]').forEach(el=>el.remove());
                    fill(25);
                }};
                function fill(count) {
                    mainEl.replaceChildren();
                    for(let i=0;i<count;i++) {
                        const a=document.createElement('a');a.href=`https://www.instagram.com/p/Post${i}/`;
                        a.textContent=`Caption ${i}`;a.style.display='block';
                        a.onclick=e=>{
                            e.preventDefault();location.href=a.href;location.pathname=new URL(a.href).pathname;
                            const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
                            dialog.innerHTML='<button><svg width="20" height="20" aria-label="Remove"></svg></button>';
                            dialog.firstChild.onclick=()=>{
                                clicks++;
                                if(clicks<3)dialog.querySelector('svg').setAttribute('aria-label','Save');
                            };
                            if(clicks<2) {
                                const close=document.createElement('button');close.setAttribute('aria-label','Close');
                                close.textContent='Close';close.onclick=()=>{
                                    dialog.remove();a.remove();location.href=saved;location.pathname=new URL(saved).pathname;
                                };dialog.append(close);
                            }
                            document.body.append(dialog);
                        };mainEl.append(a);
                    }
                }
                fill(10);sleep=async()=>{};scroll=()=>{};
                const testPort={addEventListener:(_,fn)=>listener=fn,postMessage:data=>{
                    const m=JSON.parse(data);sent.push(m);
                    if(m.t==='status'&&m.unsaveFailed)failed=true;
                    const reply=m.t==='hello'?{t:'init',run:'fixture',known:[],signed:true,unsave:true,unsaveFailed:failed}:
                        m.t==='ping'?{t:'signed',on:true,active:true}:
                        m.t==='batch'?{t:'stored',batch:m.batch,urls:m.items.map(x=>x.url)}:null;
                    if(reply)listener({data:JSON.stringify(reply)});
                }};
                await main(testPort);
                await main(testPort);
                return {urls:sent.filter(m=>m.t==='batch').flatMap(m=>m.items.map(x=>x.url)),
                    clicks,reloads,failed,end:sent.at(-1)};
            }''', saved)
            self.assertEqual(len(set(result['urls'])), 25)
            self.assertEqual(result['clicks'], 3)
            self.assertEqual(result['reloads'], 1)
            self.assertTrue(result['failed'])
            self.assertEqual(result['end'], {'t': 'end', 'reason': 'end'})
            self.assertEqual(errors, [])

    def test_option_defaults_off_and_reaches_native_only_for_supported_readers(self):
        with mobile_browser() as (browser, base):
            for site, width in [('facebook', 320), ('instagram', 390), ('threads', 390)]:
                with self.subTest(site=site), synthetic_phone(browser, base, width, 844, 'dark') as (page, errors):
                    reader_test(page, site=site)
                    script = FACEBOOK_NATIVE.replace('export async function siteOpen(site, known, full, complete) {',
                                                     'async function legacyOpen(site, known, full, complete) {', 1)
                    script = script.replace('t.calls.push({site,known,full,complete});',
                                            't.calls.push({site,known,full,complete,unsave:arguments[4]});')
                    page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=script))
                    page.goto(base + '/mobile.html#/import')
                    block = show(page, site.title())
                    toggle = block.get_by_role('button', name='Unsave collected posts', exact=True)
                    if site == 'threads':
                        expect(toggle).to_have_count(0)
                    else:
                        expect(toggle).to_have_attribute('aria-pressed', 'false')
                        toggle.click()
                        expect(toggle).to_have_attribute('aria-pressed', 'true')
                    scan = block.get_by_role('button', name='Scan saved posts', exact=True)
                    scan.click()
                    block.get_by_role('button', name='Cancel', exact=True).click()
                    self.assertEqual(page.evaluate('window.__sites.calls'), [])
                    scan.click()
                    block.get_by_role('button', name='Continue', exact=True).click()
                    page.wait_for_function('window.__sites.calls.length === 1')
                    self.assertEqual(page.evaluate('window.__sites.calls[0].unsave'), site != 'threads')
                    expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_enabled()
                    if site != 'threads':
                        expect(toggle).to_be_disabled()
                    settle_import(page)
                    self.assertLessEqual(block.evaluate('e=>e.scrollWidth-e.clientWidth'), 1)
                    OUT.mkdir(parents=True, exist_ok=True)
                    block.screenshot(path=str(OUT / f'{site}-unsave-{width}.png'))
                    self.assertEqual(errors, [])

    def test_adapters_remove_only_the_target_and_require_a_confirmed_change(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('https://www.facebook.com/saved/', lambda route: route.fulfill(
                path=ROOT / 'tests/fixtures/site_cards/facebook.html', content_type='text/html'))
            page.goto('https://www.facebook.com/saved/')
            runner = (ROOT / 'scrapers/sites/_runner.js').read_text(encoding='utf-8')
            adapter = (ROOT / 'scrapers/sites/facebook.js').read_text(encoding='utf-8')
            result = page.evaluate('async () => {' + adapter + runner + '''
                sleep=async()=>{};
                const cards=SITE.read(document), row=SITE.rows.get(cards[0].url);
                const more=document.createElement('button');more.setAttribute('aria-label','More options');row.append(more);
                more.onclick=()=>{const menu=document.createElement('div');menu.setAttribute('role','menu');
                  menu.innerHTML='<button role="menuitem">Unsave</button>';document.body.append(menu);
                  menu.firstChild.onclick=()=>{row.remove();menu.remove()}};
                const guarded=await SITE.unsave(document,cards[0].url,()=>false);
                document.querySelector('[role="menu"]').remove();
                const removed=await SITE.unsave(document,cards[0].url,()=>true);
                return [guarded,removed,SITE.read(document).map(c=>c.url)];
            }''')
            self.assertFalse(result[0])
            self.assertTrue(result[1])
            self.assertNotIn('https://www.facebook.com/reel/1234567890/', result[2])
            self.assertIn('https://www.facebook.com/watch/?v=9876543210', result[2])

            page.route('https://www.instagram.com/sam.example/saved/all-posts/', lambda route: route.fulfill(
                path=ROOT / 'tests/fixtures/site_cards/instagram.html', content_type='text/html'))
            page.goto('https://www.instagram.com/sam.example/saved/all-posts/')
            adapter = (ROOT / 'scrapers/sites/instagram.js').read_text(encoding='utf-8')
            result = page.evaluate('async () => {' + adapter + runner + '''
                sleep=async()=>{};
                const url=SITE.read(document)[0].url, link=document.querySelector('main a');
                let clicks=0, change=true;
                link.onclick=e=>{e.preventDefault();history.pushState({},'',new URL(url).pathname);
                  const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
                  dialog.innerHTML='<button><svg width="20" height="20" aria-label="Remove"></svg></button><button aria-label="Close">Close</button>';
                  document.body.append(dialog);
                  dialog.firstChild.onclick=()=>{clicks++;if(change)dialog.querySelector('svg').setAttribute('aria-label','Save')};
                  dialog.lastChild.onclick=()=>{dialog.remove();history.pushState({},'','/sam.example/saved/all-posts/')}};
                const guarded=await SITE.unsave(document,url,()=>false);
                document.querySelector('[aria-label="Close"]').click();
                change=false;const unchanged=await SITE.unsave(document,url,()=>true);
                change=true;const removed=await SITE.unsave(document,url,()=>true);
                return [guarded,unchanged,removed,clicks,SITE.onSaved(location)];
            }''')
            self.assertEqual(result, [False, False, True, 2, True])
            self.assertEqual(errors, [])
