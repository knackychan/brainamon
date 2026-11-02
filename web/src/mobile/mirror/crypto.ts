// The mirror's sealing, phone side (the desktop's library/mirror.py MirrorKey; format in
// projects/mobile-app/plans/03-drive-mirror.md and 04-phone-mirror.md). WebCrypto only:
// - two subkeys from the 32-byte mirror key by HKDF-SHA256 (no salt), info "brainamon-mirror-1 data"
//   and "brainamon-mirror-1 name"
// - a Drive name is HMAC-SHA256(name key, logical name), first 16 bytes as hex
// - a file is "BAM1" + 12-byte nonce + AES-256-GCM(data key, nonce, plaintext, aad = logical name)
// - a video is "BAV1" + chunk size (u32 big endian) + per chunk i: nonce + AES-256-GCM(..., aad =
//   "<logical>#<i>")
// - a change file the phone writes is a file whose logical name is its Drive name ("chg-" + 32 hex)
// - AI keys for a phone being paired: a file sealed with a one-time key from the pairing link, named
//   "pky-<expiry, unix s>-<its Drive name of pair-keys.json>" (mirror.py pair_drop)
// No imports: tests/test_phone_js.py runs this file under Node against files sealed in Python.

const enc = new TextEncoder()
const MAGIC = [0x42, 0x41, 0x4d, 0x31]           // BAM1
const VMAGIC = [0x42, 0x41, 0x56, 0x31]          // BAV1
export const CHANGE_PREFIX = 'chg-'
export const SOLO_PREFIX = 'solo-'
export const PAIR_LOGICAL = 'pair-keys.json'

export interface VideoIntegrity { integrity?: number; bytes?: number; sha256?: string }

export class MirrorKeyError extends Error {}

export function b64urlDecode(s: string): Uint8Array {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4))
  const out = new Uint8Array(b.length)
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i)
  return out
}

export function b64urlEncode(a: Uint8Array): string {
  let s = ''
  for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000))
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const hex = (a: ArrayBuffer | Uint8Array) => [...new Uint8Array(a)].map(b => b.toString(16).padStart(2, '0')).join('')
const has = (a: Uint8Array, m: number[]) => m.every((b, i) => a[i] === b)
// a plain ArrayBuffer view WebCrypto accepts everywhere (TS 5.7+ types are strict about SharedArrayBuffer)
const buf = (a: Uint8Array) => a as Uint8Array<ArrayBuffer>

export class MirrorKey {
  readonly fingerprint: string
  private data: CryptoKey
  private nameKey: CryptoKey
  private constructor(fingerprint: string, data: CryptoKey, nameKey: CryptoKey) {
    this.fingerprint = fingerprint; this.data = data; this.nameKey = nameKey
  }

