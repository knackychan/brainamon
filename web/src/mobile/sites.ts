// The sites the phone site reader knows (projects/phone-site-reader): their link rules, the hashes of the
// library's links a site's page may see, the checks every item read from a page passes before it becomes a
// phone change, and the picture plan of a post read from a site. The page is untrusted (the site's own
// scripts can post on the same channel), so nothing it sends is used before checkItems. Each rule's canon()
// and key() copy scrapers/sites/<site>.js; tests/test_phone_sites.py keeps them the same.
import type { Saved } from './imports'
import { imageUrl } from './linkinfo'

export type SiteId = 'facebook' | 'instagram' | 'tiktok' | 'threads'

export const SITES: { id: SiteId; name: string }[] = [
  { id: 'facebook', name: 'Facebook' },
  { id: 'instagram', name: 'Instagram' },
  { id: 'tiktok', name: 'TikTok' },
  { id: 'threads', name: 'Threads' },
]

export interface SiteRule {
  canon: (href: string) => string   // the post's one link form; '' for a link this reader does not read
  key: (url: string) => string      // the post's id across link forms ('fb:123'), from its canonical link
  cdn: string[]                     // host suffixes a picture link may use
}

const parse = (url: string) => { try { return new URL(url) } catch { return null } }

export const RULES: Partial<Record<SiteId, SiteRule>> = {
  threads: {
    canon(href) {
      const u = parse(String(href))
      if (!u || !/^https?:$/.test(u.protocol) || !/(^|\.)threads\.(com|net)$/i.test(u.hostname) || u.username || u.password || u.port) return ''
      const m = /^\/@([A-Za-z0-9_.]{1,40})\/post\/([A-Za-z0-9_-]{5,40})\/?$/.exec(u.pathname)
      return m ? `https://www.threads.com/@${m[1]}/post/${m[2]}` : ''
    },
    key(url) {
      const m = /^https:\/\/www\.threads\.com\/@[A-Za-z0-9_.]{1,40}\/post\/([A-Za-z0-9_-]{5,40})$/.exec(url)
      return m ? `th:${m[1]}` : ''
    },
    cdn: ['cdninstagram.com', 'fbcdn.net'],
  },
  instagram: {
    canon(href) {
      const u = parse(String(href))
      if (!u || !/^https?:$/.test(u.protocol) || !/(^|\.)instagram\.com$/i.test(u.hostname) || u.username || u.password || u.port) return ''
      const m = /^\/(?:[A-Za-z0-9._]+\/)?(p|reels?|tv)\/([A-Za-z0-9_-]{5,40})\/?$/.exec(u.pathname)
      return m ? `https://www.instagram.com/${m[1] === 'p' || m[1] === 'tv' ? 'p' : 'reel'}/${m[2]}/` : ''
    },
    key(url) {
      const m = /^https:\/\/www\.instagram\.com\/(?:p|reel)\/([A-Za-z0-9_-]{5,40})\/$/.exec(url)
      return m ? `ig:${m[1]}` : ''
    },
    cdn: ['cdninstagram.com', 'fbcdn.net'],
  },
  facebook: {
    canon(href) {
      const u = parse(String(href))
      if (!u || !/^https?:$/.test(u.protocol) || !/(^|\.)facebook\.com$/i.test(u.hostname) || u.username || u.password || u.port) return ''
      const p = u.pathname, v = u.searchParams.get('v') || ''
      let m = /^\/reel\/(\d{5,25})\/?$/.exec(p)
      if (m) return `https://www.facebook.com/reel/${m[1]}/`
      if (/^\/watch\/?$/.test(p) && /^\d{5,25}$/.test(v)) return `https://www.facebook.com/watch/?v=${v}`
      m = /^\/watch\/(\d{5,25})\/?$/.exec(p) || /^\/[^/]+\/videos\/(?:[^/]+\/)?(\d{5,25})\/?$/.exec(p) || /^\/videos\/(\d{5,25})\/?$/.exec(p)
      return m ? `https://www.facebook.com/watch/?v=${m[1]}` : ''
    },
    key(url) {
      const m = /^https:\/\/www\.facebook\.com\/(?:reel\/(\d{5,25})\/|watch\/\?v=(\d{5,25}))$/.exec(url)
      return m ? `fb:${m[1] || m[2]}` : ''
    },
    cdn: ['fbcdn.net'],
  },
}

export const canonical = (site: SiteId, url: string) => RULES[site]?.canon(url) ?? ''

// the post's key from any of its link forms ('' when the link is not one of this site's posts)
export function siteKey(site: SiteId, url: string): string {
  const r = RULES[site]
  const c = r ? r.canon(url) : ''
  return r && c ? r.key(c) : ''
}

export const postKey = (url: string): string => siteKey('instagram', url) || siteKey('facebook', url) || siteKey('threads', url)

