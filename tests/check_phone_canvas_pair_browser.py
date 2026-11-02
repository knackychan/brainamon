"""Paired canvas handoff and refusal on a temporary PC and fake Drive, at 360x800."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
from PIL import Image
from core import app_paths, local_auth
from core.db import Database


BASE = 'http://127.0.0.1:18799'
HEAD = {'X-CM': '1', 'Content-Type': 'application/json'}
AUTH = {}                                   # the server's per-run credential, read once it answers


def api(path, body=None):
    req = Request(BASE + path, data=json.dumps(body or {}).encode() if body is not None else None,
                  headers={**HEAD, **AUTH} if body is not None else dict(AUTH))
    try:
        with urlopen(req, timeout=10) as response:
            return json.load(response)
    except HTTPError as e:                  # the server's refusal, in its words
        raise AssertionError(f'{path}: {e.code} {e.read().decode(errors="replace")}') from None


def alive():
    try:
        return api('/api/health')
    except OSError:                         # not listening yet
        return None


def until(check, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(.2)
    raise AssertionError('timed out waiting for isolated PC sync')


def pending(page, fingerprint, name, token, item_id=None, uid=None):
    page.evaluate('''async ({fingerprint,name,token,item_id,uid}) => {
      const key='wiskit-canvas-proposal:'+fingerprint;
      const element=item_id ? {kind:'thumbnail',item_id} : {kind:'text',text:name};
      const preview={target:{id:null,name,new:true,count:0},layout:'rows',arrange:false,
        counts:{thumbnail:item_id?1:0,frame:0,text:item_id?0:1,sections:0,moves:0},
        sections:[{title:null,elements:[element]}],explicit:[]};
      const db=await new Promise((ok,bad)=>{const r=indexedDB.open('brainamon-phone',2);r.onsuccess=()=>ok(r.result);r.onerror=()=>bad(r.error)});
      await new Promise((ok,bad)=>{const t=db.transaction('kv','readwrite');
        t.objectStore('kv').put({token,raw:{new_name:name,elements:[element]},refs:item_id?{[item_id]:uid}:{},quick:true,preview},key);
        t.oncomplete=ok;t.onerror=()=>bad(t.error)});
    }''', {'fingerprint': fingerprint, 'name': name, 'token': token, 'item_id': item_id, 'uid': uid})
    page.goto(BASE + '/mobile.html#/jv')
    page.reload()
    page.get_by_role('heading', name=f'New canvas: {name}').wait_for()
    page.get_by_role('button', name='Apply', exact=True).click()
    page.get_by_role('button', name='Open canvas').click()
    if item_id:
        page.locator('.m-cv-el img').wait_for()
        page.wait_for_function("(() => { const e = document.querySelector('.m-cv-el img'); return e?.complete && e.naturalWidth > 0 })")
    else:
        page.get_by_text(name, exact=True).wait_for()
    return re.search(r'/canvas/([0-9a-f]{32})', page.url).group(1)


def main():
    with tempfile.TemporaryDirectory(prefix='paired-canvas-', ignore_cleanup_errors=True) as temp:
        env = dict(os.environ, CM_DATA_DIR=str(Path(temp) / 'data'), CM_PORT='18799', PYTHONUTF8='1',
                   BRAINAMON_HOME=str(Path(temp) / 'home'))
        db = Database(Path(env['CM_DATA_DIR']) / 'content_manager.db')
        item_id = db.add_item({'url': 'https://example.com/photo', 'description': 'Photo', 'thumb_path': 'thumb.jpg'})
        uid = db.conn.execute('SELECT uid FROM items WHERE id = ?', (item_id,)).fetchone()[0]
        Image.new('RGB', (90, 160), '#5588aa').save(db.item_dir(item_id) / 'thumb.jpg')
        db.close()
        log = open(Path(temp) / 'server.log', 'w')
        proc = subprocess.Popen([sys.executable, '-m', 'tests.isolated_canvas_server'], env=env,
                                stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            until(alive, 300)
            app_paths.LOCAL = Path(temp) / 'home' / 'local'
            AUTH.update(local_auth.headers(18799))
            api('/api/cloud/connect', {})
            until(lambda: api('/api/cloud').get('last_publish'))
            pair = api('/api/cloud/pair', {})
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel='msedge')
                context = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True)
                context.add_init_script("Object.defineProperty(navigator, 'connection', {value: {type: 'wifi', addEventListener() {}}})")
                page = context.new_page()
                page.set_default_timeout(7000)
                page.goto(pair['url'].replace('localhost', '127.0.0.1'))
                page.get_by_text('Paired with your PC.', exact=True).wait_for()
                # DEV enables the synthetic Drive transport but skips registration; exercise the real worker for offline images.
                page.evaluate("async () => { await navigator.serviceWorker.register('/sw.js', {scope:'/mobile.html'}); await navigator.serviceWorker.ready }")
                page.reload()
                page.wait_for_function('navigator.serviceWorker.controller !== null')
                page.goto(BASE + '/mobile.html#/jv')
                page.get_by_placeholder('Ask your library…').wait_for()
                api('/api/cloud/stop', {})
                cid = pending(page, pair['fingerprint'], 'Paired offline', 'paired-1')
                page.reload()
                page.get_by_text('Paired offline', exact=True).wait_for()
                page.goto(BASE + '/mobile.html#/backup')
                page.get_by_role('button', name='Send now', exact=True).first.click()
                page.get_by_text(re.compile('Changes from this phone:.*waiting for the PC')).first.wait_for()
                previous = api('/api/cloud')['last_publish']
                api('/api/cloud/connect', {})
                until(lambda: (Path(temp) / 'data' / 'canvases' / f'{cid}.json').exists())
                until(lambda: api('/api/cloud').get('last_intake'))
                until(lambda: api('/api/cloud').get('last_publish', 0) > previous)
                page.goto(BASE + '/mobile.html#/canvas')
                page.reload()
                page.get_by_text(re.compile('Synced')).wait_for(timeout=12000)
                api('/api/cloud/stop', {})
                thumb = pending(page, pair['fingerprint'], 'Photo board', 'paired-thumb', item_id, uid)
                context.set_offline(True)
                page.reload()
                page.locator('.m-cv-el img').wait_for()
                page.wait_for_function("(() => { const e = document.querySelector('.m-cv-el img'); return e?.complete && e.naturalWidth > 0 })")
                context.set_offline(False)
                refused = pending(page, pair['fingerprint'], 'Taken name', 'paired-2')
                api('/api/canvases', {'name': 'Taken name'})
                page.goto(BASE + '/mobile.html#/backup')
                page.get_by_role('button', name='Send now', exact=True).first.click()
                page.get_by_text(re.compile('Changes from this phone:.*waiting for the PC')).first.wait_for()
                previous = api('/api/cloud')['last_publish']
                intake_before = api('/api/cloud')['last_intake']
                api('/api/cloud/connect', {})
                until(lambda: api('/api/cloud').get('last_intake', 0) > intake_before)
                until(lambda: api('/api/cloud').get('last_publish', 0) > previous)
                assert (Path(temp) / 'data' / 'canvases' / f'{thumb}.json').exists()
                page.goto(BASE + '/mobile.html#/canvas')
                page.reload()
                page.get_by_text(re.compile('Not synced:.*name already exists')).wait_for(timeout=12000)
                page.get_by_role('button', name=re.compile('Taken name.*Not synced')).click()
                page.locator('.m-cv-txt').filter(has_text='Taken name').wait_for()
                assert not (Path(temp) / 'data' / 'canvases' / f'{refused}.json').exists()
                context.close()
                browser.close()
            print('Paired browser: offline Apply, thumbnail offline reload, PC handoff/receipt and name refusal retention passed')
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            log.close()


if __name__ == '__main__':
    main()
