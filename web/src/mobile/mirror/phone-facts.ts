// The facts the status model reads (phone-state.ts), from what a phone paired with a PC holds (pairedFacts) and what the
// phone without a PC holds (soloFacts): pure functions, so Node checks them against the states of
// tests/fixtures/phone_states.json (tests/test_phone_screens.py). state.svelte.ts phoneFacts() gathers the inputs. Its
// one runtime import names its file (phone-state.ts has none), so Node runs it as it is.
import type { NoLibraryWhy } from './diagnose'
import type { AccessKind } from './license'
import { clock, type PhoneFacts } from './phone-state.ts'

export interface PairedInput {
  app: boolean                 // the Android app (native.ts isApp)
  online: boolean              // network.online
  paused: boolean              // syncPaused(): offline, or Wi-Fi only on another network
  refreshing: boolean          // a library read runs now
  tried: boolean               // a library read has finished since the app started
  token: boolean               // pairing.ts token(): a Google token for the confirmed account is held, not expired
  refused: boolean             // phone.signIn: the last read had no token, or Google refused it
  account: string              // the account confirmed on this phone (pairing `g`), '' none
  pcAccount: string            // the account the PC backs up to (pairing `e`), '' unknown
  mismatch: string             // the account the last sign-in gave when it is not the PC's (phone.account), else ''
  access: '' | AccessKind      // network.licenseKind: why the last access check refused, '' when it did not
  accessAt: number             // network.licenseAt: when the refused confirmation was issued (ms), 0 unknown
  last: number                 // license.ts lastAccess(f).at: when this pairing last had access (ms), 0 never
  noLibrary: NoLibraryWhy | null   // phone.noLibraryWhy while the last read found no library
  reachable: boolean           // the last library read worked
  tooOld: boolean              // the PC's copy needs a newer app
  checked: string              // fmtAgo of the last read ("2 min ago"), '' never
  pend: { unsent: number; waiting: number; resending: number }   // phone.pend: the change journal now
  now: number                  // ms; phone.now, so the words follow the clock
}

// Before the first read has finished the phone does not ask for a sign-in: the start renews an expired token once
// (state.svelte.ts renewSignIn) and the state says Connecting meanwhile. A confirmed account whose token ran out or
// was refused is "sign in again"; a pairing with no confirmed account is "connect".
export function pairedFacts(i: PairedInput): PhoneFacts {
  return {
    mode: 'pc', app: i.app, online: i.online, wifiWait: i.online && i.paused, refreshing: i.refreshing, tried: i.tried,
    signedIn: !i.refused && (i.token || !i.tried), account: i.account, pcAccount: i.pcAccount, mismatch: i.mismatch,
    access: i.access, hadAccess: i.last > 0, since: clock(i.access === 'expired' ? i.accessAt : i.last, i.now),
    noLibrary: i.noLibrary?.cause ?? '', noLibraryText: i.noLibrary?.message ?? '', reachable: i.reachable, tooOld: i.tooOld,
    checked: i.checked, unsent: i.pend.unsent, waiting: i.pend.waiting, resending: i.pend.resending, recovery: 'none',
  }
}

export interface SoloInput {
  app: boolean                 // the Android app (native.ts isApp)
  online: boolean              // network.online
  paused: boolean              // syncPaused(): offline, or Wi-Fi only on another network
  refreshing: boolean          // a round runs now
  started: boolean             // phone.tried: a refresh has finished since the app started
  token: boolean               // pairing.ts token(): a Google token for the confirmed account is held, not expired
  account: string              // the account confirmed on this phone (pairing `g`), '' none
  round: { ok: boolean; ago: string } | null   // MirrorSource.round: the last backup round and fmtAgo of it; null none yet
  recovery: PhoneFacts['recovery']             // recovery-fact.ts recoveryFact()
  unsent: number               // edits not backed up yet (phone.pend.unsent)
}

// Without a PC the phone says Backed up only after a round that sent what was queued and read Drive back (the round,
// set by MirrorSource.rows); a failed round is "could not be reached". Before the first refresh has finished a confirmed
// account is not asked to sign in again (the app renews an expired token at the start), as for a paired phone.
export function soloFacts(i: SoloInput): PhoneFacts {
  return {
    mode: 'solo', app: i.app, online: i.online, wifiWait: i.online && i.paused, refreshing: i.refreshing, tried: !!i.round,
    signedIn: i.token || (!!i.account && !i.started), account: i.account, pcAccount: '', mismatch: '', access: '',
    hadAccess: false, since: '', noLibrary: '', noLibraryText: '', reachable: !!i.round?.ok, tooOld: false,
    checked: i.round?.ok ? i.round.ago : '', unsent: i.unsent, waiting: 0, resending: 0, recovery: i.recovery,
  }
}

// Unpair's first tap (plan P10): the edits that never reach the PC once this phone unpairs. The journal stays on the
// phone, and an edit already sent still reaches a PC that runs, unless the PC refused this phone's access: then only
// pairing again sends it (sub-plan 02).
export function unpairEdits(p: { unsent: number; waiting: number; held: number }, refused: boolean): number {
  return p.unsent + p.held + (refused ? p.waiting : 0)
}
export const unpairWarning = (n: number) => !n ? '' : n === 1
  ? "1 edit hasn't reached your PC yet. If you unpair now, it never will."
  : `${n} edits haven't reached your PC yet. If you unpair now, they never will.`
