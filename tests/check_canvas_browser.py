"""Real built-app geometry and approval checks. Run: py -m tests.check_canvas_browser.

Uses an isolated database, a free loopback port and the installed Edge browser.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

from PIL import Image
from playwright.sync_api import sync_playwright

from core.db import Database


def check_geometry(page, layout):
    # Neutralize only the camera, so rectangles are in board units, not layout's oracle.
    page.locator('#cv-world').evaluate("e => e.style.transform = 'translate(0px,0px) scale(1)'")
    rects = page.locator('#cv-world > .ce').evaluate_all('''els => els.map(e => {
        const r = e.getBoundingClientRect(), label = e.querySelector('.lbl');
        const l = label?.getBoundingClientRect();
        return {id:e.dataset.eid, x:r.x, y:Math.min(r.y,l?.y ?? r.y), right:r.right,
                bottom:r.bottom, label:l ? {x:l.x,right:l.right} : null};
    })''')
    for i, a in enumerate(rects):
        if a['label']:
            assert a['label']['x'] >= a['x'] - 2
            assert a['label']['right'] <= a['right'] + 1
        for b in rects[i + 1:]:
            assert not (a['x'] < b['right'] and b['x'] < a['right'] and
                        a['y'] < b['bottom'] and b['y'] < a['bottom']), (layout, a, b)


def check_selection(page):
    board = page.locator('#cv-board')
    world = page.locator('#cv-world')
    cards = world.locator('.ce')
    rects = [card.bounding_box() for card in cards.all()]
    left, top = min(r['x'] for r in rects) - 12, min(r['y'] for r in rects) - 12
    right = max(r['x'] + r['width'] for r in rects) + 12
    bottom = max(r['y'] + r['height'] for r in rects) + 12
    camera = world.get_attribute('style')
    assert board.evaluate('e => getComputedStyle(e).cursor') == 'default'
    # Reverse-direction box selection works with the fitted camera and never pans.
    page.mouse.move(right, bottom)
    page.mouse.down()
    page.mouse.move(left, top, steps=10)
    assert page.locator('.cv-marquee').is_visible()
    assert world.locator('.ce.sel').count() == 2
    page.mouse.up()
    assert page.locator('.cv-marquee').count() == 0
    assert world.get_attribute('style') == camera
    assert page.evaluate('window.getSelection().toString()') == ''
    # Dragging a selected note's body moves the whole group without moving the camera.
    note = world.locator('.ce.note').bounding_box()
    page.mouse.move(note['x'] + 30, note['y'] + 30)
    page.mouse.down()
    page.mouse.move(note['x'] + 70, note['y'] + 60, steps=5)
    page.mouse.up()
    for card, before in zip(cards.all(), rects):
        after = card.bounding_box()
        assert abs(after['x'] - before['x'] - 40) < 2
        assert abs(after['y'] - before['y'] - 30) < 2
    assert world.get_attribute('style') == camera
    # Ctrl-drag over a card pans without changing selection or element coordinates.
    positions = cards.evaluate_all('els => els.map(e => [e.style.left, e.style.top])')
    page.keyboard.down('Control')
    assert board.evaluate('e => getComputedStyle(e).cursor') == 'grab'
    page.mouse.down()
    page.mouse.move(note['x'] + 90, note['y'] + 80, steps=5)
    assert board.evaluate('e => getComputedStyle(e).cursor') == 'grabbing'
    page.mouse.up()
    page.keyboard.up('Control')
    assert board.evaluate('e => getComputedStyle(e).cursor') == 'default'
    assert world.get_attribute('style') != camera
    assert world.locator('.ce.sel').count() == 2
    assert cards.evaluate_all('els => els.map(e => [e.style.left, e.style.top])') == positions
    # Empty click clears; Shift-click adds/removes; Shift-box adds to a selection.
    r = board.bounding_box()
    page.mouse.click(r['x'] + 5, r['y'] + 5)
    assert world.locator('.ce.sel').count() == 0
    note = world.locator('.ce.note').bounding_box()
    image = world.locator('.ce.img').bounding_box()
    page.mouse.click(note['x'] + 20, note['y'] + 20)
    assert world.locator('.ce.note.sel').count() == 1
    page.keyboard.down('Shift')
    page.mouse.click(image['x'] + 20, image['y'] + 20)
    assert world.locator('.ce.sel').count() == 2
    page.mouse.click(image['x'] + 20, image['y'] + 20)
    assert world.locator('.ce.sel').count() == 1
    page.mouse.move(image['x'] - 10, image['y'] - 30)
    page.mouse.down()
    page.mouse.move(image['x'] + 30, image['y'] + 30, steps=5)
    page.mouse.up()
    page.keyboard.up('Shift')
    assert world.locator('.ce.sel').count() == 2
    world.locator('.ce-text').dblclick()
    page.locator('.ce-ed').wait_for()
    assert cards.count() == 2
    page.keyboard.press('Escape')
    print('PASS: box selection, group dragging, Ctrl-pan over cards, cursors and Shift selection', flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix='canvas-browser-', ignore_cleanup_errors=True) as temp:
        data = Path(temp)
        db = Database(data / 'content_manager.db')
        db.set_setting('setup_dismissed', '1')
        iid = db.add_item({'url': 'https://example.com/canvas', 'description': 'Canvas geometry'})
        image_dir = db.item_dir(iid)
        image_dir.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (600, 40), 'navy').save(image_dir / 'thumb.jpg')
        db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'

        def api(path, body=None, method=None):
            req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'X-CM': '1', 'Content-Type': 'application/json'}, method=method)
            with urlopen(req, timeout=10) as response:
                return json.load(response)

        env = dict(os.environ, CM_DATA_DIR=temp, CM_PORT=str(port))
        with (data / 'server.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'server'], env=env, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                for _ in range(100):
                    try:
                        api('/api/canvases')
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise AssertionError((data / 'server.log').read_text())
                        time.sleep(.1)
                else:
                    raise AssertionError('isolated server did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, channel='msedge')
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, has_touch=True)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.add_init_script("localStorage.setItem('cm-v6-ws', 'canvas')")
                    long_text = ('Long paragraph with Unicode 漢字 café. ' * 28)[:950] + '\n<b>literal</b> DISTINCTIVE END'
                    texts = ['Line\n' * 19 + 'Last line', long_text, '漢字\n' * 90, 'short']
                    label = 'W' * 80
                    for layout in ('rows', 'columns'):
                        elements = [({'kind': 'text', 'text': texts[i % 4], 'group': 'Section title'} if i % 2 == 0
                                     else {'kind': 'thumbnail', 'item_id': iid, 'label': '' if i == 3 else 'Short' if i == 5 else label,
                                           'group': 'Section title'}) for i in range(11)]
                        elements += [{'kind': 'text', 'text': long_text, 'x': 0, 'y': 0},
                                     {'kind': 'thumbnail', 'item_id': iid, 'label': '漢' * 80, 'x': 300, 'y': 0}]
                        req = api('/api/canvases/request', {'proposal': {'new_name': layout, 'layout': layout,
                                                                      'elements': elements}})
                        result = api(f"/api/jobs/request/{req['id']}/approve", {})
                        cid = result['canvas']['canvas_id']
                        api('/api/canvas/active', {'id': cid}, 'PUT')
                        page.goto(base)
                        page.locator('#cv-world .ce').first.wait_for()
                        page.evaluate('document.fonts.ready')
                        page.wait_for_function("[...document.querySelectorAll('#cv-world img')].every(i => i.complete)")
                        check_geometry(page, layout)
                        doc = api(f'/api/canvases/{cid}')['canvas']
                        for el in doc['items']:
                            if el['type'] == 'note':
                                node = page.locator(f"[data-eid='{el['id']}']")
                                assert abs(node.bounding_box()['height'] - el['h']) < .1
                                assert node.locator('.ce-text').text_content() == el['text']
                        # An arranged existing note keeps every property except x/y.
                        old = next(e for e in doc['items'] if e['type'] == 'note' and len(e['text']) > 500)
                        old_image = next(e for e in doc['items'] if e.get('label') == label)
                        req = api('/api/canvases/request', {'proposal': {'canvas_id': cid, 'arrange': True,
                            'layout': layout, 'elements': [{'kind': 'existing', 'id': old['id']},
                                                          {'kind': 'existing', 'id': old_image['id']}]}})
                        api(f"/api/jobs/request/{req['id']}/approve", {})
                        moved = next(e for e in api(f'/api/canvases/{cid}')['canvas']['items'] if e['id'] == old['id'])
                        assert {k:v for k,v in moved.items() if k not in ('x','y')} == {k:v for k,v in old.items() if k not in ('x','y')}
                        page.reload()
                        page.locator(f"[data-eid='{old['id']}'] .ce-text").wait_for()
                        assert page.locator(f"[data-eid='{old['id']}'] .ce-text").text_content() == old['text']
                        page.evaluate('document.fonts.ready')
                        check_geometry(page, layout)
                        moved_image = next(e for e in api(f'/api/canvases/{cid}')['canvas']['items'] if e['id'] == old_image['id'])
                        assert {k:v for k,v in moved_image.items() if k not in ('x','y')} == {k:v for k,v in old_image.items() if k not in ('x','y')}
                        print(f'PASS: {layout}, wraps, explicit offsets, Unicode/newlines, titles, labels and moved notes/images', flush=True)

                    # A compact board for real input interactions, without camera overrides.
                    req = api('/api/canvases/request', {'proposal': {'new_name': 'Interaction', 'elements': [
                        {'kind': 'text', 'text': long_text}, {'kind': 'thumbnail', 'item_id': iid, 'label': label}]}})
                    cid = api(f"/api/jobs/request/{req['id']}/approve", {})['canvas']['canvas_id']
                    api('/api/canvas/active', {'id': cid}, 'PUT')
                    page.reload()
                    note = page.locator('#cv-world .ce-text')
                    note.wait_for()
                    page.evaluate('document.fonts.ready')
                    # Panning across the navigation hint must not start native text selection.
                    hint = page.locator('#cv-st').bounding_box()
                    camera = page.locator('#cv-world').get_attribute('style')
                    page.evaluate('window.getSelection().removeAllRanges()')
                    page.mouse.move(hint['x'] + 20, hint['y'] + hint['height'] / 2)
                    page.keyboard.down('Control')
                    page.mouse.down()
                    page.mouse.move(hint['x'] + 200, hint['y'] + hint['height'] / 2, steps=10)
                    assert page.evaluate('window.getSelection().toString()') == ''
                    assert page.locator('#cv-world').get_attribute('style') != camera
                    camera = page.locator('#cv-world').get_attribute('style')
                    page.mouse.move(hint['x'] + 240, hint['y'] - 40, steps=5)
                    page.mouse.up()
                    page.keyboard.up('Control')
                    assert page.locator('#cv-world').get_attribute('style') != camera
                    assert page.evaluate('window.getSelection().toString()') == ''
                    page.reload()
                    note.wait_for()
                    check_selection(page)
                    page.reload()
                    note.wait_for()
                    note.focus()
                    page.keyboard.press('End')
                    page.wait_for_function("document.querySelector('.ce-text').scrollTop > 0")
                    note.evaluate('e => e.scrollTop = 0')
                    note.hover()
                    camera = page.locator('#cv-world').get_attribute('style')
                    page.mouse.wheel(0, 300)
                    page.wait_for_function("document.querySelector('.ce-text').scrollTop > 0")
                    assert page.locator('#cv-world').get_attribute('style') == camera
                    note.evaluate('e => e.scrollTop = 0')
                    r = note.bounding_box()
                    cdp = context.new_cdp_session(page)
                    cdp.send('Input.synthesizeScrollGesture', {'x': r['x'] + r['width']/2,
                        'y': r['y'] + r['height']/2, 'yDistance': -80, 'gestureSourceType': 'touch'})
                    page.wait_for_function("document.querySelector('.ce-text').scrollTop > 0")
                    assert page.locator('#cv-world').get_attribute('style') == camera
                    page.keyboard.down('Control')
                    page.mouse.wheel(0, -100)
                    page.keyboard.up('Control')
                    page.wait_for_function('(old) => document.querySelector("#cv-world").getAttribute("style") !== old', arg=camera)
                    # Drag using the note border, leaving text selection/scrolling intact.
                    r = page.locator('#cv-world .ce.note').bounding_box()
                    page.mouse.move(r['x'] + 3, r['y'] + 3)
                    page.mouse.down()
                    page.mouse.move(r['x'] + 43, r['y'] + 33, steps=5)
                    page.mouse.up()
                    assert page.locator('#cv-world .ce.note').bounding_box()['x'] > r['x'] + 20
                    button = page.locator('#cv-world .lbl')
                    button.focus()
                    page.keyboard.press('Enter')
                    page.get_by_text(label, exact=True).last.wait_for(state='visible')
                    page.get_by_role('button', name='Close', exact=True).last.click()
                    button.tap()
                    page.get_by_text(label, exact=True).last.wait_for(state='visible')
                    page.get_by_role('button', name='Close', exact=True).last.click()
                    note.focus()
                    page.keyboard.press('Enter')
                    page.locator('.ce-ed').wait_for()
                    assert page.locator('.ce-ed').input_value() == long_text
                    page.keyboard.press('Escape')
                    page.get_by_role('button', name='Add note', exact=True).click()
                    page.locator('.ce-ed').fill(long_text * 2)
                    page.keyboard.press('Escape')
                    manual = page.locator('#cv-world .ce.note').last
                    assert manual.locator('.ce-text').text_content() == long_text * 2
                    assert manual.locator('.ce-text').evaluate('e => e.scrollHeight > e.clientHeight')
                    print('PASS: keyboard/wheel/touch note reading, zoom, border dragging, editing, keyboard/touch full label', flush=True)

                    # Actual review component, safe literal text, default activation and narrow keyboard reading.
                    req = api('/api/canvases/request', {'proposal': {'new_name': 'Review text', 'elements': [
                        {'kind': 'text', 'text': long_text}, {'kind': 'text', 'text': long_text}]}})
                    review = page.get_by_role('region', name='Proposed canvas contents')
                    review.wait_for()
                    assert 'DISTINCTIVE END' in review.text_content()
                    assert '<b>literal</b>' in review.text_content()
                    assert review.locator('b').count() == 0
                    assert not page.get_by_role('checkbox', name='Make it the active canvas').is_checked()
                    page.set_viewport_size({'width': 540, 'height': 720})
                    review.focus()
                    page.keyboard.press('End')
                    page.wait_for_function("document.querySelector('.review').scrollTop > 0")
                    page.get_by_role('button', name='Apply (2)', exact=True).click()
                    review.wait_for(state='hidden')
                    assert api('/api/canvas/active')['id'] == cid
                    saved = next(c for c in api('/api/canvases') if c['name'] == 'Review text')
                    assert all(e['text'] == long_text for e in api(f"/api/canvases/{saved['id']}")['canvas']['items'])
                    req = api('/api/canvases/request', {'proposal': {'new_name': 'Declined board', 'elements': [
                        {'kind': 'text', 'text': long_text}]}})
                    review.wait_for()
                    page.keyboard.press('Escape')
                    review.wait_for(state='hidden')
                    assert api('/api/jobs')['request']['state'] == 'pending'
                    assert not any(c['name'] == 'Declined board' for c in api('/api/canvases'))
                    # Reload reopens the deferred request; Decline writes nothing.
                    page.reload()
                    review.wait_for()
                    page.get_by_role('button', name='Decline', exact=True).click()
                    review.wait_for(state='hidden')
                    assert api('/api/jobs')['request']['state'] == 'declined'
                    assert not any(c['name'] == 'Declined board' for c in api('/api/canvases'))
                    req = api('/api/canvases/request', {'proposal': {'new_name': 'Activated board', 'elements': [
                        {'kind': 'text', 'text': 'Only after Apply'}]}})
                    review.wait_for()
                    page.get_by_role('checkbox', name='Make it the active canvas').check()
                    assert api('/api/canvas/active')['id'] == cid
                    requests = []
                    page.on('request', lambda r: requests.append((r.method, r.url)))
                    page.get_by_role('button', name='Apply (1)', exact=True).click()
                    review.wait_for(state='hidden')
                    page.wait_for_function("document.querySelector('#cv-name').value === 'Activated board'")
                    assert api('/api/canvas/active')['id'] != cid
                    approve = next(i for i,r in enumerate(requests) if r[0] == 'POST' and r[1].endswith('/approve'))
                    activate = next(i for i,r in enumerate(requests) if r[0] == 'PUT' and r[1].endswith('/api/canvas/active'))
                    assert activate > approve
                    print('PASS: Close defers, Decline is a no-op, selected activation follows successful Apply', flush=True)
                    assert not errors, errors
                    print('PASS: full review suffix, literal markup, keyboard scrolling, Apply and unchecked activation', flush=True)
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
