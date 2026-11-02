import { b64urlDecode, b64urlEncode, MirrorKey } from './crypto'
import { recoveryKey } from './recovery-kdf'

export const PHONE_RECOVERY_PREFIX = 'vi-phone-recovery-'
export const RECOVERY_LIMIT = 32768
const FORMAT = 'brainamon-phone-backup-recovery'
const KIT = 'brainamon-phone-backup-kit'
const KDF = { name: 'scrypt', n: 131072, r: 8, p: 1 }
const enc = new TextEncoder()
interface Wrapper { nonce: string; ciphertext: string; salt?: string; kdf?: typeof KDF }
export interface PhoneEnvelope {
  header: { format: string; version: number; library: string; fingerprint: string; generation: string; created: number; account: string }
  password: Wrapper
  kit: Wrapper
}
export interface PhoneKit { format: string; version: number; secret: string; record: PhoneEnvelope }

const fail = (message = 'This phone recovery file is damaged or unsupported.'): never => { throw new Error(message) }
const random = (size: number) => crypto.getRandomValues(new Uint8Array(size))
const hex = (data: Uint8Array) => Array.from(data, b => b.toString(16).padStart(2, '0')).join('')
export function recoveryJSON(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(recoveryJSON).join(',') + ']'
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + recoveryJSON((value as Record<string, unknown>)[k])).join(',') + '}'
  return JSON.stringify(value)
}
export function parseRecovery(text: string): unknown {
  if (text.length > RECOVERY_LIMIT || enc.encode(text).length > RECOVERY_LIMIT) fail('Recovery files must be smaller than 32 KiB.')
  try { return JSON.parse(text) } catch { return fail() }
}
function fields(value: any, expected: string[]) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== expected.sort().join(',')) fail()
}
function decode(value: unknown, length: number): Uint8Array<ArrayBuffer> {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value) || value.length > length * 2) return fail()
  const bytes = new Uint8Array(b64urlDecode(value))
  if (bytes.length !== length || b64urlEncode(bytes) !== value) fail()
  return bytes
}
export function validatePhoneEnvelope(value: unknown): PhoneEnvelope {
  const r = value as PhoneEnvelope
  fields(r, ['header', 'password', 'kit'])
  fields(r.header, ['format', 'version', 'library', 'fingerprint', 'generation', 'created', 'account'])
  const h = r.header
  if (h.format !== FORMAT) fail('This is not a standalone phone backup. Restore desktop libraries in Settings > Backup & phones on a PC.')
  if (h.version !== 1) fail('Update Brainamon to open this recovery version.')
  for (const [key, length] of [['library', 32], ['generation', 32], ['fingerprint', 12]] as const) {
    if (typeof h[key] !== 'string' || !new RegExp(`^[a-f0-9]{${length}}$`).test(h[key])) fail()
  }
  if (!Number.isSafeInteger(h.created) || h.created <= 0 || typeof h.account !== 'string' || !h.account || h.account.length > 320) fail()
  for (const kind of ['password', 'kit'] as const) {
    const w = r[kind]
    fields(w, kind === 'password' ? ['nonce', 'ciphertext', 'salt', 'kdf'] : ['nonce', 'ciphertext'])
    decode(w.nonce, 12); decode(w.ciphertext, 48)
    if (kind === 'password') {
      fields(w.kdf, ['name', 'n', 'r', 'p'])
      if (recoveryJSON(w.kdf) !== recoveryJSON(KDF)) fail('Unsupported recovery password parameters.')
      decode(w.salt, 16)
    }
  }
  return r
}
export function readPhoneKit(text: string): PhoneKit {
  const kit = parseRecovery(text) as PhoneKit
  if (kit?.format !== KIT) fail('Choose a phone recovery file. Desktop recovery files are restored on a PC; original phone codes use the Code option.')
  fields(kit, ['format', 'version', 'secret', 'record'])
  if (kit.version !== 1) fail()
  validatePhoneEnvelope(kit.record); decode(kit.secret, 32)
  return kit
}
export function phoneRecoveryName(record: PhoneEnvelope): string {
  const { library, generation } = validatePhoneEnvelope(record).header
  return `${PHONE_RECOVERY_PREFIX}${library}-${generation}.json`
}
function aad(record: PhoneEnvelope, kind: 'password' | 'kit') {
  const { ciphertext: _, ...wrapper } = record[kind]
  return enc.encode(recoveryJSON({ header: record.header, kind, ...wrapper }))
}
async function derive(password: string, salt: string) {
  if ([...password].length < 12 || [...password].length > 1024 || enc.encode(password).length > 4096 || /[\uD800-\uDFFF]/u.test(password)) fail('Use a recovery passphrase of 12 to 1024 characters.')
  return recoveryKey(enc.encode(password), decode(salt, 16))
}
async function aes(raw: Uint8Array<ArrayBuffer>) {
  try { return await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt']) }
  finally { raw.fill(0) }
}
export async function createPhoneKit(keyText: string, password: string, account: string): Promise<PhoneKit> {
  const master = decode(keyText, 32), key = await MirrorKey.fromText(keyText)
  const record: PhoneEnvelope = {
    header: { format: FORMAT, version: 1, library: await key.name('phone-recovery'), fingerprint: key.fingerprint,
      generation: hex(random(16)), created: Math.floor(Date.now() / 1000), account: account.toLowerCase() },
    password: { nonce: b64urlEncode(random(12)), salt: b64urlEncode(random(16)), kdf: { ...KDF }, ciphertext: '' },
    kit: { nonce: b64urlEncode(random(12)), ciphertext: '' },
  }
  const secret = b64urlEncode(random(32))
  try {
    for (const kind of ['password', 'kit'] as const) {
      const wrapping = await aes(kind === 'password' ? await derive(password, record.password.salt!) : decode(secret, 32))
      record[kind].ciphertext = b64urlEncode(new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: decode(record[kind].nonce, 12), additionalData: aad(record, kind) }, wrapping, master)))
    }
    validatePhoneEnvelope(record)
    return { format: KIT, version: 1, secret, record }
  } finally { master.fill(0) }
}
export async function unlockPhoneEnvelope(value: unknown, account: string, credential: { password: string } | { secret: string }): Promise<string> {
  const record = validatePhoneEnvelope(value)
  if (record.header.account.toLowerCase() !== account.toLowerCase()) fail('Connect the Google account used for this phone recovery setup.')
  const kind = 'password' in credential ? 'password' : 'kit'
  const wrapping = await aes('password' in credential ? await derive(credential.password, record.password.salt!) : decode(credential.secret, 32))
  let raw: Uint8Array<ArrayBuffer>
  try { raw = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: decode(record[kind].nonce, 12), additionalData: aad(record, kind) }, wrapping, decode(record[kind].ciphertext, 48))) }
  catch { return fail('The recovery secret is incorrect or the recovery file was changed.') }
  try {
    const text = b64urlEncode(raw), key = await MirrorKey.fromText(text)
    if (key.fingerprint !== record.header.fingerprint || await key.name('phone-recovery') !== record.header.library) fail('Recovery key does not match this phone backup.')
    return text
  } finally { raw.fill(0) }
}
