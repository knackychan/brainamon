// Saved, explicitly selected standalone backup work. Never touches PC or legacy chg- files.
import { secrets, secretsSaved } from '../native'
import { kv } from '../store'
import { SyncPaused, syncPaused } from '../network.svelte'
import { CHANGE_FORMAT, type Changes, type ChangeEntry } from './changes'
import { MirrorKey } from './crypto'
import { Drive } from './drive'
import { allowCloudWork, stopCloudWork } from './gate'
import { deviceId, disconnectDrive, dropToken, GOOGLE_DRIVE, newKeyText, pairing, token, validateStoredPairing, type Pairing } from './pairing'
import { recordPublish } from './phone-reconnect'

export interface PhoneBackup { prefix: string; files: number; bytes: number; current: boolean }
export interface BackupTask {
  kind: 'replace' | 'delete'; account: string; prefix: string; owner: string
  phase: 'prepare' | 'upload' | 'install' | 'delete' | 'disconnect' | 'done'
  paused: boolean; files: { id: string; name: string }[]; removed: number
  key?: string; name?: string; id?: string
}
interface Snapshot { entries: ChangeEntry[]; doc: { format: number; device: string; at: number; changes: unknown[] } }
const SNAPSHOT = 'phone_backup_snapshot'
const soloName = /^solo-[a-f0-9]{32}-[a-f0-9]{32}$/
export const backupTask = () => pairing()?.backupTask
let pauseRequested = false

function standalone(): Pairing {
  const p = pairing()
  if (!p?.solo) throw new Error('Manage the PC backup on your PC. Only standalone phone backups can be changed here.')
  return p
}
function client(p: Pairing) { return new Drive(p.d || GOOGLE_DRIVE, () => token(p), dropToken) }
async function save(task: BackupTask, paused?: boolean) {
  const p = standalone()
  if (p.k !== task.owner && p.k !== task.key) throw new Error('The phone library changed. This task cannot continue.')
  task.paused = paused ?? (pauseRequested || p.backupTask?.paused || task.paused)
  secrets.set('bp-pair', JSON.stringify({ ...p, backupTask: task }))
  await secretsSaved()
}
async function account(drive: Drive, task?: BackupTask) {
  const p = standalone(), address = (await drive.about()).toLowerCase()
  if (!address || p.g?.toLowerCase() !== address || task && address !== task.account) throw new Error('Connect the Google account selected for this backup, then retry.')
  return address
}
export async function listPhoneBackups(): Promise<PhoneBackup[]> {
  const p = standalone(), drive = client(p)
  await account(drive)
  const own = await (await MirrorKey.fromText(p.k)).soloPrefix(), groups = new Map<string, PhoneBackup>()
  for (const f of await drive.list()) {
    if (!soloName.test(f.name)) continue
    const prefix = f.name.slice(0, 38)
    const group = groups.get(prefix) ?? { prefix, files: 0, bytes: 0, current: prefix === own }
    group.files++; group.bytes += f.size; groups.set(prefix, group)
  }
  return [...groups.values()].sort((a, b) => Number(b.current) - Number(a.current) || a.prefix.localeCompare(b.prefix))
}

export async function beginBackupTask(kind: BackupTask['kind'], prefix: string) {
  const p = standalone()
  if (p.backupTask) throw new Error('Finish the saved backup task first.')
  if (!/^solo-[a-f0-9]{32}-$/.test(prefix)) throw new Error('Select a standalone phone backup first.')
  // Quiesce before the fresh listing: a send already accepted by Drive must be included.
  await stopCloudWork()
  const drive = client(p), address = await account(drive)
  const files = (await drive.list()).filter(f => soloName.test(f.name) && f.name.startsWith(prefix)).map(({ id, name }) => ({ id, name }))
  const task: BackupTask = { kind, account: address, prefix, owner: p.k, phase: kind === 'replace' ? 'prepare' : 'delete', paused: false, files, removed: 0 }
  pauseRequested = false
  if (kind === 'replace') task.key = newKeyText()
  await save(task)
  return task
}

export async function pauseBackupTask(on: boolean) {
  // Pairing briefly awaits key validation during installation; keep the tap across that commit.
  pauseRequested = on
  if (!pairing() && running) await validateStoredPairing()
  const task = backupTask()
  if (task) await save(task, on)
}

