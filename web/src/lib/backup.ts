// Backup & phones: the words (README of projects/backup-phones-mockup, D8), the shapes of /api/cloud and
// /api/cloud/recovery, and the formatting the page, the Recover window and the rail's Jobs module share.
import type { RecoveryActivity } from './recovery'

export const W = {
  backUp: 'Back up to Google Drive', turnOn: 'Turn on backup', signInAgain: 'Sign in again', switchAccount: 'Switch account…',
  stop: 'Disconnect Google Drive…', stopGo: 'Disconnect', pause: 'Pause backup', resume: 'Resume backup',
  backupTitle: 'Backup', googleTitle: 'Google account', phonesTitle: 'Phones', file: 'recovery file',
  saveFile: 'Save recovery file…', saveNewFile: 'Save new recovery file…', checkFile: 'Check recovery file…',
  createPass: 'Create recovery passphrase', changePass: 'Change passphrase…', addPhone: 'Add a phone',
  removeAll: 'Remove all phones…', removeAllGo: 'Remove all phones', recover: 'Recover a library…',
  keepFolder: 'Keep this folder', copyNew: 'Copy into new folder', takeOver: 'Make this PC the backup PC…',
  takeOverGo: 'Make this PC the backup PC', findBackup: 'Find backup',
} as const

// the long task of server/sync.py `_task_view`: removing phones, saving a passphrase, switching account, resetting, a one-time backup
export interface CloudTask {
  id: string; kind: 'remove_phones' | 'enroll' | 'switch_account' | 'reset_backup' | 'one_shot_publish' | 'update_folder'; stage: string; title: string
  step: number; of: number; steps: { label: string; state: 'done' | 'active' | 'waiting' }[]
  done: number; total: number; bytes_done: number; bytes_total: number; since: number; error: string; code: string; lock: string
}
export interface PhoneRecord { device: string; name: string; seen: number }

export interface CloudView {
  recovery_activity?: RecoveryActivity | null; upload_step?: string; upload_since?: number
  licensed: boolean; rotation?: string; rotation_lock?: string; rotation_locked_at?: number; rotation_locked_by?: number; ignored_changes?: number
  paused_since?: number; key_missing?: boolean; task?: CloudTask | null
  token_expired?: boolean; token_issued?: number; error_code?: string; error_action?: string; error_at?: number; error_account?: string
  phones?: PhoneRecord[] | null
  seq: number; on: boolean; running: boolean; signed_in: boolean; configured: boolean
  state: 'locked' | 'off' | 'idle' | 'signing-in' | 'starting' | 'publishing' | 'stopping' | 'disconnecting' | 'error' | 'signed-out'
  done: number; total: number; bytes_done?: number; bytes_total?: number; error: string; files: number; size: number; last_publish: number; last_summary: string
  skipped?: number; skipped_note?: string      // files the last backup left out because recovery would refuse their size, and the sentence about them ('' for none)
  account: string; used: number; limit: number; options: { videos: 'off' | 'fav' | 'all'; canvases: boolean }
  phone_url: string; web_client: boolean; phone_keys: string[]; last_intake: number; intake_summary: string
  vault: { on: boolean; folder: string }; vault_running: boolean
  vault_devices: { device: string; ok: boolean }[] | null
  vault_members: string[]
  vault_state: 'locked' | 'off' | 'starting' | 'idle' | 'syncing' | 'stopping' | 'brake' | 'error'; vault_reason: string; vault_summary: string; vault_last: number
  vault_step: string; vault_done: number; vault_total: number; vault_since: number
  vault_skipped?: number; vault_skipped_note?: string      // files the last vault round left out for their size, and the sentence about them ('' for none)
}
export interface Sizes { base: number; canvases: number; videos_fav: number; videos_all: number; videos_fav_count: number; videos_all_count: number }

export interface RecoveryPreview {
  items: number; files: number; bytes: number; published: number; videos: string; canvases: boolean; omissions: string[]; duplicates: number
  generation: { created: number; fingerprint: string } | null; notice: string; reconnect: { ok: boolean; reason: string; message: string }
  password_known: boolean      // the passphrase typed to find the backup is kept in memory for Keep this folder (D3)
  fingerprint?: string         // the found backup's key: this folder's own offers Update this folder (W4b)
}
export interface RecoveryJob { state: string; done: number; total: number; error: string; destination: string }
export interface Readiness { state: string; message: string; account: string; enrolled: boolean; code?: string; action?: string }
// Update this folder (S9): whether this folder can take the newer backup another PC made with the same key, and its cost
export interface UpdateCheck {
  eligible: boolean; reason: string; message: string; bytes?: number; files?: number; nothing?: boolean; local_changes?: number
  published?: number; owner_at?: number; last_backup?: number; account?: string
}
// the last update that finished here: the changes made here after the last backup stay in `folder`
export interface UpdateDone { at: number; published: number; kept: number; folder: string }
export interface RecoveryView {
  configured: boolean; enrolled: boolean; verified: boolean; verified_at: number; saved_at?: number; setup_at?: number; fingerprint: string; account: string
  restored: boolean; restart_required: boolean; rotation_pending: boolean; preview: RecoveryPreview | null
  file_outdated?: boolean; replaced_at?: number; takeover_ready?: boolean
  activity?: RecoveryActivity | null; check?: Readiness | null
  update?: UpdateCheck | null; updated?: UpdateDone | null
  job: RecoveryJob
}

export const SEC = 1000, MIN = 60 * SEC, HOUR = 60 * MIN, DAY = 24 * HOUR
const GIB = 1073741824

export const hm = (t: number) => new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
export const day = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
export const gb = (b: number) => (b / GIB).toFixed(1)
export const amount = (b: number) => b < GIB ? `${Math.max(1, Math.round(b / 1048576))} MB` : `${gb(b)} GB`
export const num = (x: number) => Math.round(x).toLocaleString('en')
export const dur = (ms: number) => ms < MIN ? `${Math.max(0, Math.round(ms / SEC))} s` : ms < HOUR ? `${Math.round(ms / MIN)} min` : `${(ms / HOUR).toFixed(1)} h`
// how long a pause has lasted: seconds and minutes as `dur`, then whole days ("3 days")
export const long = (ms: number) => ms < DAY ? dur(ms) : `${Math.floor(ms / DAY)} day${ms < 2 * DAY ? '' : 's'}`

// bytes sent over the last minute -> time left at that pace (null until there is a pace to read)
export interface Sample { t: number; bytes: number }
export function addSample(samples: Sample[], t: number, bytes: number): Sample[] {
  const last = samples[samples.length - 1]
  if (last && (bytes < last.bytes || t - last.t > 5 * MIN)) samples = []         // a new pass starts over
  if (last && last.t === t) return samples
  return [...samples.filter(s => t - s.t <= MIN), { t, bytes }]
}
export function timeLeft(samples: Sample[], done: number, total: number): number | null {
  const first = samples[0], last = samples[samples.length - 1]
  if (!first || !last || last.t - first.t < 5 * SEC || last.bytes <= first.bytes || total <= done) return null
  return (total - done) / ((last.bytes - first.bytes) / (last.t - first.t))
}

export const sameAccount = (a: string, b: string) => !!a && !!b && a.toLowerCase() === b.toLowerCase()
