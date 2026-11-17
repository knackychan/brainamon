"""Pure Wiskit Deep research steps and source rows for motion-language D4."""
import unittest

from tests.test_phone_js import _node_ok, node

SETUP = r"""
import assert from 'node:assert/strict'
import { emptyResearch, onTool, settle, closeResearch, researchDone, readAt, VERB, COUNTED, ROWS_PER_CALL, ROWS_MAX, READ_DELAY_MS } from './web/src/lib/research.ts'
import { READ_MS, arrivalDelay } from './web/src/lib/motion/motion.ts'
const known = id => id < 900
const freeze = o => { for (const v of Object.values(o)) if (v && typeof v === 'object') freeze(v); return Object.freeze(o) }
const start = (n, name, extra = {}) => ({ phase: 'start', n, name, line: 'line', q: '', ids: [], ...extra })
const done = (n, name, ok, ids) => ({ phase: 'done', n, name, ok, ids })
const states = r => r.rows.map(x => [x.id, x.state])
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class MotionResearchJsTest(unittest.TestCase):
    def test_steps_labels_and_hits(self):
        node(SETUP + r"""
let r = freeze(onTool(emptyResearch(), start(1, 'search_library', { q: 'glass' }), 0, known))
assert.deepEqual(r.steps, [{ n: 1, name: 'search_library', label: 'search library', q: 'glass', state: 'run', hits: null }])
assert.deepEqual(r.rows, [])
assert.equal(onTool(r, start(1, 'search_library'), 0, known), r, 'one step per call')
r = freeze(onTool(r, done(1, 'search_library', true, [3, 4, 3, -1, 2.5, '5', 0]), 10, known))
assert.equal(r.steps[0].state, 'ok')
assert.equal(r.steps[0].hits, 2)
assert.equal(onTool(r, done(1, 'search_library', true, []), 10, known), r, 'a step ends once')
assert.equal(onTool(r, done(9, 'search_library', true, [1]), 10, known), r, 'no done without its start')
r = freeze(onTool(r, start(2, 'topic_items', { q: 'x'.repeat(200) }), 0, known))
assert.equal(r.steps[1].q.length, 80)
assert.equal(r.steps[1].label, 'browse topic')
r = freeze(onTool(r, done(2, 'topic_items', false, [7]), 0, known))
assert.deepEqual([r.steps[1].state, r.steps[1].hits], ['err', null])
r = freeze(onTool(r, start(3, 'read_note'), 0, known))
r = freeze(onTool(r, done(3, 'read_note', true, [8]), 0, known))
assert.deepEqual([r.steps[2].label, r.steps[2].state, r.steps[2].hits], ['read note', 'ok', null], 'only listing tools count hits')
assert.equal(onTool(r, start(4, 'new_tool'), 0, known).steps[3].label, 'new tool')
for (const name of ['propose_category', 'propose_categories', 'propose_reformat', 'propose_canvas'])
  assert.equal(onTool(r, start(5, name), 0, known), r, 'proposals are not research steps')
for (const bad of [null, { phase: 'start', name: 'x' }, { phase: 'start', n: 1.5, name: 'x' }, { phase: 'start', n: 6 }])
  assert.equal(onTool(r, bad, 0, known), r)
assert.equal(Object.keys(VERB).length, 11)
assert.deepEqual([...COUNTED], ['search_library', 'topic_items', 'related_items'])
""")

    def test_rows_are_known_deduplicated_and_capped(self):
        node(SETUP + r"""
