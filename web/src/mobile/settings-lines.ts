// The one-line state and the dot of each row on Settings and Backup & phones (projects/phone-settings, spec
// docs/superpowers/specs/2026-11-07-phone-settings-design.md sections 2.2 and 3.4): words from data the page already
// has, at most 33 characters for every fixed line (one line beside a dot and a chevron at 320 px; a name the person
// chose, an account or a vault, ends in an ellipsis). Run by Node in the tests (type stripping): no imports.
export type Tone = 'done' | 'todo' | 'next' | 'busy'
interface Status { id: string; tone: Tone; action: { id: string } | null }

// the status ids that speak about syncing (the Sync row takes their dot); every other id speaks about the pairing,
// the Google account or recovery (the Your phone / Your PC row takes it)
export const SYNC_IDS = ['paused', 'offline', 'wifi', 'connecting', 'unreachable', 'resending', 'in-sync', 'solo-local', 'solo-ok', 'first-backup', 'no-library']
const GOOGLE_ACTIONS = ['connect', 'sign-in-again', 'change-account', 'back-up']
const ACCESS_IDS = ['replaced', 'removed', 'confirming', 'waiting-pc', 'license', 'access-invalid', 'webview']
export type LineWords = (key: string, params?: Record<string, unknown>) => string
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

// Settings: the dots of Sync, Your phone / Your PC and Wiskit on this phone
export function settingsTones(st: Status | null, o: { running: boolean; driveOk: boolean; ai: boolean }): { sync: Tone; phone: Tone; ai: Tone } {
  const sync = !!st && SYNC_IDS.includes(st.id)
  return {
    sync: st && sync ? st.tone : o.running ? 'busy' : o.driveOk ? 'done' : 'todo',
    phone: st && !sync ? st.tone : 'done',
    ai: o.ai ? 'done' : 'todo',
  }
}

// Sync: `lamp` is the Sync lamp ('idle' when nothing runs, waits or is refused)
export function syncLine(o: { signedIn: boolean; lamp: string; wifiOnly: boolean }, words?: LineWords): string {
  if (!o.signedIn) return (words?.('settings.sync.noDrive') ?? 'Google Drive not connected')
  if (o.lamp !== 'idle') return o.lamp
  return (words?.('settings.sync.automatic', { network: words(o.wifiOnly ? 'settings.sync.wifi' : 'settings.sync.anyNetwork') }) ?? `${o.wifiOnly ? 'Wi-Fi only' : 'Any network'} · runs on its own`)
}

export const phoneLine = (solo: boolean, fingerprint: string, words?: LineWords): string => solo ? (words?.('settings.phone.solo') ?? 'Saving here · a PC is optional') : (words?.('settings.phone.paired', { fingerprint }) ?? `Paired · key ${fingerprint}`)

// Wiskit on this phone: `provider` is the key's provider label (Anthropic, OpenAI), '' without a key
export const aiLine = (provider: string, solo: boolean, words?: LineWords): string => provider ? (words?.('settings.keys.providerLine', { provider }) ?? `${provider} on your key`) : solo ? (words?.('settings.keys.noKey') ?? 'No AI key yet') : (words?.('settings.keys.pairKey') ?? 'No AI key · pair again')

// Obsidian: the vault name, then the vault lamp while the vault syncs with the PC (Android app, paired)
export function vaultLine(o: { name: string; syncing: boolean; lamp: string }, words?: LineWords): string {
  if (!o.name) return o.syncing ? (words?.('settings.vault.unnamedSync', { lamp: o.lamp }) ?? `Vault name not set · ${o.lamp}`) : (words?.('settings.vault.notNamed') ?? 'Vault name not set')
  return o.syncing ? (words?.('settings.vault.namedSync', { name: o.name, lamp: o.lamp }) ?? `${o.name} · ${o.lamp}`) : o.name
}
// its dot, only while the vault syncs: running or queued needs no tap (teal), in step is done, off or never run is
// nothing to do here, the rest needs a look
export function vaultTone(lamp: string, syncing: boolean): Tone | undefined {
  if (!syncing) return undefined
  if (lamp === 'syncing' || lamp === 'queued' || lamp === 'stopping') return 'busy'
  if (lamp === 'in step') return 'done'
  if (lamp === 'off' || lamp === 'no folder' || lamp === 'not run yet' || lamp === 'paused') return 'todo'
  return 'next'
}

