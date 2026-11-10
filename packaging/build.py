"""Build the installed app: py packaging/build.py  [--skip-web] [--installer] [--sign]

1. a clean venv in build/venv with the pinned packages of packaging/requirements-build.txt
   (PyInstaller 6.22.3 among them; the one-folder build is checked on Python 3.14),
2. web/dist from an isolated copy of web/ (npm ci + npm run build), unless --skip-web,
3. PyInstaller one-folder: dist/Brainamon/Brainamon.exe. ffmpeg, ffprobe and yt-dlp are NOT bundled: the app finds
   them on PATH or in the folder the user picks in Settings (core/app_paths.py puts that folder first on PATH).
   The build then checks that no cookies file and no .env ended up in dist/: users set their own cookies in
   Settings > Downloads,
4. with --installer: Inno Setup 6 (ISCC.exe, `winget install JRSoftware.InnoSetup --scope user`)
   builds dist/installer/Brainamon-Setup-<version>.exe and its checksum.

Update releases use the free pinned Ed25519 key: packaging/update_keys.py init.
Installer builds emit .update.json; --release requires the key and verifies the final payload.
Optional Windows signing (Authenticode): the certificate is either
  - SIGN_THUMBPRINT: a code-signing certificate in the CurrentUser My store (or a hardware token), or
  - SIGN_PFX (path to a .pfx file outside the repo) + SIGN_PFX_PASSWORD,
plus SIGN_TIMESTAMP_URL (your provider's RFC 3161 endpoint); SIGNTOOL names signtool.exe if it is not on PATH
or in the Windows SDK. Brainamon.exe is signed before the installer is built and the setup exe after it, before
the .sha256 files are written. --sign makes signing required: a release build without a certificate stops instead of
shipping unsigned. Without --sign and without a certificate the build is unsigned and says so.
Never put a PIN, password, .pfx or key in this repo (.gitignore keeps *.pfx out).

Nothing here reads or writes data/. Output folders build/ and dist/ are gitignored.

--contributor builds Brainamon-Contributor with isolated data and disabled official
updates. It ignores owner credentials/signers; optional --contributor-oauth supplies
the contributor's own registration JSON. See docs/development/BUILDING.md.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import build_channel, update_signing
VENV = ROOT / 'build' / 'venv'
PY = VENV / 'Scripts' / 'python.exe'
REQS = ROOT / 'packaging' / 'requirements-build.txt'
SPEC = ROOT / 'packaging' / 'brainamon.spec'
ISS = ROOT / 'packaging' / 'installer.iss'
OAUTH_KEYS = ('BRAINAMON_GOOGLE_CLIENT_ID', 'BRAINAMON_GOOGLE_CLIENT_SECRET', 'BRAINAMON_GOOGLE_WEB_CLIENT_ID')


@contextmanager
def build_environment(contributor):
    if not contributor:
        yield
        return
    previous = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix='brainamon-contributor-build-') as td:
        clean = {k: v for k, v in previous.items() if not any(word in k.upper() for word in
                 ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'SIGN_', 'BRAINAMON_', 'CM_DATA_DIR', 'CM_PORT', 'YTDLP_COOKIES'))}
        clean.update(BRAINAMON_HOME=td, CM_DATA_DIR=str(Path(td) / 'data'),
                     LOCALAPPDATA=td, APPDATA=td, TEMP=td, TMP=td, PYTHON_DOTENV_DISABLED='1')
        os.environ.clear()
        os.environ.update(clean)
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(previous)


def version() -> str:
    return re.search(r"__version__ = '([^']+)'", (ROOT / 'core' / 'version.py').read_text(encoding='utf-8')).group(1)


def iscc() -> Path | None:
    for base in (os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')):
        for sub in ('Programs/Inno Setup 6/ISCC.exe', 'Inno Setup 6/ISCC.exe'):
            p = Path(base) / sub
            if base and p.exists():
                return p
    return None


def signtool() -> str | None:
    found = os.environ.get('SIGNTOOL') or shutil.which('signtool.exe')
    if found:
        return found
    kits = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Windows Kits' / '10' / 'bin'
    hits = sorted(kits.glob('*/x64/signtool.exe'))
    return str(hits[-1]) if hits else None


def cert_args(env=os.environ, required: bool = False) -> list | None:
    """signtool's certificate arguments from the environment, or None (unsigned build).
    `required` (--sign): no certificate is an error instead of an unsigned build."""
    thumb = env.get('SIGN_THUMBPRINT', '').replace(' ', '')
    pfx = env.get('SIGN_PFX', '')
    if thumb and pfx:
        raise SystemExit('Set SIGN_THUMBPRINT or SIGN_PFX, not both.')
    if thumb:
        return ['/s', 'My', '/sha1', thumb]
    if pfx:
        if not Path(pfx).is_file():
            raise SystemExit(f'SIGN_PFX does not name a file: {pfx}')
        return ['/f', pfx] + (['/p', env['SIGN_PFX_PASSWORD']] if env.get('SIGN_PFX_PASSWORD') else [])
    if required:
        raise SystemExit('--sign: no certificate. Set SIGN_THUMBPRINT, or SIGN_PFX and SIGN_PFX_PASSWORD.')
    return None


def sign(path: Path, required: bool = False) -> bool:
    """Authenticode-sign and verify `path` when a certificate is configured; a failure stops the build.
    Returns False for an unsigned build."""
    cert = cert_args(required=required)
    if cert is None:
        print(f'WARNING: {path.name} is NOT signed (no SIGN_THUMBPRINT / SIGN_PFX): SmartScreen will warn on install.',
              file=sys.stderr)
        return False
    stamp, tool = os.environ.get('SIGN_TIMESTAMP_URL'), signtool()
    if not stamp or not tool:
        raise SystemExit('Signing needs SIGN_TIMESTAMP_URL and signtool.exe (PATH, Windows SDK or SIGNTOOL).')
    run([tool, 'sign', *cert, '/fd', 'SHA256', '/tr', stamp, '/td', 'SHA256', '/d', 'Brainamon', path],
        shown=[tool, 'sign', *(['/f', cert[1], '/p', '***'] if '/p' in cert else cert), '...', path])
    run([tool, 'verify', '/pa', path])
    return True


def leaked_secrets(folder: Path) -> list:
    """Files that must never ship: any cookies .txt (Fred's logins) and any .env (API keys)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('brainamon_payload_guard', ROOT / 'packaging' / 'payload_guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return [Path(folder) / name for name in guard.inspect_payload(folder)]


def mcp_smoke(exe: Path) -> str:
    """Brainamon.exe --mcp (Wiskit's Claude Code mode) on an empty data folder: '' when it answers initialize and
    tools/list with only JSON-RPC on stdout and exactly the expected tools, else why not."""
    sys.path.insert(0, str(ROOT))
    from knowledge import claude_code
    msgs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'build', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
    with tempfile.TemporaryDirectory(prefix='mcp-', dir=ROOT / 'build') as td:
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in
               ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'SIGN_', 'BRAINAMON_', 'CM_DATA_DIR', 'YTDLP_COOKIES'))}
        env.update(BRAINAMON_HOME=td, CM_DATA_DIR=str(Path(td) / 'data'), CM_PORT='1',
                   LOCALAPPDATA=td, APPDATA=td, TEMP=td, TMP=td)
        p = subprocess.Popen([exe, '--mcp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, cwd=td)
        timer = threading.Timer(60, p.kill)        # a server that never answers fails the check, not the build
        timer.start()
        try:
            p.stdin.write(''.join(json.dumps(m) + '\n' for m in msgs).encode())
            p.stdin.flush()
            lines = [p.stdout.readline(), p.stdout.readline()]
        finally:
            timer.cancel()
            p.kill()
            p.communicate()
    try:
        replies = [json.loads(line) for line in lines]
    except ValueError:
        return f'stdout is not JSON-RPC: {lines!r:.300}'
    tools = {t['name'] for t in replies[-1].get('result', {}).get('tools', [])}
    expected = set(claude_code.READ_TOOLS + claude_code.ASK_TOOLS) | {'control_job', 'list_topics', 'read_topic'}
    return '' if tools == expected else f'tools differ: missing {sorted(expected - tools)}, extra {sorted(tools - expected)}'


def run(cmd, cwd=ROOT, shown=None):
    print('>', ' '.join(str(c) for c in (shown or cmd)), flush=True)    # shown: the line without a password
    subprocess.run(cmd, cwd=cwd, check=True, shell=(sys.platform == 'win32' and str(cmd[0]) == 'npm'))


def build_web():
    # Editors and dev servers can lock native modules in web/node_modules on Windows.
    (ROOT / 'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-', dir=ROOT / 'build') as td:
        stage = Path(td)
        web = stage / 'web'
        shutil.copytree(ROOT / 'web', web,
                        ignore=shutil.ignore_patterns('node_modules', 'dist', '.git', '.tmp', 'local', '.env', '.env.*', '.npmrc'))
        shutil.copytree(ROOT / 'knowledge' / 'prompts', stage / 'knowledge' / 'prompts')
        (stage / 'core').mkdir()
        shutil.copy2(ROOT / 'core' / 'license.py', stage / 'core' / 'license.py')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'mobile-shell/store/privacy-policy.md',
                     'mobile-shell/store/privacy-policy.fr.md', 'mobile-shell/store/privacy-policy.zh-Hant.md'):
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        run(['npm', 'ci'], cwd=web)
        run(['npm', 'run', 'build'], cwd=web)
        if not (web / 'dist' / 'index.html').is_file():
            raise SystemExit('Frontend build did not produce dist/index.html.')
        target = ROOT / 'web' / 'dist'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(web / 'dist', target)


def write_google_oauth(contributor=False, contributor_oauth=None):
    """Ship only the app OAuth registration; the developer's .env must never ship."""
    sys.path.insert(0, str(ROOT))
    if contributor:
        public = json.loads(Path(contributor_oauth).read_text(encoding='utf-8')) if contributor_oauth else {}
        if not isinstance(public, dict) or public and (set(public) != set(OAUTH_KEYS) or
                any(not isinstance(v, str) for v in public.values()) or not all(public[k].strip() for k in OAUTH_KEYS[:2])):
            raise SystemExit('Contributor OAuth must be {} or contain exactly the three documented app-registration strings, including desktop ID/secret.')
    else:
        from core import config
        values = config.read_env_file()
        public = {key: os.environ.get(key, values.get(key, '')).strip() for key in OAUTH_KEYS}
    if not contributor and (not public[OAUTH_KEYS[0]] or not public[OAUTH_KEYS[1]]):
        raise SystemExit('Cannot package Google sign-in: set BRAINAMON_GOOGLE_CLIENT_ID and '
                         'BRAINAMON_GOOGLE_CLIENT_SECRET in the build environment or project .env.')
    target = ROOT / 'build' / 'google-oauth.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(public), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-web', action='store_true')
    parser.add_argument('--installer', action='store_true')
    parser.add_argument('--release', action='store_true')
    parser.add_argument('--sign', action='store_true')
    parser.add_argument('--contributor', action='store_true')
    parser.add_argument('--contributor-oauth', type=Path, help='explicit own-project registration JSON; no .env fallback')
    args = parser.parse_args()
    if args.contributor and (args.release or args.sign):
        parser.error('--contributor cannot be combined with --release or --sign')
    if args.contributor_oauth and not args.contributor:
        parser.error('--contributor-oauth requires --contributor')
    # Resolve the compiler before isolating the runtime home (Inno may be user-installed).
    compiler = iscc() if args.installer else None
    with build_environment(args.contributor):
        return build(args, compiler)


