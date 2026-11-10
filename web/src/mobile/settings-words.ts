import { lang, t, type Key } from '../lib/i18n/index.ts'
import { captureError } from './capture-words.ts'
import { fmtNum } from '../lib/i18n/format.ts'
import type { PhoneWords } from './mirror/phone-state'

export const phoneWords: PhoneWords = (key, params) => t(key as Key, key === 'backup.task.sizeMb' || key === 'backup.task.sizeGb'
  ? { size: lang() === 'en' ? (params!.n as number).toFixed(params!.digits as number) : fmtNum(params!.n as number, 'en', { useGrouping: false, minimumFractionDigits: params!.digits as number, maximumFractionDigits: params!.digits as number }) } : params)
export const phoneLocale = () => lang() === 'en' ? 'en-GB' : lang() === 'fr' ? 'fr' : 'zh-Hant-TW'

const LAMPS: Record<string, Key> = {
  "PC update needed": "backup.state.pcUpdateLamp",
  "update app": "backup.state.updateLamp",
  "paused": "settings.lamp.paused",
  "running": "settings.lamp.running",
  "queued": "settings.lamp.queued",
  "idle": "settings.lamp.idle",
  "stopping": "settings.lamp.stopping",
  "off": "settings.lamp.off",
  "needs Drive": "settings.lamp.needs_Drive",
  "held": "settings.lamp.held",
  "error": "settings.lamp.error",
  "waiting for PC": "settings.lamp.waiting_for_PC",
  "waiting": "settings.lamp.waiting",
  "in step": "settings.lamp.in_step",
  "not run yet": "settings.lamp.not_run_yet",
  "no folder": "settings.lamp.no_folder",
  "access pending": "settings.lamp.access_pending",
  "license required": "settings.lamp.license_required",
  "sign in": "settings.lamp.sign_in",
  "offline": "settings.lamp.offline",
  "syncing": "settings.lamp.syncing",
  "connecting": "settings.lamp.connecting",
  "no library yet": "settings.lamp.no_library_yet",
  "connected": "settings.lamp.connected",
  "not reachable": "settings.lamp.not_reachable",
  "access removed": "settings.lamp.access_removed",
  "PC changed": "settings.lamp.PC_changed",
  "license off": "settings.lamp.license_off",
  "update needed": "settings.lamp.update_needed",
  "check failed": "settings.lamp.check_failed"
}
export const lampLabel = (id: string): string => Object.hasOwn(LAMPS, id) ? t(LAMPS[id]) : id
export const connectLabel = (step: string): string => t('settings.connect.busy', { step: step === 'Waiting for Google'
  ? t('settings.connect.waitingGoogle') : step === 'Checking the account' ? t('settings.connect.checkingAccount') : step || t('settings.connect.connecting') })

export type NativeOperation = 'google' | 'scanner' | 'secure' | 'network' | 'vault' | 'recovery' | 'backup' | 'openUri'
const ERRORS: Record<string, Key> = {
  "google:replaced": "shared.native.google.replaced",
  "google:write": "shared.native.secure.write",
  "scanner:write": "shared.native.secure.write",
  "recovery:write": "shared.native.secure.write",
  "backup:write": "shared.native.secure.write",
  "google:denied": "shared.native.google.denied",
  "google:consent": "shared.native.google.consent",
  "google:failed": "shared.native.google.failed",
  "google:timeout": "shared.native.google.timeout",
  "google:renewal-timeout": "shared.native.google.renewal-timeout",
  "scanner:failed": "shared.native.scanner.failed",
  "secure:write": "shared.native.secure.write",
  "network:timeout": "shared.native.network.timeout",
  "network:network": "shared.native.network.network",
  "recovery:kit-in-code": "shared.native.recovery.kit-in-code",
  "recovery:passphrase-mismatch": "shared.native.recovery.passphrase-mismatch",
  "recovery:file-limit": "shared.native.recovery.file-limit",
  "backup:pc-managed": "shared.native.backup.pc-managed",
  "backup:library-changed": "shared.native.backup.library-changed",
  "backup:account": "shared.native.backup.account",
  "backup:saved-task": "shared.native.backup.saved-task",
  "backup:select-backup": "shared.native.backup.select-backup",
  "backup:task-changed": "shared.native.backup.task-changed",
  "backup:identity": "shared.native.backup.identity",
  "backup:paused": "shared.native.backup.paused",
  "backup:replacement-missing": "shared.native.backup.replacement-missing",
  "backup:replacement-duplicate": "shared.native.backup.replacement-duplicate",
  "backup:replacement-verification": "shared.native.backup.replacement-verification",
  "backup:replacement-retained": "shared.native.backup.replacement-retained",
  "recovery:material": "shared.native.recovery.material",
  "recovery:fingerprint": "shared.native.recovery.fingerprint",
  "recovery:unsupported": "shared.native.recovery.unsupported",
  "recovery:identity": "shared.native.recovery.identity",
  "recovery:name": "shared.native.recovery.name",
  "recovery:missing-setup": "shared.native.recovery.missing-setup",
  "recovery:setup-mismatch": "shared.native.recovery.setup-mismatch",
  "recovery:verification": "shared.native.recovery.verification",
  "recovery:select-file": "shared.native.recovery.select-file",
  "recovery:other-backup": "shared.native.recovery.other-backup",
  "recovery:prepare-first": "shared.native.recovery.prepare-first",
  "recovery:changed-while-saving": "shared.native.recovery.changed-while-saving",
  "recovery:eligibility-paired_pc": "recovery.eligibility.paired_pc",
  "recovery:eligibility-not_connected": "recovery.eligibility.not_connected",
  "recovery:eligibility-no_upload": "recovery.eligibility.no_upload",
  "recovery:eligibility-other_library": "recovery.eligibility.other_library",
  "recovery:eligibility-not_latest": "recovery.eligibility.not_latest",
  "recovery:eligibility-busy": "recovery.eligibility.busy",
  "recovery:eligibility-interrupted": "recovery.eligibility.interrupted"
}
// Call only after classifying cancellation; native messages/codes remain intact for their existing catches.
export function nativeError(operation: NativeOperation, error: unknown): string {
  const e = error as { code?: unknown; message?: unknown; displayKey?: Key } | null
  const detail = String(e?.message ?? error)
  if (lang() === 'en') return detail
  if (e?.displayKey) return captureError(e)
  const code = typeof e?.code === 'string' ? e.code : ''
  const id = `${operation}:${code}`
  return phoneWords(Object.hasOwn(ERRORS, id) ? ERRORS[id] : `shared.native.${operation}.detail`, { detail })
}
