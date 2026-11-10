"""Production Import against disposable phone storage and a fake native reader, never accounts."""
import io
import json
from pathlib import Path
import unittest
import zipfile

from playwright.sync_api import expect
from tests.test_mobile_info_browser import mobile_browser, synthetic_phone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/phone-site-reader-05/browser'
NAMES = ['Instagram', 'Facebook', 'Threads', 'TikTok']
POST = [{'label_values': [{'label': 'URL', 'value': 'https://www.instagram.com/p/Promotion1/'}]}]


def show(page, name):
    block = page.get_by_role('region', name=name, exact=True)
    button = block.locator('.m-import-toggle')
    if button.get_attribute('aria-expanded') != 'true':
        button.click()
    expect(button).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('.m-import-toggle[aria-expanded="true"]')).to_have_count(1)
    return block


def close_help(page):
    dialog = page.get_by_role('dialog')
    ident = dialog.get_attribute('id')
    dialog.evaluate("x => { delete x.dataset.closed; x.addEventListener('close', () => x.dataset.closed='yes', {once:true}) }")
    dialog.get_by_role('button', name='Close', exact=True).click()
    expect(page.locator(f'dialog[id="{ident}"]')).to_have_attribute('data-closed', 'yes')


def settle_import(page):
    page.locator('.m-import-screen').evaluate('async x=>{await Promise.allSettled(x.getAnimations({subtree:true}).map(a=>a.finished))}')


NATIVE = '''
export * from '/src/mobile/native.ts?real-import-check';
export const siteState = async () => {
  const t=window.__sites;t.stateCalls=(t.stateCalls||0)+1;
  if(t.holdState) await new Promise(resolve=>{t.refresh=resolve});
  return structuredClone(t.state);
};
export async function siteOpen(site, known, full, complete) {
  const test=window.__sites;
  test.calls.push({site,known,full,complete});
  if(test.mode==='busy') throw Object.assign(new Error('native busy'),{code:'busy'});
  if(test.mode==='unsupported') return {reason:'unsupported'};
  if(test.mode==='wait') await new Promise(resolve => { test.finish=resolve });
  test.state.sites[site].signedIn=true;
  return {reason:'signed-in',added:0,known:0,other:0,dropped:0};
}
export async function siteForget(site) {
  const test=window.__sites;
  test.forgets.push(site);
  if(test.mode==='forget-error') throw new Error('Login could not be forgotten. Try again.');
  test.state.sites[site].signedIn=false;
  return 'cleared';
}
'''

FACEBOOK_NATIVE = NATIVE + '''
export async function siteOpen(site, known, full, complete) {
  const t=window.__sites;
  t.calls.push({site,known,full,complete});
  if(t.mode==='busy') throw Object.assign(new Error('native busy'),{code:'busy'});
  if(t.mode==='unsupported') return {reason:'unsupported'};
  if(t.mode==='wait') await new Promise(resolve=>{t.finish=resolve});
  t.state.sites[site].pending=t.items.length;
  return {reason:t.reason,added:t.items.length,known:0,other:2,dropped:0};
}
export async function sitePending(site,offset,max) {
  const t=window.__sites;
  if(t.mode==='pending-error') throw new Error('Could not read saved results. Retry.');
  return {items:t.items.slice(offset,offset+max),total:t.items.length};
}
export async function siteClear(site) {
  const t=window.__sites;
  if(t.mode==='clear-error') throw new Error('Could not clear saved results. Retry.');
  t.clears.push(site);t.items=[];t.state.sites[site].pending=0;
}
'''


def reader_test(page, *, pending=False, site='facebook'):
    state = {'supported': True, 'sites': {n.lower(): {'signedIn': False, 'forgetting': False,
             'pending': 0, 'reader': n.lower() == site} for n in NAMES}}
    items = [dict(url='https://www.facebook.com/reel/1234567890/', kind='Reel', caption='Synthetic boat <img src=x onerror="window.__injected=true">',
                  creator='Example', pic='https://scontent.xx.fbcdn.net/synthetic.jpg'),
             dict(url='https://www.facebook.com/watch/?v=1234567890', kind='Video'),
             dict(url='https://evil.example/reel/1234567891/', kind='Reel')]
    if site == 'instagram':
        items = [dict(url='https://www.instagram.com/reel/Cx1_ab-Z9/', kind='Reel',
                      caption='Synthetic <img src=x onerror="window.__injected=true">', creator='Example',
                      pic='https://scontent.cdninstagram.com/synthetic.jpg'),
                 dict(url='https://www.instagram.com/p/Cx1_ab-Z9/', kind='Post'),
                 dict(url='https://evil.example/p/Cx1_ab-Z9/', kind='Post')]
    if site == 'threads':
        items = [dict(url='https://www.threads.com/@sam.example/post/DAbc_12xyz', kind='Post',
                      caption='Synthetic <img src=x onerror="window.__injected=true">', creator='sam.example',
                      pic='https://scontent.cdninstagram.com/threads.jpg'),
                 dict(url='https://www.threads.com/@renamed.user/post/DAbc_12xyz', kind='Post'),
                 dict(url='https://evil.example/@sam.example/post/DAbc_12xyz', kind='Post')]
    if pending:
        state['sites'][site]['pending'] = len(items)
    page.add_init_script('window.__sites=' + json.dumps(dict(state=state, calls=[], clears=[],
                         items=items, reason='end', mode='')))
    # Keep the fake native module separate so existing sign-in coverage remains intact.
    script = FACEBOOK_NATIVE.replace('export async function siteOpen(site, known, full, complete) {',
                                    'async function legacyOpen(site, known, full, complete) {', 1)
    page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=script))


