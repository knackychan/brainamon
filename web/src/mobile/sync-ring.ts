// The sync key's ring (projects/phone-dock-shell, mockups/sync-v4.html): what the 36 px circle draws for the
// phone's sync state. The arc is progress, the colour (tone) is the state, no words. Pure, so the Node tests
// run it (tests/test_phone_shell.py); SyncKey.svelte gathers the facts.
export type RingTone = 'ok' | 'run' | 'warn' | 'paused' | 'pull'
export type RingGlyph = 'check' | 'sync' | 'warn' | 'pause' | 'down'
export interface RingFacts {
  pull: number               // how far the finger pulled, 1 = far enough (Mobile.svelte); 0 when not pulling
  running: boolean           // Sync now, a refresh, or a vault / picture lane at work
  fill: number | null        // that work's progress 0..1, null when unknown
  manualPause: boolean       // Pause sync (network.svelte.ts)
  waiting: boolean           // paused by the network rules: Wi-Fi only, or the app in the background
  problem: boolean           // the lamp's amber rule, or the last run failed
}
export interface Ring { tone: RingTone; glyph: RingGlyph; frac: number; spin: boolean; turn: number }

// the ring's length: radius 11 in a 28 x 28 box
export const RING_C = 2 * Math.PI * 11
// the mockup's glyphs, 700 12px mono
export const GLYPH: Record<RingGlyph, string> = { check: '✓', sync: '↻', warn: '!', pause: '‖', down: '↓' }

const clamp = (n: number) => Math.min(1, Math.max(0, n))

export function ringOf(f: RingFacts): Ring {
  if (f.pull > 0) {
    const p = clamp(f.pull)
    return { tone: p >= 1 ? 'run' : 'pull', glyph: 'down', frac: p, spin: false, turn: Math.round(p * 180) }
  }
  if (f.running) return { tone: 'run', glyph: 'sync', frac: Math.max(0.05, clamp(f.fill ?? 0.25)), spin: true, turn: 0 }
  if (f.manualPause || f.waiting) return { tone: 'paused', glyph: 'pause', frac: 0, spin: false, turn: 0 }
  if (f.problem) return { tone: 'warn', glyph: 'warn', frac: 1, spin: false, turn: 0 }
  return { tone: 'ok', glyph: 'check', frac: 1, spin: false, turn: 0 }
}
