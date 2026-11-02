"""Exercise the Windows handoff with disposable executables, never the installed app."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from desktop import updater


@unittest.skipUnless(sys.platform == 'win32', 'Windows installer handoff')
class InstallHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.fixture = Path(cls.temp.name) / 'fixture.exe'
        source = '''
using System;
using System.IO;
using System.Threading;
class Fixture {
    static void Main(string[] args) {
        if (args.Length > 0 && args[0] == "hold") {
            Thread.Sleep(60000);
        } else {
            File.WriteAllLines(System.Reflection.Assembly.GetExecutingAssembly().Location + ".started", args);
        }
    }
}
'''
        script = "Add-Type -TypeDefinition @'\n" + source + "\n'@ -OutputType ConsoleApplication -OutputAssembly $env:HANDOFF_FIXTURE"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                       env={**os.environ, 'HANDOFF_FIXTURE': str(cls.fixture)},
                       check=True, capture_output=True, timeout=30, creationflags=updater.app_paths.NO_WINDOW)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="update space ' $ ")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.app = self.folder / 'handoff-app.exe'
        self.installer = self.folder / 'Brainamon-Setup-99.0.0.exe'
        shutil.copyfile(self.fixture, self.app)
        shutil.copyfile(self.fixture, self.installer)
        self.checksum = hashlib.sha256(self.installer.read_bytes()).hexdigest()
        self.marker = self.installer.with_name(self.installer.name + '.started')
        self.log = self.installer.with_suffix('.handoff.log')

    def start(self, command):
        process = subprocess.Popen(command, creationflags=updater.app_paths.NO_WINDOW)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        self.addCleanup(cleanup)
        return process

    def handoff(self, timeout=20):
        with mock.patch.object(updater.sys, 'executable', str(self.app)), \
                mock.patch.object(updater, 'INSTALL_EXIT_TIMEOUT', timeout):
            return self.start(updater._install_command(self.installer, self.checksum))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue(predicate())

    def test_waits_for_every_app_process_then_launches_with_quoted_log_path(self):
        first = self.start([str(self.app), 'hold'])
        second = self.start([str(self.app), 'hold'])
        helper = self.handoff()
        self.wait_for(self.log.exists)
        first.terminate(); first.wait(10)
        time.sleep(.75)
        self.assertIsNone(helper.poll())
        self.assertFalse(self.marker.exists())
        second.terminate(); second.wait(10)
        self.assertEqual(helper.wait(15), 0)
        self.wait_for(self.marker.exists)
        self.assertEqual(self.marker.read_text().splitlines(),
                         ['/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                          '/LOG=' + str(self.installer.with_suffix('.log'))])

    def test_timeout_does_not_launch_or_kill_the_app(self):
        app = self.start([str(self.app), 'hold'])
        self.assertEqual(self.handoff(timeout=1).wait(15), 1)
        self.assertIsNone(app.poll())
        self.assertFalse(self.marker.exists())
        self.assertIn('did not exit in time', self.log.read_text())

    def test_changed_installer_is_rejected_after_wait(self):
        self.installer.write_bytes(b'changed')
        self.assertEqual(self.handoff().wait(15), 1)
        self.assertFalse(self.marker.exists())
        self.assertIn('installer changed', self.log.read_text())

    def test_same_name_in_another_folder_does_not_block(self):
        other = self.folder / 'other'
        other.mkdir()
        other_app = other / self.app.name
        shutil.copyfile(self.fixture, other_app)
        app = self.start([str(other_app), 'hold'])
        self.assertEqual(self.handoff().wait(15), 0)
        self.wait_for(self.marker.exists)
        self.assertIsNone(app.poll())
