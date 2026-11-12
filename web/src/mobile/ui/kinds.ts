import type { Kind } from '../settings-steps'
export const KIND_PATH: Record<Kind, string> = {
  done: 'M2 6l3 3 5-6', working: '', attention: 'M6 2v5m0 2v1', failed: 'M3 3l6 6m0-6L3 9',
  paused: 'M4 2v8m4-8v8', waiting: 'M6 3v3l2 1M6 1a5 5 0 1 0 0 10 5 5 0 0 0 0-10', empty: '',
}
