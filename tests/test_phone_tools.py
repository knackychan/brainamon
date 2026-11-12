"""The phone Tools panel's rules (web/src/mobile/tools.ts, projects/phone-processing-flow), run under Node like
tests/test_capture_recap.py: which rows a phone step takes, when a run asks first (more than 20 model calls, Run again,
Analyze; Index counts one call per 64 texts), the confirm line and its key, the line under the rows, the finished summary
and its orange key (Retry, Continue, Next 25), the running ledger's window, the meter's range, the closed key's spoken
status. These are pure rules: the run engine, the PC's job events and Undo are exercised by
tests/check_phone_tools_engine.py and the panel by tests/check_phone_tools_browser.py. Skips without Node 22.6+."""
import json
import unittest

from tests.test_phone_js import TS_RESOLVE, _node_ok, node


def run(body: str):
    return json.loads(node(TS_RESOLVE + "const t = await import('./web/src/mobile/tools.ts')\n" + body))


@unittest.skipUnless(_node_ok(), 'needs Node 22.6+ (type stripping)')
class PhoneToolsTest(unittest.TestCase):
    def test_phone_can_resume_missing_previews_without_ai_calls(self):
        out = run("""
            const rows = [{id:1,thumb:true,ai:false,cat:'Art',tags:''}, {id:2,thumb:false,ai:true,cat:'Art',tags:''}]
            console.log(JSON.stringify([t.phoneTargets(rows,'thumb',false), t.phoneTargets(rows,'thumb',true),
              t.needsConfirm('thumb',25,false), t.aiCalls('thumb',25)]))
        """)
        self.assertEqual(out, [[2], [1, 2], False, 0])

    def test_phone_targets_and_when_to_ask(self):
        out = run("""
            const rows = [{ id: 1, ai: false, cat: 'INTERESTING', tags: '' }, { id: 2, ai: true, cat: '', tags: '' },
                          { id: 3, ai: false, cat: 'Art', tags: '' }, { id: 4, ai: true, cat: 'INTERESTING', tags: 'x' }]
            console.log(JSON.stringify([
              t.phoneTargets(rows, 'describe', false), t.phoneTargets(rows, 'categorize', false), t.phoneTargets(rows, 'categorize', true),
              t.needsConfirm('describe', 20, false), t.needsConfirm('describe', 21, false), t.needsConfirm('describe', 1, true),
              t.needsConfirm('analyze', 1, false), t.needsConfirm('thumb', 500, false), t.needsConfirm('thumb', 500, true),
              t.PHONE_LIMIT, t.CONFIRM_OVER,
            ]))
        """)
        self.assertEqual(out, [[1, 3], [1, 2], [1, 2, 3, 4], False, True, True, True, False, True, 25, 20])

    def test_the_boundaries_of_the_question(self):
        # decision 2: more than 20 model calls ask; Index sends 64 texts per call; Analyze and Run again always ask
        out = run("""
            const q = (k, n, re = false) => t.needsConfirm(k, n, re)
            console.log(JSON.stringify([
              [20, 21, 25, 26].map(n => q('describe', n)), [20, 21].map(n => q('categorize', n)),
              [1280, 1281].map(n => q('index', n)), [1, 64, 65].map(n => t.aiCalls('index', n)),
              q('index', 1), q('index', 1, true), q('analyze', 1), q('thumb', 1), q('thumb', 9999),
              t.aiCalls('analyze', 5), t.aiCalls('thumb', 5), t.aiCalls('describe', 5),
              t.chargeLine('describe', 25), t.chargeLine('index', 1281), t.chargeLine('index', 64), t.chargeLine('analyze', 3), t.chargeLine('thumb', 3),
              t.EMBED_BATCH,
            ]))
        """)
        self.assertEqual(out, [[False, True, True, True], [False, True], [False, True], [1, 1, 2], False, True, True, False, False,
                               0, 0, 5, '25 AI calls', '21 embedding calls', '1 embedding call', 'charges may apply', '', 64])

    def test_meter_never_has_a_zero_range_or_a_count_past_it(self):
        out = run("""
            console.log(JSON.stringify([t.meter(0, 0), t.meter(0, 5), t.meter(80, 100), t.meter(25, 4), t.meter(NaN, NaN), t.meter(3.9, 2.9)]))
        """)
        self.assertEqual(out, [{'max': 1, 'now': 0}, {'max': 1, 'now': 1}, {'max': 80, 'now': 80}, {'max': 25, 'now': 4},
                               {'max': 1, 'now': 0}, {'max': 3, 'now': 2}])

    def test_progress_uses_the_pc_counts_only_when_no_rows_are_loaded(self):
        out = run("""
            const items = st => st.map(s => ({ st: s }))
            const counts = { done: 3, skip: 1, err: 1 }
            console.log(JSON.stringify([
              t.progress({ items: [], total: 80, counts }), t.progress({ items: items(['done', 'wait']), total: 80, counts }),
              t.progress({ items: [], total: 4, counts: null }),
              t.ringText(t.progress({ items: items(['done', 'done', 'wait', 'run']), total: 4, counts: null }), false),
              t.ringText(t.progress({ items: items(['done', 'err']), total: 2, counts: null }), true),
              t.ringText(t.progress({ items: items(['done']), total: 1, counts: null }), true),
            ]))
        """)
        self.assertEqual(out, [
            {'n': 80, 'done': 3, 'skip': 1, 'err': 1, 'left': 75}, {'n': 2, 'done': 1, 'skip': 0, 'err': 0, 'left': 1},
            {'n': 4, 'done': 0, 'skip': 0, 'err': 0, 'left': 4},
            'Tools: 2 of 4 done, 2 left', 'Tools: finished, 1 failed', 'Tools: finished'])

    def test_confirm_lines_and_keys(self):
        out = run("""
            const c = o => { const x = t.confirmText({ rerun: false, src: 'phone', provider: 'OpenAI', replace: 'Replace existing AI descriptions.', ...o }); return x.lead + ' ' + x.rest }
            console.log(JSON.stringify([
              c({ kind: 'describe', n: 25, all: 80 }),
              c({ kind: 'describe', n: 30, all: 30, src: 'pc' }),
              c({ kind: 'describe', n: 3, all: 3, rerun: true }),
              c({ kind: 'thumb', n: 4, all: 4, rerun: true, src: 'pc', replace: 'Fetch again.' }),
              c({ kind: 'analyze', n: 2, all: 2, src: 'pc' }),
              c({ kind: 'analyze', n: 1, all: 1, src: 'pc', join: true }),
              t.confirmGo({ kind: 'describe', n: 25, all: 80, src: 'phone' }),
              t.confirmGo({ kind: 'categorize', n: 3, all: 3, src: 'solo' }),
              t.confirmGo({ kind: 'describe', n: 30, all: 30, src: 'pc' }),
              c({ kind: 'index', n: 1281, all: 1281, src: 'pc', provider: 'embeddings' }),
            ]))
        """)
        self.assertEqual(out, [
            '80 items need Describe. This phone does 25 at a time: the first 25 now, 25 AI calls on its OpenAI key. Provider charges may apply.',
            '30 AI calls on the PC’s OpenAI key. Provider charges may apply. The PC works through them; you can close this.',
            'Run again on 3 items. Replace existing AI descriptions. 3 AI calls on this phone’s OpenAI key; provider charges may apply.',
            'Run again on 4 items. Fetch again.',
            '2 videos. Uses a saved copy or downloads it, then frames and transcription, with the options below. Several minutes per video; AI and transcription charges may apply.',
            '1 video. They join the running analysis and use its options, which are shared with that job.',
            'Describe the first 25', 'Auto-categorize 3 now', 'Start 30 on the PC',
            '21 embedding calls on the PC’s embeddings key. Provider charges may apply. The PC works through them; you can close this.'])

    def test_a_follow_up_names_its_action_and_keeps_the_original_options(self):
        out = run("""
            const c = o => { const x = t.confirmText({ rerun: false, src: 'pc', provider: 'OpenAI', replace: 'Replace.', ...o }); return x.lead + ' ' + x.rest }
            console.log(JSON.stringify([
              c({ kind: 'describe', n: 30, all: 30, act: 'retry' }), c({ kind: 'describe', n: 3, all: 3, rerun: true, act: 'continue' }),
              c({ kind: 'analyze', n: 2, all: 2, act: 'retry', retained: true }), c({ kind: 'describe', n: 25, all: 25, src: 'phone', act: 'next' }),
            ]))
        """)
        self.assertEqual(out, [
            'Retry 30 failed. 30 AI calls on the PC’s OpenAI key. Provider charges may apply. The PC works through them; you can close this.',
            'Continue with 3. Run again on 3 items. Replace. 3 AI calls on the PC’s OpenAI key; provider charges may apply.',
            'Retry 2 failed. 2 videos. Same options as this run. Uses a saved copy or downloads it, then frames and transcription. Several minutes per video; AI and transcription charges may apply.',
            'Next 25. 25 AI calls on this phone’s OpenAI key. Provider charges may apply.'])

    def test_each_step_has_its_own_key_message(self):
        out = run("""
            console.log(JSON.stringify([t.KEY_MSG.describe, t.KEY_MSG.index, t.KEY_MSG.analyze, t.KEY_MSG.thumb, t.PC_NO_KEY === t.KEY_MSG.categorize,
              t.STEPS.index.charge, t.STEPS.analyze.charge, t.STEPS.thumb.charge]))
        """)
        self.assertEqual(out[0], 'API key required: on the PC open Settings > API keys.')
        self.assertIn('Embeddings key required', out[1])
        self.assertIn('Choose None under AI report', out[2])
        self.assertEqual(out[3:], ['', True, 'embed', 'analyze', 'none'])

    def test_lines_summary_and_next_key(self):
        out = run("""
            const items = st => st.map(s => ({ st: s }))
            const a = t.tally(items(['done', 'done', 'skip', 'err', 'wait', 'run']))
            console.log(JSON.stringify([
              t.whereLine('phone', 'OpenAI', 'gpt-6-luna'), t.whereLine('pc', 'OpenAI', 'gpt-6-luna'), t.whereLine('pc', '', ''),
              t.runNote('phone', false), t.runNote('phone', true), t.runNote('pc', false), t.runNote('pc', false, true), t.stopLabel(false), t.stopLabel(true),
              t.savedLine('phone'), t.savedLine('solo'), t.savedLine('pc'),
              a, t.summary(a, 'describe'), t.summary(t.tally(items(['done'])), 'categorize'),
              t.nextKey(a, false, 0), t.nextKey({ done: 1, skip: 0, err: 0, left: 4 }, true, 30), t.nextKey({ done: 25, skip: 0, err: 0, left: 0 }, false, 55),
              t.nextKey({ done: 2, skip: 0, err: 0, left: 0 }, false, 0), t.nextKey({ done: 2, skip: 0, err: 0, left: 3 }, false, 0),
              t.pcBusy('Fetch link info', 30, 80, 'Describe').rest, t.scopeText(true, 'Art', 1), t.scopeText(false, 'Art', 12),
              t.STEPS.describe.line(12), t.STEPS.analyze.line(1), t.callsLine(0), t.callsLine(1),
            ]))
        """)
        self.assertEqual(out, [
            'Runs on this phone with its OpenAI key · gpt-6-luna. Tap a step to start it.',
            'Runs on your PC · OpenAI gpt-6-luna. Tap a step to start it.', 'Runs on your PC. Tap a step to start it.',
            'Stop finishes this item first. Each result is saved as it lands. Closing this keeps it going while the app stays open.',
            'Stopping after this item…', 'Runs on your PC. Close this any time: the PC keeps going.',
            'Runs on your PC, joined to a running analysis. Stop ends the whole PC job. Close this any time.', 'Stop', 'Stop PC job',
            'Saved on this phone. It reaches the PC at the next sync.', 'Saved on this phone.', 'Saved on the PC.',
            {'done': 2, 'skip': 1, 'err': 1, 'left': 2}, '2 described · 1 skipped · 1 failed', '1 sorted',
            {'act': 'retry', 'text': 'Retry 1 failed'}, {'act': 'continue', 'text': 'Continue with 4'},
            {'act': 'next', 'text': 'Next 25'}, None, None,
            'Fetch link info, 30 of 80. One job at a time; Describe can start when it ends.', 'This item', 'Art · 12',
            '12 without a summary', '1 video', '', '1 AI call'])

    def test_the_running_ledger_shows_six_from_two_before_the_current(self):
        out = run("""
            const items = (n, cur) => Array.from({ length: n }, (_, i) => ({ id: i + 1, st: i < cur ? 'done' : i === cur ? 'run' : 'wait' }))
            const ids = xs => xs.map(x => x.id)
            console.log(JSON.stringify([ids(t.ledgerWindow(items(4, 1))), ids(t.ledgerWindow(items(25, 0))),
              ids(t.ledgerWindow(items(25, 10))), ids(t.ledgerWindow(items(25, 24)))]))
        """)
        self.assertEqual(out, [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6], [9, 10, 11, 12, 13, 14], [20, 21, 22, 23, 24, 25]])


if __name__ == '__main__':
    unittest.main()
