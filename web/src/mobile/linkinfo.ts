// What a saved link's own page says, read on the phone with no PC and no yt-dlp
// (projects/mobile-app/plans/09-link-details.md): a picture address, a title, the creator and the
// caption, through a plain request like a chat app's link preview. Per-site rules first, then the
// page's og: tags. Measured 2026-10-13 (BRAINSTORM.md "Link details with no PC"); a site that changes
// its pages breaks its rule, and a paired PC's thumbnail job still fills the item. `get` is native
// HTTP in the app (native.ts linkGet) and a stand-in in the tests (tests/test_phone_linkinfo.py).
export interface LinkInfo { title: string; creator: string; desc: string; image: string }
export type Get = (url: string) => Promise<{ status: number; text: string }>

const NONE: LinkInfo = { title: '', creator: '', desc: '', image: '' }
const ENT: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }

function codePoint(n: number): string {
  try { return String.fromCodePoint(n) } catch { return '' }
}

export function unescape(s: string): string {
  return s.replace(/&(#[xX][0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, (m, e: string) =>
    e[0] !== '#' ? ENT[e.toLowerCase()] ?? m : codePoint(/^#x/i.test(e) ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)))
}

// one <meta property|name="key" content="..."> value, attributes in either order
export function meta(html: string, key: string): string {
  const k = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const tag = new RegExp(`<meta\\b[^>]*?\\b(?:property|name)\\s*=\\s*["']${k}["'][^>]*>`, 'i').exec(html)?.[0] ?? ''
  const v = /\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')/i.exec(tag)
  return v ? unescape(v[1] ?? v[2] ?? '').trim() : ''
}

const hostOf = (url: string) => { try { return new URL(url).hostname.toLowerCase() } catch { return '' } }
const on = (host: string, ...names: string[]) => names.some(n => host === n || host.endsWith('.' + n))
const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '')

function json(r: { status: number; text: string }): Record<string, unknown> | null {
  if (r.status !== 200) return null
  try { const j = JSON.parse(r.text); return j && typeof j === 'object' ? j as Record<string, unknown> : null } catch { return null }
}

export function youtubeId(url: string): string {
  let u: URL
  try { u = new URL(url) } catch { return '' }
  const id = on(u.hostname.toLowerCase(), 'youtu.be') ? u.pathname.split('/')[1]
    : u.searchParams.get('v') || /^\/(?:shorts|embed|live)\/([\w-]+)/.exec(u.pathname)?.[1]
  return id && /^[\w-]{6,20}$/.test(id) ? id : ''
}

export const instagramCode = (url: string) => /instagram\.com\/(?:[\w.]+\/)?(?:p|reels?|tv)\/([\w-]+)/i.exec(url)?.[1] ?? ''

// A picture's address that needs no page to be read: YouTube and Instagram. '' for every other site
// (its picture address is in the page: linkInfo finds it). Instagram's /reel/ form of this address
// answers 404 or 500; the /p/ form works for reels too (tested 2026-10-14 on three reel codes).
export function imageUrl(url: string): string {
  const host = hostOf(url)
  if (on(host, 'youtube.com', 'youtu.be')) { const id = youtubeId(url); return id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : '' }
  if (on(host, 'instagram.com')) { const code = instagramCode(url); return code ? `https://www.instagram.com/p/${code}/media/?size=m` : '' }
  return ''
}

// og:description `60 likes, 5 comments - handle on May 23, 2021: "caption". `, og:title `Name on Instagram: "caption"`
export function instagramText(ogDesc: string, ogTitle: string): { creator: string; desc: string } {
  const desc = /:\s*"([\s\S]*)"\s*\.?\s*$/.exec(ogDesc)?.[1] ?? /:\s*"([\s\S]*)"\s*$/.exec(ogTitle)?.[1] ?? ''
  const creator = /^(.+?) on Instagram\b/.exec(ogTitle)?.[1] ?? / - ([\w.]+) on /.exec(ogDesc)?.[1] ?? ''
  return { creator: creator.trim(), desc: desc.trim() }
}

// og:title "<views> · <reactions> | caption | Creator" (the numbers in the viewer's language)
export function facebookCreator(ogTitle: string): string {
  const parts = ogTitle.split(' | ')
  return parts.length >= 3 ? parts[parts.length - 1].trim() : ''
}

export async function linkInfo(url: string, get: Get): Promise<LinkInfo | null> {
  const host = hostOf(url)
  if (!host) return null
  if (on(host, 'youtube.com', 'youtu.be')) {
    const id = youtubeId(url)
    if (!id) return null
    const j = json(await get(`https://www.youtube.com/oembed?format=json&url=${encodeURIComponent('https://www.youtube.com/watch?v=' + id)}`))
    return { ...NONE, title: str(j?.title), creator: str(j?.author_name), image: `https://i.ytimg.com/vi/${id}/hqdefault.jpg` }
  }
  if (on(host, 'reddit.com', 'redd.it')) {
    const j = json(await get(`https://www.reddit.com/oembed?url=${encodeURIComponent(url)}`))
    return j ? { ...NONE, title: str(j.title), creator: str(j.author_name) } : null
  }
  const r = await get(url)
  const page = r.status === 200 ? r.text : ''
  if (on(host, 'instagram.com')) {
    const code = instagramCode(url)
    const t = instagramText(meta(page, 'og:description'), meta(page, 'og:title'))
    return code || t.desc ? { ...NONE, ...t, image: code ? `https://www.instagram.com/p/${code}/media/?size=m` : '' } : null
  }
  if (!page) return null
  const title = meta(page, 'og:title'), desc = meta(page, 'og:description'), image = meta(page, 'og:image')
  if (on(host, 'facebook.com', 'fb.watch')) return desc || image ? { title: '', creator: facebookCreator(title), desc, image } : null
  const out = { title: title || unescape(/<title[^>]*>([^<]*)<\/title>/i.exec(page)?.[1] ?? '').trim(), creator: meta(page, 'og:site_name'), desc, image }
  return out.title || out.desc || out.image ? out : null
}
