"""Pure finish detection for the motion language's D1 jobs/status plan."""
import unittest

from tests.test_phone_js import _node_ok, node

SETUP = r"""
import assert from 'node:assert/strict'
import { finishedJob, endsHold } from './web/src/lib/motion/finish.ts'
const job = (overrides = {}) => Object.freeze({
  id: 7, kind: 'thumb', label: 'Fetch link info', state: 'running',
  total: 3, done: 0, skipped: 0, err: 0, current: 42, auto: false, t0: 1, t1: 0,
  ...overrides,
})
const state = (current = null, last = null) => Object.freeze({ current, last })
const running = job()
const done = job({ state: 'finished', done: 1, skipped: 1, err: 1, current: null, t1: 2 })
const prev = state(running)
const next = state(null, done)
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class MotionFinishJsTest(unittest.TestCase):
    def test_only_a_new_successful_manual_finish_holds(self):
        node(SETUP + r"""
assert.equal(finishedJob(prev, next), done, 'the pure detector returns next.last itself')
assert.equal(finishedJob(state(job({ state: 'paused' })), next), done)
assert.equal(finishedJob(prev, state(null, job({ ...done, state: 'stopped' }))), null)
assert.equal(finishedJob(state(job({ auto: true })), state(null, job({ ...done, auto: true }))), null)
for (const n of [0, -1]) assert.equal(finishedJob(prev, state(null, job({ ...done, done: n }))), null)
assert.equal(finishedJob(prev, state(null, job({ ...done, id: 8 }))), null)
assert.equal(finishedJob(state(), next), null, 'hello or a replay has no prior current job')
assert.equal(finishedJob(prev, state()), null, 'missing last')
assert.equal(finishedJob(prev, state(running, done)), null, 'the previous job is still current')
assert.equal(finishedJob(next, next), null, 'repeated finish does not renew a hold')
const auto = job({ id: 8, kind: 'index', auto: true })
assert.equal(finishedJob(prev, state(auto, done)), done, 'auto follow-up preserves the manual finish')
""")

    def test_only_a_new_manual_job_ends_a_hold(self):
        node(SETUP + r"""
assert.equal(endsHold(prev, next), false, 'finishing does not end the hold it creates')
assert.equal(endsHold(next, next), false)
assert.equal(endsHold(state(), state()), false)
const auto = job({ id: 8, kind: 'index', auto: true })
assert.equal(endsHold(prev, state(auto, done)), false)
assert.equal(endsHold(next, state(auto, done)), false)
const manual = job({ id: 9, kind: 'describe' })
assert.equal(endsHold(next, state(manual, done)), true)
assert.equal(endsHold(state(auto, done), state(manual, done)), true)
assert.equal(endsHold(prev, state(manual, done)), true, 'a new manual job wins when both happen together')
assert.equal(finishedJob(prev, state(manual, done)), done, 'the caller gives endsHold precedence')
const paused = job({ state: 'paused' })
assert.equal(endsHold(prev, state(paused)), false)
assert.equal(endsHold(state(paused), prev), false, 'pause and resume keep the same job id')
assert.equal(endsHold(prev, prev), false)
""")


if __name__ == '__main__':
    unittest.main()
