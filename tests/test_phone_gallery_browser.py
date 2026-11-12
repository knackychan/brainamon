"""Phone gallery against synthetic rows and disposable browser storage; no real library."""
from pathlib import Path
import json
import unittest

from playwright.sync_api import expect
from tests.test_mobile_info_browser import PAIR, mobile_browser, synthetic_phone

OUT = Path(__file__).resolve().parents[1] / 'local/phone-gallery'


def seed(page):
    expect(page.locator('#m-app')).to_be_visible()
    page.wait_for_function("async () => {const {phone}=await import('/src/mobile/state.svelte.ts');return phone.tried&&!phone.refreshing}")
    page.route('**/thumb/**', lambda r: r.fulfill(content_type='image/svg+xml', body=
               '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="240"><rect width="180" height="240" fill="#39776b"/><circle cx="90" cy="100" r="50" fill="#bdebdb"/></svg>'))
    page.evaluate("""async () => {
      const { phone } = await import('/src/mobile/state.svelte.ts');
      const { saveOnb } = await import('/src/mobile/onboard.svelte.ts');
      await saveOnb({answer:'phone',hidden:true,coach:true});
      phone.rows = Array.from({length:3000}, (_,i) => ({id:i+1,title:i%3===1?'':`Saved item ${i+1} with a longer title`,
        creator:'Example creator',type:'Post',cat:'Art',tags:'',desc:'',url:`https://example.com/post/${i+1}`,
        src:'web',thumb:i%3===0,ai:i%3!==1,an:false,nd:0,fav:false,created:3000-i,tv:0}));
      phone.loaded=true;phone.error='';
    }""")
    expect(page.locator('.m-grid')).to_be_visible()


def touch(page, kind, points):
    return page.locator('.m-grid').evaluate("""(el, {kind,points}) => {
      const box=el.getBoundingClientRect();
      const touches=points.map(([x,y],identifier)=>new Touch({identifier,target:el,clientX:box.x+x,clientY:Math.max(100,box.y)+y}));
      const event=new TouchEvent(kind,{bubbles:true,cancelable:true,touches,targetTouches:touches});
      el.dispatchEvent(event);return event.defaultPrevented;
    }""", dict(kind=kind, points=points))


def visible_ids(page):
    return page.locator('.m-cell-a').evaluate_all("""els => els.filter(e=>{
      const b=e.getBoundingClientRect(),s=document.querySelector('.m-main').getBoundingClientRect();
      return b.bottom>s.top && b.top<s.bottom;
    }).map(e=>e.getAttribute('href'))""")


def columns(page):
    return page.locator('.m-grid-rows').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").length')


def seed_items(page, mode='mirror'):
    seed(page)
    page.evaluate(r"""async mode => {
      const {phone,source}=await import('/src/mobile/state.svelte.ts');
      const {items}=await import('/src/mobile/store.ts');
      const f=window.__items={fail:'',edits:[],deletes:[],descriptions:{},reports:{},transcripts:{},slow:false,waits:[],slowText:false,textWaits:[],reads:0};
      f.release=()=>{f.slow=false;for(const resolve of f.waits.splice(0))resolve()};
      f.releaseText=()=>{f.slowText=false;for(const resolve of f.textWaits.splice(0))resolve()};
      const rows=Array.from({length:80},(_,i)=>({id:i+1,title:i===0?'Level hard.':`Saved item ${i+1}`,
        creator:'@chef.marco',type:'Reel',cat:'Art',tags:'',desc:'Example caption',url:`https://example.com/post/${i+1}`,
        src:'instagram',thumb:i%3===0,ai:false,an:false,nd:2,fav:false,created:Date.UTC(2026,10,6)-i,tv:0}));
      rows.push({...rows[0],id:-1,title:'Phone link',creator:'unknown',cat:'Other',created:1});
      rows.push({...rows[0],id:999,title:'Outside this collection',cat:'Other',created:0});
      f.rows=new Map(rows.map(r=>[r.id,r]));
      const check=op=>{if(f.fail===op)throw new Error(`Synthetic ${op} failure`)};
      const full=id=>{const r=f.rows.get(id);return {id,url:r.url,description:f.descriptions[id]??'Example caption',
        short_desc:r.title,creator:r.creator,type:r.type,category:r.cat,tags:r.tags,ai_desc:r.ai?(f.descriptions[id]||'AI text'):'',
        notes:'A saved note that wraps onto another line when the viewport is narrow.',thumb_path:'',created:r.created,modified:0,
        files:{thumb:r.thumb,report:!!f.reports[id],transcript:!!f.transcripts[id],frames:0,frame_names:[],video:false}}};
      source.kind=mode;
      source.item=async id=>{if(f.slow)await new Promise(resolve=>f.waits.push(resolve));f.reads++;return full(id)};
      source.itemText=async(id,which)=>{if(f.slowText)await new Promise(resolve=>f.textWaits.push(resolve));return (which==='report'?f.reports:f.transcripts)[id]||''};
      source.related=async id=>id===999?[]:[f.rows.get(999)].filter(Boolean);
      source.rows=async()=>({rows:[...f.rows.values()],cats:phone.cats});
      source.rowsByIds=async ids=>ids.map(id=>f.rows.get(id)).filter(Boolean);
      source.tints=async()=>({});source.linkDetails=async()=>[];source.fillPictures=async()=>({got:[],blocked:false});
      source.thumbUrl=r=>`/thumb/${r.id}`;source.thumbBlob=async()=>null;
      source.search=async q=>[...f.rows.values()].filter(r=>r.creator.includes(q)).map(r=>r.id);
      source.smart=source.search;
      source.favourite=async(id,on)=>{const r={...f.rows.get(id),fav:on};f.rows.set(id,r);return r};
      source.edit=async(id,fields)=>{check('edit');f.edits.push({id,fields});const r={...f.rows.get(id),...fields,
        ...(fields.category?{cat:fields.category}:{})};f.rows.set(id,r);return r};
      source.deleteItem=async(id,pc)=>{check('delete');f.deletes.push({id,pc});f.rows.delete(id)};
      source.ai=()=>({providers:[],provider:'fixture',model:'fixture',label:'Fixture AI',smart:true,synth:''});
      source.describe=async id=>{check('describe');f.descriptions[id]='Fresh description from Tools';f.rows.set(id,{...f.rows.get(id),ai:true});return f.descriptions[id]};
      source.categorize=async id=>{const r={...f.rows.get(id),cat:'Other',tags:'fixture'};f.rows.set(id,r);return r};
      source.videoSize=id=>id===3?100:0;
      source.video=async(id,progress)=>{check('video');progress?.(42,100);await new Promise(resolve=>f.finishVideo=resolve);return new Blob([new Uint8Array(100)],{type:'video/mp4'})};
      phone.rows=rows;phone.cats=[{name:'Art',color:'#39776b',count:80},{name:'Other',color:'#bc6c25',count:2},
        {name:'Empty collection',color:'#5b8def',count:0}];
      for(const c of phone.cats)TYPE[c.name]=c.color;
      phone.cat='Art';phone.fav=false;phone.q='';phone.searchIds=null;phone.rank=null;phone.sort='new';
      phone.scroll.lib=0;phone.lastItem=null;phone.motionOff=true;phone.loaded=true;
      document.documentElement.classList.add('motion-off');
      f.cached=items;
    }""", mode)
    expect(page.locator('.m-grid')).to_be_visible()


