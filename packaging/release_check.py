"""Release eligibility is separate from building a local development artifact.

Read-only. Windows requires the pinned update signature; APKs require a production signer.
Inno extraction, clean install/update, Console and physical-device evidence remain external.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from payload_guard import inspect_payload
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import build_channel, update_signing


def dependency_versions(versions):
    def numbers(name):
        value = versions.get(name) if isinstance(versions, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
            raise ValueError('Compiled dependency report is missing or malformed: ' + name)
        return tuple(map(int, value.split('.')))
    # Pillow 13 Windows wheels backport the OpenJPEG fix while still reporting 2.5.4.
    if numbers('Pillow') < (13, 0, 0) or numbers('pypdf') < (6, 21, 2) or numbers('OpenJPEG') == (2, 5, 3):
        raise ValueError('The compiled image/PDF dependency gate failed.')
    return versions


def windows_signature(path, expected):
    escaped = str(Path(path).resolve()).replace("'", "''")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; @{{status=$s.Status.ToString();thumbprint=$s.SignerCertificate.Thumbprint}} | ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=True, timeout=30)
    signature = json.loads(result.stdout)
    if signature.get('status') != 'Valid' or not expected or signature.get('thumbprint', '').upper() != expected.replace(' ', '').upper():
        raise ValueError('Production signature identity is missing or mismatched: ' + Path(path).name)
    return signature


def android_signature(path, expected):
    signer, analyzer = shutil.which('apksigner'), shutil.which('apkanalyzer')
    if not signer or not analyzer:
        raise ValueError('APK signer/manifest inspection tools unavailable; release remains blocked.')
    signed = subprocess.run([signer, 'verify', '--verbose', '--print-certs', str(path)], capture_output=True, text=True, check=True, timeout=30)
    fingerprints = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)$', signed.stdout, re.M)
    want = expected.replace(':', '').lower()
    if 'Android Debug' in signed.stdout or not re.fullmatch(r'[0-9a-f]{64}', want) or [f.lower() for f in fingerprints] != [want]:
        raise ValueError('APK production signer identity mismatch.')
    command = [analyzer, 'manifest', 'debuggable', str(path)]
    if os.name == 'nt' and analyzer.lower().endswith(('.bat', '.cmd')):
        command = ['cmd', '/q', '/c', *command]
    debug = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    if debug.stdout.strip() != 'false':
        raise ValueError('Debuggable APK is ineligible for release.')


def windows_payload(installer, expanded, expected=None, contributor=False):
    """Inspect the actual installer with approved existing tooling; never infer equivalence."""
    tool = shutil.which('innounp') or shutil.which('innoextract')
    if not tool:
        raise ValueError('Inno extraction tool unavailable; final installer payload gate remains open.')
    channel = build_channel.read(expanded / '_internal')
    wanted = 'contributor' if contributor else 'official'
    if channel != wanted:
        raise ValueError('Expanded build has no matching explicit build-channel marker.')
    exe = build_channel.HOME_NAMES[channel] + '.exe'
    if contributor:
        if expected or installer.with_name(installer.name + '.update.json').exists():
            raise ValueError('Contributor artifacts cannot carry official signing/update metadata.')
    else:
        update_signing.verify_file(installer)
    if expected:
        windows_signature(installer, expected)
        windows_signature(expanded / exe, expected)
    with tempfile.TemporaryDirectory(prefix='brainamon-release-') as folder:
        root = Path(folder)
        command = ([tool, '-x', '-b', '-q', f'-d{root}', str(installer)]
                   if Path(tool).stem.lower() == 'innounp' else
                   [tool, '--silent', '--output-dir', str(root), str(installer)])
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        leaks = inspect_payload(root)
        if leaks:
            raise ValueError(f'Private installer files ({len(leaks)}): ' + ', '.join(leaks))
        app = root / 'app'
        if not app.is_dir():
            app = root / '{app}'
        def inventory(directory):
            return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in directory.rglob('*') if p.is_file()}
        if not app.is_dir() or inventory(app) != inventory(expanded):
            raise ValueError('Final installer payload does not match the inspected expanded build.')
        # Probe only the verified application, with a disposable home and no inherited credentials.
        home = root / 'probe-home'
        home.mkdir()
        import os
        env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL', 'SIGN_PFX', 'BRAINAMON_', 'CM_DATA_DIR'))}
        env.update(BRAINAMON_HOME=str(home), CM_DATA_DIR=str(home / 'data'), LOCALAPPDATA=str(home), APPDATA=str(home), TEMP=str(home), TMP=str(home))
        report = subprocess.run([str(expanded / exe), '--dependency-report'], env=env,
                                capture_output=True, text=True, check=True, timeout=30)
        # The windowless launcher writes its dependency report to the isolated home log.
        output = report.stdout.strip() or (home / 'error_log.txt').read_text(encoding='utf-8')
        versions = next(json.loads(line) for line in output.splitlines() if line.startswith('{"Pillow"'))
        return dependency_versions(versions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifact', type=Path)
    parser.add_argument('--signer', help='Required APK signer, or optional Windows Authenticode fingerprint')
    parser.add_argument('--expanded', type=Path, help='Expanded Windows build to compare with actual extracted installer')
    parser.add_argument('--contributor', action='store_true', help='validate separate Windows contributor artifact, without official trust')
    args = parser.parse_args()
    leaks = inspect_payload(args.artifact if args.artifact.suffix.lower() == '.apk' else args.expanded or args.artifact)
    if leaks:
        raise ValueError(f'Private payload files ({len(leaks)}): ' + ', '.join(leaks))
    if args.artifact.suffix.lower() == '.apk':
        if args.contributor:
            raise ValueError('Contributor APKs use payload_guard; this command validates production APK eligibility.')
        if not args.signer:
            raise ValueError('APK release validation requires --signer.')
        android_signature(args.artifact, args.signer)
    else:
        if not args.expanded:
            raise ValueError('Expanded build plus final installer extraction/equivalence evidence is required.')
        windows_payload(args.artifact, args.expanded, args.signer, args.contributor)
    with args.artifact.open('rb') as artifact:
        digest = hashlib.file_digest(artifact, 'sha256').hexdigest()
    print(json.dumps({'artifact': args.artifact.name, 'sha256': digest, 'signer': args.signer}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
