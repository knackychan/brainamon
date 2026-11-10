"""Attachment actions ask inside the picture's card (projects/phone-add-sheet): the first tap only opens the confirm
line, only Continue runs the action, Cancel and Escape never read a file or open Wiskit. The words are the ones the
browser pop-up (window.confirm) used to show, word for word. The recap's Suggest (projects/phone-add-confirm) asks
the same way: its key only opens its line, its own Continue runs it, Cancel and Escape only close it."""
from pathlib import Path
import shutil
import subprocess
import unittest
from tests.phone_catalog import english

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / 'web/src/mobile/screens/Capture.svelte'
SAYS = {
    'Read text': 'Copy the text in this attachment into your draft for you to review before saving.',
    'Describe': 'AI describes what the photo shows and copies its visible text into your draft. Review the result before saving.',
    'Ask Wiskit': 'Open chat with your draft text as context so you can ask questions about it. If the attachment has not been read yet, it is read or described first and added to your draft.',
}


class CaptureActionsWordsTest(unittest.TestCase):
    def test_the_confirm_words_stay_and_no_browser_pop_up_is_left(self):
        source = CAPTURE.read_text(encoding='utf-8')
        self.assertNotIn('window.confirm', source)
        self.assertNotIn('confirm(', source)
        names = ['capture.attachment.read', 'processing.action.describe.label', 'shell.askWiskitLabel']
        lines = ['capture.attachment.readSays', 'capture.attachment.describeSays', 'capture.attachment.askSays']
        for (name, says), name_key, says_key in zip(SAYS.items(), names, lines):
            self.assertEqual(english(name_key), name)
            self.assertEqual(english(says_key), says)
            self.assertIn(f"name: t('{name_key}'), says: t('{says_key}')", source)
            self.assertIn('draft', says)

    def test_cancel_and_escape_only_close_the_line(self):
        source = CAPTURE.read_text(encoding='utf-8').replace('\r\n', '\n')
        start = source.index('function cancelAsk() {')
        body = source[start:source.index('\n  }\n', start)]
        for forbidden in ('read(', 'askWiskit(', 'go('):
            self.assertNotIn(forbidden, body)
        self.assertIn("e.key === 'Escape' && sure", source)
        self.assertIn('cancelAsk()', source)
        start = source.index('function cancelSuggest() {')
        body = source[start:source.index('\n', start)].split('{', 1)[1]
        self.assertNotIn('suggest(', body)
        self.assertIn("e.key === 'Escape' && sureCat", source)


@unittest.skipUnless(shutil.which('node') and (ROOT / 'web/node_modules/svelte').exists(),
                     'needs Node and installed web dependencies')
class CaptureActionsHandlersTest(unittest.TestCase):
    def test_the_real_click_handlers_ask_first_and_only_continue_runs(self):
        result = subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', r"""
            import assert from 'node:assert/strict'
            import fs from 'node:fs'
            import vm from 'node:vm'
            import compiler from './web/node_modules/svelte/compiler/index.js'
            import { messages } from './web/src/lib/i18n/en/index.ts'
            const source = fs.readFileSync('web/src/mobile/screens/Capture.svelte', 'utf8')
            const handlers = {}
            function walk(node) {
                if (!node || typeof node !== 'object') return
                if (node.type === 'Component' && node.name === 'MButton') {
                    const e = node.attributes.find(a => a.name === 'onclick')?.value.expression
                    const cls = node.attributes.find(a => a.name === 'class')?.value?.[0]?.data
                    const textNode = node.fragment?.nodes.find(n => n.type === 'ExpressionTag')?.expression
                    const text = node.fragment?.nodes.find(n => n.type === 'Text' && n.data.trim())?.data.trim()
                      || (textNode?.callee?.name === 't' ? messages[textNode.arguments[0]?.value] : '')
                      || (cls === 'm-cap-suggest' ? 'Suggest' : '')
                    if (e && text) (handlers[text] ??= []).push(source.slice(e.start, e.end))   // in source order
                }
                for (const child of Object.values(node)) {
                    if (Array.isArray(child)) child.forEach(walk)
                    else if (child && typeof child === 'object') walk(child)
                }
            }
            walk(compiler.parse(source, { modern: true }).fragment)
            const run = (name, sure, i = 0) => {
                const calls = [], ctx = { sure, read: how => calls.push(how), askWiskit: () => calls.push('ask') }
                vm.runInNewContext(`(${handlers[name][i]})()`, ctx)
                return { sure: ctx.sure, calls }
            }
            const acts = { 'Read text': 'digest', Describe: 'describe', 'Ask Wiskit': 'ask' }
            for (const [name, act] of Object.entries(acts)) {
                assert.ok(handlers[name], name)
                assert.deepEqual(run(name, ''), { sure: act, calls: [] })                  // the first tap only opens the line
                assert.deepEqual(run(name, act), { sure: '', calls: [] })                  // the same pill again closes it
                const other = Object.values(acts).find(a => a !== act)
                assert.deepEqual(run(name, other), { sure: act, calls: [] })               // another pill switches the line
            }
            assert.equal(handlers.Continue.length, 2)                                      // the attachment's line, then Suggest's
            assert.deepEqual(run('Continue', ''), { sure: '', calls: [] })
            assert.deepEqual(run('Continue', 'digest'), { sure: '', calls: ['digest'] })
            assert.deepEqual(run('Continue', 'describe'), { sure: '', calls: ['describe'] })
            assert.deepEqual(run('Continue', 'ask'), { sure: '', calls: ['ask'] })
            // Suggest: its key only opens or closes its line; only its own Continue asks Wiskit
            const suggest = (code, sureCat) => {
                const calls = [], ctx = { sureCat, suggest: () => calls.push('suggest') }
                vm.runInNewContext(`(${code})()`, ctx)
                return { sureCat: ctx.sureCat, calls }
            }
            assert.equal(handlers.Suggest.length, 1)
            assert.deepEqual(suggest(handlers.Suggest[0], false), { sureCat: true, calls: [] })
            assert.deepEqual(suggest(handlers.Suggest[0], true), { sureCat: false, calls: [] })
            assert.deepEqual(suggest(handlers.Continue[1], true), { sureCat: true, calls: ['suggest'] })
            console.log('ok')
        """], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
