"""The desktop startup bar's model (web/public/boot.js), run under Node: each step owns a growing slice,
the bar eases toward a cap inside its step and never reaches the next milestone early, never goes back
or past its estimate, freezes on a failure, carries over from the loading page to the app page, and
only the first screen takes it to 100 %. Skips without Node."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from desktop.early_splash import progress

ROOT = Path(__file__).resolve().parent.parent
BOOT = ROOT / 'web' / 'public' / 'boot.js'


def run(script: str) -> dict:
    """script sees M (cmBootModel) and returns a JSON-able value."""
    js = f"""
        const vm = require('node:vm'), fs = require('node:fs')
        const ctx = {{}}
        vm.createContext(ctx)
        vm.runInContext(fs.readFileSync({json.dumps(str(BOOT))}, 'utf8'), ctx)
        const M = ctx.cmBootModel
        process.stdout.write(JSON.stringify((() => {{ {script} }})()))
    """
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, encoding='utf-8', timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr[-2000:])
    return json.loads(r.stdout)


# a startup: frames every 16 ms; step i starts at MARKS[i] ms; the first screen at `done` ms
SIMULATE = """
    const sim = (marks, done, still, end) => {
      const s = M.state(0, 0, 0), out = []
      for (let t = 0; t <= end; t += 16) {
        marks.forEach((at, i) => { if (t >= at) M.enter(s, i + 1, t) })
        if (done !== null && t >= done) M.complete(s, t)
        const goal = s.done ? 100 : M.goal(s.step, t - s.since)
        out.push([t, M.advance(s, t, still), goal, s.step])
      }
      return out
    }
"""


@unittest.skipUnless(shutil.which('node'), 'needs Node')
class BootProgressTest(unittest.TestCase):
    def test_slow_steps_keep_moving_and_native_handoff_uses_the_same_curve(self):
        r = run("""
            const times = [0, 250, 1000, 5000, 10000, 20000, 60000]
            return M.STEPS.map((step, i) => times.map(t => M.goal(i, t)))
        """)
        for values in r:
            self.assertTrue(all(b > a for a, b in zip(values, values[1:])))
            self.assertGreater(values[-1] - values[-2], 0.1)
        for elapsed, estimate in zip([0, 250, 1000, 5000, 10000, 20000, 60000], r[0]):
            self.assertAlmostEqual(progress(elapsed), estimate)
        self.assertEqual(progress(-100), 0)
        self.assertLess(progress(60000), 10.2)

    def test_later_steps_own_wider_slices_and_estimates_stop_short_of_them(self):
        r = run("""
            const ends = M.STEPS.map(s => s.end), out = []
            M.STEPS.forEach((s, i) => {
              const ts = [0, 50, 200, 1000, 5000, 60000, 1e9]
              out.push({ lo: i ? ends[i - 1] : 0, end: s.end, label: s.label, g: ts.map(t => M.goal(i, t)) })
            })
            return { ends, out, cap: M.CAP }
        """)
        self.assertEqual(r['ends'][-1], 100)
        shares = [b - a for a, b in zip([0] + r['ends'], r['ends'])]
        self.assertEqual(shares, sorted(shares))                  # small early, wide late
        self.assertEqual(len(set(shares)), len(shares))
        for step in r['out']:
            g = step['g']
            self.assertEqual(g[0], step['lo'])
            self.assertEqual(g, sorted(g))
            self.assertLessEqual(g[-1], step['lo'] + (step['end'] - step['lo']) * r['cap'] + 1e-9)
            self.assertLess(g[-1], step['end'])
            self.assertTrue(step['label'].endswith('…'))

    def test_milestones_move_the_bar_forward_smoothly_and_only_the_first_screen_ends_it(self):
        r = run(SIMULATE + """
            return { cold: sim([2600, 3300, 4200], 4500, false, 6000),
                     warm: sim([20, 400, 900], 1100, false, 3000),
                     instant: sim([5, 10, 15], 20, false, 2000),
                     stuck: sim([2000, 2600, 3200], null, false, 600000) }
        """)
        done_ats = {'cold': 4500, 'warm': 1100, 'instant': 20}
        for name, done_at in done_ats.items():
            frames = r[name]
            shown = [f[1] for f in frames]
            self.assertEqual(shown, sorted(shown), name)                          # monotonic
            self.assertTrue(all(f[1] <= f[2] + 1e-9 for f in frames), name)      # never past the estimate
            jumps = [b - a for a, b in zip(shown, shown[1:])]
            self.assertLess(max(jumps), 4, name)                                  # no abrupt jump per frame
            before = [f[1] for f in frames if f[0] < done_at]
            self.assertLess(max(before), 100, name)
            self.assertEqual(shown[-1], 100, name)
            self.assertLess(next(f[0] for f in frames if f[1] == 100) - done_at, 800, name)   # a short finish
        # slow at first, faster later: the mean speed of the first step is below the last ones'
        cold = r['cold']
        speed = lambda a, b: (next(f[1] for f in cold if f[0] >= b) - next(f[1] for f in cold if f[0] >= a)) / (b - a)
        self.assertLess(speed(0, 2600), speed(3300, 4200))
        # a first screen that never comes: the bar stays well short of 99 %
        self.assertLess(max(f[1] for f in r['stuck']), 96)
        self.assertEqual([f[3] for f in r['stuck']][-1], 3)

    def test_a_failure_freezes_the_bar_until_the_first_screen(self):
        r = run("""
            const s = M.state(1, 0, 10)
            for (let t = 0; t < 800; t += 16) M.advance(s, t, false)
            const at = s.shown
            s.failed = true
            const frozen = []
            for (let t = 800; t < 60000; t += 16) frozen.push(M.advance(s, t, false))
            M.complete(s, 60000)
            let t = 60000
            while (s.shown < 100 && t < 70000) { t += 16; M.advance(s, t, false) }
            return { at, frozen: [Math.min(...frozen), Math.max(...frozen)], end: s.shown, took: t - 60000 }
        """)
        self.assertEqual(r['frozen'], [r['at'], r['at']])
        self.assertEqual(r['end'], 100)
        self.assertLess(r['took'], 800)  # same maximum completion time as the other startup paths

    def test_reduced_motion_shows_the_estimate_without_easing(self):
        r = run(SIMULATE + "return sim([1000, 1500, 2000], 2300, true, 2400)")
        for t, shown, goal, _ in r:
            self.assertAlmostEqual(shown, goal, places=9)
        self.assertEqual(r[-1][1], 100)

    def test_the_app_page_picks_up_where_the_loading_page_was(self):
        r = run("""
            const out = []
            for (const t1 of [5, 300, 1800, 9000]) {
              const s = M.state(0, 0, 0)
              for (let t = 0; t <= t1; t += 16) M.advance(s, t, false)
              const page = M.state(1, t1, M.goal(0, t1))
              out.push([s.shown, page.shown, M.advance(page, t1 + 120, false)])
            }
            return out
        """)
        for loading, start, next_ in r:
            self.assertGreaterEqual(start, loading)
            self.assertLess(start - loading, 1.5)                     # no visible jump at the hand-over
            self.assertGreaterEqual(next_, start)


if __name__ == '__main__':
    unittest.main()
