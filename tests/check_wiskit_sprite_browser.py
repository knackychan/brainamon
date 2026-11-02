"""Isolated browser check of the shared Wiskit player; no library or API keys used."""
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='wiskit-sprite-') as td, open(Path(td) / 'vite.log', 'w') as log:
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in
               ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'BRAINAMON_', 'CM_DATA_DIR', 'YTDLP_COOKIES'))}
        env.update(BRAINAMON_HOME=td, CM_DATA_DIR=str(Path(td) / 'data'),
                   LOCALAPPDATA=td, APPDATA=td, TEMP=td, TMP=td, PYTHON_DOTENV_DISABLED='1')
        proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port)],
                                cwd=ROOT / 'web', env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urlopen(base + '/src/components/WiskitSprite.svelte', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Isolated Vite did not start')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge')
                page = browser.new_page(viewport={'width': 720, 'height': 800})
                page.emulate_media(reduced_motion='no-preference')
                page.clock.install()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('**/wiskit/*', lambda r: r.fulfill(path=str(ROOT / 'web/public/wiskit' / r.request.url.rsplit('/', 1)[1])))
                page.route('**/__wiskit_sprite', lambda r: r.fulfill(content_type='text/html', body='''
                  <!doctype html><style>body{background:#16163a;color:#fff;font:14px system-ui;padding:20px}
                  #host{width:288px;height:168px} .gallery{display:grid;grid-template-columns:1fr 1fr;gap:12px}
                  .pose{height:112px;background:#1b1f4a}</style><div id="host"></div>'''))
                page.goto(base + '/__wiskit_sprite')
                page.evaluate(r'''async () => {
                  const source=await(await fetch('/src/components/WiskitSprite.svelte')).text()
                  const runtime=source.match(/from ["']([^"']*\/svelte\.js[^"']*)["']/)[1]
                  const {mount,unmount}=await import(runtime)
                  const {default:Sprite}=await import('/src/components/WiskitSprite.svelte')
                  let app
                  window.show=async props=>{if(app)await unmount(app);app=mount(Sprite,{target:document.querySelector('#host'),props})}
                  window.pixels=()=>Array.from(document.querySelector('#host canvas').getContext('2d').getImageData(0,0,96,56).data).join(',')
                  window.gallery=async()=>{
                    const index=await(await fetch('/wiskit/sheet.json')).json()
                    const grid=document.createElement('div');grid.className='gallery';document.body.replaceChildren(grid)
                    for(const pose of ['idle','processing','searching','done','hover','slither','inch']){
                      const box=document.createElement('div');box.textContent=pose;const target=document.createElement('div');target.className='pose';box.append(target);grid.append(box)
                      mount(Sprite,{target,props:{pose,motionOff:true}})
                    }
                  }
                  window.desk=async()=>{
                    if(app)await unmount(app)
                    const {default:Desk}=await import('/src/components/WiskitDesk.svelte')
                    await import('/src/app.css')
                    const style=document.createElement('link');style.rel='stylesheet';style.href='/styles/v6-page.css';document.head.prepend(style)
                    document.body.innerHTML='<div id="host"></div>'
                    document.body.style.cssText='display:block;margin:0;padding:16px'
                    mount(Desk,{target:document.querySelector('#host')})
                  }
                  await window.show({pose:'processing'})
                }''')
                page.wait_for_function("document.querySelector('canvas')?.width===96 && document.querySelector('canvas').getContext('2d').getImageData(0,0,96,56).data.some(v=>v)", timeout=5000)
                before = page.evaluate('pixels()')
                page.clock.run_for(160)
                assert page.evaluate('pixels()') != before, 'Working stance must animate'
                for props in ({'pose': 'processing', 'motionOff': True}, {'pose': 'processing'}):
                    page.emulate_media(reduced_motion='reduce' if not props.get('motionOff') else 'no-preference')
                    page.evaluate('props=>show(props)', props)
                    page.wait_for_function("document.querySelector('canvas').getContext('2d').getImageData(0,0,96,56).data.some(v=>v)")
                    before = page.evaluate('pixels()')
                    page.clock.run_for(600)
                    assert page.evaluate('pixels()') == before, 'Motion off must keep a still frame'
                assert page.evaluate("document.querySelector('canvas').getContext('2d').getImageData(0,0,1,1).data[3]") == 0, 'Key color must be transparent'
                page.emulate_media(reduced_motion='no-preference')
                page.evaluate('gallery()')
                page.wait_for_function("document.querySelectorAll('canvas').length===7 && [...document.querySelectorAll('canvas')].every(c=>c.getContext('2d').getImageData(0,0,96,56).data.some(v=>v))")
                out = Path(td) / 'ported-stances.png'
                page.screenshot(path=str(out), full_page=True)
                page.route('**/api/**', lambda r: r.abort())
                page.set_viewport_size({'width': 460, 'height': 900})
                page.evaluate('desk()')
                page.add_style_tag(content='.jv{position:relative!important;inset:auto!important;transform:none!important;width:412px!important;height:850px!important} #host{width:auto;height:auto}')
                page.wait_for_function("document.querySelector('.scene canvas')?.getContext('2d').getImageData(0,0,96,56).data.some(v=>v)")
                assert page.locator('.meter,#lv,#xp,#m-cpu,#m-cite').count() == 0
                assert page.locator('.hud').count() == 0
                assert page.locator('.wbar .scene').evaluate('(el)=>el.getBoundingClientRect().height') >= 64
                assert page.locator('.wbar .scene').evaluate('(el)=>el.clientWidth') >= 200
                page.locator('.wbar').screenshot(path=str(out.with_name('ported-desk.png')))
                assert not errors, errors
                browser.close()
                print('Wiskit browser: animation, motion settings, transparency and seven stances passed')
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == '__main__':
    main()