class PhoneGalleryBrowser(unittest.TestCase):
    def test_tools_popover(self):
        with mobile_browser() as (browser, base):
            for theme in ('light', 'dark'):
                with self.subTest(theme=theme), synthetic_phone(browser, base, 360, 780, theme) as (page, errors):
                    page.goto(base + '/mobile.html#/lib')
                    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                    seed_items(page)
                    for screen, key_selector in (('library', '.m-lib-tools'), ('item', '.m-it-tools')):
                        if screen == 'item':
                            page.locator('.m-cell-a[href="#/item/1"]').click()
                        key = page.locator(key_selector)
                        key.click()
                        panel = page.get_by_role('dialog', name='Tools', exact=True)
                        expect(panel).to_be_visible()
                        expect(key).to_have_attribute('aria-expanded', 'true')
                        bounds, anchor = panel.bounding_box(), key.bounding_box()
                        self.assertGreaterEqual(bounds['x'], 0)
                        self.assertLessEqual(bounds['x'] + bounds['width'], 360)
                        self.assertGreaterEqual(bounds['y'], anchor['y'] + anchor['height'] - 2)
                        self.assertLessEqual(bounds['y'] + bounds['height'], 780)
                        for control in (panel.get_by_role('button', name='Describe', exact=True),
                                        panel.get_by_role('button', name='Auto-categorize', exact=True),
                                        panel.locator('.m-tl-line').first,
                                        panel.get_by_text('More', exact=True)):
                            rect = control.bounding_box()
                            self.assertIsNotNone(rect)
                            self.assertGreaterEqual(rect['y'], bounds['y'])
                            self.assertLessEqual(rect['y'] + rect['height'], bounds['y'] + bounds['height'], f'{screen}: {control}')
                        page.keyboard.press('Escape')
                        expect(panel).to_have_count(0)
                        expect(key).to_have_attribute('aria-expanded', 'false')
                        key.click()
                        expect(panel).to_be_visible()
                        page.mouse.click(2, 2)
                        expect(panel).to_have_count(0)
                        expect(key).to_have_attribute('aria-expanded', 'false')
                    # Simulate the WebView viewport shrinking when the keyboard opens.
                    page.evaluate("async()=>{const {source}=await import('/src/mobile/state.svelte.ts');source.synthesize=async()=>({file:'fixture.md',queued:false})}")
                    key.click()
                    panel.get_by_text('More', exact=True).click()
                    topic = panel.get_by_role('textbox', name='Note topic', exact=True)
                    topic.focus()
                    page.set_viewport_size({'width': 360, 'height': 480})
                    page.wait_for_function("""() => {const e=document.querySelector('input[placeholder="Topic"]'), r=e.getBoundingClientRect();
                        const p=e.closest('dialog').getBoundingClientRect();
                        return r.top >= p.top && r.bottom <= Math.min(p.bottom, innerHeight)} """)
                    expect(topic).to_be_focused()
                    self.assertEqual(errors, [])

    def test_tools_native_back(self):
        # Simulate the Capacitor callback in the browser; no Android app or real library is used.
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 780, 'light') as (page, errors):
            page.add_init_script("""
              window.androidBridge={};window.__listeners={};window.__secrets={'bp-pair':PAIR};
              window.Capacitor={
                PluginHeaders:['Brainamon','App'].map(name=>({name,methods:[{name:'secretGet',rtype:'promise'},
                  {name:'secretSet',rtype:'promise'},{name:'networkStatus',rtype:'promise'},
                  {name:'addListener',rtype:'callback'},{name:'removeListener',rtype:'promise'}]})),
                nativeCallback(plugin,method,options,callback){if(method==='addListener')__listeners[options.eventName]=callback;return 'fixture-listener'},
                nativePromise(plugin,method,options){
                  if(method==='secretGet')return Promise.resolve({value:__secrets[options.key]||null});
                  if(method==='secretSet')__secrets[options.key]=options.value;
                  if(method==='networkStatus')return Promise.resolve({connected:true,type:'wifi'});
                  return Promise.resolve({});
                }
              };
            """.replace('PAIR', json.dumps(json.dumps(PAIR))))
            page.goto(base + '/mobile.html#/lib')
            seed_items(page)
            page.locator('.m-cell-a[href="#/item/1"]').click()
            page.locator('.m-it-tools').click()
            panel = page.get_by_role('dialog', name='Tools', exact=True)
            expect(panel).to_be_visible()
            page.wait_for_function('!!window.__listeners.backButton')
            panel.get_by_role('button', name='More info: Processing items', exact=True).click()
            help_dialog = page.get_by_role('dialog', name='Processing items', exact=True)
            expect(help_dialog).to_be_visible()
            page.evaluate('__listeners.backButton({canGoBack:true})')
            expect(help_dialog).to_have_count(0)
            expect(panel).to_be_visible()
            page.evaluate('__listeners.backButton({canGoBack:true})')
            expect(panel).to_have_count(0)
            expect(page).to_have_url(base + '/mobile.html#/item/1')
            expect(page.locator('.m-it-tools')).to_have_attribute('aria-expanded', 'false')
            self.assertEqual(errors, [])

    def test_tools_desktop_choices(self):
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 360, 780, 'light') as (page, errors):
            page.goto(base + '/mobile.html#/lib')
            seed_items(page, 'desktop')
            for screen, key_selector in (('library', '.m-lib-tools'), ('item', '.m-it-tools')):
                if screen == 'item':
                    page.locator('.m-cell-a[href="#/item/1"]').click()
                page.locator(key_selector).click()
                panel = page.get_by_role('dialog', name='Tools', exact=True)
                bounds = panel.bounding_box()
                for control in (panel.get_by_role('button', name='Describe', exact=True),
                                panel.get_by_role('button', name='Auto-categorize', exact=True),
                                panel.get_by_text('Other PC steps · 3', exact=True)):
                    rect = control.bounding_box()
                    self.assertLessEqual(rect['y'] + rect['height'], bounds['y'] + bounds['height'], f'{screen}: {control}')
                other = panel.get_by_text('Other PC steps · 3', exact=True)
                other.click()
                for label in ('Fetch link info', 'Analyze videos', 'Index for search'):
                    expect(panel.get_by_role('button', name=label, exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                expect(panel).to_have_count(0)
            self.assertEqual(errors, [])

    def test_gallery(self):
        OUT.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, theme in ((320, 'light'), (390, 'dark')):
                with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, 844, theme) as (page, errors):
                    page.route('**/thumbs-proxy.js', lambda r: r.fulfill(path=OUT.parents[1] / 'web/public/thumbs-proxy.js'))
                    page.goto(base + '/mobile.html#/lib')
                    seed(page)
                    page.screenshot(path=str(OUT / f'library-initial-{width}-{theme}.png'))
                    # one view key (plans/06): it names and shows the layout it switches to
                    view = page.locator('.m-lib-view')
                    expect(view).to_have_count(1)
                    expect(page.locator('.m-mathd .m-jp')).to_have_count(0)
                    expect(page.locator('.m-gallery-tools')).to_have_count(0)
                    for before, cols, after in (('Show as rows', 1, 'Show as grid'), ('Show as grid', 3, 'Show as rows'),
                                                ('Show as rows', 1, 'Show as grid')):
                        expect(view).to_have_attribute('aria-label', before)
                        view.click()
                        expect(view).to_have_attribute('aria-label', after)
                        button = view
                        expect(button.locator('svg')).to_have_count(1)
                        self.assertEqual(button.inner_text(), '')
                        self.assertGreaterEqual(button.bounding_box()['width'], 44)
                        self.assertGreaterEqual(button.bounding_box()['height'], 44)
                        self.assertEqual(columns(page), cols)
                        self.assertLess(page.locator('.m-cell').count(), 80)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        self.assertTrue(page.locator('.m-cell').evaluate_all('els=>els.every(e=>e.querySelector("a").getBoundingClientRect().height<=e.getBoundingClientRect().height+1)'))
                        page.screenshot(path=str(OUT / f'library-{cols}-{width}-{theme}.png'))
                    expect(page.locator('.m-gallery-row').first).to_contain_text('Example creator')
                    self.assertEqual(page.locator('.m-gallery-row img').first.get_attribute('alt'), '')

                    page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');window.__phone=phone;phone.gallery='2'}")
                    # Gesture jitter does nothing. A pinch changes one step and cannot open a card.
                    self.assertTrue(touch(page, 'touchstart', [(40, 150), (240, 150)]))
                    touch(page, 'touchmove', [(45, 150), (235, 150)])
                    self.assertEqual(columns(page), 2)
                    touch(page, 'touchmove', [(70, 150), (210, 150)])
                    self.assertEqual(columns(page), 3)
                    # A deeper pinch reaches four columns without lifting either finger.
                    touch(page, 'touchmove', [(90, 150), (190, 150)])
                    self.assertEqual(columns(page), 4)
                    touch(page, 'touchend', [(90, 150)])
                    touch(page, 'touchend', [])
                    page.locator('.m-cell-a').first.evaluate('e=>e.click()')
                    self.assertTrue(page.url.endswith('#/lib'))
                    for expected in (4, 4):
                        touch(page, 'touchstart', [(40, 150), (240, 150)])
                        touch(page, 'touchmove', [(90, 150), (190, 150)])
                        touch(page, 'touchcancel', [])
                        self.assertEqual(columns(page), expected)
                    for expected in (3, 2, 2):
                        touch(page, 'touchstart', [(90, 150), (190, 150)])
                        touch(page, 'touchmove', [(70, 150), (210, 150)])
                        touch(page, 'touchend', [])
                        self.assertEqual(columns(page), expected)
                    self.assertFalse(touch(page, 'touchstart', [(40, 150)]))
                    self.assertFalse(touch(page, 'touchmove', [(40, 100)]))
                    touch(page, 'touchend', [])
                    self.assertEqual(page.evaluate('visualViewport.scale'), 1)

                    # Fingers land separately on different cards, with small initial movement.
                    client = page.context.new_cdp_session(page)
                    client.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':40,'y':398,'id':1}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':40,'y':400,'id':1}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':40,'y':400,'id':1},{'x':260,'y':400,'id':2}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':73,'y':400,'id':1},{'x':227,'y':400,'id':2}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
                    self.assertEqual(columns(page), 3)
                    expect(view).to_have_attribute('aria-label', 'Show as rows')
                    self.assertEqual(page.evaluate('visualViewport.scale'), 1)
                    self.assertTrue(page.url.endswith('#/lib'))

                    # Layout switches far down a large library retain the first visible item.
                    page.locator('.m-main').evaluate('e=>e.scrollTop=12000')
                    page.wait_for_function("() => document.querySelector('.m-main').scrollTop>11000")
                    page.wait_for_function("() => {const a=document.querySelector('.m-cell-a');return a&&!a.getAttribute('href').endsWith('/1')}")
                    anchor = visible_ids(page)[0]
                    for layout in ('3', '4', 'rows', '2'):
                        page.evaluate('layout=>window.__phone.gallery=layout', layout)
                        page.wait_for_function('(anchor)=>[...document.querySelectorAll(".m-cell-a")].some(e=>e.getAttribute("href")===anchor)', arg=anchor)
                        self.assertIn(anchor, visible_ids(page))
                        self.assertLess(page.locator('.m-cell').count(), 80)
                    # Returning to the Library and rotating preserve the layout and current item.
                    page.evaluate("window.__phone.gallery='rows'")
                    expect(view).to_have_attribute('aria-label', 'Show as grid')
                    anchor = visible_ids(page)[0]
                    page.evaluate("location.hash='#/more'")
                    expect(page.locator('.m-grid')).to_have_count(0)
                    page.evaluate("location.hash='#/lib'")
                    expect(view).to_have_attribute('aria-label', 'Show as grid')
                    page.wait_for_function('(anchor)=>[...document.querySelectorAll(".m-cell-a")].some(e=>e.getAttribute("href")===anchor)', arg=anchor)
                    self.assertIn(anchor, visible_ids(page))
                    page.evaluate("window.__phone.gallery='4'")
                    self.assertEqual(columns(page), 4)
                    anchor = visible_ids(page)[0]
                    page.set_viewport_size({'width':640,'height':844})
                    page.wait_for_function("() => document.querySelector('.m-grid').clientWidth===640")
                    page.wait_for_function('(anchor)=>[...document.querySelectorAll(".m-cell-a")].some(e=>e.getAttribute("href")===anchor)', arg=anchor)
                    self.assertIn(anchor, visible_ids(page))
                    page.set_viewport_size({'width':width,'height':844})
                    # Native input scrolls rather than navigating.
                    page.locator('.m-main').evaluate('e=>e.scrollTop=0')
                    page.wait_for_function("() => document.querySelector('.m-main').scrollTop===0")
                    client.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':150,'y':600}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':150,'y':350}]})
                    client.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
                    page.wait_for_function("() => document.querySelector('.m-main').scrollTop>0")
                    self.assertTrue(page.url.endswith('#/lib'))
                    # A fresh tap still opens an item after scrolling or pinching.
                    touch(page, 'touchstart', [(40, 150)])
                    touch(page, 'touchend', [])
                    page.locator('.m-cell-a').first.evaluate('e=>e.click()')
                    page.wait_for_function("() => location.hash.startsWith('#/item/')")
                    self.assertEqual(errors, [])


    def test_item_strip_navigation_and_metadata(self):
        art = OUT.parent / 'phone-item'
        art.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for width, theme in ((390, 'light'), (390, 'dark'), (320, 'light')):
                with self.subTest(width=width, theme=theme), synthetic_phone(browser, base, width, 844, theme) as (page, errors):
                    page.route('**/thumbs-proxy.js', lambda r: r.fulfill(path=OUT.parents[1] / 'web/public/thumbs-proxy.js'))
                    page.goto(base + '/mobile.html#/lib')
                    seed_items(page)
                    page.locator('.m-cell-a[href="#/item/1"]').click()
                    expect(page.locator('.m-it-tt')).to_have_text('Level hard.')
                    expect(page.locator('.m-abar')).to_have_count(0)
                    expect(page.locator('.m-it-stage .slot')).to_have_count(1)
                    expect(page.get_by_role('button', name='Favourite', exact=True)).to_have_attribute('aria-pressed', 'false')
                    expect(page.get_by_role('group', name='Item tabs')).not_to_contain_text('Transcript')
                    strip = page.get_by_role('navigation', name='Items', exact=True)
                    expect(strip).to_be_visible()
                    self.assertLessEqual(strip.get_by_role('button').count(), 41)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    page.evaluate('window.__strip=document.querySelector(".m-item-strip")')
                    before = page.evaluate('history.length')
                    page.screenshot(path=str(art / f'item-rest-{width}-{theme}.png'))
                    # One picture per 28 px. The preview exists only during the drag.
                    box = strip.bounding_box()
                    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.move(x - 28, y, steps=3)
                    expect(page.locator('.m-item-preview')).to_be_visible()
                    expect(page.locator('.m-item-preview .m-ws')).to_have_text('2 / 80')
                    page.screenshot(path=str(art / f'item-drag-{width}-{theme}.png'))
                    page.mouse.up()
                    expect(page).to_have_url(base + '/mobile.html#/item/2')
                    expect(page.locator('.m-item-preview')).to_have_count(0)
                    self.assertEqual(page.evaluate('history.length'), before)
                    self.assertTrue(page.evaluate('window.__strip===document.querySelector(".m-item-strip")'))
                    # A long hold opens nothing; cancellation also restores the current position.
                    page.mouse.move(x + 40, y)
                    page.mouse.down()
                    page.wait_for_timeout(400)
                    page.mouse.up()
                    expect(page).to_have_url(base + '/mobile.html#/item/2')
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.move(x - 28, y)
                    strip.evaluate("e=>e.dispatchEvent(new PointerEvent('pointercancel',{pointerId:1,bubbles:true}))")
                    page.mouse.up()
                    expect(page).to_have_url(base + '/mobile.html#/item/2')
                    # Native button/assistive activation uses the same replacement navigation.
                    strip.get_by_role('button', name='Saved item 20', exact=True).evaluate('e=>e.click()')
                    expect(page).to_have_url(base + '/mobile.html#/item/20')
                    self.assertEqual(page.evaluate('history.length'), before)
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/lib')
                    target = page.locator('.m-cell-a[href="#/item/20"]')
                    expect(target).to_be_in_viewport()
                    bounds, main = target.bounding_box(), page.locator('.m-main').bounding_box()
                    self.assertAlmostEqual(bounds['y'] + bounds['height'] / 2, main['y'] + main['height'] / 2, delta=3)
                    target.click()
                    # Empty collections are choices, and moving does not change the captured strip.
                    page.get_by_role('button', name='Choose collection: Art', exact=True).click()
                    picker = page.get_by_role('dialog', name='Choose collection', exact=True)
                    picker.get_by_role('searchbox', name='Search collection').fill('Empty')
                    picker.get_by_role('button', name='Empty collection', exact=True).click()
                    expect(page.get_by_role('button', name='Choose collection: Empty collection', exact=True)).to_be_visible()
                    self.assertEqual(page.evaluate('window.__items.edits.at(-1)'), {'id': 20, 'fields': {'category': 'Empty collection'}})
                    self.assertEqual(strip.get_by_role('button').count(), 40)
                    saved_scroll = page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.scroll.lib}")
                    page.get_by_role('button', name='Back', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/lib')
                    page.wait_for_function('(y)=>Math.abs(document.querySelector(".m-main").scrollTop-y)<2', arg=saved_scroll)
                    page.go_forward()
                    expect(page).to_have_url(base + '/mobile.html#/item/20')
                    # The Info editor keeps its old field/Cancel/Save; focus hides the strip.
                    page.get_by_role('button', name='Edit tags', exact=True).click()
                    expect(page.get_by_role('textbox', name='Tags', exact=True)).to_be_focused()
                    expect(strip).not_to_be_visible()
                    page.get_by_role('textbox', name='Tags', exact=True).fill('cooking, saved')
                    page.get_by_role('button', name='Save', exact=True).click()
                    expect(page.get_by_role('textbox', name='Tags', exact=True)).to_have_count(0)
                    expect(strip).to_be_visible()
                    expect(page.locator('.m-it-tags')).to_contain_text('cooking, saved')
                    page.screenshot(path=str(art / f'item-info-{width}-{theme}.png'))
                    # Creator search mounts TopBar with the supplied text, not a blank local draft.
                    page.locator('.m-it-by button').click()
                    expect(page).to_have_url(base + '/mobile.html#/search')
                    expect(page.get_by_role('searchbox', name='Search the library')).to_have_value('@chef.marco')
                    page.wait_for_function("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');return phone.q==='@chef.marco'&&phone.cat==='all'&&phone.searchIds?.has(20)}")
                    self.assertEqual(errors, [])

    def test_item_keep_delete_tools_and_missing_states(self):
        art = OUT.parent / 'phone-item'
        art.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base):
            for mode, pair, theme in (('mirror', PAIR, 'light'), ('mirror', dict(PAIR, solo=False), 'dark'), ('desktop', PAIR, 'light')):
                paired = mode == 'mirror' and not pair['solo']
                label = 'paired' if paired else mode
                with self.subTest(mode=label), synthetic_phone(browser, base, 390, 844, theme, pair=pair) as (page, errors):
                    page.route('**/thumbs-proxy.js', lambda r: r.fulfill(path=OUT.parents[1] / 'web/public/thumbs-proxy.js'))
                    page.goto(base + '/mobile.html#/lib')
                    seed_items(page, mode)
                    if paired:
                        page.evaluate('window.__items.slow=true')
                    page.locator('.m-cell-a[href="#/item/1"]').click()
                    if paired:
                        page.wait_for_function('()=>window.__items.waits.length===1')
                        expect(page.locator('.m-rep')).to_contain_text('Example caption')
                        page.evaluate('window.__items.release()')
                    expect(page.locator('.m-rep')).to_contain_text('Example caption')
                    key = page.get_by_role('button', name='Keep on this phone', exact=True)
                    expect(key).to_have_attribute('aria-pressed', 'true' if mode == 'desktop' else 'false')
                    if mode == 'desktop':
                        # A late detail reply cannot undo Forget.
                        page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');window.__items.slow=true;phone.rows=phone.rows.map(r=>r.id===1?{...r,tv:r.tv+1}:r)}")
                        page.wait_for_function('()=>window.__items.waits.length===1')
                        key.click()
                        expect(key).to_have_attribute('aria-pressed', 'false')
                        # Forget started no load of its own: the pending reply is the original slow one.
                        self.assertEqual(page.evaluate('window.__items.waits.length'), 1)
                        reads = page.evaluate('window.__items.reads')
                        page.evaluate('window.__items.release()')
                        page.wait_for_function('(n)=>window.__items.reads>n', arg=reads)
                        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                        self.assertTrue(page.evaluate('async()=>!(await window.__items.cached.get(1))'))
                        expect(key).to_have_attribute('aria-pressed', 'false')
                        reads = page.evaluate('window.__items.reads')
                        page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.rows=phone.rows.map(r=>r.id===1?{...r,tv:r.tv+1}:r)}")
                        page.wait_for_function('(n)=>window.__items.reads>n', arg=reads)
                        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                        self.assertTrue(page.evaluate('async()=>!(await window.__items.cached.get(1))'))
                        expect(key).to_have_attribute('aria-pressed', 'false')
                        key.click()
                        expect(key).to_have_attribute('aria-pressed', 'true')
                    else:
                        key.click()
                        expect(key).to_have_attribute('aria-pressed', 'true')
                        page.screenshot(path=str(art / f'item-kept-{label}.png'))
                        key.click()
                        expect(key).to_have_attribute('aria-pressed', 'false')
                        # A failed save leaves the key unpressed and exposes the error.
                        page.evaluate("window.__items.fail='video';location.hash='#/item/3'")
                        page.get_by_role('button', name='Keep on this phone', exact=True).click()
                        expect(page.get_by_role('alert')).to_contain_text('Synthetic video failure')
                        expect(page.get_by_role('button', name='Keep on this phone', exact=True)).to_have_attribute('aria-pressed', 'false')
                        page.evaluate("window.__items.fail=''")
                        page.get_by_role('button', name='Keep on this phone', exact=True).click()
                        saving = page.get_by_role('button', name='Saving video 42%', exact=True)
                        expect(saving).to_be_disabled()
                        self.assertEqual(page.locator('.m-phone-face').evaluate('e=>e.style.getPropertyValue("--m-save")'), '42%')
                        page.screenshot(path=str(art / f'item-saving-{label}.png'))
                        page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.rows=phone.rows.map(r=>r.id===3?{...r,tv:r.tv+1}:r)}")
                        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                        expect(saving).to_be_disabled()
                        page.evaluate('window.__items.finishVideo()')
                        expect(page.get_by_role('button', name='Keep on this phone', exact=True)).to_have_attribute('aria-pressed', 'true')
                        self.assertTrue(page.evaluate('async()=>!!(await window.__items.cached.get(3))?.saved'))
                        # Phone-made items are named images and never keep toggles.
                        page.evaluate("location.hash='#/item/-1'")
                        expect(page.get_by_role('img', name='Waiting for the PC' if paired else 'Saved on this phone', exact=True)).to_be_visible()
                        expect(page.get_by_role('button', name='Keep on this phone', exact=True)).to_have_count(0)
                        expect(page.locator('.m-it-by')).to_have_count(0)
                        page.screenshot(path=str(art / f'item-phone-state-{label}.png'))
                    page.evaluate("location.hash='#/item/1'")
                    # Favourite's accessible label stays compatible with the phone-state browser check.
                    fav = page.get_by_role('button', name='Favourite', exact=True)
                    fav.click()
                    expect(fav).to_have_attribute('aria-pressed', 'true')
                    if mode == 'mirror':
                        tools = page.locator('.m-it-tools')
                        tools.click()
                        expect(tools).to_have_attribute('aria-expanded', 'true')
                        panel = page.get_by_role('dialog', name='Tools', exact=True)
                        # A focused step row is not text entry: the strip stays.
                        panel.get_by_role('button', name='Describe', exact=True).focus()
                        expect(panel.get_by_role('button', name='Describe', exact=True)).to_be_focused()
                        expect(page.locator('nav[aria-label="Items"]')).to_be_visible()
                        panel.get_by_role('button', name='Describe', exact=True).click()
                        expect(page.locator('.m-rep')).to_contain_text('Fresh description from Tools')
                        page.keyboard.press('Escape')
                        expect(panel).to_have_count(0)
                        # The new description appears before slow report text; Report gets its own tab.
                        page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');window.__items.slowText=true;window.__items.descriptions[1]='New source description';window.__items.reports[1]='# Fresh report';window.__items.transcripts[1]='Fresh transcript';phone.rows=phone.rows.map(r=>r.id===1?{...r,an:true}:r)}")
                        page.wait_for_function('()=>window.__items.textWaits.length===2')
                        expect(page.locator('.m-rep')).to_contain_text('New source description')
                        expect(page.get_by_role('button', name='Description', exact=True)).to_have_attribute('aria-pressed', 'true')
                        page.evaluate('window.__items.releaseText()')
                        expect(page.get_by_role('button', name='Report', exact=True)).to_be_visible()
                        expect(page.get_by_role('button', name='Description', exact=True)).to_have_attribute('aria-pressed', 'true')
                        page.get_by_role('button', name='Report', exact=True).click()
                        expect(page.locator('.m-rep')).to_contain_text('Fresh report')
                        page.get_by_role('button', name='Description', exact=True).click()
                        expect(page.locator('.m-rep')).to_contain_text('New source description')
                        page.get_by_role('button', name='Transcript', exact=True).click()
                        expect(page.locator('.m-rep')).to_contain_text('Fresh transcript')
                    # Edit errors keep the old category. Delete always asks and restores focus on dismissal.
                    page.evaluate("window.__items.fail='edit'")
                    page.get_by_role('button', name='Choose collection: Art', exact=True).click()
                    page.get_by_role('dialog', name='Choose collection', exact=True).get_by_role('button', name='Other', exact=True).click()
                    expect(page.get_by_role('alert')).to_contain_text('Synthetic edit failure')
                    expect(page.get_by_role('button', name='Choose collection: Art', exact=True)).to_be_visible()
                    delete = page.get_by_role('button', name='Delete', exact=True)
                    delete.click()
                    dialog = page.get_by_role('dialog', name='Delete "Level hard."?', exact=True)
                    expect(dialog).to_be_visible()
                    self.assertEqual(page.evaluate('window.__items.deletes'), [])
                    expect(dialog.get_by_role('button', name='Cancel', exact=True)).to_be_focused()
                    for _ in range(5):
                        page.keyboard.press('Tab')
                        self.assertTrue(dialog.evaluate('e=>e.contains(document.activeElement)'))
                    page.keyboard.press('Escape')
                    expect(dialog).not_to_be_visible()
                    expect(delete).to_be_focused()
                    delete.click()
                    page.mouse.click(2, 2)
                    expect(dialog).not_to_be_visible()
                    expect(delete).to_be_focused()
                    delete.click()
                    dialog.get_by_role('button', name='Cancel', exact=True).click()
                    expect(dialog).not_to_be_visible()
                    page.evaluate("window.__items.fail='delete'")
                    delete.click()
                    dialog.get_by_role('button', name='Phone and PC' if paired else 'Delete', exact=True).click()
                    expect(page.get_by_role('alert')).to_contain_text('Synthetic delete failure')
                    expect(page.locator('.m-it-tt')).to_have_text('Level hard.')
                    page.evaluate("window.__items.fail=''")
                    entry = page.evaluate('navigation.currentEntry.index')
                    delete.click()
                    page.screenshot(path=str(art / f'item-delete-{label}.png'))
                    if paired:
                        expect(dialog.get_by_role('button', name='Phone and PC', exact=True)).to_be_visible()
                        dialog.get_by_role('button', name='This phone', exact=True).click()
                    else:
                        dialog.get_by_role('button', name='Delete', exact=True).click()
                    expect(page).to_have_url(base + '/mobile.html#/lib')
                    # Desktop opened item 1 straight from Library: one step back, no duplicate Library entry.
                    # The mirror runs came through items 3 and -1: the Library replaces the item's entry.
                    self.assertEqual(page.evaluate('navigation.currentEntry.index'), entry - 1 if mode == 'desktop' else entry)
                    self.assertEqual(page.evaluate('window.__items.deletes'), [{'id': 1, 'pc': not paired}])
                    # A missing row has Back + ITEM but no Delete/Open/strip. One row also hides the strip.
                    page.evaluate("location.hash='#/item/123456'")
                    expect(page.locator('.m-empty')).to_contain_text("No card No.123456 in the phone's copy.")
                    expect(page.get_by_role('button', name='Back', exact=True)).to_be_visible()
                    expect(page.get_by_role('button', name='Delete', exact=True)).to_have_count(0)
                    expect(page.get_by_role('navigation', name='Items', exact=True)).to_have_count(0)
                    page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.rows=phone.rows.filter(r=>r.id===2);location.hash='#/item/2'}")
                    expect(page.get_by_role('navigation', name='Items', exact=True)).to_have_count(0)
                    self.assertEqual(errors, [])


    def test_item_strip_limits_snap_and_snapshot_lifecycle(self):
        art = OUT.parent / 'phone-item'
        art.mkdir(parents=True, exist_ok=True)
        with mobile_browser() as (browser, base), synthetic_phone(browser, base, 390, 844, 'light') as (page, errors):
            page.route('**/thumbs-proxy.js', lambda r: r.fulfill(path=OUT.parents[1] / 'web/public/thumbs-proxy.js'))
            page.goto(base + '/mobile.html#/lib')
            seed_items(page)
            page.locator('.m-cell-a[href="#/item/1"]').click()
            strip = page.get_by_role('navigation', name='Items', exact=True)

            def begin(dx):
                box = strip.bounding_box()
                x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                page.mouse.move(x, y)
                page.mouse.down()
                page.mouse.move(x + dx, y, steps=4)

            begin(120)
            expect(page.locator('.m-item-preview .m-ws')).to_have_text('1 / 80')
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/1')
            page.evaluate("location.hash='#/item/80'")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 80')
            begin(-120)
            expect(page.locator('.m-item-preview .m-ws')).to_have_text('80 / 80')
            expect(page.locator('.m-item-preview .m-tint')).to_be_visible()
            page.screenshot(path=str(art / 'item-drag-tint-390-light.png'))
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/80')
            # Animated snap is 150 ms; reduced motion removes the settling phase.
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.motionOff=false;document.documentElement.classList.remove('motion-off');location.hash='#/item/2'}")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 2')
            page.emulate_media(reduced_motion='no-preference')
            begin(-28)
            page.mouse.up()
            expect(page.locator('.m-item-settling')).to_have_count(1)
            expect(page).to_have_url(base + '/mobile.html#/item/3')
            # A touch during the snap completes that snap first, so the ring and the page agree; held past
            # 380 ms without travel it opens nothing more.
            begin(-28)
            page.mouse.up()
            page.mouse.down()
            expect(page).to_have_url(base + '/mobile.html#/item/4')
            expect(strip.locator('[aria-current="page"]')).to_have_attribute('data-item', '4')
            page.wait_for_timeout(400)
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/4')
            expect(strip.locator('[aria-current="page"]')).to_have_attribute('data-item', '4')
            page.emulate_media(reduced_motion='reduce')
            begin(-28)
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/5')
            expect(page.locator('.m-item-settling')).to_have_count(0)
            # The centre window remains bounded, and changing favourites does not recapture it.
            page.evaluate("location.hash='#/item/40'")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 40')
            self.assertEqual(strip.get_by_role('button').count(), 41)
            page.get_by_role('button', name='Favourite', exact=True).click()
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.fav=true}")
            begin(28)
            expect(page.locator('.m-item-preview .m-ws')).to_have_text('39 / 80')
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/39')
            # The third preview form is the grid's link block when there are no details yet.
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');const f=window.__items,r={...f.rows.get(80),title:f.rows.get(80).url};f.rows.set(80,r);phone.rows=phone.rows.map(x=>x.id===80?r:x);location.hash='#/item/79'}")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 79')
            begin(-28)
            expect(page.locator('.m-item-preview .m-ghost')).to_be_visible()
            self.assertEqual(page.locator('.m-item-preview .m-ghost').evaluate('e=>getComputedStyle(e).backgroundColor'),
                             page.locator('.m-main').evaluate('e=>getComputedStyle(e).backgroundColor'))
            page.screenshot(path=str(art / 'item-drag-link-390-light.png'))
            page.mouse.up()
            page.evaluate("location.hash='#/item/39'")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 39')
            # Related is outside the snapshot and the visible favourites: recapture the whole library.
            page.locator('.m-rel button').click()
            expect(page).to_have_url(base + '/mobile.html#/item/999')
            begin(28)
            expect(page.locator('.m-item-preview .m-ws')).to_have_text('81 / 82')
            page.mouse.up()
            expect(page).to_have_url(base + '/mobile.html#/item/-1')
            # Missing neighbours/current rows are pruned without undefined keyed rows or stale timers.
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.rows=phone.rows.filter(r=>r.id!==999)}")
            expect(strip).to_be_visible()
            begin(28)
            expect(page.locator('.m-item-preview .m-ws')).to_have_text('80 / 81')
            page.mouse.up()
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');phone.rows=phone.rows.filter(r=>r.id!==phone.route.item)}")
            expect(strip).to_have_count(0)
            # Empty copy, absent URL/format and literal unknown creator do not leave false controls.
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');const f=window.__items,r={...f.rows.get(2),url:'',type:'',creator:'unknown'};f.rows.set(2,r);f.descriptions[2]='';phone.rows=[r];location.hash='#/item/2'}")
            expect(page.locator('.m-it-tt')).to_have_text('Saved item 2')
            expect(page.locator('.m-it-by,.m-it-format,.m-it-open,.m-it-open-corner')).to_have_count(0)
            expect(page.locator('.m-rep')).to_contain_text('No description yet. Open Tools to describe it with your AI key, or let the PC do it.')
            # A partly completed failed Tools run still reloads its stored result through ondone.
            page.evaluate("async()=>{const {source}=await import('/src/mobile/state.svelte.ts');source.describe=async id=>{window.__items.descriptions[id]='Partial result retained';throw Error('Synthetic partial failure')}}")
            page.get_by_role('button', name='Tools', exact=True).click()
            panel = page.get_by_role('dialog', name='Tools', exact=True)
            panel.get_by_role('button', name='Describe', exact=True).click()
            expect(panel).to_contain_text('Synthetic partial failure')
            expect(page.locator('.m-rep')).to_contain_text('Partial result retained')
            # Larger phone text and a long collection still leave the corner (i) and keys on screen.
            page.evaluate("async()=>{const {phone}=await import('/src/mobile/state.svelte.ts');const f=window.__items,name='A collection with a deliberately long name for the phone kicker';const r={...f.rows.get(2),cat:name};f.rows.set(2,r);phone.cats=[...phone.cats,{name,color:'#39776b',count:1}];TYPE[name]='#39776b';phone.rows=[r]}")
            expect(page.locator('.m-it-catname')).to_contain_text('deliberately long name')
            title_h = page.locator('.m-it-tt').evaluate('e=>e.getBoundingClientRect().height')
            # Desktop Edge ignores text-size-adjust (Android only): zoom the head and key row to stand in for
            # 130% phone text, and prove the zoom took effect.
            page.add_style_tag(content='#m-app .m-it-head,#m-app .m-it-keyrow{zoom:1.3}')
            self.assertGreater(page.locator('.m-it-tt').evaluate('e=>e.getBoundingClientRect().height'), title_h * 1.2)
            page.keyboard.press('Escape')
            page.locator('.m-main').evaluate('e=>e.scrollTop=0')
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertTrue(page.locator('.m-main').evaluate('e=>e.scrollWidth<=e.clientWidth'))
            self.assertTrue(page.locator('.m-it-catname').evaluate('e=>e.scrollWidth>e.clientWidth'))
            expect(page.get_by_role('button', name='More info: On this phone', exact=True)).to_be_in_viewport()
            page.screenshot(path=str(art / 'item-large-text-390-light.png'))
            self.assertEqual(errors, [])
            # Render the five approved local references with the same bundled fonts, offline.
            fonts = page.evaluate("() => [...document.styleSheets].flatMap(s=>[...s.cssRules].filter(r=>r.type===CSSRule.FONT_FACE_RULE).map(r=>r.cssText)).join('\\n')")
            reference = page.context.new_page()
            reference.set_viewport_size({'width': 390, 'height': 844})
            try:
                reference.route(base + '/phone-item-reference.html', lambda r: r.fulfill(content_type='text/html', body='<!doctype html>'))
                reference.goto(base + '/phone-item-reference.html')
                mockups = OUT.parents[1] / 'projects/phone-dock-shell/mockups'
                for name, selector in (('item-final', '.phones > div .ph'), ('item-keep-delete', '.option[data-choice="d1"] .ph'),
                                       ('item-strip', '.option[data-choice="b"] .ph'), ('item-meta', '.option[data-choice="m2"] .mini'),
                                       ('item-corner-2', '.option[data-choice="k2"] .mini, .option[data-choice="k2"] .strip')):
                    if not (mockups / f'{name}.html').is_file():
                        continue        # the approved mockups live in the private project folder, which a public checkout does not have
                    html = '\n'.join(line for line in (mockups / f'{name}.html').read_text(encoding='utf-8').splitlines()
                                     if not line.startswith('<link'))
                    reference.set_content(f'<base href="{base}/"><style>{fonts.replace("Archivo Variable", "Archivo")}</style>' + html)
                    reference.evaluate('()=>document.fonts.ready')
                    self.assertTrue(reference.evaluate("() => ['Archivo','IBM Plex Mono'].every(name=>[...document.fonts].some(f=>f.family===name&&f.status==='loaded'))"))
                    self.assertEqual(reference.evaluate("() => [...document.fonts].filter(f=>f.status==='error').length"), 0)
                    for i, shot in enumerate(reference.locator(selector).all()):
                        shot.screenshot(path=str(art / f'reference-{name}-{i}.png'))
            finally:
                reference.close()


if __name__ == '__main__':
    unittest.main()