  static async fromText(text: string): Promise<MirrorKey> {
    const master = b64urlDecode(text.trim())
    if (master.length !== 32) throw new MirrorKeyError('A mirror key is 32 bytes.')
    const subtle = crypto.subtle
    const base = await subtle.importKey('raw', buf(master), 'HKDF', false, ['deriveBits'])
    const derive = (info: string) => subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: enc.encode(info) }, base, 256)
    const [d, n] = await Promise.all([derive('brainamon-mirror-1 data'), derive('brainamon-mirror-1 name')])
    const id = new Uint8Array([...enc.encode('brainamon-mirror-1 id'), ...master])
    const fp = hex(await subtle.digest('SHA-256', id)).slice(0, 12)
    return new MirrorKey(fp,
      await subtle.importKey('raw', d, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']),
      await subtle.importKey('raw', n, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']))
  }

  // the Drive name of a logical file
  async name(logical: string): Promise<string> {
    return hex(await crypto.subtle.sign('HMAC', this.nameKey, enc.encode(logical))).slice(0, 32)
  }

  // vault sync: names a file's content without revealing it (MirrorKey.content_id on the PC)
  async contentId(data: Uint8Array): Promise<string> {
    const head = enc.encode('vault-content ')
    const all = new Uint8Array(head.length + data.length)
    all.set(head, 0); all.set(data, head.length)
    return hex(await crypto.subtle.sign('HMAC', this.nameKey, all)).slice(0, 32)
  }

  async open(logical: string, blob: Uint8Array): Promise<Uint8Array> {
    if (blob.length < 16 + 16 || !has(blob, MAGIC)) throw new MirrorKeyError('Not a sealed mirror file.')
    try {
      return new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf(blob.slice(4, 16)), additionalData: enc.encode(logical) }, this.data, buf(blob.subarray(16))))
    } catch {
      throw new MirrorKeyError(`${logical} does not open with this key.`)
    }
  }

  async openText(logical: string, blob: Uint8Array): Promise<string> {
    return new TextDecoder().decode(await this.open(logical, blob))
  }

  async openJSON<T>(logical: string, blob: Uint8Array): Promise<T> {
    return JSON.parse(await this.openText(logical, blob)) as T
  }

  async seal(logical: string, plaintext: Uint8Array): Promise<Uint8Array> {
    const nonce = crypto.getRandomValues(new Uint8Array(12))
    const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: enc.encode(logical) }, this.data, buf(plaintext)))
    const out = new Uint8Array(16 + ct.length)
    out.set(MAGIC, 0); out.set(nonce, 4); out.set(ct, 16)
    return out
  }

  async soloPrefix(): Promise<string> {
    return `${SOLO_PREFIX}${await this.name('phone-backup')}-`
  }

  // Standalone backups never enter the PC's change-file intake.
  async sealChange(doc: unknown, solo = false): Promise<[string, Uint8Array]> {
    const name = (solo ? await this.soloPrefix() : CHANGE_PREFIX) + hex(crypto.getRandomValues(new Uint8Array(16)))
    return [name, await this.seal(name, enc.encode(JSON.stringify(doc)))]
  }

  // a video, chunk by chunk (each chunk checked on its own); returns the plain chunks in order
  async openVideo(logical: string, blob: Uint8Array, integrity: VideoIntegrity, progress?: (done: number, total: number) => void): Promise<Uint8Array[]> {
    if (!integrity || integrity.integrity !== 2 || !Number.isSafeInteger(integrity.bytes) || integrity.bytes! < 0 || !/^[a-f0-9]{64}$/.test(integrity.sha256 || '')) throw new MirrorKeyError('Republish this legacy video from the PC before playback.')
    if (blob.length < 36 || !has(blob, VMAGIC)) throw new MirrorKeyError('Not a sealed mirror video.')
    const size = new DataView(blob.buffer, blob.byteOffset + 4, 4).getUint32(0)
    if (size < 1 || size > 4 * 1024 * 1024) throw new MirrorKeyError('Invalid video chunk size.')
    const out: Uint8Array[] = []
    let at = 8, i = 0
    while (at < blob.length) {
      const n = Math.min(12 + size + 16, blob.length - at)
      const part = blob.subarray(at, at + n)
      try {
        out.push(new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf(part.slice(0, 12)), additionalData: enc.encode(`${logical}#${i}`) }, this.data, buf(part.subarray(12)))))
      } catch {
        throw new MirrorKeyError(`${logical} chunk ${i} does not open with this key.`)
      }
      at += n; i++
      progress?.(at, blob.length)
    }
    const length = out.reduce((n, p) => n + p.length, 0)
    if (length !== integrity.bytes) throw new MirrorKeyError('Complete video length does not match.')
    const all = new Uint8Array(length)
    let offset = 0
    for (const part of out) { all.set(part, offset); offset += part.length }
    if (hex(await crypto.subtle.digest('SHA-256', all)) !== integrity.sha256) throw new MirrorKeyError('Complete video digest does not match.')
    return out
  }
}

// the Drive name of the AI keys the PC left for this pairing (`one` is the link's one-time key `t`)
export async function pairDropName(one: MirrorKey, tx: number): Promise<string> {
  return `pky-${Math.trunc(tx)}-${await one.name(PAIR_LOGICAL)}`
}

// thumbs/pack-NNNN.bin: "BTP1" + index length (u32 BE) + index JSON {"<id>": [offset, length]} + JPEGs
export function readPack(data: Uint8Array): Map<number, Uint8Array> {
  const n = new DataView(data.buffer, data.byteOffset + 4, 4).getUint32(0)
  const index = JSON.parse(new TextDecoder().decode(data.subarray(8, 8 + n))) as Record<string, [number, number]>
  const base = 8 + n, out = new Map<number, Uint8Array>()
  for (const [k, [o, len]] of Object.entries(index)) out.set(+k, data.subarray(base + o, base + o + len))
  return out
}

// vectors.bin: "BVE1" + header length (u32 BE) + header JSON {model, dim, count, ids, uids} + int8 rows
export interface Vectors { model: string; dim: number; ids: number[]; uids: string[]; mat: Int8Array; norms: Float32Array }
export function readVectors(data: Uint8Array): Vectors {
  const n = new DataView(data.buffer, data.byteOffset + 4, 4).getUint32(0)
  const head = JSON.parse(new TextDecoder().decode(data.subarray(8, 8 + n))) as { model: string; dim: number; count: number; ids: number[]; uids: string[] }
  const mat = new Int8Array(data.buffer.slice(data.byteOffset + 8 + n, data.byteOffset + 8 + n + head.count * head.dim))
  const norms = new Float32Array(head.count)
  for (let r = 0; r < head.count; r++) {
    let s = 0
    for (let j = r * head.dim, e = j + head.dim; j < e; j++) s += mat[j] * mat[j]
    norms[r] = Math.sqrt(s) || 1
  }
  return { model: head.model, dim: head.dim, ids: head.ids, uids: head.uids, mat, norms }
}

// the rows nearest to row `r` by cosine (Related by meaning, no AI call)
export function nearest(v: Vectors, r: number, k: number): number[] {
  const { dim, mat, norms } = v, out: [number, number][] = []
  const a = r * dim
  for (let q = 0; q < v.ids.length; q++) {
    if (q === r) continue
    let s = 0
    for (let j = 0, b = q * dim; j < dim; j++) s += mat[a + j] * mat[b + j]
    out.push([s / (norms[r] * norms[q]), q])
  }
  return out.sort((x, y) => y[0] - x[0]).slice(0, k).map(([, q]) => v.ids[q])
}
