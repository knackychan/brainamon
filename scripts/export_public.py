"""Export approved committed files, never private Git history. Dry-run by default.

The manifest and receipts are private review records; see docs/development/EXPORT.md.
This tool neither grants publication clearance nor pushes, tags, builds or signs.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
import sys
from pathlib import Path, PurePosixPath


PUBLIC_URL = 'https://github.com/knackychan/brainamon.git'
MODES = {'100644', '100755'}
CARDS = {'design/card-designs/cards.css', 'design/card-designs/engine.js',
         'design/card-designs/full-art-v2/fa2.css', 'design/card-designs/full-art-v2/fa2.js'}
PRIVATE_ROOTS = {'.git', '.claude', '.commandcode', '.superpowers', '.worktrees',
                 '_old', 'archive', 'assets', 'data', 'local', 'certificate', 'projects',
                 'build', 'dist', 'graphify-out'}
PRIVATE_NAMES = re.compile(r'(?i)(^\.env($|\.)|cookies|^id_(rsa|ed25519)$|'
                           r'\.(key|pem|pfx|p12|dpapi|jks|keystore|db|sqlite3?)($|\.)|'
                           r'^(credentials|token|google-services|google-oauth)\.json$|'
                           r'^(secret|secrets|service-account|firebase-service-account)(\.|-))')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, *args):
    # Git's inherited worktree/index/alternate settings must not cross repositories.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '--no-replace-objects', '-C', str(repo), *args], env=env,
                            capture_output=True, check=False)
    if result.returncode:
        raise ValueError('Git validation failed: ' + args[0])
    return result.stdout


def checked_path(value, source_input=False):
    if not isinstance(value, str) or not value or unicodedata.normalize('NFC', value) != value:
        raise ValueError('Invalid manifest path')
    parts = value.split('/')
    if any(not p or p in ('.', '..') or p.endswith((' ', '.')) or
           re.search(r'[\x00-\x1f\x7f\\:<>"|?*]', p) or
           re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', p)
           for p in parts):
        raise ValueError('Unsafe manifest path: ' + value)
    folded = [p.casefold() for p in parts]
    private_roots = PRIVATE_ROOTS - {'projects'} if source_input else PRIVATE_ROOTS
    if (folded[0] in private_roots or
            any(p in {'.git', 'node_modules', '__pycache__', '.venv'} for p in folded) or
            any(PRIVATE_NAMES.search(p) and p != '.env.example' for p in folded)):
        raise ValueError('Private manifest path: ' + value)
    return value


def destination(value):
    value = checked_path(value)
    folded = value.casefold()
    if (folded in ('docs', 'docs/development') or
            folded.startswith('docs/') and not folded.startswith('docs/development/') or
            folded.startswith('design/') and value not in CARDS):
        raise ValueError('Protected website/design path: ' + value)
    return value


def regular_path(root, name):
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError('Symlink/junction in target path: ' + name)
        if path.exists() and path != root / name and not path.is_dir():
            raise ValueError('Non-directory target parent: ' + name)
    if path.exists() and not path.is_file():
        raise ValueError('Nonregular target file: ' + name)
    return path


def read_record(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def committed_inputs(source, revision, entries):
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
        raise ValueError('A full committed source_revision is required')
    if git(source, 'rev-parse', revision + '^{commit}').decode().strip() != revision:
        raise ValueError('Source revision mismatch')
    tree = {}
    for record in git(source, 'ls-tree', '-rz', '--full-tree', revision).split(b'\0'):
        if record:
            meta, name = record.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            tree[name.decode('utf-8')] = (mode, kind, oid)
    outputs = {}
    for row in entries:
        action = row.get('action')
        if action not in ('copy unchanged', 'modify', 'extract', 'generate'):
            raise ValueError('Unknown/unimplemented action')
        records = row.get('source_inputs')
        if not isinstance(records, list):
            raise ValueError('Exact source_inputs required')
        records = list(records)
        primary = row.get('source_path')
        if primary is not None:
            records.append({'path': primary, 'revision': row.get('source_revision'),
                            'blob': row.get('source_blob'), 'sha256': row.get('source_sha256'),
                            'mode': row.get('source_mode')})
        inputs = {}
        for record in records:
            name = checked_path(record['path'], source_input=True)
            if record.get('revision') != revision:
                raise ValueError('Input revision mismatch: ' + name)
            mode, kind, oid = tree.get(name, (None, None, None))
            if mode not in MODES or kind != 'blob':
                raise ValueError('Missing/nonregular committed input: ' + name)
            if record.get('mode') != mode or record.get('blob') != oid:
                raise ValueError('Input mode/blob mismatch: ' + name)
            raw = git(source, 'cat-file', 'blob', oid)
            if record.get('sha256') != digest(raw):
                raise ValueError('Input hash mismatch: ' + name)
            inputs[name] = raw
        if action != 'generate' and primary not in inputs:
            raise ValueError('Primary committed input required')
        raw = inputs.get(primary, b'')
        transform = row.get('transform')
        if action == 'copy unchanged':
            if transform is not None:
                raise ValueError('Copy cannot contain a transform')
        elif action == 'modify':
            if not isinstance(transform, dict) or set(transform) != {'replacements'} or not transform['replacements']:
                raise ValueError('Unimplemented modify transform')
            for patch in transform['replacements']:
                old, new = patch['old'].encode(), patch['new'].encode()
                count = patch.get('count')
                if not old or type(count) is not int or count < 1 or raw.count(old) != count:
                    raise ValueError('Replacement precondition failed: ' + primary)
                raw = raw.replace(old, new)
        elif action == 'extract':
            if not isinstance(transform, dict) or set(transform) != {'start', 'end'}:
                raise ValueError('Unimplemented extract transform')
            start, end = transform['start'].encode(), transform['end'].encode()
            if not start or not end or raw.count(start) != 1 or raw.count(end) != 1:
                raise ValueError('Extraction markers must be unique')
            begin, finish = raw.index(start) + len(start), raw.index(end)
            if begin > finish:
                raise ValueError('Extraction markers out of order')
            raw = raw[begin:finish].strip() + b'\n'
        else:
            if not isinstance(transform, dict) or set(transform) != {'parts'}:
                raise ValueError('Unimplemented generate transform')
            chunks = []
            for part in transform['parts']:
                if set(part) == {'text'}:
                    chunks.append(part['text'].encode())
                elif set(part) == {'input'} and part['input'] in inputs:
                    chunks.append(inputs[part['input']])
                else:
                    raise ValueError('Unknown generation input')
            raw = b''.join(chunks)
        mode = row.get('output_mode')
        if mode not in MODES or row.get('output_sha256') != digest(raw):
            raise ValueError('Output hash/mode mismatch: ' + row['public_destination'])
        outputs[row['public_destination']] = (raw, mode)
    return outputs


def repository_boundary(source, target, public_url):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and target must be independent directories')
    roots, commons = [], []
    for repo in (source, target):
        roots.append(Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve())
        common = git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()
        commons.append(Path(common).resolve())
    if roots != [source, target] or commons[0] == commons[1] or commons[1] != target / '.git':
        raise ValueError('Target must be an independent clone, not a worktree')
    if (commons[1] / 'objects/info/alternates').exists():
        raise ValueError('Target uses a shared object store')
    if (commons[1] / 'objects').is_symlink() or (commons[1] / 'objects').is_junction():
        raise ValueError('Target uses a linked object store')
    remotes = git(target, 'remote').decode().split()
    if remotes != ['origin'] or git(target, 'remote', 'get-url', '--all', 'origin').decode().splitlines() != [public_url]:
        raise ValueError('Target origin must match the selected public repository')
    if git(target, 'remote', 'get-url', '--push', '--all', 'origin').decode().splitlines() != [public_url]:
        raise ValueError('Target push URL must match its public origin')
    source_commits = set(git(source, 'rev-list', '--all').splitlines())
    if source_commits.intersection(git(target, 'rev-list', '--all').splitlines()):
        raise ValueError('Private source history is reachable in the target')
    return source, target


def prepare(source, target, manifest, previous=None, public_url=PUBLIC_URL, verification=False):
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported manifest schema')
    rows = manifest.get('entries')
    approved = manifest.get('approved_export')
    if not isinstance(rows, list) or not isinstance(approved, list) or not approved:
        raise ValueError('No approved export; candidate manifests cannot export files')
    names = [destination(row['public_destination']) for row in rows]
    deletions = [destination(name) for name in manifest.get('deletions', [])]
    all_names = names + deletions
    if len(set(n.casefold() for n in all_names)) != len(all_names):
        raise ValueError('Duplicate/case-folding destination')
    if len(approved) != len(all_names) or set(approved) != set(all_names):
        raise ValueError('Every manifest destination must be explicitly approved')
    # A file and a directory cannot share a case-insensitive destination.
    folded = {n.casefold() for n in all_names}
    for name in all_names:
        if any(p.as_posix().casefold() in folded for p in PurePosixPath(name).parents if p.as_posix() != '.'):
            raise ValueError('File/directory destination collision')
    gates = manifest.get('gate_results', {})
    required = ('O1', 'S1') if verification else ('O1', 'S1', 'C1')
    if not all(gates.get(g) is True for g in required):
        raise ValueError('Source ownership/privacy/verification gates are not cleared')
    for row in rows:
        if row.get('status') != 'approved' or not all(
                gates.get(g) is True for g in row.get('gate_ids', []) if not (verification and g == 'C1')):
            raise ValueError('Unapproved row/gate: ' + row['public_destination'])
    source, target = repository_boundary(source, target, public_url)
    head = git(target, 'rev-parse', 'HEAD').decode().strip()
    owned = {}
    if previous is not None:
        if previous.get('schema_version') != 1 or previous.get('public_url') != public_url:
            raise ValueError('Receipt identity mismatch')
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', previous['public_base']):
            raise ValueError('Receipt requires a full public commit ID')
        git(target, 'merge-base', '--is-ancestor', previous['public_base'], head)
        owned = previous['owned']
        for name, info in owned.items():
            destination(name)
            if not (info['sha256'] is None and info['mode'] is None) and (
                    not isinstance(info['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', info['sha256']) or info['mode'] not in MODES):
                raise ValueError('Invalid receipt hash/mode')
    if not set(deletions) <= owned.keys() or set(owned) - set(names) != set(deletions):
        raise ValueError('Deletions require explicit previously owned paths')
    outputs = committed_inputs(source, manifest['source_revision'], rows)
    tracked_names = git(target, 'ls-files', '-z').decode('utf-8').split('\0')
    for existing in filter(None, tracked_names):
        for name in all_names:
            if existing != name and (existing.casefold() == name.casefold() or
                    existing.casefold().startswith(name.casefold() + '/') or
                    name.casefold().startswith(existing.casefold() + '/')):
                raise ValueError('Existing public path collision: ' + name)
    changes, pending, next_owned = [], [], {}
    for name in sorted(all_names):
        path = regular_path(target, name)
        current = digest(path.read_bytes()) if path.exists() else None
        old = owned.get(name)
        new = outputs.get(name)
        new_hash = digest(new[0]) if new is not None else None
        if old is None and current is not None:
            row = rows[names.index(name)]
            if name != 'README.md' or row.get('public_base_sha256') != current:
                raise ValueError('Unowned public file collision: ' + name)
        elif old is not None and current not in (old['sha256'], new_hash):
            raise ValueError('Public contribution needs private integration: ' + name)
        if new is not None:
            next_owned[name] = {'sha256': new_hash, 'mode': new[1]}
        else:
            next_owned[name] = {'sha256': None, 'mode': None}
        # Index modes are authoritative on Windows, where chmod has no executable bit.
        tracked = git(target, 'ls-files', '--stage', '-z', '--', name).split(b'\0')[0]
        mode = tracked.split(b' ', 1)[0].decode() if tracked else None
        if current != new_hash or new is not None and mode not in (None, new[1]):
            operation = 'delete' if new is None else 'add' if current is None else 'change'
            changes.append({'path': name, 'operation': operation, 'sha256': new_hash,
                            'mode': new[1] if new is not None else None})
            pending.append((name, new))
    # Refuse unrelated local work, including staged changes and untracked files.
    for record in git(target, 'status', '--porcelain=v1', '-z', '--untracked-files=all').split(b'\0'):
        if not record:
            continue
        state, name = record[:2], record[3:].decode('utf-8')
        if state[:1] in (b'R', b'C', b'U') or name not in owned:
            raise ValueError('Target has unrelated/staged work')
        path = regular_path(target, name)
        actual = digest(path.read_bytes()) if path.exists() else None
        if actual != owned[name]['sha256']:
            raise ValueError('Target has unrecorded local edits: ' + name)
        if state[:1] != b' ' and state != b'??':
            staged = git(target, 'ls-files', '--stage', '-z', '--', name).split(b'\0')[0]
            if staged:
                mode, oid, stage = staged.split(b'\t', 1)[0].decode().split()
                if stage != '0' or mode != owned[name]['mode'] or digest(git(target, 'cat-file', 'blob', oid)) != owned[name]['sha256']:
                    raise ValueError('Target has unrecorded staged changes: ' + name)
            elif owned[name]['sha256'] is not None:
                raise ValueError('Target has an unrecorded staged deletion: ' + name)
    receipt = {'schema_version': 1, 'source_revision': manifest['source_revision'],
               'purpose': 'verification' if verification else 'release-preparation',
               'public_url': public_url, 'public_base': head, 'owned': next_owned}
    return changes, pending, receipt


def write_atomic(path, raw, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    try:
        if mode:
            temporary.chmod(0o755 if mode == '100755' else 0o644)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_files(target, pending):
    for name, output in pending:
        path = regular_path(target, name)
        if output is None:
            path.unlink()
        else:
            write_atomic(path, output[0], output[1])
            tracked = git(target, 'ls-files', '--stage', '-z', '--', name)
            # Windows has no executable bit: record it in Git for the Gradle wrapper.
            if output[1] == '100755' or tracked.startswith(b'100755 '):
                git(target, 'update-index', '--add', '--chmod=' + ('+x' if output[1] == '100755' else '-x'), '--', name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--previous-receipt', type=Path)
    parser.add_argument('--receipt-output', type=Path)
    parser.add_argument('--public-url', default=PUBLIC_URL)
    parser.add_argument('--apply', action='store_true', help='write approved files and a private receipt')
    parser.add_argument('--verification', action='store_true',
                        help='materialize reviewed inputs for C1 testing; does not assert C1 clearance')
    args = parser.parse_args(argv)
    try:
        if args.apply and args.receipt_output is None:
            raise ValueError('--apply requires --receipt-output outside the public clone')
        if args.receipt_output is not None:
            receipt_path = args.receipt_output.resolve()
            target = args.target.resolve()
            if receipt_path == target or target in receipt_path.parents or receipt_path in (args.manifest.resolve(),):
                raise ValueError('Receipt must be private and separate from the manifest')
        manifest = read_record(args.manifest)
        previous = read_record(args.previous_receipt) if args.previous_receipt else None
        changes, pending, receipt = prepare(args.source, args.target, manifest, previous, args.public_url,
                                            verification=args.verification)
        if args.apply:
            apply_files(args.target.resolve(), pending)
            write_atomic(args.receipt_output, (json.dumps(receipt, indent=2) + '\n').encode())
        print(json.dumps({'applied': args.apply, 'purpose': receipt['purpose'], 'changes': changes}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        # Never echo Git stderr, blob contents or secret values from a malformed manifest.
        print('Export refused: manifest, repository boundary or contribution validation failed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
