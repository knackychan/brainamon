"""Every state of the phone's status model (tests/fixtures/phone_states.json) on the real phone page, each reached by its
cause (docs/superpowers/plans/2026-10-31-phone-backup-phones.md, sub-plan 07; P7, P12). The backend runs on a temporary
library with a temporary cloud folder and a synthetic license, server/dev_drive.py stands in for Google Drive, and the
phone page runs on Vite with the pairing the PC's own link gives. The link's development Drive is left out, so the page
signs in and reads Drive the way it does on a phone: Google's sign-in, its token info and Drive are Playwright routes,
Drive forwarded to the stand-in. More and More > Backup & phones are photographed for every state at 360 x 780 in light
and dark, into local/ui-blocks/phone-states/<theme>/, listed in its index.md. No account, no real Drive, no data folder.
Run: py tests/check_phone_states_browser.py
"""
import base64
from collections import Counter
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.phone_groups import open_group  # noqa: E402  (the group rows, projects/phone-settings)

ART = ROOT / 'local/ui-blocks/phone-states'
VIEW = {'width': 360, 'height': 780}
FIXED_TIME = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)
PC_ACCOUNT, OTHER_ACCOUNT = 'a@example.com', 'b@example.com'
PROJECT = '123456789012'
DESKTOP_CLIENT = '123456789012-desktop.apps.googleusercontent.com'
WEB_CLIENT = '123456789012-phone.apps.googleusercontent.com'
TOKEN_SECONDS = 4 * 3600        # a synthetic Google token outlasts the clock moved past the grant's hour (waiting-pc)
PASSPHRASE = 'Disposable phone states recovery passphrase'
SOLO_RAW = bytes([13]) * 32
SOLO_KEY = base64.urlsafe_b64encode(SOLO_RAW).decode().rstrip('=')
SOLO_PAIR = dict(v=2, k=SOLO_KEY, f=hashlib.sha256(b'brainamon-mirror-1 id' + SOLO_RAW).hexdigest()[:12], c='', e='',
                 ai={}, at=0, solo=True)
PLACEHOLDER = 'Diagnosis words from diagnose.ts, naming the PC.'     # the fixture's stand-in for them
CASES = {c['name']: c['expect'] for c in json.loads((ROOT / 'tests/fixtures/phone_states.json').read_text(encoding='utf-8'))['cases']}
STATE_IDS = set(re.findall(r"'([a-z-]+)'", re.search(r'export type StateId =(.*?)\nexport ',
                (ROOT / 'web/src/mobile/mirror/phone-state.ts').read_text(encoding='utf-8'), re.S).group(1)))
# web/vite.config.ts sends these to 127.0.0.1:18765, the app itself, by plain prefix (also /thumbs-proxy.js): the
# check points them at its own backend and never lets the browser reach them
PROXIED = ('/api', '/thumb', '/cards', '/files', '/wiskit')
PUBLIC = (ROOT / 'web/public').resolve()
SETTLED = ("async () => { const { phone } = await import('/src/mobile/state.svelte.ts')"
           "; return phone.tried && !phone.refreshing && !phone.connecting && (!phone.sync || !!phone.sync.end) }")
# navigator.connection as Chrome on a phone reports it; __network(type) switches it for the rest of the scene
NET = """(() => { const c = new EventTarget(); c.type = sessionStorage.getItem('fixture-net') || 'wifi'
  Object.defineProperty(navigator, 'connection', { value: c })
  window.__network = type => { sessionStorage.setItem('fixture-net', type); c.type = type; c.dispatchEvent(new Event('change')) } })();"""
# a browser that cannot check Ed25519 signatures (the issuer's key in the access check); P-256 and the rest still work
NO_ED25519 = """(() => { const original = crypto.subtle.importKey.bind(crypto.subtle)
  crypto.subtle.importKey = (format, data, algorithm, ...rest) => (algorithm === 'Ed25519' || algorithm?.name === 'Ed25519')
    ? Promise.reject(new DOMException('Ed25519 is not supported', 'NotSupportedError')) : original(format, data, algorithm, ...rest) })();"""
STATE = ("async () => { const { phone } = await import('/src/mobile/state.svelte.ts')"
         "; const { network } = await import('/src/mobile/network.svelte.ts')"
         "; const { tried, refreshing, connecting, reachable, answered, noLibrary, pend } = phone"
         "; return JSON.stringify({ tried, refreshing, connecting, reachable, answered, noLibrary, pend, network }) }")


def solo_seed(signed_in, token):
    """What the Android app leaves on a phone without a PC: its pairing and, after Google's Android sign-in, the confirmed
    account and a token. Set once per page session, before the page runs."""
    seed = {'bp-pair': json.dumps(dict(SOLO_PAIR, g=PC_ACCOUNT) if signed_in else SOLO_PAIR)}
    if token:
        seed['bp-gtoken'] = json.dumps({'access': 'synthetic-solo', 'exp': int(time.time() * 1000) + TOKEN_SECONDS * 1000})
    return ("if (!sessionStorage.getItem('fixture')) { sessionStorage.setItem('fixture', '1'); for (const [k, v] of Object.entries("
            + json.dumps(seed) + ")) localStorage.setItem(k, v) }")


def words(text):
    """A fixture sentence; its "checked 2 min ago" and its clock times read what the run gives."""
    t = re.escape(text).replace(re.escape('2 min ago'), r'(just now|\d+ min ago)')
    for clock in ('15:05', '14:02'):
        t = t.replace(re.escape(clock), r'(\d{1,2} [A-Z][a-z]{2} )?\d{2}:\d{2}')
    return re.compile('^' + t + '$')


