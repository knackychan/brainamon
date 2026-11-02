import { scrypt } from '@noble/hashes/scrypt.js'
import { SCRYPT_OPTIONS } from './recovery-kdf-options'

self.onmessage = ({ data }: MessageEvent<{ password: Uint8Array; salt: Uint8Array }>) => {
  try {
    const key = scrypt(data.password, data.salt, SCRYPT_OPTIONS)
    self.postMessage(key)
    key.fill(0)
  } catch {
    self.postMessage(null)
  } finally { data.password.fill(0) }
}