let running: Promise<void> | null = null
export function runBackupTask(changes: Changes, progress: (text: string) => void): Promise<void> {
  return running ??= execute(changes, progress).finally(() => { running = null })
}
async function execute(changes: Changes, progress: (text: string) => void): Promise<void> {
  await stopCloudWork()
  const task = backupTask()
  if (!task) return
  let drive = client(standalone())
  const check = () => {
    const p = standalone(), live = p.backupTask
    if (!live || live.owner !== task.owner || live.prefix !== task.prefix) throw new Error('The selected backup task changed.')
    if ((p.k !== task.owner && p.k !== task.key) || p.g?.toLowerCase() !== task.account || !token(p)) throw new Error('The phone key or Google sign-in changed. Connect the selected account and retry.')
    if (pauseRequested || live.paused) throw new Error('Backup task paused. Resume when ready.')
    if (syncPaused()) throw new SyncPaused()
  }
  let listed: Awaited<ReturnType<Drive['list']>> = []
  if (task.phase !== 'disconnect' && task.phase !== 'done') {
    check(); await account(drive, task)
    // Every retry re-lists Drive, including after manual deletion or an uncertain upload response.
    listed = await drive.list(); check()
  }
  if (task.phase === 'prepare') {
    progress('Preparing this phone’s complete backup…')
    await changes.load()
    const entries = structuredClone(changes.list)
    const doc = { format: CHANGE_FORMAT, device: deviceId(), at: Date.now(), changes: entries.map(({ id: _i, state: _s, sentAt: _a, chg: _c, canvasLocal: _l, stream: _t, seq: _q, legacy: _g, resend: _r, ...c }) => c) }
    await kv.set(SNAPSHOT, { entries, doc } satisfies Snapshot)
    const key = await MirrorKey.fromText(task.key!)
    const [name] = await key.sealChange(doc, true)
    check(); task.name = name; task.phase = 'upload'; await save(task)
  }
  if (task.phase === 'upload' || task.phase === 'install') {
    progress('Uploading and checking the replacement; the old backup stays…')
    const snapshot = await kv.get<Snapshot>(SNAPSHOT)
    if (!snapshot) throw new Error('The saved replacement is missing. The old backup has been kept. Disconnect backup and keep this phone’s local content.')
    const key = await MirrorKey.fromText(task.key!), plain = new TextEncoder().encode(JSON.stringify(snapshot.doc))
    check()
    if (task.phase === 'upload') {
      const copies = listed.filter(f => f.name === task.name)
      if (copies.length > 1) throw new Error('Drive has duplicate replacement files. The old backup has been kept. Disconnect backup and keep this phone’s local content.')
      task.id = copies[0]?.id ?? await drive.createReplacement(key, task.name!, await key.seal(task.name!, plain))
      await save(task); check()
    }
    // Verify again after restart before installing the key or removing any old file.
    listed = await drive.list()
    const opened = await key.open(task.name!, await drive.getRecovered(task.id!, key))
    if (opened.length !== plain.length || opened.some((b, i) => b !== plain[i])) throw new Error('Replacement verification failed. The old backup has been kept. Retry or disconnect backup.')
    check(); task.phase = 'install'; await save(task)
    progress('Keeping the verified replacement and this phone’s queued edits…')
    const live = standalone()
    if (live.k === task.owner) {
      const before = { ...live }; delete before.backupTask
      secrets.set(`bp-pair-before-replace-${task.name}`, JSON.stringify(before))
      await secretsSaved()
    }
    check()
    const next: Pairing = { ...standalone(), k: task.key!, f: key.fingerprint, backupTask: task }
    delete next.recovery
    // Idempotent across restart; edits changed since the snapshot stay queued.
    secrets.set('bp-pair', JSON.stringify(next)); await secretsSaved(); await validateStoredPairing()
    await changes.acceptBackup(snapshot.entries, task.name!, snapshot.doc.at)
    await recordPublish(key, task.name!, task.id!, snapshot.doc)
    task.phase = 'delete'; await save(task)
    drive = client(standalone())
  }
  if (task.phase === 'delete') {
    // Delete only confirmed IDs. Later uploads from another phone are independent copies.
    listed = await drive.list()
    if (task.kind === 'replace') {
      const snapshot = await kv.get<Snapshot>(SNAPSHOT), key = await MirrorKey.fromText(task.key!)
      if (!snapshot || new TextDecoder().decode(await key.open(task.name!, await drive.getRecovered(task.id!, key))) !== JSON.stringify(snapshot.doc)) throw new Error('The replacement could not be verified. Remaining old files have been kept. Retry or disconnect backup.')
    }
    for (; task.removed < task.files.length; task.removed++) {
      check()
      const f = task.files[task.removed]
      progress(`Removing selected backup files · ${task.removed} / ${task.files.length}`)
      if (listed.some(x => x.id === f.id && x.name === f.name)) await drive.removeSolo(f.id, task.prefix)
      await save({ ...task, removed: task.removed + 1 })
    }
    check(); task.phase = task.kind === 'delete' ? 'disconnect' : 'done'; await save(task)
  }
  if (task.phase === 'disconnect') {
    if (backupTask()?.paused) throw new Error('Backup task paused. Resume when ready.')
    allowCloudWork()
    disconnectDrive(standalone()); await secretsSaved()
    task.phase = 'done'; await save(task)
  }
  if (task.phase === 'done') {
    await kv.del(SNAPSHOT)
    const live = standalone(); delete live.backupTask
    secrets.set('bp-pair', JSON.stringify(live)); await secretsSaved()
  }
}

export async function disconnectPhoneBackup() {
  if (backupTask()) await pauseBackupTask(true)
  await running?.catch(() => {})
  await stopCloudWork()
  if (!pairing()) return
  allowCloudWork()
  const live = pairing()!
  delete live.backupTask
  secrets.set('bp-pair', JSON.stringify(live)); await secretsSaved()
  await kv.del(SNAPSHOT)
  disconnectDrive(live); await secretsSaved()
}
