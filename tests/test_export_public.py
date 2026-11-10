"""Synthetic, independent Git repositories exercise the publication boundary."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('export_public', ROOT / 'scripts/export_public.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='brainamon-export-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'private'
        self.target = self.root / 'public'
        self.public_url = 'https://example.invalid/public.git'
        for folder, text in ((self.source, 'private README\n'), (self.target, 'public README\n')):
            folder.mkdir()
            self.git(folder, 'init', '-q', '-b', 'main')
            (folder / 'README.md').write_text(text)
        (self.source / 'module.py').write_bytes(b"MESSAGE = 'hello'\n")
        (self.source / 'drawing.html').write_bytes(b'private header\nBEGIN\nconst shape = 1;\nEND\nprivate footer')
        (self.source / 'gradlew').write_bytes(b'#!/bin/sh\nexit 0\n')
        (self.target / 'docs/img').mkdir(parents=True)
        (self.target / 'docs/index.html').write_bytes(b'unchanged website')
        (self.target / 'docs/img/mark.png').write_bytes(b'unchanged mark')
        for folder in (self.source, self.target):
            self.commit(folder, 'baseline')
        self.git(self.source, 'update-index', '--chmod=+x', 'gradlew')
        self.git(self.source, 'commit', '-qm', 'executable wrapper')
        self.git(self.target, 'remote', 'add', 'origin', self.public_url)
        self.rev = self.git(self.source, 'rev-parse', 'HEAD').strip()
        self.manifest = {'schema_version': 1, 'source_revision': self.rev,
                         'entries': [], 'approved_export': [],
                         'gate_results': dict.fromkeys(('O1', 'S1', 'C1'), True)}
        self.add_row('module.py')

    def git(self, folder, *args):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run(['git', '-C', str(folder), '-c', 'user.name=Synthetic Author',
                                 '-c', 'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false',
                                 '-c', 'core.autocrlf=false', *args],
                                env=env, capture_output=True, text=True, check=True)
        return result.stdout

    def commit(self, folder, message):
        self.git(folder, 'add', '-A')
        self.git(folder, 'commit', '-qm', message)

    def add_row(self, source, dest=None, **kw):
        raw = export.git(self.source, 'show', self.rev + ':' + source)
        meta = self.git(self.source, 'ls-tree', self.rev, '--', source).split()
        record = {'path': source, 'revision': self.rev, 'mode': meta[0],
                  'blob': meta[2], 'sha256': export.digest(raw)}
        row = {'source_path': source, 'source_revision': self.rev, 'source_mode': record['mode'],
               'source_blob': record['blob'], 'source_sha256': record['sha256'],
               'source_inputs': [record], 'public_destination': dest or source,
               'action': 'copy unchanged', 'status': 'approved', 'gate_ids': ['O1', 'S1', 'C1'],
               'output_sha256': export.digest(raw), 'output_mode': record['mode']}
        row.update(kw)
        self.manifest['entries'].append(row)
        self.manifest['approved_export'].append(row['public_destination'])
        return row

    def prepare(self, previous=None):
        return export.prepare(self.source, self.target, self.manifest, previous, self.public_url)

    def apply(self, previous=None):
        changes, pending, receipt = self.prepare(previous)
        export.apply_files(self.target, pending)
        return changes, receipt

    def test_dry_run_ignores_dirty_source_and_never_copies_history_or_unknown_files(self):
        (self.source / 'module.py').write_bytes(b'private unfinished edits')
        (self.source / 'unlisted.py').write_bytes(b'not approved')
        public_commits = self.git(self.target, 'rev-list', '--all')
        changes, pending, _ = self.prepare()
        self.assertEqual([c['path'] for c in changes], ['module.py'])
        self.assertEqual(pending[0][1][0], b"MESSAGE = 'hello'\n")
        self.assertFalse((self.target / 'module.py').exists())
        self.assertEqual(self.git(self.target, 'rev-list', '--all'), public_commits)

    def test_apply_is_repeatable_and_preserves_website(self):
        changes, receipt = self.apply()
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.prepare(receipt)[0], [])
        self.assertEqual((self.target / 'docs/index.html').read_bytes(), b'unchanged website')
        self.assertFalse((self.target / 'unlisted.py').exists())
        self.commit(self.target, 'public source')
        self.assertEqual(self.prepare(receipt)[0], [])

    def test_empty_candidate_or_missing_approvals_fail_closed(self):
        for mutate in (lambda m: m.update(approved_export=[]),
                       lambda m: m['entries'][0].update(status='candidate'),
                       lambda m: m['gate_results'].update(O1=False),
                       lambda m: m['entries'][0].update(gate_ids=['W1'])):
            with self.subTest(mutate=mutate):
                baseline = copy.deepcopy(self.manifest)
                mutate(self.manifest)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.manifest = baseline

    def test_verification_stage_never_claims_c1_or_bypasses_ownership_and_privacy(self):
        self.manifest['gate_results']['C1'] = False
        with self.assertRaises(ValueError):
            self.prepare()
        _, pending, receipt = export.prepare(self.source, self.target, self.manifest,
                                            public_url=self.public_url, verification=True)
        self.assertEqual(receipt['purpose'], 'verification')
        export.apply_files(self.target, pending)
        with self.assertRaises(ValueError):
            self.prepare(receipt)
        self.manifest['gate_results']['C1'] = True
        self.assertEqual(self.prepare(receipt)[0], [])
        for gate in ('O1', 'S1'):
            self.manifest['gate_results'][gate] = False
            with self.assertRaises(ValueError):
                export.prepare(self.source, self.target, self.manifest, receipt,
                               self.public_url, verification=True)
            self.manifest['gate_results'][gate] = True

    def test_unsafe_or_private_paths_rejected(self):
        for name in ('/absolute.py', '../escape.py', 'a/../escape.py', 'C:/escape.py',
                     'a\\escape.py', 'a//b', 'a/./b', 'a/file:stream', 'a/NUL.txt', 'a/CON',
                     'a/trailing.', 'a/trailing ', '.git/config', 'data/content.db',
                     'local/settings.json', 'projects/private.py', 'archive/old.py', '.env', '.env.backup',
                     'mobile-shell/debug.keystore', 'cookies.txt', 'a/private.key',
                     'a/access.key.dpapi', 'node_modules/a.js', 'a\n.py', 'a/e\u0301.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                export.destination(name)
        self.assertEqual(export.destination('.env.example'), '.env.example')
        with self.assertRaises(ValueError):
            export.checked_path('archive/old.py', source_input=True)

    def test_website_and_unowned_collisions_are_rejected_even_for_identical_bytes(self):
        for name in ('docs/index.html', 'docs/privacy/index.html', 'docs/img/new.png', 'design/other.js'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                export.destination(name)
        row = self.manifest['entries'][0]
        row['public_destination'] = 'README.md'
        self.manifest['approved_export'] = ['README.md']
        with self.assertRaisesRegex(ValueError, 'Unowned'):
            self.prepare()
        row['public_base_sha256'] = export.digest((self.target / 'README.md').read_bytes())
        self.assertEqual(self.prepare()[0][0]['path'], 'README.md')

    def test_casefold_and_file_directory_collisions(self):
        for name in ('MODULE.py', 'module.py/child.py'):
            with self.subTest(name=name):
                self.add_row('module.py', name)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.manifest['entries'].pop()
                self.manifest['approved_export'].pop()
        (self.target / 'MODULE.py').write_bytes(b'existing public file')
        self.commit(self.target, 'public case collision')
        with self.assertRaisesRegex(ValueError, 'path collision'):
            self.prepare()

    def test_input_revision_hash_blob_mode_and_output_hash_drift(self):
        row = self.manifest['entries'][0]
        for field, wrong in (('source_revision', '0' * 40), ('source_sha256', '0' * 64),
                             ('source_blob', '0' * 40), ('source_mode', '120000'),
                             ('output_sha256', '0' * 64), ('output_mode', '120000'),
                             ('action', 'copy folder')):
            with self.subTest(field=field):
                old = row[field]
                row[field] = wrong
                with self.assertRaises(ValueError):
                    self.prepare()
                row[field] = old
        row['source_inputs'][0].pop('sha256')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_symlink_or_submodule_committed_input_is_rejected(self):
        for mode, oid in (('120000', self.manifest['entries'][0]['source_blob']), ('160000', self.rev)):
            with self.subTest(mode=mode):
                self.git(self.source, 'update-index', '--add', '--cacheinfo', f'{mode},{oid},link')
                self.git(self.source, 'commit', '-qm', 'synthetic nonregular input')
                rev = self.git(self.source, 'rev-parse', 'HEAD').strip()
                manifest = copy.deepcopy(self.manifest)
                self.manifest['source_revision'] = rev
                row = self.manifest['entries'][0]
                row.update(source_path='link', source_revision=rev, source_mode=mode, source_blob=oid,
                           source_inputs=[])
                with self.assertRaisesRegex(ValueError, 'nonregular'):
                    self.prepare()
                self.manifest = manifest

    def test_exact_modify_extract_generate_and_executable_inputs(self):
        row = self.manifest['entries'][0]
        row.update(action='modify', transform={'replacements': [{'old': 'hello', 'new': 'world', 'count': 1}]},
                   output_sha256=export.digest(b"MESSAGE = 'world'\n"))
        extracted = b'const shape = 1;\n'
        self.add_row('drawing.html', 'assets-source/drawing.js', action='extract',
                     transform={'start': 'BEGIN', 'end': 'END'}, output_sha256=export.digest(extracted))
        self.add_row('gradlew')
        self.manifest['entries'].append({'source_path': None, 'source_inputs': [], 'action': 'generate',
            'public_destination': 'CONTRIBUTING.md', 'status': 'approved',
            'transform': {'parts': [{'text': 'Contributions: GPL-3.0-only\n'}]},
            'output_sha256': export.digest(b'Contributions: GPL-3.0-only\n'), 'output_mode': '100644'})
        self.manifest['approved_export'].append('CONTRIBUTING.md')
        changes, pending, _ = self.prepare()
        self.assertEqual(len(changes), 4)
        outputs = dict(pending)
        self.assertEqual(outputs['gradlew'][1], '100755')
        self.assertEqual(outputs['assets-source/drawing.js'][0], extracted)
        _, receipt = self.apply()
        self.assertTrue(self.git(self.target, 'ls-files', '--stage', '--', 'gradlew').startswith('100755 '))
        self.assertEqual(self.prepare(receipt)[0], [])
        row['transform']['replacements'][0]['count'] = 2
        with self.assertRaisesRegex(ValueError, 'precondition'):
            self.prepare()
        row['transform'] = {'shell': 'never executed'}
        with self.assertRaisesRegex(ValueError, 'Unimplemented'):
            self.prepare()

    def test_public_only_edits_and_same_file_conflicts_require_private_integration(self):
        _, receipt = self.apply()
        self.commit(self.target, 'first export')
        (self.target / 'module.py').write_bytes(b'accepted public contribution\n')
        self.commit(self.target, 'public contribution')
        with self.assertRaisesRegex(ValueError, 'integration'):
            self.prepare(receipt)
        row = self.manifest['entries'][0]
        row.update(action='modify', transform={'replacements': [{'old': 'hello', 'new': 'private edit', 'count': 1}]},
                   output_sha256=export.digest(b"MESSAGE = 'private edit'\n"))
        with self.assertRaisesRegex(ValueError, 'integration'):
            self.prepare(receipt)
        # The reviewed import is committed privately before export can continue.
        (self.source / 'module.py').write_bytes(b'accepted public contribution\n')
        self.commit(self.source, 'import reviewed public contribution with attribution')
        self.rev = self.git(self.source, 'rev-parse', 'HEAD').strip()
        self.manifest.update(source_revision=self.rev, entries=[], approved_export=[])
        self.add_row('module.py')
        self.assertEqual(self.prepare(receipt)[0], [])

    def test_private_only_change_and_unrelated_public_website_change(self):
        _, receipt = self.apply()
        self.commit(self.target, 'first export')
        (self.target / 'docs/index.html').write_bytes(b'public website improvement')
        self.commit(self.target, 'website change')
        row = self.manifest['entries'][0]
        row.update(action='modify', transform={'replacements': [{'old': 'hello', 'new': 'new', 'count': 1}]},
                   output_sha256=export.digest(b"MESSAGE = 'new'\n"))
        changes, receipt = self.apply(receipt)
        self.assertEqual(changes[0]['operation'], 'change')
        self.assertEqual((self.target / 'docs/index.html').read_bytes(), b'public website improvement')
        self.assertEqual(self.prepare(receipt)[0], [])

    def test_relocated_canonical_input_keeps_public_destination_and_receipt(self):
        self.manifest.update(entries=[], approved_export=[])
        self.add_row('drawing.html', 'assets-source/drawing.js', action='extract',
                     transform={'start': 'BEGIN', 'end': 'END'},
                     output_sha256=export.digest(b'const shape = 1;\n'))
        _, receipt = self.apply()
        self.commit(self.target, 'first extracted export')
        (self.source / 'drawing.js').write_bytes(b'const shape = 1;\n')
        self.commit(self.source, 'make extracted drawing the canonical editable source')
        self.rev = self.git(self.source, 'rev-parse', 'HEAD').strip()
        self.manifest.update(source_revision=self.rev, entries=[], approved_export=[])
        self.add_row('drawing.js', 'assets-source/drawing.js')
        self.assertEqual(self.prepare(receipt)[0], [])

    def test_deletions_are_explicit_owned_only_and_repeatable(self):
        self.add_row('gradlew')
        _, receipt = self.apply()
        self.commit(self.target, 'first export')
        self.manifest['entries'].pop(0)
        self.manifest['deletions'] = ['module.py']
        changes, receipt = self.apply(receipt)
        self.assertEqual(changes[0]['operation'], 'delete')
        self.assertFalse((self.target / 'module.py').exists())
        self.assertEqual(self.prepare(receipt)[0], [])
        self.manifest['deletions'].append('unowned.py')
        self.manifest['approved_export'].append('unowned.py')
        with self.assertRaisesRegex(ValueError, 'previously owned'):
            self.prepare(receipt)

    def test_unrelated_or_staged_target_changes_are_rejected_before_any_write(self):
        (self.target / 'unrelated.txt').write_bytes(b'local work')
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            self.prepare()
        self.assertFalse((self.target / 'module.py').exists())
        self.git(self.target, 'add', 'unrelated.txt')
        with self.assertRaisesRegex(ValueError, 'staged'):
            self.prepare()

    def test_wrong_origin_alternates_and_shared_history_are_rejected(self):
        self.git(self.target, 'remote', 'set-url', 'origin', 'https://example.invalid/private.git')
        with self.assertRaisesRegex(ValueError, 'origin'):
            self.prepare()
        self.git(self.target, 'remote', 'set-url', 'origin', self.public_url)
        alternate = self.target / '.git/objects/info/alternates'
        alternate.write_text(str(self.source / '.git/objects'))
        with self.assertRaisesRegex(ValueError, 'shared object store'):
            self.prepare()
        alternate.unlink()
        self.git(self.target, 'fetch', '-q', str(self.source), 'main:refs/heads/private-history')
        with self.assertRaisesRegex(ValueError, 'Private source history'):
            self.prepare()

    def test_nested_target_and_worktree_rejected(self):
        with self.assertRaisesRegex(ValueError, 'independent directories'):
            export.repository_boundary(self.source, self.source / 'export', self.public_url)
        worktree = self.root / 'worktree'
        self.git(self.target, 'worktree', 'add', '-q', str(worktree), '-b', 'candidate')
        with self.assertRaisesRegex(ValueError, 'independent clone'):
            export.repository_boundary(self.source, worktree, self.public_url)
        self.git(self.target, 'worktree', 'remove', str(worktree))

    def test_duplicate_json_keys_and_receipt_in_public_target_rejected(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text('{"schema_version": 1, "schema_version": 2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON'):
            export.read_record(manifest)
        manifest.write_text(json.dumps(self.manifest))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = export.main(['--source', str(self.source), '--target', str(self.target),
                                '--manifest', str(manifest), '--apply',
                                '--receipt-output', str(self.target / 'private-receipt.json')])
        self.assertEqual(code, 1)
        self.assertFalse((self.target / 'module.py').exists())


if __name__ == '__main__':
    unittest.main()
