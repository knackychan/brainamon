import { SCRYPT_OPTIONS } from './recovery-kdf-options'

export async function recoveryKey(password: Uint8Array<ArrayBuffer>, salt: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer>> {
  // Node's format/interoperability checks have no browser Worker.
  if (typeof Worker === 'undefined') {
    try {
      const { scrypt } = await import('@noble/hashes/scrypt.js')
      return new Uint8Array(scrypt(password, salt, SCRYPT_OPTIONS))
    } finally { password.fill(0) }
  }
  let worker: Worker | undefined
  try {
    const active = worker = new Worker(new URL('./recovery-kdf.worker.ts', import.meta.url), { type: 'module' })
    return await new Promise((resolve, reject) => {
      const failed = () => reject(new Error('Passphrase processing failed. Close other apps and retry.'))
      active.onerror = failed
      active.onmessageerror = failed
      active.onmessage = ({ data }) => {
        if (data instanceof Uint8Array && data.length === 32) { resolve(new Uint8Array(data)); data.fill(0) }
        else failed()
      }
      active.postMessage({ password, salt })
    })
  } finally { worker?.terminate(); password.fill(0) }
}
