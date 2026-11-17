"""The motion language's shared pieces (projects/motion-language plan 01): web/src/lib/motion/motion.ts under
Node (tick, lift, arrival, motionOn, Tween with a fake clock), arrive.ts, the durations motion.css shares with
motion.ts, its motion-off and reduced-motion rules, and the two entries that load it."""
import json
import re
import unittest
from pathlib import Path

from tests.test_phone_js import _node_ok, node

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / 'web' / 'src' / 'lib' / 'motion'

SCRIPT = r"""
const m = await import('./web/src/lib/motion/motion.ts')
const { arrive } = await import('./web/src/lib/motion/arrive.ts')
const out = {}
out.tickMs = [[5, 5], [5, 6], [0, 2], [0, 10], [0, 38], [75, 37], [0, 1000]].map(([a, b]) => m.tickMs(a, b))
out.tickValue = [[0, 40, 0, 1600], [0, 40, 800, 1600], [0, 40, 1600, 1600], [0, 40, 9999, 1600], [7, 8, 0, 0], [75, 37, 760, 1520]].map(a => m.tickValue(...a))
out.lift = [0, 110, 220, -5].map(m.liftPx)
out.arrival = [0, 3, -1].map(m.arrivalDelay)
out.noDocument = m.motionOn()
out.arriveNoDocument = arrive(null, { x: -28 })
let now = 1000, queue = []
Object.defineProperty(globalThis, 'performance', { value: { now: () => now }, configurable: true, writable: true })
globalThis.requestAnimationFrame = fn => { queue.push(fn); return queue.length }
globalThis.cancelAnimationFrame = () => { queue = [] }
const classes = new Set()
let reduced = false
globalThis.document = { documentElement: { classList: { contains: c => classes.has(c) } } }
globalThis.matchMedia = () => ({ matches: reduced })
const frames = ms => { const end = now + ms; while (queue.length && now < end) { now += 16; const q = queue; queue = []; for (const f of q) f(now) } }
out.motionOn = m.motionOn()
const a = arrive(null, { x: -28, delay: 90 })
out.arrive = { delay: a.delay, duration: a.duration, start: a.css(0, 1), end: a.css(1, 0) }
const seen = []
const tw = new m.Tween(0, (v, lift) => seen.push([v, Math.round(lift * 100) / 100]))
tw.to(40)
const first = seen[0]
frames(3000)
out.tween = { first, last: seen.at(-1), many: seen.length > 20, value: tw.value, idle: queue.length === 0 }
seen.length = 0
tw.to(41)
frames(1000)
out.one = { first: seen[0], last: seen.at(-1) }
seen.length = 0
tw.to(90, true)
out.jump = { seen: [...seen], queued: queue.length }
classes.add('motion-off'); seen.length = 0
out.offOn = m.motionOn()
tw.to(10)
out.off = { seen: [...seen], queued: queue.length }
classes.delete('motion-off'); classes.add('cm-rest')
out.restOn = m.motionOn()
classes.delete('cm-rest'); reduced = true
out.reducedOn = m.motionOn()
out.interrupted = []
for (const mode of ['motion-off', 'cm-rest', 'reduced']) {
  reduced = false
  const values = []
  const active = new m.Tween(0, (v, lift) => values.push([v, lift]))
  active.to(100)
  frames(160)
  const before = active.value
  if (mode === 'reduced') reduced = true
  else classes.add(mode)
  frames(16)
  out.interrupted.push({ before, last: values.at(-1), value: active.value, queued: queue.length })
  classes.delete(mode)
}
console.log(JSON.stringify(out))
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class MotionJsTest(unittest.TestCase):
    def test_tick_lift_arrival_tween_and_motion_off(self):
        out = json.loads(node(SCRIPT))
        self.assertEqual(out['tickMs'], [0, 0, 160, 400, 1520, 1520, 1600])
        self.assertEqual(out['tickValue'], [0, 35, 40, 40, 8, 42])
        self.assertEqual(out['lift'], [3, 1.5, 0, 0])
        self.assertEqual(out['arrival'], [0, 270, 0])
        self.assertIs(out['noDocument'], False)
        self.assertEqual(out['arriveNoDocument'], {'duration': 0})
        self.assertIs(out['motionOn'], True)
        self.assertEqual(out['arrive'], {'delay': 90, 'duration': 320, 'start': 'transform:translate(-28px,0px);opacity:0',
                                         'end': 'transform:translate(0px,0px);opacity:1'})
        self.assertEqual(out['tween'], {'first': [0, 0], 'last': [40, 0], 'many': True, 'value': 40, 'idle': True})
        self.assertEqual(out['one'], {'first': [41, 3], 'last': [41, 0]})
        self.assertEqual(out['jump'], {'seen': [[90, 0]], 'queued': 0})
        self.assertIs(out['offOn'], False)
        self.assertEqual(out['off'], {'seen': [[10, 0]], 'queued': 0})
        self.assertIs(out['restOn'], False)
        self.assertIs(out['reducedOn'], False)
        for interrupted in out['interrupted']:
            self.assertTrue(0 < interrupted['before'] < 100)
            self.assertEqual(interrupted['last'], [100, 0])
            self.assertEqual(interrupted['value'], 100)
            self.assertEqual(interrupted['queued'], 0)


class MotionCssTest(unittest.TestCase):
    css = (MOTION / 'motion.css').read_text(encoding='utf-8')
    ts = (MOTION / 'motion.ts').read_text(encoding='utf-8')

    def ms(self, name):
        return int(re.search(rf'export const {name} = (\d+)', self.ts).group(1))

    def seconds(self, token):
        return round(float(re.search(rf'--{token}:([\d.]+)s', self.css).group(1)) * 1000)

    def test_durations_agree_with_motion_ts(self):
        self.assertEqual(self.seconds('mo-arrive'), self.ms('ARRIVE_MS'))
        self.assertEqual(self.seconds('mo-read'), self.ms('READ_MS'))
        self.assertEqual(self.seconds('mo-pop'), self.ms('POP_MS'))
        self.assertEqual((self.seconds('mo-sweep'), self.seconds('mo-land'), self.seconds('mo-busy')), (850, 320, 1180))

    def test_every_move_stops_with_motion_off_and_reduced_motion(self):
        off = self.css.split(':is(.motion-off,.cm-rest) .mo-bar>i{', 1)[1]
        reduced = self.css.split('@media (prefers-reduced-motion:reduce){', 1)[1]
        for rule in ('.mo-bar.mo-busy>i{', '.mo-scan::after{', '.mo-read::after{'):
            self.assertIn(rule, off)
            self.assertIn(rule, reduced)
        self.assertIn(':is(.motion-off,.cm-rest) :is(.mo-delta,.mo-pop,.mo-nudge){animation:none}', self.css)
        self.assertIn('.mo-delta,.mo-pop,.mo-nudge{animation:none}', reduced)

    def test_class_names_never_reuse_the_card_css(self):
        names = set(re.findall(r'\.([a-z][\w-]*)', re.sub(r'/\*.*?\*/', '', self.css, flags=re.S)))
        allowed = {'prog', 'lit', 'motion-off', 'cm-rest'}
        self.assertEqual({n for n in names if not n.startswith('mo-')} - allowed, set())

    def test_both_entries_load_it_after_type_css(self):
        for entry, line in (('web/src/main.ts', "import './lib/motion/motion.css'"),
                            ('web/src/mobile/main.ts', "import '../lib/motion/motion.css'")):
            text = (ROOT / entry).read_text(encoding='utf-8')
            self.assertIn(line, text)
            self.assertLess(text.index('type.css'), text.index(line))


if __name__ == '__main__':
    unittest.main()
