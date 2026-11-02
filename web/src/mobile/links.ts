// The link in shared text (PLAN.md Phase 4 step 4): apps share "Check this out
// https://www.instagram.com/reel/...?igsh=...", so the first http(s) link is pulled out and share
// tracking parameters are dropped, so items.url UNIQUE still dedupes a link shared twice. The same
// rule as knowledge/inbox.py link() and desktop/widget.py, and public/sw.js has a copy for the
// share target; tests/fixtures/share_links.json checks all four (tests/test_phone_js.py).
// Plain string work, no URL() normalising, so every copy gives the same text. No imports: the
// Python test runs this file under Node.
export const TRACKING = /^(utm_\w+|igsh|igshid|si|mibextid|fbclid|rdid|share_id|feature)$/i
const FIND = /https?:\/\/[^\s<>"']+/i
const BARE = /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24})(:\d{1,5})?([/?#]\S*)?$/i
const FILE_ENDINGS = new Set(['md', 'txt', 'py', 'js', 'ts', 'json', 'csv', 'html', 'css', 'xml', 'yaml', 'yml', 'log', 'ini',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'pdf', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'zip', 'exe', 'doc', 'docx'])

export function cleanUrl(url: string): string {
  url = url.replace(/[.,;:!?'"]+$/, '')
  if (url.endsWith(')') && !url.includes('(')) url = url.replace(/\)+$/, '')
  const h = url.indexOf('#')
  const frag = h >= 0 ? url.slice(h) : ''
  let base = h >= 0 ? url.slice(0, h) : url
  const q = base.indexOf('?')
  if (q >= 0) {
    const keep = base.slice(q + 1).split('&').filter(p => p && !TRACKING.test(p.split('=')[0]))
    base = base.slice(0, q) + (keep.length ? '?' + keep.join('&') : '')
  }
  return base + frag
}

// '' when the text holds no link
export function cleanLink(text: string): string {
  const t = String(text || '').trim()
  const m = t.match(FIND)
  if (m) return cleanUrl(m[0])
  const b = t.match(BARE)
  if (!b || (FILE_ENDINGS.has(b[1].toLowerCase()) && !t.toLowerCase().startsWith('www.') && !b[3])) return ''
  return cleanUrl('https://' + t)
}
