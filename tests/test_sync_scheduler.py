"""Execute production SyncWork scheduling against an in-memory WorkManager/runner, no phone."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'mobile-shell/android/app/src/main/java/app/brainamon/mobile'


def method(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'requires an installed JDK')
class SyncSchedulerTest(unittest.TestCase):
    def test_chunks_crashes_contention_policy_and_observers(self):
        source = (NATIVE / 'SyncWork.java').read_text(encoding='utf-8')
        source = re.sub(r'^import (?:android|androidx|org\.json)\..*;\n', '', source, flags=re.M)
        source = source.replace('@NonNull ', '')
        # Only platform capability/network queries are replaced; scheduling/status code is unchanged.
        for signature, body in (
            ('static boolean supported()', 'static boolean supported(){return true;}'),
            ('static String network(', 'static String network(Context c,JSONObject p){return c.network;}'),
            ('static Constraints constraints(', 'static Constraints constraints(JSONObject p){return new Constraints(p.optBoolean("wifiOnly",true));}'),
        ):
            source = source.replace(method(source, signature), body)
        runner = (NATIVE / 'SyncRunner.java').read_text(encoding='utf-8')
        checkpoints = '\n'.join(method(runner, s) for s in (
            'static final class BudgetExpired', 'static final class UploadsPending', 'static final class Cancelled',
            'void checkpoint()', 'void checkpoint(boolean budget)', 'static String reason('))
        checkpoints = checkpoints.replace('android.os.SystemClock.elapsedRealtime()', 'Clock.now')
        harness = (ROOT / 'tests/fixtures/sync_scheduler.java').read_text(encoding='utf-8').replace('/* CHECKPOINTS */', checkpoints)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'SyncWork.java').write_text(source, encoding='utf-8')
            (root / 'SchedulerCheck.java').write_text(harness, encoding='utf-8')
            build = subprocess.run(['javac', '-d', str(root), str(root / 'SyncWork.java'), str(root / 'SchedulerCheck.java')], capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run(['java', '-ea', '-cp', str(root), 'app.brainamon.mobile.SchedulerCheck'], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('scheduler checks passed', result.stdout)