def main():
    ART.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='brainamon-phone-states-') as folder:
        root = Path(folder)
        for name in ('home', 'data', 'tmp', 'appdata', 'localappdata'):
            (root / name).mkdir()
        env = {**os.environ, 'BRAINAMON_HOME': str(root / 'home'), 'CM_DATA_DIR': str(root / 'data'),
               'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
               'APPDATA': str(root / 'appdata'), 'LOCALAPPDATA': str(root / 'localappdata')}
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--fixture', str(root)], cwd=ROOT, env=env, timeout=1800)
        sys.exit(r.returncode)


class PhoneDrive:
    """Google Drive as one phone sees it: every request to www.googleapis.com goes to the stand-in Drive, unless the
    scene holds it (`hold`, a test on the request), refuses the token (`refuse`), cuts the network (`cut`) or names
    another account (`account`)."""

    # Historical PH12/legacy-license/WebView cases model an older PC. V2 transport, watermark and
    # anti-downgrade are covered by test_licensed_sync and test_phone_access; no signature is bypassed here.
    legacy_only = set()

    def __init__(self, base):
        self.base, self.held, self.calls = base, [], []
        self.hold, self.refuse, self.cut, self.account = None, False, False, ''

    def route(self, route):
        req, url = route.request, urlparse(route.request.url)
        self.calls.append(f'{req.method} {url.path}')
        if self.cut:
            return route.abort()
        if self.refuse:
            return route.fulfill(status=401, json={'error': {'code': 401, 'message': 'Invalid Credentials'}})
        if url.path == '/drive/v3/about' and self.account:
            return route.fulfill(json={'user': {'emailAddress': self.account}})
        if self.hold and self.hold(req):
            self.held.append(route)
            return None
        return self.forward(route)

    def forward(self, route):
        req, url = route.request, urlparse(route.request.url)
        headers = {k: v for k, v in req.headers.items() if k.lower() in ('authorization', 'content-type')}
        body = req.post_data_buffer if req.method in ('POST', 'PATCH', 'PUT') else None
        try:
            with urlopen(Request(self.base + url.path + ('?' + url.query if url.query else ''), data=body,
                                 method=req.method, headers=headers), timeout=30) as r:
                status, data, ctype = r.status, r.read(), r.headers.get('Content-Type', 'application/json')
        except HTTPError as e:
            status, data, ctype = e.code, e.read(), e.headers.get('Content-Type', 'application/json')
        part = re.search(r"name contains '([^']*)'", parse_qs(url.query).get('q', [''])[0])
        if part and status == 200 and req.method == 'GET':          # the stand-in answers `name = 'X'` only
            data = json.dumps({'files': [f for f in json.loads(data)['files'] if part.group(1) in f['name']]}).encode()
        if status == 200 and req.method == 'GET' and url.path == '/drive/v3/files':
            body = json.loads(data)
            body['files'] = [f for f in body['files'] if f.get('name') not in self.legacy_only]
            data = json.dumps(body).encode()
        return route.fulfill(status=status, body=data, headers={'content-type': ctype, 'access-control-allow-origin': '*'})

    def release(self):
        held, self.held = self.held, []
        for r in held:
            self.forward(r)


def upload_name(req):
    """The Drive name of a multipart upload (the phone's change files, its record, its recovery setup), else ''."""
    if req.method not in ('POST', 'PATCH') or '/upload/drive/v3/files' not in req.url:
        return ''
    message = BytesParser(policy=default).parsebytes(
        ('Content-Type: ' + req.headers['content-type'] + '\r\n\r\n').encode() + req.post_data_buffer)
    meta = next(iter(message.iter_parts()))
    return json.loads(meta.get_payload(decode=True) or b'{}').get('name', '')


def changes_up(req):
    return upload_name(req).startswith('chg-')


