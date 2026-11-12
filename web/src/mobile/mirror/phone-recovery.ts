import { Drive } from './drive'
import { beginCloudChange, cloudCheckpoint, cloudRevision, endCloudChange, reconnectGate } from './gate'
import { pairing, token, type Pairing } from './pairing'
import { isApp, secrets, secretsSaved, vaultFs, vaultPick } from '../native'
import { downloadRecovery } from '../../lib/recovery'
import { createPhoneKit, parseRecovery, phoneRecoveryName, readPhoneKit, recoveryJSON, unlockPhoneEnvelope, validatePhoneEnvelope, type PhoneEnvelope, type PhoneKit } from './recovery-envelope'
import { downloadAsked } from './recovery-fact'

function current(pair: Pairing, account: string) {
  const live = pairing()
  if (!live?.solo || live.k !== pair.k || !token(live) || live.g?.toLowerCase() !== account.toLowerCase()) throw Object.assign(new Error('The phone library or Google account changed. Reconnect and retry recovery.'), { code: 'identity' })
}
export async function recoveryAccount(pair: Pairing, drive: Drive) {
  const account = (await drive.about()).toLowerCase()
  current(pair, account)
  return account
}
async function remember(pair: Pairing, kit: PhoneKit, verified: boolean) {
  current(pair, kit.record.header.account)
  pair.recovery = { kit, verified }
  secrets.set('bp-pair', JSON.stringify({ ...pairing(), recovery: pair.recovery }))
  await secretsSaved()
}
export async function discoverPhoneRecovery(drive: Drive): Promise<{ id: string; record: PhoneEnvelope }[]> {
  const out = []
  const files = await drive.listPhoneRecovery()
  for (let i = 0; i < files.length; i += 4) {
    out.push(...await Promise.all(files.slice(i, i + 4).map(async file => {
      const record = validatePhoneEnvelope(parseRecovery(await drive.getPhoneRecovery(file.id)))
      if (phoneRecoveryName(record) !== file.name) throw Object.assign(new Error('The phone recovery file name does not match its contents.'), { code: 'name' })
      return { id: file.id, record }
    })))
  }
  return out.sort((a, b) => b.record.header.created - a.record.header.created)
}
async function remoteKit(drive: Drive, kit: PhoneKit) {
  const file = (await drive.listPhoneRecovery()).find(f => f.name === phoneRecoveryName(kit.record))
  if (!file) throw Object.assign(new Error('This recovery setup is missing from Google Drive. Keep the recovery file and connect the original account.'), { code: 'missing-setup' })
  const record = validatePhoneEnvelope(parseRecovery(await drive.getPhoneRecovery(file.id)))
  if (recoveryJSON(record) !== recoveryJSON(kit.record)) throw Object.assign(new Error('The saved recovery file does not match the recovery setup in Drive.'), { code: 'setup-mismatch' })
  return record
}
export async function preparePhoneRecovery(pair: Pairing, drive: Drive, password: string, confirmation: string) {
  reconnectGate()
  const revision = cloudRevision()
  beginCloudChange()
  try {
  if (password !== confirmation) throw Object.assign(new Error('The recovery passphrases do not match.'), { code: 'passphrase-mismatch' })
  const account = await recoveryAccount(pair, drive)
  const kit = await createPhoneKit(pair.k, password, account)
  cloudCheckpoint(revision)
  current(pair, account)
  await drive.create(phoneRecoveryName(kit.record), new TextEncoder().encode(recoveryJSON(kit.record)))
  const record = await remoteKit(drive, kit)
  if (await unlockPhoneEnvelope(record, account, { password }) !== pair.k || await unlockPhoneEnvelope(record, account, { secret: kit.secret }) !== pair.k) throw Object.assign(new Error('Recovery verification failed. Keep your original recovery code.'), { code: 'verification' })
  cloudCheckpoint(revision)
  await remember(pair, kit, false)
  } finally { endCloudChange() }
}
export async function verifyPhoneRecovery(pair: Pairing, drive: Drive, text: string) {
  reconnectGate()
  const revision = cloudRevision()
  beginCloudChange()
  try {
  const kit = readPhoneKit(text), account = await recoveryAccount(pair, drive)
  if (!pair.recovery || recoveryJSON(pair.recovery.kit) !== recoveryJSON(kit)) throw Object.assign(new Error('Select the recovery file saved for this setup.'), { code: 'select-file' })
  const record = await remoteKit(drive, kit)
  if (await unlockPhoneEnvelope(record, account, { secret: kit.secret }) !== pair.k) throw Object.assign(new Error('This recovery file belongs to a different phone backup.'), { code: 'other-backup' })
  cloudCheckpoint(revision)
  await remember(pair, kit, true)
  } finally { endCloudChange() }
}
export async function restorePhoneKit(pair: Pairing, drive: Drive, text: string) {
  const kit = readPhoneKit(text), account = await recoveryAccount(pair, drive)
  const key = await unlockPhoneEnvelope(kit.record, account, { secret: kit.secret })
  current(pair, account)
  return { key, account }
}
export async function restorePhonePassphrase(pair: Pairing, drive: Drive, id: string, password: string) {
  const account = await recoveryAccount(pair, drive)
  const record = validatePhoneEnvelope(parseRecovery(await drive.getPhoneRecovery(id)))
  const key = await unlockPhoneEnvelope(record, account, { password })
  current(pair, account)
  return { key, account }
}
// Save recovery file…: the app writes it to a folder the person picks and then records that it did (`recovery.saved`), if
// the library and its setup are still the same; a browser can only ask for a download, which this session counts as
// saved (recovery-fact.ts) and nothing records
export async function savePhoneKit(pair: Pairing): Promise<'saved' | 'downloaded' | 'cancelled'> {
  const revision = cloudRevision()
  const r = pair.recovery
  if (!r) throw Object.assign(new Error('Prepare recovery first.'), { code: 'prepare-first' })
  const kit = r.kit, filename = `Brainamon-phone-recovery-kit-${kit.record.header.generation}.json`
  if (!isApp) { downloadRecovery(kit, filename); downloadAsked(kit.record.header.generation); return 'downloaded' }
  let folder: { uri: string }
  try { folder = await vaultPick() } catch (e) { if ((e as Error).message === 'cancelled') return 'cancelled'; throw e }
  reconnectGate()
  cloudCheckpoint(revision)
  if (pairing()?.k !== pair.k || pair.recovery !== r) throw Object.assign(new Error('The phone library or its recovery changed while saving. Save the recovery file again.'), { code: 'changed-while-saving' })
  beginCloudChange()
  try {
  await vaultFs(folder.uri).write(filename, new TextEncoder().encode(recoveryJSON(kit)))
  cloudCheckpoint(revision)
  if (pairing()?.k !== pair.k || pair.recovery !== r) throw Object.assign(new Error('The phone library or its recovery changed while saving. Save the recovery file again.'), { code: 'changed-while-saving' })
  pair.recovery = { ...r, saved: Date.now() }
  secrets.set('bp-pair', JSON.stringify(pair))
  await secretsSaved()
  return 'saved'
  } finally { endCloudChange() }
}
