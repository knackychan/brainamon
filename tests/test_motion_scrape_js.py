"""Pure scraper tray transitions and bounded row playback for motion-language D3."""
import unittest

from tests.test_phone_js import _node_ok, node

SETUP = r"""
import assert from 'node:assert/strict'
import { idleTray, startScan, readCount, scanEnded, imported, played, PLAY_MAX, playRows, playedCount } from './web/src/lib/scrape-tray.ts'
const result = Object.freeze({ added: 25, duplicates: 3, invalid: 1, ids: Array.from({ length: 25 }, (_, i) => i + 1) })
const scan = Object.freeze(startScan('instagram'))
const finish = Object.freeze({ state: 'finished', err: 0 })
"""


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class MotionScrapeJsTest(unittest.TestCase):
    def test_read_is_bounded_and_only_advances_during_scan(self):
        node(SETUP + r"""
const ready = idleTray('instagram')
assert.deepEqual(ready, { site: 'instagram', phase: 'ready', read: null, result: null, ended: '' })
assert.equal(readCount(ready, 1), ready)
const first = readCount(scan, 0)
assert.equal(first.read, 0)
const next = readCount(first, 12)
assert.equal(next.read, 12)
for (const n of [12, 11, -1, 1.5, NaN, Infinity, 10000000]) assert.equal(readCount(next, n), next)
assert.equal(readCount(next, 9999999).read, 9999999)
assert.equal(scan.read, null, 'input is not mutated')
assert.equal(readCount(scanEnded(next, finish), 20).read, 12, 'reading ends with the scan')
""")

    def test_stop_and_failure_wait_for_a_late_import_without_losing_it(self):
        node(SETUP + r"""
const reading = Object.freeze(readCount(scan, 9))
assert.equal(scanEnded(reading, finish).phase, 'wait')
assert.equal(scanEnded(reading, null).phase, 'wait')
const stopped = scanEnded(reading, { state: 'stopped', err: 1 })
assert.equal(stopped.phase, 'off')
assert.equal(stopped.ended, 'stopped', 'stop takes precedence over errors')
const failed = scanEnded(reading, { state: 'finished', err: 1 })
assert.equal(failed.ended, 'failed')
for (const old of [idleTray('instagram'), scan, scanEnded(reading, finish), stopped, failed,
                   imported(scan, result), played(imported(scan, result))]) {
  const next = imported(Object.freeze(old), result)
  assert.equal(next.phase, 'play')
  assert.equal(next.result, result)
  assert.equal(next.ended, '')
  assert.equal(next.site, 'instagram')
  assert.equal(scanEnded(next, finish), next, 'job end must not overwrite an earlier import')
  const done = played(Object.freeze(next))
  assert.equal(done.phase, 'done')
  assert.equal(played(done), done, 'finish persists')
  assert.equal(scanEnded(done, finish), done)
  assert.equal(readCount(done, 100), done)
}
assert.equal(played(scan), scan)
assert.equal(scanEnded(idleTray('instagram'), finish).phase, 'ready')
""")

    def test_playback_is_capped_and_counts_the_whole_import(self):
        node(SETUP + r"""
assert.equal(PLAY_MAX, 12)
assert.equal(playRows(result), 12)
assert.equal(playedCount(result, 0), 0)
assert.equal(playedCount(result, 1), 2)
assert.equal(playedCount(result, 6), 13)
assert.equal(playedCount(result, 12), 25)
assert.equal(playedCount(result, 50), 25)
assert.equal(playedCount(result, -1), 0)
const one = { ...result, added: 1, ids: [1] }
assert.equal(playRows(one), 1)
assert.equal(playedCount(one, 0), 0)
assert.equal(playedCount(one, 1), 1)
const empty = { added: 0, duplicates: 7, invalid: 2, ids: [] }
assert.equal(playRows(empty), 0)
assert.equal(playedCount(empty, 0), 0)
assert.equal(playedCount({ ...empty, added: 4 }, 0), 4, 'no row ids must not divide by zero or strand a result')
const fresh = startScan('facebook')
assert.deepEqual(fresh, { site: 'facebook', phase: 'scan', read: null, result: null, ended: '' })
""")


if __name__ == '__main__':
    unittest.main()
