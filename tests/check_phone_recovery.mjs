// Synthetic secrets only: node tests/check_phone_recovery.mjs
import { strict as assert } from 'node:assert'
import { createDecipheriv, scryptSync } from 'node:crypto'
import { registerHooks } from 'node:module'
registerHooks({ resolve(s, c, next) {
  try { return next(s, c) } catch (e) {
    if (s.startsWith('.') && !/\.\w+$/.test(s)) return next(s + '.ts', c)
    throw e
  }
} })
const R = await import('../web/src/mobile/mirror/recovery-envelope.ts')
const { generateRecoveryPassphrase } = await import('../web/src/lib/recovery.ts')
const raw = Buffer.alloc(32, 7), original = raw.toString('base64url'), account = 'sample@example.com'
const password = '  tést phone recovery 🔑  '
const kit = await R.createPhoneKit(original, password, account)
assert.equal(await R.unlockPhoneEnvelope(kit.record, account, { password }), original)
assert.equal(await R.unlockPhoneEnvelope(kit.record, account, { secret: kit.secret }), original)
assert.deepEqual(R.readPhoneKit(R.recoveryJSON(kit)), kit)
assert.match(R.phoneRecoveryName(kit.record), /^vi-phone-recovery-[a-f0-9]{32}-[a-f0-9]{32}\.json$/)

// Independent OpenSSL scrypt/AES implementation verifies the browser envelope.
const w = kit.record.password
const derived = scryptSync(password, Buffer.from(w.salt, 'base64url'), 32, { N: 131072, r: 8, p: 1, maxmem: 140 * 1024 * 1024 })
const { ciphertext, ...wrapper } = w
const encrypted = Buffer.from(ciphertext, 'base64url')
const cipher = createDecipheriv('aes-256-gcm', derived, Buffer.from(w.nonce, 'base64url'))
cipher.setAAD(Buffer.from(R.recoveryJSON({ header: kit.record.header, kind: 'password', ...wrapper })))
cipher.setAuthTag(encrypted.subarray(-16))
assert.deepEqual(Buffer.concat([cipher.update(encrypted.subarray(0, -16)), cipher.final()]), raw)

await assert.rejects(R.unlockPhoneEnvelope(kit.record, account, { password: 'incorrect password' }), /incorrect/)
await assert.rejects(R.unlockPhoneEnvelope(kit.record, 'other@example.com', { secret: kit.secret }), /Google account/)
const changed = structuredClone(kit.record)
changed.header.account = 'other@example.com'
await assert.rejects(R.unlockPhoneEnvelope(changed, 'other@example.com', { secret: kit.secret }), /incorrect|changed/)
changed.password.kdf.n = 2 ** 30
assert.throws(() => R.validatePhoneEnvelope(changed), /parameters/)
assert.throws(() => R.parseRecovery(' '.repeat(32769)), /32 KiB/)
assert.throws(() => R.readPhoneKit('{"format":"brainamon-recovery-kit"}'), /Desktop/)
assert.throws(() => R.readPhoneKit(JSON.stringify({ ...kit, secret: 'not-a-valid-key' })))
assert.throws(() => R.validatePhoneEnvelope({ ...kit.record, header: { ...kit.record.header, format: 'brainamon-recovery' } }), /desktop/i)
await assert.rejects(R.createPhoneKit(original, 'too short', account), /12 to 1024/)
const generated = Array.from({ length: 100 }, generateRecoveryPassphrase)
assert.equal(new Set(generated).size, 100)
assert(generated.every(value => /^[a-f0-9]{8}(-[a-f0-9]{8}){3}$/.test(value)))
const { recoveryKey } = await import('../web/src/mobile/mirror/recovery-kdf.ts')
let terminated = false
globalThis.Worker = class {
  postMessage() { queueMicrotask(() => this.onerror(new Error('synthetic worker failure'))) }
  terminate() { terminated = true }
}
const workerPassword = new TextEncoder().encode(password)
try {
  await assert.rejects(recoveryKey(workerPassword, new Uint8Array(16)), /processing failed/)
  assert(terminated)
  assert(workerPassword.every(byte => byte === 0))
} finally { delete globalThis.Worker }
console.log('Phone recovery: independent crypto roundtrip, formats, wrong secrets/accounts, tampering and size/KDF limits passed.')