// the first 16 hex characters of a SHA-256 (_runner.js hashOf gives the same)
export async function hash16(text: string): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))
  return Array.from(d.subarray(0, 8), b => b.toString(16).padStart(2, '0')).join('')
}

// what the site's page learns of the library: the hashes of its posts' keys on that site, nothing else
export async function knownHashes(site: SiteId, urls: string[]): Promise<string[]> {
  const keys = new Set<string>()
  for (const u of urls) {
    const k = siteKey(site, u)
    if (k) keys.add(k)
  }
  return Promise.all([...keys].map(hash16))
}

export const LIMITS = { url: 500, pic: 2000, caption: 5000, creator: 120, items: 20000 }
const KINDS = new Set(['Reel', 'Video', 'Post'])
const str = (v: unknown) => (typeof v === 'string' ? v : '')

// a picture link the queue may fetch: https on the site's CDN, no user, no port (never a local address)
export function picOk(site: SiteId, pic: string): boolean {
  const r = RULES[site]
  if (!r || !pic || pic.length > LIMITS.pic) return false
  const u = parse(pic)
  if (!u || u.protocol !== 'https:' || u.username || u.password || u.port) return false
  const host = u.hostname.toLowerCase()
  return r.cdn.some(s => host === s || host.endsWith('.' + s))
}

// Match the picture's CDN to the post's adapter, including when a hint is loaded back from local kv.
export function postPicOk(url: string, pic: string): boolean {
  const site = SITES.find(s => siteKey(s.id, url))?.id
  return !!site && picOk(site, pic)
}

// The items of a run (SiteRunFile lines, read through sitePending) as saved posts: a canonical post link of
// the site, a known kind, the text cut to size. Picture links that pass picOk come back as [url, pic] hints.
// Anything else is dropped and counted.
export function checkItems(site: SiteId, raw: unknown[]): { posts: Saved[]; pics: [string, string][]; dropped: number } {
  const posts: Saved[] = [], pics: [string, string][] = [], seen = new Set<string>()
  let dropped = 0
  for (const x of Array.isArray(raw) ? raw : []) {
    const o = x && typeof x === 'object' ? x as Record<string, unknown> : null
    const url = str(o?.url)
    if (!o || !url || url.length > LIMITS.url || canonical(site, url) !== url || !KINDS.has(str(o.kind))) {
      dropped++
      continue
    }
    const key = siteKey(site, url)
    if (seen.has(key)) continue
    if (posts.length >= LIMITS.items) { dropped++; continue }
    seen.add(key)
    posts.push({ url, at: 0, caption: str(o.caption).slice(0, LIMITS.caption), creator: str(o.creator).slice(0, LIMITS.creator), tags: '' })
    const pic = str(o.pic)
    if (picOk(site, pic)) pics.push([url, pic])
  }
  return { posts, pics, dropped }
}

// Native offsets count physical JSONL lines, including a line cut by a crash. Validate once across
// all pages so duplicates and the cap cannot reset at a page boundary. Nothing is cleared here.
export async function readPending(site: SiteId, page: (offset: number, max: number) => Promise<{ items: unknown[]; total: number }>) {
  const raw: unknown[] = []
  let total: number | undefined
  for (let offset = 0; total === undefined || offset < total; offset += 500) {
    const p = await page(offset, 500)
    if (!p || !Number.isSafeInteger(p.total) || p.total < 0 || p.total > LIMITS.items ||
      !Array.isArray(p.items) || p.items.length > Math.min(500, Math.max(0, p.total - offset)) ||
      (total !== undefined && total !== p.total)) throw new Error('Could not read saved results. Keep them and retry.')
    total = p.total
    raw.push(...p.items)
  }
  const checked = checkItems(site, raw)
  return { ...checked, dropped: checked.dropped + (total ?? 0) - raw.length }
}

// A picture link the site's page showed, kept on this phone (kv 'site-pics' in source/mirror.ts) and never
// in a change file: CDN links are signed and expire within days.
export interface PicHint { u: string; at: number }
export const PIC_HINT_TTL_MS = 5 * 86_400_000     // a hint older than this is not tried
export const PIC_HINT_KEEP_MS = 30 * 86_400_000   // a hint not used by then is dropped

// How the picture queue gets a phone link's picture: the fresh hint first, then the link's own rule
// (linkinfo.ts imageUrl), then, for a post read from a site (it has a hint, fresh or not) with no rule,
// the picture its page names.
export function picturePlan(url: string, hint: PicHint | undefined, now: number): { hint: string; rule: string; page: boolean } {
  const rule = imageUrl(url)
  const valid = !!(hint && Number.isFinite(hint.at) && hint.at <= now && postPicOk(url, hint.u))
  return { hint: valid && now - hint!.at < PIC_HINT_TTL_MS ? hint!.u : '', rule, page: valid && !rule }
}
