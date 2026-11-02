"""Build the signed Android release on this PC: py mobile-shell/scripts/release.py  [--create-key] [--skip-web]

The upload key stays on this PC (never in the repo, never on GitHub). Default place:
%LOCALAPPDATA%\\Brainamon-Android\\brainamon-upload.jks, or BRAINAMON_UPLOAD_KEYSTORE.

  --create-key  makes that key once with keytool (it asks for the passwords). BACK IT UP with its
                passwords: Play can reset a lost upload key, but only after a slow request.

Steps: web/dist (npm run build, unless --skip-web), the phone page into the app (npm run sync),
gradlew bundleRelease assembleRelease, the private-file gate on both outputs, apksigner on the APK.
Version name = core/version.py; version code = major*1000000 + minor*1000 + patch (0.2.4 -> 2004),
so it grows with every desktop release; BRAINAMON_VERSION_CODE overrides it. Passwords come from
BRAINAMON_UPLOAD_STORE_PASSWORD / BRAINAMON_UPLOAD_KEY_PASSWORD or are asked for, never saved.

Output: dist/android/Brainamon-<version>.aab (upload to Play) and Brainamon-<version>.apk (your own
device tests only: the app is distributed through Play only), each with a .sha256. Guide: docs/RELEASING.md. Nothing here reads or writes data/.
"""
import getpass
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / 'mobile-shell'
ANDROID = SHELL / 'android'
OUT = ROOT / 'dist' / 'android'
KEY = Path(os.environ.get('BRAINAMON_UPLOAD_KEYSTORE') or Path(os.environ['LOCALAPPDATA']) / 'Brainamon-Android' / 'brainamon-upload.jks')
ALIAS = os.environ.get('BRAINAMON_UPLOAD_KEY_ALIAS') or 'upload'


def run(cmd, cwd, env=None):
    print('>', ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=True, shell=os.name == 'nt' and cmd[0] in ('npm',))


def sdk() -> Path:
    for v in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'), Path(os.environ.get('LOCALAPPDATA', '')) / 'Android' / 'Sdk'):
        if v and (Path(v) / 'platforms').is_dir():
            return Path(v)
    raise SystemExit('No Android SDK found: install Android Studio or set ANDROID_HOME.')


def version() -> tuple[str, int]:
    name = re.search(r"__version__ = '([^']+)'", (ROOT / 'core' / 'version.py').read_text(encoding='utf-8')).group(1)
    major, minor, patch = (int(x) for x in name.split('.'))
    return name, int(os.environ.get('BRAINAMON_VERSION_CODE') or major * 1_000_000 + minor * 1_000 + patch)


def create_key():
    if KEY.exists():
        raise SystemExit(f'{KEY} exists already: keep it, every update must be signed with it.')
    KEY.parent.mkdir(parents=True, exist_ok=True)
    run(['keytool', '-genkeypair', '-v', '-keystore', KEY, '-alias', ALIAS, '-keyalg', 'RSA', '-keysize', '4096',
         '-validity', '10000', '-dname', 'CN=Frederic TOMAS, O=Brainamon'], ROOT)
    print(f'\nUpload key made: {KEY}\nBack up this file and its passwords now (not in the repo, not in Drive with the library).')


def sha256(p: Path) -> None:
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    p.with_name(p.name + '.sha256').write_text(f'{h}  {p.name}\n', encoding='ascii')


def main():
    if '--create-key' in sys.argv:
        return create_key()
    if not KEY.is_file():
        raise SystemExit(f'No upload key at {KEY}. Make it once: py mobile-shell/scripts/release.py --create-key')
    name, code = version()
    home = sdk()
    env = dict(os.environ, ANDROID_HOME=str(home), BRAINAMON_UPLOAD_KEYSTORE=str(KEY), BRAINAMON_UPLOAD_KEY_ALIAS=ALIAS,
               BRAINAMON_VERSION_NAME=name, BRAINAMON_VERSION_CODE=str(code))
    env['BRAINAMON_UPLOAD_STORE_PASSWORD'] = env.get('BRAINAMON_UPLOAD_STORE_PASSWORD') or getpass.getpass(
        'Password of the upload key (the one chosen with --create-key): ')
    env['BRAINAMON_UPLOAD_KEY_PASSWORD'] = env.get('BRAINAMON_UPLOAD_KEY_PASSWORD') or env['BRAINAMON_UPLOAD_STORE_PASSWORD']
    # check the password before the long build (keytool reads it from the environment, not the command line)
    if subprocess.run(['keytool', '-list', '-keystore', str(KEY), '-alias', ALIAS, '-storepass:env', 'BRAINAMON_UPLOAD_STORE_PASSWORD'],
                      env=env, capture_output=True).returncode:
        raise SystemExit(f'That password does not open {KEY} (or it has no "{ALIAS}" key). Run again with the '
                         'password typed at --create-key; the build has not started.')
    print(f'Brainamon Android {name} (version code {code})')

    if '--skip-web' not in sys.argv:
        run(['npm', 'run', 'build'], ROOT / 'web')
    if not (SHELL / 'node_modules').is_dir():
        run(['npm', 'ci'], SHELL)
    run(['npm', 'run', 'sync'], SHELL)
    run([ANDROID / ('gradlew.bat' if os.name == 'nt' else 'gradlew'), 'bundleRelease', 'assembleRelease', '--no-daemon'], ANDROID, env)

    aab = ANDROID / 'app' / 'build' / 'outputs' / 'bundle' / 'release' / 'app-release.aab'
    apk = ANDROID / 'app' / 'build' / 'outputs' / 'apk' / 'release' / 'app-release.apk'
    for p in (aab, apk):
        run([sys.executable, ROOT / 'packaging' / 'payload_guard.py', p], ROOT)
    tools = sorted((home / 'build-tools').iterdir())[-1]
    signer = tools / ('apksigner.bat' if os.name == 'nt' else 'apksigner')
    run([signer, 'verify', '--print-certs', apk], ROOT)

    OUT.mkdir(parents=True, exist_ok=True)
    for p, ext in ((aab, 'aab'), (apk, 'apk')):
        dest = OUT / f'Brainamon-{name}.{ext}'
        shutil.copy2(p, dest)
        sha256(dest)
        print('Built', dest)
    print('\nPlay: upload the .aab (Play Console > Test and release > Internal testing first). The .apk is for'
          '\nyour own test phone only (adb install -r). docs/RELEASING.md has the full routine.')


if __name__ == '__main__':
    main()
