// Why the phone found no library in Google Drive (MirrorSource.loadManifest: no file with the manifest's
// hashed name). The same words came out for five different causes. The phone lists its app data folder and
// tells them apart where it can; each answer says what to do next. No imports: Node runs this file.
//
//   uploading    files sealed with this phone's key are there, the manifest is not (the PC's first upload is running)
//   key          library files are there, none for this phone's key (the PC made a new key, or this phone paired earlier)
//   mirror-off   only the Obsidian vault is there: the PC uploads the vault but not the phone library
//   project      the folder is empty and this phone's sign-in app is in another Google Cloud project than the PC's
//   account      the folder is empty and the PC never said which account it uploads to, so none could be checked
//   empty        the folder is empty and the account is the PC's: the PC has not uploaded, or the project differs
//   unknown      the folder could not be listed

export type NoLibraryCause = 'uploading' | 'key' | 'mirror-off' | 'project' | 'account' | 'empty' | 'unknown'

export interface NoLibraryFacts {
  listed: string[] | null      // names in the app data folder, null when it could not be listed
  ours: boolean                // a file named with this phone's key is among them
  signedAs: string             // the account the user confirmed on this phone
  pcAccount: string            // the account the PC uploads to (from the pairing code), '' if it did not say
  pcProject: string            // the PC's Google Cloud project number (pairing code), '' if unknown
  phoneProject: string         // the project of this phone's sign-in app (Google's token info), '' if unknown
  problem?: string             // why listing failed
}
export interface NoLibraryWhy {
  cause: NoLibraryCause
  title: string               // a few words, for the sync widget
  message: string
  changeAccount: boolean       // offer Change account
  pairAgain: boolean           // offer Pair again
}

// library files have hashed names of 32 hex digits; vault files vb- / vi- / vs-, except the PC's recovery records
// (vi-recovery-, vi-phone-recovery-: library/recovery.py, mirror/recovery-envelope.ts); change files chg-; AI keys pky-
export const isLibraryName = (name: string) => /^[0-9a-f]{32}$/.test(name)
const isVaultName = (name: string) => /^v[bis]-/.test(name) && !/^vi-(phone-)?recovery-/.test(name)

// OAuth client ids start with the project number: 123456789-abc.apps.googleusercontent.com
export function projectOf(clientId: string): string {
  const m = /^(\d{6,})-/.exec(clientId.trim())
  return m ? m[1] : ''
}

export function diagnoseNoLibrary(f: NoLibraryFacts, words?: (key: string, params?: Record<string, unknown>) => string): NoLibraryWhy {
  const as = f.signedAs ? (words?.('backup.diagnose.account', { account: f.signedAs }) ?? `Signed in as ${f.signedAs}. `) : ''
  if (!f.listed) {
    return { cause: 'unknown', title: (words?.('backup.diagnose.unknown.title') ?? 'Could not look in Google Drive'), changeAccount: true, pairAgain: true,
      message: (words?.('backup.diagnose.unknown.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}No library in Google Drive for this pairing, and its folder could not be listed${f.problem ? ` (${f.problem})` : ''}. Try Sync again; if it stays, Change account or pair again.`) }
  }
  if (f.ours) {
    return { cause: 'uploading', title: (words?.('backup.diagnose.uploading.title') ?? 'The PC is still uploading'), changeAccount: false, pairAgain: false,
      message: (words?.('backup.diagnose.uploading.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}The PC has started its first upload to this account and has not finished. Sync again in a few minutes (PC: Settings > Backup & phones shows the progress).`) }
  }
  if (f.listed.some(isLibraryName)) {
    return { cause: 'key', title: (words?.('backup.diagnose.key.title') ?? "This phone's key is not the PC's"), changeAccount: false, pairAgain: true,
      message: (words?.('backup.diagnose.key.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}Google Drive holds a library, but not one this phone's key opens: the PC made a new key (Remove all phones or Reset backup), or this phone was paired before that. Pair again with the new code from your PC (Settings > Backup & phones > Add a phone).`) }
  }
  if (f.listed.some(isVaultName)) {
    return { cause: 'mirror-off', title: (words?.('backup.diagnose.mirror-off.title') ?? 'The PC is not uploading the library'), changeAccount: false, pairAgain: false,
      message: (words?.('backup.diagnose.mirror-off.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}The PC keeps the Obsidian vault in this Drive but is not backing up the library. On the PC open Settings > Backup & phones and click Turn on backup.`) }
  }
  if (f.pcProject && f.phoneProject && f.pcProject !== f.phoneProject) {
    return { cause: 'project', title: (words?.('backup.diagnose.project.title') ?? "Another Google Cloud project than the PC's"), changeAccount: false, pairAgain: false,
      message: (words?.('backup.diagnose.project.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}This phone's Google sign-in app is in another Google Cloud project (${f.phoneProject}) than your PC's (${f.pcProject}), and each project has its own hidden folder. Register the phone's Android sign-in in the PC's project (mobile-shell/README.md), then Sync.`) }
  }
  if (!f.pcAccount) {
    return { cause: 'account', title: (words?.('backup.diagnose.account.title') ?? 'The account could not be checked'), changeAccount: true, pairAgain: true,
      message: (words?.('backup.diagnose.account.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}The folder is empty, and the PC did not say which account it backs up to, so this one could not be checked. On the PC open Settings > Backup & phones and read Google account: if it is another account, Change account here; then pair again so the phone learns it.`) }
  }
  return { cause: 'empty', title: (words?.('backup.diagnose.empty.title') ?? 'Nothing uploaded to this account'), changeAccount: false, pairAgain: false,
    message: (words?.('backup.diagnose.empty.message', { signedAs: as, phoneProject: f.phoneProject, pcProject: f.pcProject, pcAccount: f.pcAccount, problem: f.problem ? ` (${f.problem})` : '' }) ?? `${as}That is the account your PC backs up to (${f.pcAccount}), but its hidden folder is empty. Either the PC has not backed up yet (PC: Settings > Backup & phones > Turn on backup), or this phone's Google sign-in app is in another Google Cloud project than the PC's.`) }
}
