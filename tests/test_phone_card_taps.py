"""Phone touch releases reach the locked engine only when they are taps."""
import unittest

from tests.test_phone_js import _node_ok, node


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneCardTapTest(unittest.TestCase):
    def test_touch_tap_hold_drag_cancel_and_keyboard(self):
        node("""
            import assert from 'node:assert/strict'
            import fs from 'node:fs'
            import vm from 'node:vm'
            import { fingerTilt } from './web/src/mobile/finger.ts'

            let now = 0, taps = 0
            const ctx = vm.createContext({
                window: {}, matchMedia: () => ({ matches: false }),
                document: { documentElement: { classList: { toggle() {} } } },
                performance: { now: () => now }, requestAnimationFrame() {},
            })
            vm.runInContext(fs.readFileSync('design/card-designs/engine.js', 'utf8') +
                ';globalThis.HandCard = HandCard', ctx)
            const slotEvents = new Map(), stageEvents = new Map()
            const slot = {
                querySelector: () => ({ style: {} }), querySelectorAll: () => [],
                classList: { add() {}, remove() {} }, setPointerCapture() {},
                getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 280 }),
                addEventListener: (k, f) => slotEvents.set(k, f),
            }
            const h = new ctx.HandCard(slot, { idle: false, onTap: () => taps++ })
            const stage = {
                addEventListener: (k, f) => stageEvents.set(k, f),
                removeEventListener: k => stageEvents.delete(k),
            }
            const off = fingerTilt(stage, () => h)
            const send = (kind, x = 100, y = 100) => {
                const t = { identifier: 1, clientX: x, clientY: y, target: { closest: () => slot } }
                stageEvents.get(kind)({ changedTouches: [t], cancelable: true, preventDefault() {} })
            }
            send('touchstart'); now += 100; send('touchend')
            assert.equal(taps, 1, 'quick release taps once')
            send('touchstart'); now += 380; send('touchend')
            assert.equal(taps, 1, 'hold never taps')
            send('touchstart'); now += 30; send('touchmove', 140, 130)
            assert.notEqual(h.tgt.ry, 0, 'movement still tilts')
            send('touchmove'); now += 30; send('touchend')
            assert.equal(taps, 1, 'out and back is still a drag')
            assert.equal(h.tgt.ry, 0, 'drag settles')
            send('touchstart'); now += 30; send('touchend', 107)
            assert.equal(taps, 1, 'travel on release also prevents a tap')
            send('touchstart'); send('touchcancel'); send('touchend')
            assert.equal(taps, 1, 'cancel never taps')
            send('touchstart'); now += 30; send('touchend', 106)
            assert.equal(taps, 2, 'six pixel slop allows a tap')
            let blocked = false
            stageEvents.get('pointerup')({ pointerType: 'touch', stopPropagation() { blocked = true } })
            assert.ok(blocked, 'touch pointer events cannot double fire')
            for (const key of ['Tab', 'Escape', 'ArrowDown']) {
                slotEvents.get('keydown')({ key, preventDefault() { assert.fail('unrelated key') } })
            }
            assert.equal(taps, 2, 'unrelated keys never activate')
            for (const key of ['Enter', ' ']) {
                let prevented = false
                slotEvents.get('keydown')({ key, preventDefault() { prevented = true } })
                assert.ok(prevented, 'activation suppresses the default')
            }
            assert.equal(taps, 4, 'each deliberate keyboard activation taps once')
            off()
            assert.equal(stageEvents.size, 0, 'listeners cleaned up')
        """)
