"""Splash handshake: ready content and a late native bridge must meet exactly once."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node') and (ROOT / 'web/node_modules/typescript').exists(),
                     'needs Node and installed web dependencies')
class StartupHandshakeTest(unittest.TestCase):
    def test_ready_signals_late_bridge_and_failure_fallback(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r"""
            import assert from 'node:assert/strict'
            import fs from 'node:fs'
            import vm from 'node:vm'
            import ts from './web/node_modules/typescript/lib/typescript.js'
            const main = fs.readFileSync('web/src/main.ts', 'utf8')
            const source = ts.transpile(main.slice(main.indexOf('function signalReady()')))
            function setup(marks = [], bridge = true) {
                let calls = 0, observer, timer, disconnected = false, onBridge
                const api = { ready() { calls++ } }
                const window = {
                    pywebview: bridge ? { api } : undefined,
                    addEventListener(_, callback) { onBridge = callback },
                    setTimeout(callback) { timer = callback; return 1 },
                }
                const context = {
                    window,
                    clearTimeout() { timer = undefined },
                    performance: { getEntriesByType: () => marks.map(name => ({ name })) },
                    PerformanceObserver: class {
                        constructor(callback) { observer = callback }
                        observe() {}
                        disconnect() { disconnected = true }
                    },
                }
                vm.runInNewContext(source + '; signalReady()', context)
                return {
                    emit(name) { observer({ getEntries: () => [{ name }] }) },
                    bridge() { window.pywebview = { api }; onBridge() },
                    timeout() { timer() },
                    get calls() { return calls },
                    get cleaned() { return disconnected && !timer },
                }
            }
            for (const name of ['cm-first-cards', 'cm-first-screen']) {
                assert.equal(setup([name]).calls, 1)
                const late = setup([], false)
                late.emit('unrelated')
                assert.equal(late.calls, 0)
                late.emit(name)
                assert.equal(late.calls, 0)
                assert.ok(late.cleaned)
                late.bridge()
                late.emit(name)
                assert.equal(late.calls, 1)
            }
            const failed = setup()
            failed.timeout()
            assert.equal(failed.calls, 1)
            assert.ok(failed.cleaned)
            failed.emit('cm-first-screen')
            assert.equal(failed.calls, 1)
        """], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