let r = freeze(onTool(emptyResearch(), start(1, 'read_items', { ids: [5, 5, 950, 0, -2, 1.5, '6', 6, 7, 8, 9, 10, 11, 12, 13, 14] }), 1000, known))
assert.equal(ROWS_PER_CALL, 8)
assert.deepEqual(r.rows.map(x => x.id), [5, 6, 7, 8, 9, 10, 11, 12])
assert.deepEqual(r.rows.map(x => x.d), [0, 1, 2, 3, 4, 5, 6, 7].map(arrivalDelay))
assert.ok(r.rows.every(x => x.at === 1000 && x.n === 1 && x.state === 'reading' && x.got === false))
r = freeze(onTool(r, start(2, 'read_items', { ids: [5, 6, ...Array.from({ length: 12 }, (_, i) => 20 + i)] }), 2000, known))
assert.deepEqual(r.rows.slice(8).map(x => x.id), [20, 21, 22, 23, 24, 25, 26, 27], 'one row per id per answer')
assert.equal(r.rows[8].d, 0, 'each call staggers from zero')
r = freeze(onTool(r, start(3, 'read_items', { ids: Array.from({ length: 20 }, (_, i) => 50 + i) }), 3000, known))
r = freeze(onTool(r, start(4, 'read_items', { ids: [80, 81] }), 4000, known))
assert.equal(ROWS_MAX, 24)
assert.equal(r.rows.length, 24)
assert.equal(r.steps.length, 4, 'the step shows even without room for rows')
assert.equal(onTool(r, start(5, 'read_items'), 0, known).rows.length, 24)
""")

    def test_rows_read_on_the_clock_and_unused_rows(self):
        node(SETUP + r"""
let r = freeze(onTool(emptyResearch(), start(1, 'read_items', { ids: [1, 2, 3] }), 1000, known))
let s = settle(r, 1e9)
assert.equal(s.research, r)
assert.equal(s.wait, -1, 'rows wait for their call to end')
r = freeze(onTool(r, done(1, 'read_items', true, [3, 1, 99]), 1100, known))
assert.deepEqual(r.rows.map(x => [x.id, x.state, x.got]), [[1, 'reading', true], [2, 'unused', false], [3, 'reading', true]])
assert.equal(READ_DELAY_MS, 200)
assert.equal(readAt(r.rows[0]), 1000 + 200 + READ_MS)
s = settle(r, 1000 + 200 + READ_MS - 1)
assert.equal(s.research, r)
assert.equal(s.wait, 1)
s = settle(r, 1000 + 200 + READ_MS)
assert.deepEqual(states(s.research), [[1, 'read'], [2, 'unused'], [3, 'reading']])
assert.equal(s.wait, arrivalDelay(2))
const all = settle(freeze(s.research), Infinity)
assert.deepEqual(states(all.research), [[1, 'read'], [2, 'unused'], [3, 'read']])
assert.equal(all.wait, -1)
const fin = freeze(researchDone(all.research, [3, 42]))
assert.deepEqual(states(fin), [[1, 'unused'], [2, 'unused'], [3, 'read']])
assert.equal(fin.read, 2)
assert.equal(researchDone(fin, []), fin)
assert.equal(onTool(fin, start(2, 'search_library'), 0, known), fin, 'late events are ignored')
const failed = onTool(freeze(onTool(emptyResearch(), start(1, 'read_items', { ids: [4] }), 0, known)), done(1, 'read_items', false, [4]), 0, known)
assert.deepEqual(states(failed), [[4, 'unused']])
""")

    def test_stop_and_done_close_open_calls(self):
        node(SETUP + r"""
let r = onTool(emptyResearch(), start(1, 'search_library'), 0, known)
r = onTool(r, start(2, 'read_items', { ids: [1, 2] }), 0, known)
r = onTool(r, done(2, 'read_items', true, [1]), 0, known)
r = freeze(onTool(r, start(3, 'read_items', { ids: [3] }), 0, known))
const stopped = closeResearch(r, 'err')
assert.deepEqual(stopped.steps.map(s => s.state), ['err', 'ok', 'err'])
assert.deepEqual(states(stopped), [[1, 'read'], [2, 'unused'], [3, 'unused']])
assert.equal(stopped.read, null, 'no summary after Stop')
const fin = researchDone(r, [1])
assert.deepEqual(fin.steps.map(s => s.state), ['ok', 'ok', 'ok'])
assert.deepEqual(states(fin), [[1, 'read'], [2, 'unused'], [3, 'unused']])
assert.equal(fin.read, 1)
const quiet = freeze(emptyResearch())
assert.equal(closeResearch(quiet, 'err'), quiet)
assert.deepEqual(researchDone(quiet, []), { steps: [], rows: [], read: 0 })
""")


if __name__ == '__main__':
    unittest.main()