class PhoneImportBrowser(unittest.TestCase):
    def test_threads_extracts_synthetic_dom(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('https://www.threads.com/', lambda route: route.fulfill(
                path=ROOT / 'tests/fixtures/site_cards/threads.html', content_type='text/html'))
            page.goto('https://www.threads.com/')
            cards = page.evaluate('() => {' + (ROOT / 'scrapers/sites/threads.js').read_text(encoding='utf-8') + ';return SITE.read(document)}')
            self.assertEqual(len(cards), 2)
            self.assertEqual(cards[0], dict(url='https://www.threads.com/@sam.example/post/DAbc_12xyz', kind='Post',
                caption='A made-up thought about bread\nand butter', creator='sam.example',
                pic='https://scontent.cdninstagram.com/bread.jpg'))
            self.assertEqual(cards[1]['url'], 'https://www.threads.com/@pat.example/post/DAbc-34xyz')
            self.assertEqual(cards[1]['creator'], 'pat.example')
            self.assertEqual(cards[1]['pic'], '')
            self.assertEqual(errors, [])

    def test_threads_review_import_and_runs(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 320, 844, 'dark') as (page, errors):
            reader_test(page, site='threads')
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Threads')
            scan = block.get_by_role('button', name='Scan saved posts', exact=True)
            scan.click()
            block.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            scan.click()
            page.evaluate("window.__sites.mode='wait';window.__sites.reason='stop'")
            block.get_by_role('button', name='Continue', exact=True).click()
            expect(scan).to_be_disabled()
            page.wait_for_function('typeof window.__sites.finish==="function"')
            page.evaluate("window.__sites.mode='';window.__sites.finish()")
            imp = block.get_by_role('button', name='Import 1 post', exact=True)
            expect(imp).to_be_enabled()
            block.get_by_text('Review saved posts', exact=True).click()
            expect(block.get_by_text('Only validated Threads links enter your library.', exact=False)).to_be_visible()
            self.assertEqual(block.locator('img').count(), 0)
            self.assertFalse(page.evaluate('!!window.__injected'))
            OUT.mkdir(parents=True, exist_ok=True)
            settle_import(page)
            block.screenshot(path=str(OUT / 'threads-review-dark-320.png'))
            page.evaluate('''() => {const add=IDBObjectStore.prototype.add;
              IDBObjectStore.prototype.add=function(value,...args){
                if(this.name==='changes' && value.op==='details'){IDBObjectStore.prototype.add=add;throw new Error('Synthetic quota failure')}
                return add.call(this,value,...args)
              }}''')
            imp.click()
            expect(block.get_by_role('alert')).to_contain_text('Synthetic quota failure')
            self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()"), [])
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            imp.click()
            expect(block.get_by_role('status')).to_contain_text('1 added')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.threads.complete)"))
            stored = page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()")
            self.assertEqual([x['op'] for x in stored], ['link', 'details'])
            self.assertNotIn('cdninstagram.com', json.dumps(stored))
            duplicate = page.evaluate('''async()=> (await import('/src/mobile/state.svelte.ts')).mirrorSource.importLinks([
              {url:'https://www.threads.net/@renamed.user/post/DAbc_12xyz/?xmt=synthetic',at:0,caption:'',creator:'',tags:''}])''')
            self.assertEqual(duplicate, dict(ids=[], dups=1))
            page.evaluate("window.__sites.items=[];window.__sites.reason='end'")
            scan.click()
            expect(block.get_by_role('status')).to_contain_text('read to the end')
            self.assertFalse(page.evaluate('window.__sites.calls.at(-1).complete'))
            page.evaluate("window.__sites.reason='known'")
            scan.click()
            expect(block.get_by_role('status')).to_contain_text('stopped at posts already')
            call = page.evaluate('window.__sites.calls.at(-1)')
            self.assertTrue(call['complete'])
            self.assertEqual(len(call['known']), 1)
            self.assertRegex(call['known'][0], r'^[0-9a-f]{16}$')
            block.get_by_role('button', name='Read all again', exact=True).click()
            page.wait_for_function('window.__sites.calls.length===4')
            self.assertTrue(page.evaluate('window.__sites.calls.at(-1).full'))
            self.assertEqual(errors, [])

    def test_threads_pending_recovery_clear_retry(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            reader_test(page, site='threads', pending=True)
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Threads')
            imp = block.get_by_role('button', name='Import 1 post', exact=True)
            expect(imp).to_be_enabled()
            expect(block.get_by_role('status')).to_contain_text('cut off')
            block.get_by_role('button', name='Later', exact=True).click()
            block.get_by_role('button', name='Scan saved posts', exact=True).click()
            expect(imp).to_be_enabled()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            page.evaluate("window.__sites.mode='clear-error'")
            imp.click()
            expect(block.get_by_role('alert')).to_contain_text('Could not clear')
            page.evaluate("window.__sites.mode=''")
            imp.click()
            expect(block.get_by_role('status')).to_contain_text('already there')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.threads.complete)"))
            self.assertEqual(errors, [])

    def test_threads_local_hint_and_page_fallback(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            # Keep startup picture work from consuming this test's direct-source fixtures.
            page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
            page.route('**/thumbs-proxy.js', lambda route: route.fulfill(path=ROOT / 'web/public/thumbs-proxy.js', content_type='application/javascript'))
            page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=NATIVE + '''
export const isApp=true;
export async function linkImage(url){
  (window.__pictures??=[]).push(url);
  if(url.includes('expired')) throw Object.assign(new Error('Expired'),{status:403});
  const c=document.createElement('canvas');c.width=2;c.height=2;
  return Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),x=>x.charCodeAt(0));
}
export async function linkGet(url){return {status:200,text:'<meta property="og:image" content="https://xx.fbcdn.net/fallback.jpg">'}};
'''))
            page.goto(base + '/mobile.html#/import')
            page.wait_for_function("async()=>{const s=await import('/src/mobile/state.svelte.ts');return s.phone.tried && !s.phone.refreshing && s.pics.state==='idle'}")
            result = page.evaluate('''async()=>{
              const {mirrorSource:s}=await import('/src/mobile/state.svelte.ts');
              const {kv,changes}=await import('/src/mobile/store.ts');
              (await import('/src/mobile/network.svelte.ts')).network.manualPause=false;
              const make=code=>({url:'https://www.threads.com/@sam.example/post/'+code,at:0,caption:'',creator:'',tags:''});
              await s.importLinks([make('HintCode1')]);
              await s.addPicHints([['https://www.threads.net/@renamed.user/post/HintCode1','https://scontent.cdninstagram.com/good.jpg']]);
              const indexed=await kv.get('site-pics');
              const first=await s.fillPictures(()=>{},()=>false);
              await s.importLinks([make('Fallback1')]);
              await s.addPicHints([[make('Fallback1').url,'https://scontent.cdninstagram.com/expired.jpg']]);
              const fallback=await s.fillPictures(()=>{},()=>false);
              return {indexed,first,fallback,calls:window.__pictures,stored:await changes.all()};
            }''')
            self.assertIn('https://www.threads.com/@sam.example/post/HintCode1', result['indexed'])
            self.assertEqual(len(result['first']['got']), 1)
            self.assertEqual(len(result['fallback']['got']), 1)
            self.assertEqual(result['calls'], ['https://scontent.cdninstagram.com/good.jpg',
                'https://scontent.cdninstagram.com/expired.jpg', 'https://xx.fbcdn.net/fallback.jpg'])
            self.assertNotIn('cdninstagram.com', json.dumps(result['stored']))
            self.assertEqual(errors, [])

    def test_instagram_dom_and_profile_navigation(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('https://www.instagram.com/', lambda route: route.fulfill(
                path=ROOT / 'tests/fixtures/site_cards/instagram.html', content_type='text/html'))
            page.goto('https://www.instagram.com/')
            script = (ROOT / 'scrapers/sites/instagram.js').read_text(encoding='utf-8')
            result = page.evaluate('() => {' + script + ';return {cards:SITE.read(document),route:SITE.open(document)}}')
            self.assertEqual(result['route'], 'https://www.instagram.com/sam.example/saved/all-posts/')
            self.assertEqual([x['kind'] for x in result['cards']], ['Post', 'Reel', 'Post', 'Reel'])
            self.assertEqual([x['url'].split('/')[-2] for x in result['cards']], ['Cx1_ab-Z9', 'Cy2_cd-Y8', 'Cz3abcdEF', 'Cw4abcdEF'])
            self.assertEqual(result['cards'][0]['creator'], 'Sam Example')
            self.assertEqual(result['cards'][0]['caption'], 'Photo by Sam Example on May 01, 2024. Bread.')
            self.assertEqual(result['cards'][2]['creator'], 'Pat Example')
            cases = [
                ('<a href="https://evil.example/foreign/saved/">Saved</a>', None),
                ('<a href="/accounts/saved/">Saved</a><a href="/explore/">Profile</a>', None),
                ('<a href="/hidden/saved/" hidden>Saved</a><a href="/real.user/">Perfil</a>', 'real.user'),
                ('<a href="/priority/saved/">Saved</a><a href="/other/">Profile</a>', 'priority'),
                ('<a href="https://www.instagram.com/absolute/">Profile</a>', 'absolute'),
                ('<a href="https://synthetic@www.instagram.com/foreign/saved/">Saved</a>', None),
                ('<a href="https://www.instagram.com:8443/foreign/saved/">Saved</a>', None),
                ('<div><a href="/avatar.user/"><img alt="avatar.user\'s profile picture"></a></div>', 'avatar.user'),
                ('<div><a href="/avatar.user/"><img alt="avatar.user\'s profile picture"></a><a href="/avatar.user/"><img alt="avatar.user\'s profile picture"></a></div>', 'avatar.user'),
                ('<div><a href="/one.user/"><img alt="one.user\'s profile picture"></a><a href="/two.user/"><img alt="two.user\'s profile picture"></a></div>', None),
                ('<div><a href="/avatar.user/"><img alt="Photo by avatar.user on May 1"></a></div>', None),
                ('<a href="/hidden.user/" hidden><img alt="hidden.user\'s profile picture"></a>', None),
                ('<a href="https://evil.example/foreign/"><img alt="foreign\'s profile picture"></a>', None),
                ('<nav><a href="/nav.user/"><img alt="nav.user profile picture"></a></nav><div><a href="/other.user/"><img alt="other.user\'s profile picture"></a></div>', 'nav.user'),
            ]
            for html, user in cases:
                page.set_content(html)
                self.assertEqual(page.evaluate('() => {' + script + ';return SITE.open(document)}'),
                                 f'https://www.instagram.com/{user}/saved/all-posts/' if user else None)
            self.assertEqual(errors, [])

    def test_instagram_review_atomic_import_and_full_runs(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 320, 844, 'dark') as (page, errors):
            reader_test(page, site='instagram')
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Instagram')
            scan = block.get_by_role('button', name='Scan saved posts', exact=True)
            scan.click()
            block.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            scan.click()
            page.evaluate("window.__sites.mode='wait'")
            block.get_by_role('button', name='Continue', exact=True).click()
            expect(scan).to_be_disabled()
            expect(block.get_by_role('button', name='Import file', exact=True)).to_be_disabled()
            expect(show(page, 'Facebook').get_by_role('button', name='Scan saved posts')).to_be_disabled()
            block = show(page, 'Instagram')
            page.wait_for_function('typeof window.__sites.finish==="function"')
            page.evaluate("window.__sites.mode='';window.__sites.finish()")
            imp = block.get_by_role('button', name='Import 1 post', exact=True)
            expect(imp).to_be_enabled()
            block.get_by_text('Review saved posts', exact=True).click()
            expect(block.get_by_text('Only validated Instagram links enter your library.', exact=False)).to_be_visible()
            self.assertEqual(block.locator('img').count(), 0)
            self.assertFalse(page.evaluate('!!window.__injected'))
            OUT.mkdir(parents=True, exist_ok=True)
            settle_import(page)
            block.screenshot(path=str(OUT / 'instagram-review-dark-320.png'))
            page.evaluate('''() => {const add=IDBObjectStore.prototype.add;
              IDBObjectStore.prototype.add=function(value,...args){
                if(this.name==='changes' && value.op==='details'){IDBObjectStore.prototype.add=add;throw new Error('Synthetic quota failure')}
                return add.call(this,value,...args)
              }}''')
            imp.click()
            expect(block.get_by_role('alert')).to_contain_text('Synthetic quota failure')
            block.screenshot(path=str(OUT / 'instagram-error-dark-320.png'))
            self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()"), [])
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            imp.click()
            expect(block.get_by_role('status')).to_contain_text('1 added')
            stored = page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()")
            self.assertEqual([x['op'] for x in stored], ['link', 'details'])
            self.assertNotIn('cdninstagram.com', json.dumps(stored))
            self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-pics').then(x=>x['https://www.instagram.com/reel/Cx1_ab-Z9/'].u)"),
                             'https://scontent.cdninstagram.com/synthetic.jpg')
            result = page.evaluate('''async()=>{
              const {mirrorSource:s,patchRows}=await import('/src/mobile/state.svelte.ts');
              const make=url=>({url,at:0,caption:'',creator:'',tags:''});
              const result=await s.importLinks([make('https://instagram.com/sam.example/tv/Cx1_ab-Z9/?igsh=synthetic'),
                make('https://www.instagram.com/p/BatchCode1/'),make('https://www.instagram.com/reel/BatchCode1/')]);
              await patchRows(result.ids);
              return result;
            }''')
            self.assertEqual(len(result['ids']), 1)
            self.assertEqual(result['dups'], 2)
            page.evaluate("window.__sites.items=[];window.__sites.reason='known'")
            scan.click()
            expect(block.get_by_role('status')).to_contain_text('stopped at posts already')
            call = page.evaluate('window.__sites.calls.at(-1)')
            self.assertTrue(call['complete'])
            self.assertFalse(call['full'])
            self.assertEqual(len(call['known']), 2)
            self.assertTrue(all(len(x) == 16 for x in call['known']))
            block.get_by_role('button', name='Read all again', exact=True).click()
            page.wait_for_function('window.__sites.calls.length===3')
            self.assertTrue(page.evaluate('window.__sites.calls.at(-1).full'))
            self.assertEqual(errors, [])

    def test_instagram_pending_recovery_and_failure(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            reader_test(page, site='instagram', pending=True)
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Instagram')
            imp = block.get_by_role('button', name='Import 1 post', exact=True)
            expect(imp).to_be_enabled()
            expect(block.get_by_role('status')).to_contain_text('cut off')
            block.get_by_role('button', name='Later', exact=True).click()
            scan = block.get_by_role('button', name='Scan saved posts', exact=True)
            scan.click()
            expect(imp).to_be_enabled()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            page.evaluate("window.__sites.mode='clear-error'")
            imp.click()
            expect(block.get_by_role('alert')).to_contain_text('Could not clear')
            page.evaluate("window.__sites.mode=''")
            imp.click()
            expect(block.get_by_role('status')).to_contain_text('already there')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.instagram.complete)"))
            page.evaluate("window.__sites.reason='failure';window.__sites.items=[{url:'https://www.instagram.com/p/Partial1/',kind:'Post'}]")
            scan.click()
            block.get_by_role('button', name='Continue', exact=True).click()
            expect(imp).to_be_enabled()
            imp.click()
            expect(block.get_by_role('alert')).to_contain_text('could not finish')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.instagram.complete)"))
            for mode, text in [('unsupported', 'Update Android System WebView'), ('busy', 'already open')]:
                page.evaluate('(x)=>window.__sites.mode=x', mode)
                scan.click()
                expect(block.get_by_role('alert').last).to_contain_text(text)
            self.assertEqual(errors, [])

    def test_instagram_picture_hints_reload_index_and_fallback(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            # Keep startup picture work from consuming this test's direct-source fixtures.
            page.add_init_script("localStorage.setItem('bp-sync-paused','on')")
            page.route('**/thumbs-proxy.js', lambda route: route.fulfill(
                path=ROOT / 'web/public/thumbs-proxy.js', content_type='application/javascript'))
            page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=NATIVE + '''
export const isApp=true;
export async function linkImage(url){
  (window.__pictures??=[]).push(url);
  if(url.includes('expired')) throw Object.assign(new Error('Expired'),{status:403});
  const c=document.createElement('canvas');c.width=2;c.height=2;
  return Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),x=>x.charCodeAt(0));
}
'''))
            page.goto(base + '/mobile.html#/import')
            page.wait_for_function("async()=>{const s=await import('/src/mobile/state.svelte.ts');return s.phone.tried && !s.phone.refreshing && s.pics.state==='idle'}")
            result = page.evaluate('''async()=>{
              const {mirrorSource:s}=await import('/src/mobile/state.svelte.ts');
              const {kv,changes}=await import('/src/mobile/store.ts');
              (await import('/src/mobile/network.svelte.ts')).network.manualPause=false;
              const make=code=>({url:'https://www.instagram.com/p/'+code+'/',at:0,caption:'',creator:'',tags:''});
              await s.importLinks([make('IndexCode1')]);
              await s.addPicHints([['https://www.instagram.com/reel/IndexCode1/','https://scontent.cdninstagram.com/good.jpg']]);
              const indexed=await kv.get('site-pics');
              const first=await s.fillPictures(()=>{},()=>false);
              await s.importLinks([make('Fallback1')]);
              await s.addPicHints([[make('Fallback1').url,'https://scontent.cdninstagram.com/expired.jpg']]);
              const fallback=await s.fillPictures(()=>{},()=>false);
              await s.importLinks([make('StoredHint1')]);
              // Force a fresh disk read, like a new source after restart, without racing the startup queue.
              await kv.setRequired('site-pics',{
                [make('StoredHint1').url]:{u:'https://instagram.xx.fbcdn.net/stored.jpg',at:Date.now()},
                [make('Hostile1').url]:{u:'https://evil.example/a.jpg',at:Date.now()},
                ['https://www.facebook.com/reel/1234567890/']:{u:'https://scontent.xx.fbcdn.net/fb.jpg',at:Date.now()},
                [make('Expired1').url]:{u:'https://scontent.cdninstagram.com/old.jpg',at:Date.now()-31*86400000}
              });
              s.hintsLoad=null;
              const last=await s.fillPictures(()=>{},()=>false);
              return {indexed,first,fallback,last,hints:await kv.get('site-pics'),calls:window.__pictures,stored:await changes.all()};
            }''')
            self.assertIn('https://www.instagram.com/p/IndexCode1/', result['indexed'])
            for name in ('first', 'fallback', 'last'):
                self.assertEqual(len(result[name]['got']), 1, result)
                self.assertFalse(result[name]['blocked'])
            self.assertEqual(result['calls'], ['https://scontent.cdninstagram.com/good.jpg',
                'https://scontent.cdninstagram.com/expired.jpg', 'https://www.instagram.com/p/Fallback1/media/?size=m',
                'https://instagram.xx.fbcdn.net/stored.jpg'])
            self.assertEqual(list(result['hints']), ['https://www.facebook.com/reel/1234567890/'])
            self.assertNotIn('cdninstagram.com', json.dumps(result['stored']))
            self.assertEqual(errors, [])

    def test_instagram_recovery_survives_other_site_read_failure(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            state = {'supported': True, 'sites': {n.lower(): dict(signedIn=False, forgetting=False,
                pending=1 if n in ('Instagram', 'Facebook') else 0, reader=n in ('Instagram', 'Facebook')) for n in NAMES}}
            page.add_init_script('window.__sites=' + json.dumps(dict(state=state, calls=[], clears=[], mode='',
                items=[dict(url='https://www.instagram.com/p/Recovery1/', kind='Post')], reason='stop')))
            script = FACEBOOK_NATIVE.replace('export async function siteOpen(site, known, full, complete) {',
                'async function legacyOpen(site, known, full, complete) {', 1).replace(
                "if(t.mode==='pending-error')", "if(t.mode==='pending-error' || site==='facebook')")
            page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=script))
            page.goto(base + '/mobile.html#/import')
            instagram = show(page, 'Instagram')
            expect(instagram.get_by_role('button', name='Import 1 post', exact=True)).to_be_enabled()
            expect(show(page, 'Facebook').get_by_role('alert')).to_contain_text('Could not read saved results')
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            show(page, 'Instagram').get_by_role('button', name='Import 1 post', exact=True).click()
            expect(instagram.get_by_role('status')).to_contain_text('1 added')
            self.assertEqual(page.evaluate('window.__sites.clears'), ['instagram'])
            self.assertEqual(errors, [])

    def test_local_picture_hint_fallback_and_refusal(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.add_init_script('window.__pictures=[]')
            script = NATIVE + '''
export const isApp=true;
export async function linkImage(url) {
  window.__pictures.push(url);
  if(url.includes('expired')) throw Object.assign(new Error('Expired'),{status:403});
  const c=document.createElement('canvas');c.width=2;c.height=2;
  return Uint8Array.from(atob(c.toDataURL('image/png').split(',')[1]),x=>x.charCodeAt(0));
}
export async function linkGet(url) {
  window.__pictures.push(url);
  if(window.__refusePage) throw Object.assign(new Error('Slow down'),{status:429});
  return {status:200,text:'<meta property="og:image" content="https://scontent.xx.fbcdn.net/fallback.jpg">'};
}
'''
            page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=script))
            page.goto(base + '/mobile.html#/import')
            expect(page.get_by_role('heading', name='Import saved posts')).to_be_visible()
            page.wait_for_function("async()=>{const s=await import('/src/mobile/state.svelte.ts');return s.phone.tried && !s.phone.refreshing && s.pics.state==='idle'}")
            result = page.evaluate('''async()=>{
              const {mirrorSource:s}=await import('/src/mobile/state.svelte.ts');
              const make=n=>({url:'https://www.facebook.com/reel/'+n+'/',at:0,caption:'Synthetic',creator:'Example',tags:''});
              await s.importLinks([make(1234567890)]);
              await s.addPicHints([[make(1234567890).url,'https://scontent.xx.fbcdn.net/good.jpg']]);
              const open=caches.open.bind(caches);caches.open=async()=>{throw new Error('Synthetic cache full')};
              const first=await s.fillPictures(()=>{},()=>false);
              caches.open=open;
              await s.importLinks([make(1234567891)]);
              await s.addPicHints([[make(1234567891).url,'https://scontent.xx.fbcdn.net/expired.jpg']]);
              const fallback=await s.fillPictures(()=>{},()=>false);
              await s.importLinks([make(1234567892)]);
              await s.addPicHints([[make(1234567892).url,'https://scontent.xx.fbcdn.net/expired.jpg']]);
              window.__refusePage=true;
              const refused=await s.fillPictures(()=>{},()=>false);
              return {first,fallback,refused,calls:window.__pictures};
            }''')
            self.assertEqual(len(result['first']['got']), 1, result)
            self.assertEqual(len(result['fallback']['got']), 1)
            self.assertFalse(result['fallback']['blocked'])
            self.assertTrue(result['refused']['blocked'])
            self.assertEqual(result['calls'], ['https://scontent.xx.fbcdn.net/good.jpg',
                'https://scontent.xx.fbcdn.net/expired.jpg', 'https://www.facebook.com/reel/1234567891/',
                'https://scontent.xx.fbcdn.net/fallback.jpg', 'https://scontent.xx.fbcdn.net/expired.jpg',
                'https://www.facebook.com/reel/1234567892/'])
            self.assertEqual(errors, [])

    def test_built_import_page(self):
        OUT.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width in (320, 390):
                for theme in ('light', 'dark'):
                    with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, 844, theme) as (page, errors):
                        page.route('**/mobile.html', lambda route: route.fulfill(path=ROOT / 'web/dist/mobile.html'))
                        page.route('**/assets/**', lambda route: route.fulfill(path=ROOT / 'web/dist/assets' / route.request.url.split('/assets/', 1)[1].split('?')[0]))
                        page.goto(base + '/mobile.html#/import')
                        expect(page.get_by_role('heading', name='Import saved posts')).to_be_visible()
                        page.evaluate('(x)=>document.documentElement.dataset.theme=x', theme)
                        self.assertEqual([x.strip() for x in page.locator('.m-import-toggle>span:first-child').all_text_contents()], NAMES)
                        facebook = show(page, 'Facebook')
                        expect(facebook.get_by_role('button', name='Scan saved posts')).to_be_disabled()
                        instagram = show(page, 'Instagram')
                        expect(instagram.get_by_role('button', name='Import file')).to_be_enabled()
                        settle_import(page)
                        page.screenshot(path=str(OUT / f'built-{theme}-{width}.png'))
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        self.assertEqual(errors, [])

    def test_facebook_extracts_synthetic_dom(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.goto(base + '/mobile.html')
            page.set_content((ROOT / 'tests/fixtures/site_cards/facebook.html').read_text(encoding='utf-8'))
            cards = page.evaluate('() => {' + (ROOT / 'scrapers/sites/facebook.js').read_text(encoding='utf-8') + ';return SITE.read(document)}')
            self.assertEqual([x['kind'] for x in cards], ['Reel', 'Video', 'Other'])
            self.assertEqual(cards[0]['caption'], 'How to fold a paper boat in 30 seconds')
            self.assertEqual(cards[0]['creator'], 'Sam Example')
            self.assertEqual(cards[0]['url'], 'https://www.facebook.com/reel/1234567890/')
            self.assertEqual(cards[1]['url'], 'https://www.facebook.com/watch/?v=9876543210')

    def test_facebook_review_import_incremental_and_atomic_failure(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 320, 844, 'dark') as (page, errors):
            reader_test(page)
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Facebook')
            scan = block.get_by_role('button', name='Scan saved posts', exact=True)
            scan.click()
            expect(block.get_by_role('status')).to_contain_text('Uses your login')
            block.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            scan.click()
            page.evaluate('window.__sites.holdState=true')
            block.get_by_role('button', name='Continue', exact=True).click()
            expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_visible()
            expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_disabled()
            page.wait_for_function('typeof window.__sites.refresh==="function"')
            page.evaluate('window.__sites.holdState=false;window.__sites.refresh()')
            expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_enabled()
            self.assertEqual(page.evaluate('window.__sites.stateCalls'), 2)
            block.get_by_text('Review saved posts', exact=True).click()
            self.assertEqual(block.locator('img').count(), 0)
            self.assertFalse(page.evaluate('!!window.__injected'))
            OUT.mkdir(parents=True, exist_ok=True)
            settle_import(page)
            block.screenshot(path=str(OUT / 'facebook-review-dark-320.png'))
            self.assertEqual(page.evaluate('window.__sites.calls')[0],
                             dict(site='facebook', known=[], full=False, complete=False))
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            # Abort after adding the link, while adding details: the entire import must roll back.
            page.evaluate('''() => { const add=IDBObjectStore.prototype.add;
              IDBObjectStore.prototype.add=function(value,...args){
                if(this.name==='changes' && value.op==='details') { IDBObjectStore.prototype.add=add;throw new DOMException('Synthetic quota failure','QuotaExceededError') }
                return add.call(this,value,...args)
              } }''')
            block.get_by_role('button', name='Import 1 post', exact=True).click()
            expect(block.get_by_role('alert')).to_contain_text('Synthetic quota failure')
            block.screenshot(path=str(OUT / 'facebook-error-dark-320.png'))
            self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()"), [])
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            block.get_by_role('button', name='Import 1 post', exact=True).click()
            expect(block.get_by_role('status')).to_contain_text('1 added')
            self.assertEqual(page.evaluate('window.__sites.clears'), ['facebook'])
            stored = page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all()")
            self.assertEqual([x['op'] for x in stored], ['link', 'details'])
            self.assertNotIn('fbcdn.net', json.dumps(stored))
            hints = page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-pics')")
            self.assertEqual(hints['https://www.facebook.com/reel/1234567890/']['u'], 'https://scontent.xx.fbcdn.net/synthetic.jpg')
            duplicate = page.evaluate("""async()=> (await import('/src/mobile/state.svelte.ts')).mirrorSource.importLinks([
                {url:'https://www.facebook.com/watch/?v=1234567890',at:0,caption:'',creator:'',tags:''}])""")
            self.assertEqual(duplicate, {'ids': [], 'dups': 1})
            page.evaluate("window.__sites.reason='known';window.__sites.items=[]")
            scan.click()
            expect(block.get_by_role('status')).to_contain_text('stopped at posts already')
            calls = page.evaluate('window.__sites.calls')
            self.assertTrue(calls[-1]['complete'])
            self.assertFalse(calls[-1]['full'])
            self.assertEqual(len(calls[-1]['known']), 1)
            self.assertRegex(calls[-1]['known'][0], r'^[0-9a-f]{16}$')
            block.get_by_role('button', name='Read all again', exact=True).click()
            expect(block.get_by_role('status')).to_contain_text('stopped at posts already')
            page.wait_for_function('window.__sites.calls.length===3')
            self.assertTrue(page.evaluate('window.__sites.calls[2].full'))
            self.assertEqual(errors, [])

    def test_facebook_pending_later_retry_and_partial_results(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            reader_test(page, pending=True)
            page.goto(base + '/mobile.html#/import')
            block = show(page, 'Facebook')
            expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_visible()
            block.get_by_role('button', name='Later', exact=True).click()
            self.assertEqual(page.evaluate('window.__sites.clears'), [])
            block.get_by_role('button', name='Scan saved posts', exact=True).click()
            expect(block.get_by_role('button', name='Import 1 post', exact=True)).to_be_visible()
            self.assertEqual(page.evaluate('window.__sites.calls'), [])
            page.evaluate("window.__sites.mode='clear-error'")
            block.get_by_role('button', name='Import 1 post', exact=True).click()
            expect(block.get_by_role('alert')).to_contain_text('Could not clear')
            page.evaluate("window.__sites.mode=''")
            block.get_by_role('button', name='Import 1 post', exact=True).click()
            expect(block.get_by_role('status')).to_contain_text('already there')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.facebook.complete)"))
            page.evaluate("window.__sites.items=[{url:'https://www.facebook.com/reel/1234567899/',kind:'Reel'}];window.__sites.reason='failure'")
            block.get_by_role('button', name='Scan saved posts', exact=True).click()
            block.get_by_role('button', name='Continue', exact=True).click()
            expect(block.get_by_role('status')).to_contain_text('could not finish')
            block.get_by_role('button', name='Import 1 post', exact=True).click()
            expect(block.get_by_role('alert')).to_contain_text('could not finish')
            self.assertFalse(page.evaluate("async()=> (await import('/src/mobile/store.ts')).kv.get('site-runs').then(x=>x.facebook.complete)"))
            self.assertEqual(errors, [])

    def test_layout_and_existing_real_import_path(self):
        OUT.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width in (320, 390):
                for theme in ('light', 'dark'):
                    with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, 844, theme) as (page, errors):
                        page.goto(base + '/mobile.html#/import')
                        page.evaluate('(x) => document.documentElement.dataset.theme=x', theme)
                        expect(page.get_by_role('heading', name='Import saved posts')).to_be_visible()
                        self.assertEqual([x.strip() for x in page.locator('.m-import-toggle>span:first-child').all_text_contents()], NAMES)
                        self.assertEqual(page.locator('.m-import-glyph svg').count(), 4)
                        self.assertEqual(page.locator('.m-import-identity,.proto-device,.proto-picker').count(), 0)
                        for name in NAMES:
                            block = show(page, name)
                            actions = block.get_by_role('group', name=f'{name} actions')
                            self.assertEqual(actions.locator('.m-import-action>.m-btn').evaluate_all('(xs)=>xs.map(x=>x.getAttribute("aria-label"))'), ['Request export', 'Scan saved posts', 'Import file'])
                            expect(actions.get_by_role('button', name='Scan saved posts')).to_be_disabled()
                            file = actions.get_by_role('button', name='Import file')
                            expect(file).to_be_enabled() if name == 'Instagram' else expect(file).to_be_disabled()
                            self.assertEqual(actions.locator('button button,a button').count(), 0)
                            for label in ('Export', 'Scan', 'File'):
                                info = actions.get_by_role('button', name=f'More info: {name}: {label}', exact=True)
                                info.click()
                                dialog = page.get_by_role('dialog')
                                text = dialog.inner_text()
                                self.assertNotIn('Contributor', text)
                                self.assertNotIn('prototype', text)
                                if label == 'Export':
                                    self.assertIn('opening it does not submit a request', text)
                                elif label == 'Scan':
                                    self.assertIn('Scanning saved posts is not available yet', text)
                                elif name == 'Instagram':
                                    self.assertIn('up to 60 MiB', text)
                                    self.assertIn('Imported links enter your library', text)
                                else:
                                    self.assertIn('export files are not supported yet', text)
                                close_help(page)
                                expect(info).to_be_focused()
                        instagram = show(page, 'Instagram')
                        page.locator('.m-sheet-body').evaluate('x=>x.scrollTop=0')
                        page.evaluate('document.fonts.ready')
                        settle_import(page)
                        page.screenshot(path=str(OUT / f'import-{theme}-{width}.png'))
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        dims = page.locator('.m-import-screen button:visible,.m-import-screen a:visible,.m-import-screen summary:visible').evaluate_all('(xs)=>xs.map(x=>x.getBoundingClientRect()).map(x=>[x.width,x.height])')
                        self.assertTrue(all(w >= 44 and h >= 44 for w, h in dims), dims)
                        with page.expect_file_chooser() as picker:
                            instagram.get_by_role('button', name='Import file', exact=True).click()
                        picker.value.set_files({'name': 'saved_posts.json', 'mimeType': 'application/json', 'buffer': json.dumps(POST).encode()})
                        expect(instagram.get_by_role('status')).to_contain_text('Added 1 link')
                        links = page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all().then(xs=>xs.filter(x=>x.op==='link'))")
                        self.assertEqual(len(links), 1)
                        self.assertIn('Promotion1', links[0]['url'])
                        packed = io.BytesIO()
                        with zipfile.ZipFile(packed, 'w', zipfile.ZIP_DEFLATED) as z:
                            z.writestr('saved/saved_posts.json', json.dumps(POST))
                        page.locator('input[type=file]').set_input_files({'name': 'saved.zip', 'mimeType': 'application/zip', 'buffer': packed.getvalue()})
                        expect(instagram.get_by_role('status')).to_contain_text('1 already in the library')
                        self.assertEqual(page.evaluate("async()=> (await import('/src/mobile/store.ts')).changes.all().then(xs=>xs.filter(x=>x.op==='link').length)"), 1)
                        page.locator('input[type=file]').set_input_files({'name': 'wrong.json', 'mimeType': 'application/json', 'buffer': b'{}'})
                        expect(instagram.get_by_role('alert')).to_contain_text('This is not Instagram')
                        settle_import(page)
                        page.screenshot(path=str(OUT / f'error-{theme}-{width}.png'))
                        page.locator('input[type=file]').evaluate("x=>{const f=new File(['x'],'large.json');Object.defineProperty(f,'size',{value:60*1024*1024+1});const d=new DataTransfer();d.items.add(f);x.files=d.files;x.dispatchEvent(new Event('change',{bubbles:true}))}")
                        expect(instagram.get_by_role('alert')).to_contain_text('over 60 MB')
                        page.emulate_media(reduced_motion='reduce')
                        self.assertEqual(page.locator('.m-import-reveal').first.evaluate('x=>getComputedStyle(x).transitionDuration'), '0s')
                        self.assertEqual(errors, [])

    def test_native_window_and_forget_gates(self):
        with mobile_browser() as (browser, base):
            with synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
                state = {'supported': True, 'sites': {name.lower(): {'signedIn': False, 'forgetting': False, 'pending': 0, 'reader': False} for name in NAMES}}
                page.add_init_script('window.__sites=' + json.dumps({'state': state, 'calls': [], 'forgets': [], 'mode': ''}))
                page.route('**/src/mobile/native.ts', lambda route: route.fulfill(content_type='application/javascript', body=NATIVE))
                page.goto(base + '/mobile.html#/import')
                instagram = show(page, 'Instagram')
                scan = instagram.get_by_role('button', name='Scan saved posts', exact=True)
                expect(scan).to_be_enabled()
                scan.click()
                self.assertEqual(page.evaluate('window.__sites.calls'), [{'site': 'instagram', 'known': [], 'full': False, 'complete': False}])
                info = instagram.get_by_role('button', name='More info: Instagram: Scan', exact=True)
                info.click()
                dialog = page.get_by_role('dialog')
                expect(dialog.get_by_text('Signed in.', exact=True)).to_be_visible()
                dialog.get_by_role('button', name='Forget login', exact=True).click()
                self.assertEqual(page.evaluate('window.__sites.forgets'), [])
                dialog.get_by_role('button', name='Cancel', exact=True).click()
                dialog.get_by_role('button', name='Forget login', exact=True).click()
                dialog.get_by_role('button', name='Tap again to forget login', exact=True).click()
                expect(dialog.get_by_text('Signed in.', exact=True)).to_have_count(0)
                self.assertEqual(page.evaluate('window.__sites.forgets'), ['instagram'])
                # Clearing a partial/failed login remains possible even without a signed-in cookie.
                expect(dialog.get_by_role('button', name='Forget login', exact=True)).to_be_enabled()
                page.evaluate("window.__sites.mode='forget-error'")
                dialog.get_by_role('button', name='Forget login', exact=True).click()
                dialog.get_by_role('button', name='Tap again to forget login', exact=True).click()
                expect(dialog.get_by_role('alert')).to_contain_text('could not be forgotten')
                close_help(page)
                for mode, text in [('busy', 'A site window is already open.'), ('unsupported', 'Update Android System WebView')]:
                    page.evaluate('(x)=>window.__sites.mode=x', mode)
                    scan.click()
                    expect(instagram.get_by_role('alert')).to_contain_text(text)
                page.evaluate("window.__sites.mode='wait'")
                scan.click()
                expect(scan).to_be_disabled()
                expect(scan).to_have_attribute('aria-busy', 'true')
                facebook = show(page, 'Facebook')
                expect(facebook.get_by_role('button', name='Scan saved posts')).to_be_disabled()
                page.evaluate('window.__sites.finish()')
                expect(facebook.get_by_role('button', name='Scan saved posts')).to_be_enabled()
                self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
