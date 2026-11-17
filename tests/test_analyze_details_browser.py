"""Analysis options and item refresh with real reactive windows and synthetic data."""
import unittest

from playwright.sync_api import expect

from tests.test_mobile_info_browser import mobile_browser


class AnalyzeDetailsBrowser(unittest.TestCase):
    def test_interval_editing_and_submission(self):
        options = dict(frame_interval=3, transcribe=True, transcribe_method='whisper-api',
                       analysis_provider='claude', keep_frames=True, show_frames_in_canvas=True,
                       delete_video=False, delete_audio=False, ai_frame_budget='auto')
        with mobile_browser() as (browser, base):
            page = browser.new_page(viewport={'width': 600, 'height': 800})
            page.route('**/review', lambda r: r.fulfill(content_type='text/html', body='<div id="review"></div>'))
            page.route('**/api/settings/analyze', lambda r: r.fulfill(json={'options': options}))
            page.goto(base + '/review')
            page.evaluate("""async () => {
              const {mount} = await import('/node_modules/.vite/deps/svelte.js')
              const {default:Win} = await import('/src/windows/AnalyzeOptionsWin.svelte')
              mount(Win, {target:document.querySelector('#review'), props:{count:1,
                answer:o=>window.__answer=o, close:()=>{}}})
            }""")
            interval = page.get_by_role('spinbutton')
            sampling = page.get_by_role('switch', name='Sample frames', exact=True)
            submit = page.get_by_role('button', name='Analyze 1 video', exact=True)
            expect(interval).to_have_value('3')
            interval.focus()
            interval.press('Control+a')
            interval.press('Backspace')
            expect(interval).to_be_visible()
            expect(interval).to_be_focused()
            expect(sampling).to_be_checked()
            interval.press('5')
            submit.click()
            page.wait_for_function('() => window.__answer?.frame_interval === 5')
            for invalid in ('', '0', '-1', '61', '0.7'):
                with self.subTest(invalid=invalid):
                    interval.fill(invalid)
                    expect(sampling).to_be_checked()
                    submit.click()
                    expect(interval).to_have_value('5')
                    self.assertEqual(page.evaluate('window.__answer.frame_interval'), 5)
            sampling.click()
            expect(interval).to_have_count(0)
            expect(page.locator('#ao-send')).to_have_count(0)
            submit.click()
            page.wait_for_function('() => window.__answer.frame_interval === 0')
            sampling.click()
            expect(interval).to_have_value('5')
            expect(page.locator('#ao-send')).to_be_visible()
            page.locator('#ao-pr').select_option('none')
            expect(page.locator('#ao-send')).to_have_count(0)
            expect(page.locator('.ao-note')).to_be_visible()

    def test_completion_refresh_preserves_unsaved_fields(self):
        with mobile_browser() as (browser, base):
            page = browser.new_page(viewport={'width': 1000, 'height': 900})
            page.route('**/review', lambda r: r.fulfill(content_type='text/html', body='<div id="review"></div>'))
            page.goto(base + '/review')
            page.evaluate("""async () => {
              window.__item={id:123,url:'https://example.test',description:'Original description',
                short_desc:'Original title',creator:'Author',type:'Video',category:'INTERESTING',
                tags:'',notes:'Original notes',ai_desc:'Original AI',created:0,
                files:{thumb:false,report:false,transcript:false,frames:0,frame_names:[],video:false}}
              window.__report='First report'
              const realFetch=window.fetch
              window.fetch=async(url,opts)=>{
                if(String(url)==='/api/items/123') return new Response(JSON.stringify(window.__item))
                if(String(url).startsWith('/files/items/123/report.md')) return new Response(window.__report)
                if(String(url).startsWith('/api/')) return new Response('[]')
                return realFetch(url,opts)
              }
              window.__listeners={}
              window.EventSource=class {addEventListener(k,f){window.__listeners[k]=f} close(){}}
              const {connect}=await import('/src/lib/events.svelte.ts'); await connect()
              window.__changed=ids=>window.__listeners.items_changed({data:JSON.stringify({ids})})
              const {mount}=await import('/node_modules/.vite/deps/svelte.js')
              const {default:Win}=await import('/src/windows/ItemWin.svelte')
              mount(Win,{target:document.querySelector('#review'),props:{id:123,close:()=>{}}})
            }""")
            expect(page.locator('#f-mine')).to_have_value('Original notes')
            page.locator('#f-mine').fill('Unsaved notes')
            page.evaluate("""() => {
              Object.assign(window.__item,{description:'Updated description',notes:'Server notes',ai_desc:'Updated AI'})
              Object.assign(window.__item.files,{report:true,frames:1,frame_names:['001.jpg'],video:true})
              window.__changed([123])
            }""")
            expect(page.locator('#f-desc')).to_have_value('Updated description')
            expect(page.locator('#f-mine')).to_have_value('Unsaved notes')
            expect(page.locator('.aibox')).to_have_text('Updated AI')
            expect(page.locator('.md')).to_contain_text('First report')
            expect(page.get_by_role('button', name='Open video', exact=True)).to_be_enabled()
            expect(page.locator('.frm img')).to_have_attribute('src', '/files/items/123/frames/001.jpg?v=1')
            page.evaluate("""() => {
              window.__item.description='Reanalyzed description'
              window.__report='Replacement report'
              window.__changed([123])
            }""")
            expect(page.locator('#f-desc')).to_have_value('Reanalyzed description')
            expect(page.locator('#f-mine')).to_have_value('Unsaved notes')
            expect(page.locator('.md')).to_contain_text('Replacement report')
            expect(page.locator('.frm img')).to_have_attribute('src', '/files/items/123/frames/001.jpg?v=2')
