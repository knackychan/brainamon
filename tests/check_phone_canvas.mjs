import { readFileSync } from 'node:fs'
import { normalizeCanvas, pyRound, applyCanvasLocal } from '../web/src/mobile/ai/canvas.ts'

const cases = JSON.parse(readFileSync(new URL('./fixtures/canvas_proposals.json', import.meta.url)))
const out = cases.map(raw => {
  try { return { ok: normalizeCanvas(raw) } }
  catch (e) { return { error: String(e.message) } }
})
const layout = applyCanvasLocal(normalizeCanvas({ new_name: 'A', elements: [
  { kind: 'text', text: 'A', group: 'First' }, { kind: 'text', text: 'B', group: 'First' },
  { kind: 'text', text: 'C', x: 0, y: 0 },
] }), null, new Map(), 'b'.repeat(32), 'a'.repeat(32), 123)
process.stdout.write(JSON.stringify({ out, round: [pyRound(0.5), pyRound(1.5), pyRound(2.5), pyRound(-0.5), pyRound(-1.5)], layout }))
