// What the phone says about Google Drive (the app bar lamp, More > Google Drive). The lamp used to
// read "offline" whenever the last refresh failed, or had not finished yet, even with Drive signed in
// and answering: a refresh that found no library (the PC has not finished its first upload), or met
// a file Drive no longer has, is Drive replying, not Drive out of reach. Only a failed network call is.
import { DriveError, NeedsSignIn } from './drive'

// Google replied (a refusal, a missing file), so Drive is reachable; no reply (status 0) is not
export function answered(e: unknown): boolean {
  return e instanceof DriveError && !(e instanceof NeedsSignIn) && e.status > 0
}

export interface DriveFacts {
  online: boolean        // the phone has signal
  refreshing: boolean
  tried: boolean         // a refresh has finished since the app started
  signedIn: boolean      // a Google token is held
  signIn: boolean        // Google refused it, or the user disconnected
  answered: boolean      // the last Drive call got a reply
  noLibrary: boolean     // the last refresh found no manifest in Drive
}
// the last six: a refused access check, with the status model's lamp (state.svelte.ts driveStatus)
export type DriveLamp = 'access pending' | 'license required' | 'sign in' | 'offline' | 'syncing' | 'connecting' | 'no library yet' | 'connected' | 'not reachable'
  | 'access removed' | 'PC changed' | 'waiting for PC' | 'license off' | 'update needed' | 'check failed'

export function driveLamp(f: DriveFacts): DriveLamp {
  if (f.signIn || !f.signedIn) return 'sign in'
  if (!f.online) return 'offline'
  if (f.refreshing) return 'syncing'
  if (!f.tried) return 'connecting'
  if (f.noLibrary) return 'no library yet'
  return f.answered ? 'connected' : 'not reachable'
}

// Which Google account this phone may use. After a reset the app used to take whatever account
// Google remembered for it, without asking. `e`: the account the PC uploads to (from the pairing; ''
// without a PC or when the PC had not read it), `g`: the one the user confirmed on this phone (a
// reset wipes it), `got`: the one Google just signed in. 'mismatch': the PC's mirror is not there.
export type AccountCheck = 'ok' | 'confirm' | 'mismatch'
const sameAccount = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
export function accountCheck(e: string, g: string | undefined, got: string): AccountCheck {
  if (e && !sameAccount(e, got)) return 'mismatch'
  return g && sameAccount(g, got) ? 'ok' : 'confirm'
}
// Drive is called only for a confirmed account (or the development Drive, which takes any token)
export const accountConfirmed = (p: { d?: string; g?: string }) => !!p.g || (import.meta.env?.DEV === true && !!p.d && /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:[0-9]+)?(\/|$)/.test(p.d))
