"""Attachment actions wait for OK; Cancel never reads a file or opens Wiskit."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node') and (ROOT / 'web/node_modules/svelte').exists(),
                     'needs Node and installed web dependencies')
class CaptureActionsTest(unittest.TestCase):
    def test_attachment_confirmations_gate_the_actual_click_handlers(self):
        result = subprocess.run(['node', '--input-type=module', '-e', r"""
            import assert from 'node:assert/strict'
            import fs from 'node:fs'
            import vm from 'node:vm'
            import compiler from './web/node_modules/svelte/compiler/index.js'
            const source = fs.readFileSync('web/src/mobile/screens/Capture.svelte', 'utf8')
            const handlers = []
            function walk(node) {
                if (!node || typeof node !== 'object') return
                if ((node.type === 'RegularElement' && node.name === 'button') || (node.type === 'Component' && node.name === 'MButton')) {
                    const e = node.attributes.find(a => a.name === 'onclick')?.value.expression
                    const code = e && source.slice(e.start, e.end)
                    if (code?.includes('window.confirm(')) handlers.push(code)
                }
                for (const child of Object.values(node)) {
                    if (Array.isArray(child)) child.forEach(walk)
                    else if (child && typeof child === 'object') walk(child)
                }
            }
            walk(compiler.parse(source, { modern: true }).fragment)
            assert.equal(handlers.length, 3)
            const expected = { 'Read text': 'digest', Describe: 'describe', 'Ask Wiskit': 'ask' }
            const checked = new Set()
            for (const code of handlers) for (const ok of [false, true]) {
                const calls = [], prompts = []
                vm.runInNewContext(`(${code})()`, {
                    window: { confirm(message) { prompts.push(message); return ok } },
                    read: how => calls.push(how), askWiskit: () => calls.push('ask'),
                })
                assert.equal(prompts.length, 1)
                const [title, explanation] = prompts[0].split('\n\n')
                assert.ok(explanation.includes('draft'))
                assert.ok(Object.hasOwn(expected, title))
                assert.deepEqual(calls, ok ? [expected[title]] : [])
                checked.add(title)
            }
            assert.equal(checked.size, 3)
        """], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
