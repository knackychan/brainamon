"""Validate the final installer gate with both innoextract output layouts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packaging'))
spec = importlib.util.spec_from_file_location('release_check', ROOT / 'packaging/release_check.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class InstallerGateTest(unittest.TestCase):
    def test_extracted_payload_and_windowless_dependency_report(self):
        versions = {'Pillow': '13.0.0', 'pypdf': '6.21.2', 'OpenJPEG': '2.5.4'}
        for layout, stdout, altered in [('app', True, False), ('{app}', False, False),
                                        ('{app}', False, True)]:
            with self.subTest(layout=layout, stdout=stdout, altered=altered), tempfile.TemporaryDirectory() as td:
                expanded = Path(td) / 'expanded'
                expanded.mkdir()
                (expanded / 'Brainamon.exe').write_bytes(b'synthetic executable')
                (expanded / '_internal').mkdir()
                (expanded / '_internal/build-channel.json').write_text('{"channel":"official"}')

                def run(command, **kwargs):
                    if command[0] in ('innoextract', 'innounp'):
                        folder = (command[command.index('--output-dir') + 1] if command[0] == 'innoextract'
                                  else next(arg[2:] for arg in command if arg.startswith('-d')))
                        target = Path(folder) / layout
                        target.mkdir()
                        (target / 'Brainamon.exe').write_bytes(b'altered' if altered else b'synthetic executable')
                        (target / '_internal').mkdir()
                        (target / '_internal/build-channel.json').write_text('{"channel":"official"}')
                        return subprocess.CompletedProcess(command, 0)
                    report = json.dumps(versions)
                    if not stdout:
                        (Path(kwargs['env']['BRAINAMON_HOME']) / 'error_log.txt').write_text(
                            'launcher log\n' + report + '\n', encoding='utf-8')
                    return subprocess.CompletedProcess(command, 0, stdout=report if stdout else '')

                tool = 'innoextract' if layout == 'app' else 'innounp'
                with mock.patch.object(gate.shutil, 'which', side_effect=lambda name: tool if name == tool else None), \
                        mock.patch.object(gate.subprocess, 'run', side_effect=run), \
                        mock.patch.object(gate.update_signing, 'verify_file') as verify:
                    if altered:
                        with self.assertRaisesRegex(ValueError, 'does not match'):
                            gate.windows_payload(Path(td) / 'setup.exe', expanded)
                    else:
                        self.assertEqual(gate.windows_payload(Path(td) / 'setup.exe', expanded), versions)
                    verify.assert_called_once()

    def test_missing_or_contributor_marker_cannot_pass_official_gate(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(gate.shutil, 'which', return_value='synthetic-extractor'), \
                mock.patch.object(gate.update_signing, 'verify_file') as verify:
            expanded = Path(td)
            for channel in (None, 'contributor'):
                if channel:
                    (expanded / '_internal').mkdir()
                    (expanded / '_internal/build-channel.json').write_text(json.dumps({'channel': channel}))
                with self.assertRaisesRegex(ValueError, 'explicit build-channel'):
                    gate.windows_payload(expanded / 'setup.exe', expanded)
            verify.assert_not_called()