def build(args, compiler):
    release, required, contributor = args.release, args.sign, args.contributor
    if release and (not args.installer or not update_signing.PUBLIC_KEY):
        raise SystemExit('--release requires --installer and a configured update key. Run packaging/update_keys.py init.')
    if not contributor and update_signing.PUBLIC_KEY and args.installer:
        run([sys.executable, ROOT / 'packaging' / 'update_keys.py', 'check'])
    if not contributor:
        cert_args(required=required)          # a missing certificate stops --sign before the long build
    write_google_oauth(contributor, args.contributor_oauth)
    (ROOT / 'build' / build_channel.FILENAME).write_text(
        json.dumps({'channel': 'contributor' if contributor else 'official'}), encoding='utf-8')
    if not PY.exists():
        run([sys.executable, '-m', 'venv', VENV])
    run([PY, '-m', 'pip', 'install', '-q', '-r', REQS])
    if not args.skip_web:
        build_web()
    if not (ROOT / 'web' / 'dist' / 'index.html').exists():
        print('web/dist/index.html is missing: build the front end first.', file=sys.stderr)
        return 1
    folder = 'Brainamon-Contributor' if contributor else 'Brainamon'
    expanded = ROOT / 'dist' / folder
    if expanded.is_symlink() or expanded.is_junction() or expanded.resolve().parent != ROOT.resolve() / 'dist':
        raise SystemExit('Build output must stay inside this checkout\'s dist directory.')
    shutil.rmtree(expanded, ignore_errors=True)
    run([PY, '-m', 'PyInstaller', '--noconfirm', '--clean',
         '--distpath', ROOT / 'dist', '--workpath', ROOT / 'build' / 'pyi', SPEC])
    leaks = leaked_secrets(expanded)
    if leaks:
        print('Refusing to ship cookies or keys:\n  ' + '\n  '.join(map(str, leaks)), file=sys.stderr)
        return 1
    exe = expanded / f'{folder}.exe'
    why = mcp_smoke(exe)
    if why:
        print(f'Brainamon.exe --mcp failed its check: {why}', file=sys.stderr)
        return 1
    print('Brainamon.exe --mcp answered with the expected tools.')
    if not contributor:
        sign(exe, required)
    print(f'Built: {exe}')
    if args.installer:
        if compiler is None:
            print('ISCC.exe not found: winget install JRSoftware.InnoSetup --scope user', file=sys.stderr)
            return 1
        v = version()
        run([compiler, f'/DAppVersion={v}', *(['/DContributor=1'] if contributor else []), ISS])
        setup = ROOT / 'dist' / 'installer' / f'{folder}-Setup-{v}.exe'
        if not contributor:
            sign(setup, required)
        digest = hashlib.sha256(setup.read_bytes()).hexdigest()
        setup.with_name(setup.name + '.sha256').write_text(f'{digest}  {setup.name}\n', encoding='ascii')
        if not contributor and update_signing.PUBLIC_KEY:
            run([sys.executable, ROOT / 'packaging' / 'update_keys.py', 'sign', setup])
        print(f'Installer: {setup}  sha256 {digest}')
    if release or contributor and args.installer:
        run([sys.executable, ROOT / 'packaging' / 'release_check.py', setup, '--expanded',
             expanded, *(['--contributor'] if contributor else [])])
        print('Artifact gates passed. Console, clean install/update and device release evidence is still required.')
    print('Development artifact only; production release eligibility has not been established.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