const KEEPS: Record<string, string> = {
  'off-0': 'keeps favourites', 'off-1': 'favs, canvases', 'fav-0': 'keeps fav videos', 'fav-1': 'fav videos, canvases',
  'all-0': 'favs, videos', 'all-1': 'favs, canvases, videos',
}
// Storage: the meter's total (fmtMB), then what is kept automatically
export const storageLine = (total: string, canvases: boolean, videos: string, words?: LineWords): string => (words?.('settings.storage.summary', { total, keeps: words('settings.storage.keeps.' + (Object.hasOwn(KEEPS, `${videos}-${canvases ? 1 : 0}`) ? `${videos}-${canvases ? 1 : 0}` : 'off-0')) }) ?? `${total} · ${KEEPS[`${videos}-${canvases ? 1 : 0}`] ?? KEEPS['off-0']}`)

// Look: the card style's label (Auto, Cover, Holo) and the night switch
export const lookLine = (style: string, night: boolean, words?: LineWords): string => (words?.('settings.look.summary', { style, night: words(night ? 'settings.look.on' : 'settings.look.off') }) ?? `${style} cards · night ${night ? 'on' : 'off'}`)

// About: the Windows app while Settings shows it (not paired), the app's version in the Android app, then the licenses
export function aboutLine(o: { desktop: boolean; version: string }, words?: LineWords): string {
  const v = o.version ? (o.desktop ? `v${o.version}` : (words?.('settings.about.versionLine', { version: o.version }) ?? `Version ${o.version}`)) : ''
  return [o.desktop ? (words?.('settings.about.windowsApp') ?? 'Windows app') : '', v, (words?.('settings.about.licenses') ?? 'licenses')].filter(Boolean).join(' · ')
}

// Backup & phones: the Google account row. The address alone when connected, "Sign in" when not, the model's lamp
// (capitalised, "Access removed") while a paired phone's access is refused or Drive is not usable
export function googleLine(o: { signedIn: boolean; account: string; driveOk: boolean; lamp: string; solo: boolean }, words?: LineWords): string {
  if (!o.signedIn) return (words?.('settings.account.signIn') ?? 'Sign in')
  if (!o.driveOk && !o.solo) return cap(o.lamp)
  return o.account || (words?.('settings.account.signedIn') ?? 'Signed in')
}
export function googleTone(st: Status | null, o: { signedIn: boolean; driveOk: boolean; busy: boolean }): Tone {
  if (st && (ACCESS_IDS.includes(st.id) || (st.action && GOOGLE_ACTIONS.includes(st.action.id)))) return st.tone
  if (o.busy) return 'busy'
  return o.signedIn && o.driveOk ? 'done' : 'todo'
}

// This phone: its name and what it has not sent (paired), or what is not backed up yet (without a PC)
export function thisPhoneLine(o: { solo: boolean; name: string; unsent: number }, words?: LineWords): string {
  if (o.solo) return (words?.('settings.phone.soloSummary', { pending: o.unsent ? words('settings.phone.unbacked', { n: o.unsent }) : words('backup.state.allBacked') }) ?? `${o.unsent ? `${o.unsent} not backed up` : 'All backed up'} · no PC paired`)
  return (words?.('settings.phone.pcSummary', { name: o.name || words('settings.phone.defaultName'), pending: o.unsent ? words('settings.phone.unsent', { n: o.unsent }) : words('settings.phone.allSent') }) ?? `${o.name || (words?.('settings.phone.defaultName') ?? 'This phone')} · ${o.unsent ? `${o.unsent} not sent` : 'all sent'}`)
}
export function thisPhoneTone(st: Status | null, unsent: number): Tone {
  if (st?.action && (st.action.id === 'send' || st.action.id === 'scan')) return st.tone
  return unsent ? 'todo' : 'done'
}

// Recovery: managed on the PC (paired), else what protects this phone's key (mirror/recovery-fact.ts)
const FACT: Record<string, string> = { none: 'Not set up', prepared: 'Passphrase set', saved: 'File saved, not checked', checked: 'Passphrase set · file checked' }
export const recoveryLine = (solo: boolean, fact: string, words?: LineWords): string => solo ? (words?.('settings.recovery.' + (Object.hasOwn(FACT, fact) ? fact : 'none')) ?? FACT[fact] ?? FACT.none) : (words?.('settings.recovery.pc') ?? 'Managed on your PC')
export function recoveryTone(st: Status | null, solo: boolean, fact: string): Tone {
  if (!solo) return 'todo'
  if (st && (st.id === 'solo-recovery' || st.id === 'solo-check-file')) return st.tone
  return fact === 'prepared' || fact === 'checked' ? 'done' : 'todo'
}
