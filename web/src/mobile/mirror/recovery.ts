import { downloadRecovery } from '../../lib/recovery'
import { isApp, vaultFs, vaultPick } from '../native'
import { MirrorKey } from './crypto'

export async function exportPhoneRecovery(pair: { k: string; f: string }, words?: (key: string, params?: Record<string, unknown>) => string) {
  const key = await MirrorKey.fromText(pair.k)
  if (key.fingerprint !== pair.f) throw new Error('The pairing key cannot be verified. Keep this phone paired and retry.')
  const file = { format: 'brainamon-phone-recovery', version: 1, key: pair.k, fingerprint: pair.f,
    instructions: 'This file unlocks the original encrypted Drive mirror. Keep it separate from your devices. It is not a library backup. On a replacement PC: Settings > Backup & phones > Recover a library…, then Recovery file.' }
  const filename = `Brainamon-phone-recovery-${pair.f}-${Date.now()}.json`
  if (isApp) {
    const folder = await vaultPick()
    await vaultFs(folder.uri).write(filename, new TextEncoder().encode(JSON.stringify(file, null, 2)))
    return (words?.('recovery.state.exportSaved', { folder: folder.name }) ?? `Recovery file saved in ${folder.name}. Keep a copy outside this phone.`)
  }
  downloadRecovery(file, filename)
  return (words?.('recovery.state.exportDownloaded') ?? 'Recovery file download requested. Check your downloads and keep a copy outside this phone. Never share it.')
}
