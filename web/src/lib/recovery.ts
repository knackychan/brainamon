// Portable recovery files contain key material. Download only after an explicit user action.
// on an error `code` and `next` (the next step) are set: server/cloud_errors.py classified it and `step` is its sentence
export interface RecoveryActivity { action: string; state: 'running' | 'error'; step: string; started: number; step_index?: number; step_count?: number; code?: string; next?: string }

export function downloadRecovery(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = filename
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function generateRecoveryPassphrase() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('').match(/.{8}/g)!.join('-')
}
