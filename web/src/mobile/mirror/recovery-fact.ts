// What protects the key of the phone without a PC (phone-state.ts `recovery`), read by the status (state.svelte.ts
// phoneFacts), Setup's Recovery row and the Recovery group of Backup & phones: a setup this phone remembers for its own
// key and the confirmed Google account, then whether its recovery file was saved (a receipt from the app's folder, or a
// browser download asked for this session, as the PC page counts one) and checked against Drive. A setup for another
// account or key, or a damaged one, is none. Apart from phone-recovery.ts, which reaches Google Drive: reading the fact
// loads only the recovery file format.
import type { Pairing } from './pairing'
import type { PhoneFacts } from './phone-state'
import { readPhoneKit } from './recovery-envelope'

let downloaded = ''   // the generation whose recovery file this browser session asked to download (savePhoneKit)
export function downloadAsked(generation: string) { downloaded = generation }

export function recoveryFact(pair: Pairing): PhoneFacts['recovery'] {
  const r = pair.recovery
  if (!r || !pair.g) return 'none'
  try { readPhoneKit(JSON.stringify(r.kit)) } catch { return 'none' }
  const h = r.kit.record.header
  if (h.fingerprint !== pair.f || h.account.toLowerCase() !== pair.g.toLowerCase()) return 'none'
  return r.verified ? 'checked' : r.saved || downloaded === h.generation ? 'saved' : 'prepared'
}