def fixture(root):
    # This function runs only in the child, after the runner set the home and the library.
    import socket
    import threading
    import unittest
    from unittest import mock
    import uvicorn
    from cryptography.hazmat.primitives.asymmetric import ec
    from playwright.sync_api import Error, expect, sync_playwright
    expect.set_options(timeout=20_000)
    from core import app_paths, license, sync_license
    from core.db import Database
    from library import drive_client, mirror, recovery
    from library.export_targets import DriveMirrorTarget
    from server import sync as sync_mod
    from server.app import create_app
    from server.dev_drive import serve
    from tests.license_fixture import activate

    check = unittest.TestCase()
    check.maxDiff = None
    clock = mock.patch('time.time', return_value=FIXED_TIME.timestamp())
    clock.start()
    check.addCleanup(clock.stop)
    check.assertTrue(app_paths.HOME.is_relative_to(root))
    check.assertTrue(app_paths.data_dir().is_relative_to(root))
    license_key = activate(check, root)
    data, cloud, vault = root / 'data', root / 'cloud', root / 'vault'
    vault.mkdir()
    (vault / 'Synthetic note.md').write_text('# Synthetic note\n', encoding='utf-8')
    db = Database(data / 'content_manager.db')
    items = [db.add_item({'url': f'https://example.invalid/state-{n}', 'description': f'Synthetic item {n}'}) for n in range(1, 9)]
    db.set_setting('onboard_answer', 'skip')
    db.set_setting('automatic_updates', '0')
    db.set_setting('obsidian_vault', str(vault))
    db.close()
    drive = serve(root / 'fake-drive', port=0, account=PC_ACCOUNT)
    solo_drive = serve(root / 'fake-drive-solo', port=0, account=PC_ACCOUNT)
    base = f'http://127.0.0.1:{drive.server_port}'
    solo_base = f'http://127.0.0.1:{solo_drive.server_port}'

    def free_port():
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    port, vport = free_port(), free_port()
    app = create_app(data_dir=data, cloud_dir=cloud, port=port, web_dist=root / 'no-web')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False,
                                           timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, daemon=True)
    # the phone page on Vite, trusting the synthetic issuer only (tests/test_sync_loop_browser.py builds it the same way)
    vite_log = open(root / 'vite.log', 'w')
    vite = subprocess.Popen(['node', '--input-type=module', '-e', """import {createServer} from 'vite'
      const backend = {target: process.argv[3], changeOrigin: true}
      const proxy = Object.fromEntries(JSON.parse(process.argv[4]).map(prefix => [prefix, backend]))
      const s = await createServer({configFile: 'vite.config.ts', logLevel: 'error', define: {__LICENSE_PUBLIC_KEYS__: process.argv[2]},
        server: {host: '127.0.0.1', port: Number(process.argv[1]), strictPort: true, proxy}})
      await s.listen()""", str(vport), json.dumps(license.PUBLIC_KEYS), f'http://127.0.0.1:{port}', json.dumps(PROXIED)],
        cwd=ROOT / 'web', stdout=vite_log, stderr=vite_log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    origin = f'http://127.0.0.1:{vport}'
    page_url = origin + '/mobile.html'
    cards = {name: ROOT / 'design/card-designs' / name for name in ('cards.css', 'engine.js', 'full-art-v2/fa2.css', 'full-art-v2/fa2.js')}
    held = {}               # Drive name -> threading.Event: the PC's upload of that file waits until it is set
    entered, done = Counter(), Counter()        # Drive name -> uploads that reached its held gate, uploads made
    original_upload = drive_client.DriveClient.upload

    def upload(client, name, *args, **kwargs):
        gate = held.get(name)
        if gate is not None and not gate.is_set():
            entered[name] += 1
            if not gate.wait(600):
                raise AssertionError(f'the held upload of {name} was never released')
        out = original_upload(client, name, *args, **kwargs)
        done[name] += 1
        return out

    def hold(name):
        held[name] = threading.Event()

    def release(name):
        held[name].set()

    original_connect = socket.socket.connect

    def loopback_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
            raise AssertionError('Fixture refused non-loopback connection')
        return original_connect(sock, address)

    errors, reached, shots, unexpected, drives, index, pictures, dialogs = [], {}, [], [], [], [], [], []
    page = None

    def wait_for(predicate, label, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            if page is None:
                time.sleep(.05)
            else:
                page.wait_for_timeout(50)          # dispatch the browser's routes while the PC works
        try:
            pc = {k: svc.st.get(k) for k in ('state', 'error_code', 'error', 'upload_step')}
        except NameError:                          # before the PC's backup exists
            pc = None
        raise AssertionError(f'{label} (the PC: {pc})' if pc else label)

    def api(method, path, body=None):
        req = Request(f'http://127.0.0.1:{port}{path}', method=method, data=None if body is None else json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + app.state.api_token, 'X-CM': '1', 'Content-Type': 'application/json'})
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b'null')

    def link():
        """The PC's own pairing link (Settings > Backup & phones > Add a phone) without its development Drive: the
        phone page refuses one outside a development build and reaches the stand-in through Google's address."""
        code = api('POST', '/api/cloud/pair', {})['code']
        p = json.loads(base64.urlsafe_b64decode(code + '=' * (-len(code) % 4)))
        PhoneDrive.legacy_only.add(mirror.MirrorKey(base64.urlsafe_b64decode(p['k'] + '=')).name(sync_license.ACCESS_LOGICAL))
        check.assertEqual(p.pop('d'), base)
        check.assertEqual((p['e'], p['c'], p.get('p')), (PC_ACCOUNT, WEB_CLIENT, '123456789012'))
        return encode(p)

    def payload(code):
        return json.loads(base64.urlsafe_b64decode(code + '=' * (-len(code) % 4)))

    def encode(p):
        return base64.urlsafe_b64encode(json.dumps(p, separators=(',', ':')).encode()).rstrip(b'=').decode()

    def client():
        return svc._client(drive_client.load_token(svc.token_path))

    def files():
        return {f['name']: f['id'] for f in client().list()}

    def put(name, blob):
        """A Drive file written as another holder of the library key would (the PC's own upload, not held)."""
        original_upload(client(), name, data=blob, file_id=files().get(name, ''))

    with mock.patch.object(drive_client, 'API', base + '/drive/v3'), \
            mock.patch.object(drive_client, 'UPLOAD', base + '/upload/drive/v3'), \
            mock.patch('core.config.google_client', return_value=(DESKTOP_CLIENT, 'fixture')), \
            mock.patch('core.config.google_web_client', return_value=WEB_CLIENT), \
            mock.patch.object(socket.socket, 'connect', loopback_only), \
            mock.patch.object(drive_client.DriveClient, 'upload', upload), \
            mock.patch.object(DriveMirrorTarget, 'TICK_EVERY', .05), \
            mock.patch.object(sync_mod, 'INTAKE', .05), mock.patch.object(sync_mod, 'INTAKE_MAX', .1), \
            mock.patch.object(sync_mod, 'POLL', .05):
        try:
            thread.start()
            wait_for(lambda: server.started, 'fixture server startup failed')
            for _ in range(300):
                try:
                    urlopen(origin + '/src/mobile/main.ts', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError('Vite did not start')
            svc = app.state.sync
            drive_client.save_token(svc.token_path, {'access_token': 'fixture', 'refresh_token': 'fixture', 'expires_at': 4e9})
            kit = svc.recovery.enroll(PASSPHRASE, PASSPHRASE)
            svc.recovery.verify_kit(recovery.dump(kit).decode())
            key = svc.mirror_key()
            CONTROL, MANIFEST, META = key.name(sync_license.LOGICAL), key.name(mirror.MANIFEST), key.name('library/meta.json')

            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(headless=True, channel='msedge',
                                                 args=['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost'])
                except Error as e:
                    raise AssertionError('Edge unavailable: ' + str(e).splitlines()[0]) from e

                def google(route):
                    """Google's sign-in page: back to the phone page with a synthetic token, or, for a silent round trip
                    while `google.ended`, with Google's answer that the user must sign in."""
                    q = parse_qs(urlparse(route.request.url).query)
                    check.assertEqual(q['client_id'], [WEB_CLIENT])
                    google.calls += 1
                    if q.get('prompt') == ['none'] and google.ended:
                        answer = {'error': 'interaction_required', 'state': q['state'][0]}
                    else:
                        google.n += 1
                        answer = {'access_token': f'synthetic-{google.n}', 'token_type': 'Bearer', 'expires_in': TOKEN_SECONDS,
                                  'scope': 'https://www.googleapis.com/auth/drive.appdata', 'state': q['state'][0]}
                    back = q['redirect_uri'][0] + '#' + urlencode(answer)
                    route.fulfill(content_type='text/html', body=f'<script>location.replace({json.dumps(back)})</script>')
                google.n, google.calls, google.ended = 0, 0, False

                def phone(drive_base=base, init='', direct=False):
                    """A new phone browser. `direct`: a page with no pairing, which looks for its PC at the address it was
                    opened from (the phone page the PC serves): nothing answers it there."""
                    nonlocal page
                    d = PhoneDrive(drive_base)
                    drives.append(d)
                    ctx = browser.new_context(viewport=VIEW, is_mobile=True, has_touch=True, accept_downloads=True,
                                              service_workers='block', timezone_id='UTC', locale='en-GB')
                    ctx.add_init_script("localStorage.setItem('bp-lang','en')")

                    def other(route):
                        u = route.request.url
                        path = urlparse(u).path
                        if u.startswith(origin + '/') and not path.startswith(PROXIED):
                            return route.continue_()
                        public = (PUBLIC / path.lstrip('/')).resolve()
                        if u.startswith(origin + '/') and public.is_relative_to(PUBLIC) and public.is_file():
                            return route.fulfill(path=public)              # /thumbs-proxy.js, /wiskit/sheet.json
                        if not (direct and u.startswith(origin + '/api/')):
                            unexpected.append(u.split('?')[0])
                        return route.abort()
                    ctx.route('**/*', other)
                    ctx.route(origin + '/cards/**', lambda r: r.fulfill(path=cards[urlparse(r.request.url).path.removeprefix('/cards/')]))
                    # a mirror thumbnail with no service worker to answer from the page's cache: sw.js's answer for one
                    # it cannot find
                    ctx.route(lambda u: u.startswith(origin + '/thumb/'), lambda r: r.fulfill(status=503, body=''))
                    ctx.route('https://www.googleapis.com/**', d.route)
                    ctx.route('https://accounts.google.com/**', google)
                    ctx.route('https://oauth2.googleapis.com/**', lambda r: r.fulfill(json={'azp': WEB_CLIENT, 'aud': WEB_CLIENT}))
                    ctx.add_init_script("if (location.protocol === 'http:') {" + NET + init + '}')     # not about:blank
                    page = ctx.new_page()
                    page.clock.set_fixed_time(FIXED_TIME)
                    page.set_default_timeout(30000)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
                    return ctx, page, d

                def settle(p):
                    """The page's reads are over: no read running, none started a moment later."""
                    for pause in (200, 300):
                        p.wait_for_timeout(pause)
                        p.wait_for_function(SETTLED)

                def round_trip(p, act):
                    """`act` sends the page to Google's sign-in, which sends it back with its answer; then its reads end."""
                    n = google.calls
                    act()
                    wait_for(lambda: google.calls > n, 'the page did not go to Google')
                    p.wait_for_url(re.compile(r'^http://127\.0\.0\.1:\d+/mobile\.html#/'))
                    p.wait_for_load_state()
                    settle(p)

                def open_link(p, code):
                    """The PC's pairing link opened on the phone: a phone browser loads it in a tab of its own. The page
                    takes a pairing link once, when it starts (mirror/pairing.ts takeFromUrl), then shows Backup & phones;
                    a link that changed only the hash of the page already open would not be taken."""
                    p.goto('about:blank')
                    p.goto(page_url + '#pair=' + code)
                    expect(p.locator('#m-backup-status')).to_be_visible()
                    settle(p)

                def sync_now(p):
                    p.evaluate("location.hash = '#/more'")
                    open_group(p, 'Sync').get_by_role('button', name='Sync now', exact=True).first.click()
                    settle(p)

                def key_on(p, label, screen='backup'):
                    """The Status key on Backup & phones (or the card's on More)."""
                    p.evaluate(f"location.hash = '#/{screen}'")
                    p.locator('#m-backup-status' if screen == 'backup' else '#m-status').get_by_role('button', name=label, exact=True).click()

                def kind(p):
                    return p.evaluate("async () => (await import('/src/mobile/network.svelte.ts')).network.licenseKind")

                def pend(p):
                    return p.evaluate("async () => { const { phone } = await import('/src/mobile/state.svelte.ts'); return { ...phone.pend } }")

                def fav(p, n):
                    """One edit, as the user makes it: Favourite on the item's screen."""
                    p.evaluate(f"location.hash = '#/item/{items[n]}'")
                    p.get_by_role('button', name=re.compile('Favourite$')).click()

                def counts(p, want, label, seconds=60):
                    """Wait until the journal's counts (unsent, waiting, resending) are `want`."""
                    try:
                        wait_for(lambda: {k: pend(p)[k] for k in want} == want, label, seconds)
                    except AssertionError:
                        raise AssertionError(f'{label}: the journal holds {pend(p)}, not {want}') from None

                def all_in(p, label, seconds=90):
                    """Sync now until the PC has taken in every edit this phone sent (its receipts are in Drive)."""
                    def done():
                        sync_now(p)
                        return {k: pend(p)[k] for k in ('unsent', 'waiting', 'resending')} == {'unsent': 0, 'waiting': 0, 'resending': 0}
                    wait_for(done, label, seconds)

                def fits(p):
                    return p.evaluate('() => document.documentElement.scrollWidth <= innerWidth')

                def shoot(p, name):
                    """The screen as it is, light and dark, its whole height (the page scrolls inside .m-main, a sheet
                    inside .m-sheet-body)."""
                    more = p.evaluate("() => { const m = document.querySelector('.m-sheet-body') || document.querySelector('.m-main'); return m ? m.scrollHeight - m.clientHeight : 0 }")
                    p.set_viewport_size({'width': VIEW['width'], 'height': VIEW['height'] + max(0, more)})
                    for theme in ('light', 'dark'):
                        p.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
                        check.assertTrue(fits(p), (name, theme, 'no sideways scroll'))
                        (ART / theme).mkdir(parents=True, exist_ok=True)
                        p.screenshot(path=str(ART / theme / f'{name}.png'))
                    p.evaluate("document.documentElement.dataset.theme = 'light'")
                    p.set_viewport_size(VIEW)
                    shots.append(name)
                    return f'{name}.png'

                def shows(p, case, diagnosis=None):
                    """Fixture case `case` on More (the card: its dot, sentence and key), on Backup & phones (the Status: its
                    dot, sentence, detail and key), the app bar's lamp and the line under it; More and Backup & phones
                    photographed, and the Library under the line when there is one. `diagnosis`: what the scene put in
                    the folder, for a case whose detail is diagnose.ts's words."""
                    want = CASES[case]
                    state, detail = want['id'], want['detail']
                    if detail == PLACEHOLDER:
                        folder = {'listed': [], 'ours': False, 'signedAs': PC_ACCOUNT, 'pcAccount': PC_ACCOUNT,
                                  'pcProject': PROJECT, 'phoneProject': PROJECT, **diagnosis}
                        detail = p.evaluate("async f => (await import('/src/mobile/mirror/diagnose.ts')).diagnoseNoLibrary(f).message", folder)
                    n = len(reached.get(state, [])) + 1
                    name = state if n == 1 else f'{state}-{n}'
                    files = []
                    for screen, scope in (('more', '#m-status'), ('backup', '#m-backup-status')):
                        p.evaluate(f"location.hash = '#/{screen}'")
                        box = p.locator(scope).locator('.m-status')
                        expect(box.locator('b')).to_have_text(words(want['text']))
                        expect(box.locator('.m-status-dot')).to_have_class(re.compile(rf"\b{want['tone']}\b"))
                        if screen == 'backup':
                            if detail:
                                expect(box.locator('small')).to_have_text(words(detail))
                            else:
                                expect(box.locator('small')).to_have_count(0)
                        keys = box.get_by_role('button')
                        if want['action']:
                            expect(keys).to_have_count(1)
                            expect(keys).to_have_text(want['action']['label'])
                            check.assertEqual('pri' in keys.get_attribute('class').split(), want['action']['primary'], case)
                        else:
                            expect(keys).to_have_count(0)
                        files.append(shoot(p, f'{name}-{screen}'))
                    p.evaluate("location.hash = '#/lib'")
                    if want['lamp']:                                     # the lamp is the sync key's name (section pages)
                        expect(p.locator('.m-sync-key')).to_have_attribute('aria-label', 'Drive · ' + want['lamp'])
                    strip = p.locator('.m-strip-owner')
                    if want['strip']:
                        expect(strip).to_have_text(words('Backup & phones · ' + want['text']))
                        files.append(shoot(p, f'{name}-library'))
                    else:
                        expect(strip).to_have_count(0)
                    reached.setdefault(state, []).append(case)
                    index.append({'case': case, 'state': state, 'text': want['text'], 'detail': detail,
                                  'action': want['action']['label'] if want['action'] else '', 'lamp': want['lamp'],
                                  'strip': want['strip'], 'files': files})
                    print(f'{state}: {case}', flush=True)

                def stop_renewals(name):
                    """The PC's next renewal of the access record `name` waits at the gate (the control loop is woken to
                    reach it), so what the scene writes there stays."""
                    hold(name)
                    n = entered[name]
                    svc._control_wake.set()
                    wait_for(lambda: entered[name] > n, 'the PC did not try to renew the access record')

                def renew(name):
                    """The held renewal goes through: the PC's own access record is back."""
                    n = done[name]
                    release(name)
                    wait_for(lambda: done[name] > n, 'the PC did not renew the access record')

                def removed():
                    """Remove all phones has finished on the PC: the new key's backup is complete."""
                    rotation = svc._rotation(readonly=True)
                    return not rotation or rotation['stage'] == 'complete'

                def extra(p, route, name, what):
                    """A picture of no state of its own (Recover a library…, More with no pairing), listed in the index."""
                    p.evaluate(f"location.hash = '{route}'")
                    expect(p.locator('.m-pad').first).to_be_visible()
                    p.wait_for_timeout(300)
                    pictures.append({'what': what, 'file': shoot(p, name)})

                def write_index(images):
                    """local/ui-blocks/phone-states/index.md: every picture with what it must show."""
                    source = hashlib.sha256()
                    for f in sorted((ROOT / 'web/src').rglob('*')):
                        if f.is_file():
                            source.update(f.relative_to(ROOT).as_posix().encode() + b'\0' + f.read_bytes().replace(b'\r\n', b'\n'))
                    at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                    lines = ['# The phone\'s states, on the page', '',
                             f'Written by `tests/check_phone_states_browser.py` at {at} (sub-plan 07 of',
                             '`docs/superpowers/plans/2026-10-31-phone-backup-phones.md`). The phone page in Edge at 360 x 780, each picture',
                             "grown to its screen's whole height, light and dark, as a phone browser shows it (not the Android app);",
                             f'`web/src` sha256 {source.hexdigest()[:12]}. Every state of the status model reached by its cause on a temporary',
                             "library with a synthetic license, the stand-in Google Drive (`server/dev_drive.py`) and Google's sign-in",
                             f'answered by the check: no account, no real Drive, no data folder. {images} pictures.',
                             f'Clock: {FIXED_TIME.isoformat()}, UTC; waiting-pc moves past the grant expiry.',
                             'Build commit: ' + os.environ.get('BRAINAMON_REVIEW_COMMIT', 'scratch rehearsal, uncommitted; source hash above'), '',
                             '| State | Fixture case | Sentence | Detail | Key | Lamp | Line under the app bar | Pictures |',
                             '|---|---|---|---|---|---|---|---|']
                    for e in index:
                        links = ' '.join(f'[{t} {f[:-4]}]({t}/{f})' for f in e['files'] for t in ('light', 'dark'))
                        cells = [f"`{e['state']}`", e['case'], e['text'], e['detail'] or '(none)', e['action'] or '(none)',
                                 e['lamp'] or '(the usual one)', 'yes' if e['strip'] else 'no', links]
                        lines.append('| ' + ' | '.join(cells) + ' |')
                    lines += ['', 'Other pictures:', '']
                    lines += [f"- {e['what']}: [light]({'light/' + e['file']}), [dark]({'dark/' + e['file']})" for e in pictures]
                    pictured = {e['case'] for e in index}
                    lines += ['', "Fixture cases with no picture of their own (their state is pictured with another case above; the",
                              "Android app's cases are its words for the same state):", '']
                    lines += [f'- `{CASES[name]["id"]}`: {name}' for name in CASES if name not in pictured]
                    lines += ['', 'Not checked in a browser (the device gate in the master plan):', '',
                              '- Scan new code, the Android app\'s QR scanner (removed, replaced, waiting-pc, access-invalid, key): a phone',
                              "  browser opens the PC's pairing link instead, as pictured.",
                              "- Google's Android sign-in (Connect, Sign in again, Change account, Back up to Google Drive): here Google's web",
                              '  sign-in, answered by the check; a phone without a PC signs in only in the app, so the check left its account',
                              '  and token.',
                              '- The app\'s words for webview ("Update Android System WebView.", the Play Store): here "Update this browser.".',
                              "- The app's first start without a PC, which makes the phone's own library: the check left its pairing.",
                              '- A real Google account and Google Drive.', '']
                    (ART / 'index.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

                def diag():
                    """What the phone shows, its state and its last Drive calls, when a scene fails."""
                    try:
                        if page is not None and not page.is_closed():
                            print('--- the page at', page.url, flush=True)
                            print(page.locator('body').inner_text(timeout=5000), flush=True)
                            print('--- its state:', page.evaluate(STATE), flush=True)
                        if drives:
                            print('--- its last Drive calls:', drives[-1].calls[-40:], flush=True)
                    except Exception as e:  # the page is gone: what the scene printed is all there is
                        print('--- no diagnosis:', e, flush=True)

                def scenes():
                    # ── 1. a new phone: Connect, its first confirmation on its way, then no library yet ─────────────────
                    hold(CONTROL)
                    code = link()                               # starts the PC's phone access; its first upload waits
                    ctx, p, d = phone()
                    open_link(p, code)
                    stored = p.evaluate("async () => (await import('/src/mobile/native.ts')).secrets.get('bp-pair')")
                    check.assertEqual(json.loads(stored)['f'], key.fingerprint)
                    check.assertNotIn('d', json.loads(stored))           # the production transport: Google's address
                    shows(p, 'PH2 connect Google Drive')
                    round_trip(p, lambda: key_on(p, 'Connect'))
                    check.assertEqual(kind(p), 'missing')
                    shows(p, 'first confirmation on its way')
                    release(CONTROL)
                    wait_for(lambda: CONTROL in files(), 'the PC did not confirm the phone')
                    key_on(p, 'Retry')
                    wait_for(lambda: kind(p) == '', 'the phone did not find its access')
                    settle(p)
                    shows(p, 'no library, empty folder', diagnosis={})
                    # the vault in Drive, the library not backed up
                    api('POST', '/api/cloud/vault/connect')
                    wait_for(lambda: any(n.startswith(('vb-', 'vs-')) for n in files()), 'the PC did not upload the vault')
                    sync_now(p)
                    shows(p, 'PC not backing up the library')
                    api('POST', '/api/cloud/vault/stop')
                    # Back up now, its manifest held: the PC's first backup is running
                    hold(MANIFEST)
                    api('POST', '/api/cloud/publish')
                    wait_for(lambda: MANIFEST in entered and META in files(), 'the first backup did not reach its manifest')
                    sync_now(p)
                    shows(p, 'PH3 first backup running')
                    release(MANIFEST)
                    wait_for(lambda: MANIFEST in files(), 'the first backup did not finish')
                    sync_now(p)
                    shows(p, 'PH4 in sync, all sent')

                    # ── 2. edits: sent and waiting for the PC (backup is off), not sent yet, offline, sign in again ─────
                    fav(p, 0)
                    counts(p, {'unsent': 0, 'waiting': 1, 'resending': 0}, 'one edit sent')
                    shows(p, 'PH4 in sync, edits waiting for the PC')
                    d.hold = changes_up
                    fav(p, 1)
                    fav(p, 2)
                    counts(p, {'unsent': 2, 'waiting': 1, 'resending': 0}, 'two edits held')
                    shows(p, 'PH4 in sync, edits not sent')
                    ctx.set_offline(True)
                    shows(p, 'PH5 offline with edits')
                    ctx.set_offline(False)
                    d.hold = None
                    d.release()
                    counts(p, {'unsent': 0, 'waiting': 3, 'resending': 0}, 'three edits sent')
                    d.refuse, google.ended = True, True
                    sync_now(p)
                    shows(p, 'PH9 Google asks to sign in again')
                    d.refuse, google.ended = False, False
                    round_trip(p, lambda: key_on(p, 'Sign in again'))
                    api('POST', '/api/cloud/connect')            # Turn on backup: the PC takes the three edits in
                    all_in(p, 'the PC did not take the edits in')
                    shows(p, 'PH4 in sync, all sent')

                    # ── 3. Wi-Fi only on mobile data, the first read held, Drive out of reach, a PC in a newer format ───
                    p.evaluate("__network('cellular')")
                    fav(p, 3)
                    counts(p, {'unsent': 1, 'waiting': 0, 'resending': 0}, 'one edit waits for Wi-Fi')
                    shows(p, 'Wi-Fi only on mobile data')
                    p.evaluate("__network('wifi')")
                    counts(p, {'unsent': 0, 'resending': 0}, 'the edit sent on Wi-Fi')
                    all_in(p, 'the PC did not take in the edit sent on Wi-Fi')
                    d.hold = lambda req: req.method == 'GET' and f"name = '{MANIFEST}'" in parse_qs(urlparse(req.url).query).get('q', [''])[0]
                    p.reload()
                    wait_for(lambda: d.held, 'the first read did not ask for the manifest')
                    shows(p, 'first read running')
                    d.hold = None
                    d.release()
                    settle(p)
                    d.cut = True
                    fav(p, 4)
                    counts(p, {'unsent': 1, 'waiting': 0, 'resending': 0}, 'one edit out of reach')
                    sync_now(p)
                    shows(p, 'Drive out of reach')
                    d.cut = False
                    key_on(p, 'Retry')
                    settle(p)
                    with mock.patch.object(mirror, 'READER', mirror.READER + 1):
                        app.state.writer.call(lambda db: db.update_item(items[7], {'description': 'Changed on the PC'}))
                        svc.poke(force=True)
                        wait_for(lambda: json.loads(key.open(mirror.MANIFEST, client().download(files()[MANIFEST]))).get('reader') == mirror.READER,
                                 'the PC did not back up in the newer format')
                        sync_now(p)
                        shows(p, 'PC copy too new')
                    app.state.writer.call(lambda db: db.update_item(items[7], {'description': 'Changed on the PC again'}))
                    svc.poke(force=True)                                    # in its own format again
                    wait_for(lambda: json.loads(key.open(mirror.MANIFEST, client().download(files()[MANIFEST]))).get('reader') == mirror.READER,
                             'the PC did not back up in its own format again')
                    all_in(p, 'the PC did not take in the edit made out of reach')
                    shows(p, 'PH4 in sync, all sent')

                    # ── 4. the access record: written with another PC's key, damaged, the PC's license removed ─────────
                    stop_renewals(CONTROL)
                    other = ec.generate_private_key(ec.SECP256R1())         # a restored or reinstalled PC: a new signer
                    put(CONTROL, key.seal(sync_license.LOGICAL, sync_license.record(key, other)))
                    sync_now(p)
                    check.assertEqual(kind(p), 'replaced')
                    shows(p, 'PH12 in a phone browser')
                    put(CONTROL, b'a damaged access record')
                    sync_now(p)
                    check.assertEqual(kind(p), 'invalid')
                    shows(p, 'access could not be checked in a phone browser')
                    renew(CONTROL)                                          # the PC's own record again
                    n = done[CONTROL]
                    api('DELETE', '/api/license')                           # Settings > License > Remove on the PC
                    svc._control_wake.set()                                # receipts no longer alter the worker lifetime
                    wait_for(lambda: done[CONTROL] > n, 'the PC did not write its record without the license')
                    sync_now(p)
                    check.assertEqual(kind(p), 'inactive')
                    shows(p, 'PC license inactive')
                    n = done[CONTROL]
                    api('PUT', '/api/license', {'key': license_key})
                    svc._control_wake.set()
                    wait_for(lambda: done[CONTROL] > n, 'the PC did not write its record with the license')
                    api('POST', '/api/cloud/connect')                       # removing the license stopped the backup
                    sync_now(p)
                    shows(p, 'PH4 in sync, all sent')

                    # ── 5. Remove all phones on the PC: the phone keeps three edits, pairs again and sends them ──────────
                    api('POST', '/api/cloud/unpair', {'recovery_passphrase': PASSPHRASE})
                    wait_for(lambda: CONTROL not in files(), 'the PC did not lock the phones out')
                    sync_now(p)
                    check.assertEqual(kind(p), 'missing')
                    for n in (5, 6, 7):
                        fav(p, n)
                    counts(p, {'unsent': 3, 'waiting': 0, 'resending': 0}, 'three edits locked out')
                    shows(p, 'PH7 in a phone browser')
                    wait_for(removed, 'the PC did not finish removing the phones', 300)
                    new = svc.mirror_key()
                    check.assertNotEqual(new.fingerprint, key.fingerprint)
                    d.hold = changes_up                                     # the resent edits wait on their way
                    open_link(p, link())                                    # Settings > Backup & phones > Add a phone
                    counts(p, {'resending': 3}, 'the three edits are not being sent again', 120)
                    shows(p, 'PH8 resending after pairing again')
                    d.hold = None
                    d.release()
                    all_in(p, 'the PC did not take in the edits sent again')
                    shows(p, 'PH4 in sync, all sent')

                    # ── 6. the PC stops renewing: the phone's clock passes the record's hour ─────────────────────────────
                    renewed = new.name(sync_license.LOGICAL)
                    stop_renewals(renewed)
                    p.clock.set_system_time(datetime.fromtimestamp(svc._grant[1] / 1000 + 300, timezone.utc))
                    sync_now(p)
                    check.assertEqual(kind(p), 'expired')
                    shows(p, 'PH6 in a phone browser')
                    renew(renewed)
                    ctx.close()

                    # ── 7. three more phones: another Google account, a browser without Ed25519, a key the PC moved on from
                    ctx, p, d = phone()
                    d.account = OTHER_ACCOUNT                               # Google's account chooser: the other account
                    open_link(p, link())
                    round_trip(p, lambda: key_on(p, 'Connect'))
                    shows(p, 'signed in to another account')
                    ctx.close()
                    ctx, p, d = phone(init=NO_ED25519)
                    open_link(p, link())
                    round_trip(p, lambda: key_on(p, 'Connect'))
                    check.assertEqual(kind(p), 'webview')
                    shows(p, 'this browser too old')
                    ctx.close()
                    # a phone paired before the PC's key changed, its access record signed by the PC as it was then
                    older = mirror.MirrorKey.generate()
                    put(older.name(sync_license.LOGICAL), older.seal(sync_license.LOGICAL,
                                                                     sync_license.record(older, sync_license.signer(svc.control_key_path))))
                    stale = {**payload(link()), 'k': older.text(), 'f': older.fingerprint}
                    ctx, p, d = phone()
                    open_link(p, encode(stale))
                    round_trip(p, lambda: key_on(p, 'Connect'))
                    check.assertEqual(kind(p), '')
                    shows(p, 'pairing out of date in a phone browser')
                    ctx.close()

                    # ── 8. phones without a PC: the Android app makes one at its first start (plans/08-phone-solo.md)
                    # and signs in with Google's Android sign-in, which a browser does not have: the check leaves the
                    # pairing, the account and the token where the app's would be ──────────────────────────────────────
                    ctx, p, d = phone(solo_base, solo_seed(signed_in=False, token=False))
                    p.goto(page_url + '#/more')
                    settle(p)
                    shows(p, 'solo: only on this phone')
                    extra(p, '#/recover', 'recover-solo-local', 'Recover a library… on a phone without a PC, not backed up')
                    ctx.close()
                    ctx, p, d = phone(solo_base, solo_seed(signed_in=True, token=False))
                    p.goto(page_url + '#/more')
                    settle(p)
                    shows(p, 'solo: Google asks to sign in again')
                    ctx.close()
                    ctx, p, d = phone(solo_base, solo_seed(signed_in=True, token=True))
                    p.goto(page_url + '#/more')
                    settle(p)
                    shows(p, 'solo: no recovery yet')
                    key_on(p, 'Set up recovery')
                    recovery = p.locator('#m-recovery')
                    recovery.get_by_role('button', name='Generate passphrase', exact=True).click()
                    recovery.get_by_role('button', name='Save passphrase', exact=True).click()
                    expect(recovery.locator('.m-status b')).to_have_text(re.compile('^Passphrase set '), timeout=60000)
                    shows(p, 'solo: passphrase set, no recovery file')
                    p.evaluate("location.hash = '#/backup'")
                    open_group(p, 'Recovery')                      # shows() left the page: the group is closed again
                    with p.expect_download() as download:
                        recovery.get_by_role('button', name='Save recovery file…', exact=True).click()
                    kit = root / 'solo-recovery-file.json'
                    download.value.save_as(kit)
                    shows(p, 'solo: recovery file not checked')
                    with p.expect_file_chooser() as chooser:
                        key_on(p, 'Check recovery file…')
                    chooser.value.set_files(str(kit))
                    expect(recovery.get_by_text('Recovery file checked against your backup.', exact=True)).to_be_visible(timeout=30000)
                    shows(p, 'solo: backed up')
                    extra(p, '#/recover', 'recover-solo-ok', 'Recover a library… on a phone without a PC, backed up')
                    p.evaluate("async () => (await import('/src/mobile/network.svelte.ts')).setSyncPaused(true)")
                    shows(p, 'sync paused by user')
                    p.evaluate("async () => (await import('/src/mobile/network.svelte.ts')).setSyncPaused(false)")
                    settle(p)
                    p.evaluate("""async () => {
                      const {mirrorSource:m} = await import('/src/mobile/state.svelte.ts')
                      const {MirrorKey} = await import('/src/mobile/mirror/crypto.ts')
                      const k=await MirrorKey.fromText(m.pair.k), [name,blob]=await k.sealChange({format:1,device:'fixture',at:1,changes:[]},true)
                      await m.drive.create(name,blob)
                      const b=await import('/src/mobile/mirror/phone-backup.ts')
                      await b.beginBackupTask('delete',await k.soloPrefix());await b.pauseBackupTask(true)
                      ;(await import('/src/mobile/backup.svelte.ts')).backup.task=b.backupTask()
                    }""")
                    shows(p, 'solo: saved backup task')
                    ctx.close()

                    # ── 9. a phone browser with no pairing: More and Backup & phones (which falls back to More) ───────────
                    ctx, p, d = phone(direct=True)
                    p.goto(page_url + '#/backup')
                    settle(p)
                    expect(open_group(p, 'Look').get_by_role('button', name='Night', exact=True)).to_be_visible()   # Settings (its Look group)
                    expect(p.locator('#m-backup-status')).to_have_count(0)
                    expect(p.locator('#m-status')).to_have_count(0)
                    extra(p, '#/more', 'unpaired-more', 'More in a phone browser with no pairing (no status card)')
                    ctx.close()

                try:
                    scenes()
                except BaseException:
                    diag()
                    raise
                check.assertEqual(sorted(STATE_IDS - set(reached)), [], 'every state of the status model reached')
                images = 2 * (sum(len(e['files']) for e in index) + len(pictures))
                check.assertGreaterEqual(images, 100)
                check.assertFalse(sorted(set(unexpected)), 'requests other than the page, Google and the stand-in Drive')
                check.assertFalse(dialogs, dialogs)
                check.assertFalse(errors, errors)
                write_index(images)
                print(json.dumps({'states': len(reached), 'cases': len(index), 'pictures': images, 'index': str(ART / 'index.md')}))
                browser.close()
        finally:
            for gate in held.values():
                gate.set()
            server.should_exit = True
            thread.join(15)
            vite.terminate()
            vite.wait(15)
            vite_log.close()
            for dr in (drive, solo_drive):
                dr.shutdown()
                dr.server_close()
            check.doCleanups()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--fixture':
        fixture(Path(sys.argv[2]).resolve())
    else:
        main()
