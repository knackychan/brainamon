if (typeof importScripts === 'function') importScripts('/auth-worker.js')
/* Brainamon phone service worker (projects/mobile-app/PLAN.md Phase 2 and 4).
   Registered by src/mobile/main.ts with scope /mobile.html, so it controls only the phone page: the
   desktop page at / and the drop panel are never touched. Its jobs:
   - the shell (mobile.html and its built assets) is cached on install and served cache-first, so the
     page opens with no signal (mobile.html is asked of the network first, the cache when that fails);
     a new build has new asset names, and activate drops the old shell cache
   - thumbnails (/thumb/...) are served cache-first and trimmed to the cache limit the page sends
     (postMessage {type:'cap', mb}); URLs carrying pin=1 (favourites) are never trimmed. Items saved
     for offline have their own copy (OFFLINE, /offline/thumb/<id>), never trimmed.
   - on the Google Drive mirror (thumbnail URLs carry m=1, canvas images are /mirror/...), a miss asks
     the page (MessageChannel {type:'need'}): it downloads and opens the thumbnail pack or the image
     with the mirror key and puts it in the cache, then this answers from the cache
   - the share target (manifest share_target, POST): whatever is shared (a link, text, a picture, a
     PDF or a .md / .txt file) becomes a DRAFT in IndexedDB (kv 'drafts'), kept with no signal, and the
     page opens Add. Nothing is created until the user picks Note or Library there and presses Save
     (projects/note-organic-ui/plans/09-add-to-brainamon.md)
   - everything else (API, item files) goes to the network; a failed GET answers 503 so the page can
     fall back to its own copy (IndexedDB, src/mobile/store.ts) */
const SHELL = 'bp-shell-v7'
const THUMBS = 'bp-thumbs-v1'
const MIRROR = 'bp-mirror-v1'            // canvas images from the mirror (src/mobile/source/mirror.ts)
const OFFLINE = 'bp-offline-v1'          // Save for offline (src/mobile/offline.svelte.ts)
const THUMB_KB = 30                      // the grid asks for 320 px wide JPEGs: about 30 KB each
let capMB = 150

// the shared-link rule: a copy of src/mobile/links.ts (tests/test_phone_js.py checks they agree)
const TRACKING = /^(utm_\w+|igsh|igshid|si|mibextid|fbclid|rdid|share_id|feature)$/i
function cleanUrl(url) {
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
function cleanLink(text) {
  const t = String(text || '').trim()
  const m = t.match(/https?:\/\/[^\s<>"']+/i)
  return m ? cleanUrl(m[0]) : ''
}

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(['/mobile.html']).catch(() => {})).then(() => self.skipWaiting()))
})

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => ![SHELL, THUMBS, MIRROR, OFFLINE].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim()))
})

self.addEventListener('message', e => {
  const d = e.data || {}
  if (d.type === 'cap' && d.mb > 0) { capMB = d.mb; trimThumbs() }
  if (d.type === 'trim') trimThumbs()
  if (d.type === 'clear') e.waitUntil(Promise.all([caches.delete(THUMBS), caches.delete(MIRROR)]))
})

self.addEventListener('fetch', e => {
  if (typeof authenticatedLocal === 'function' && authenticatedLocal(e)) return
  const req = e.request
  const url = new URL(req.url)
  if (url.origin !== location.origin) return
  if (req.method === 'POST' && url.pathname === '/mobile.html' && url.searchParams.has('share')) { e.respondWith(share(req)); return }
  if (req.method !== 'GET') return
  if (url.pathname.startsWith('/thumb/')) { e.respondWith(thumb(req, e.clientId)); return }
  if (url.pathname.startsWith('/mirror/')) { e.respondWith(mirrorFile(req, e.clientId)); return }
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/files/')) { e.respondWith(network(req)); return }
  if (url.pathname === '/mobile.html' || url.pathname === '/thumbs-proxy.js' || url.pathname.startsWith('/assets/') || url.pathname.startsWith('/cards/')
      || url.pathname.startsWith('/styles/') || url.pathname.startsWith('/wiskit/') || url.pathname.startsWith('/brand/')
      || url.pathname === '/favicon.ico') { e.respondWith(shell(req)); return }
})

async function network(req) {
  try { return await fetch(req) } catch { return new Response('{"detail":"offline"}', { status: 503, headers: { 'Content-Type': 'application/json' } }) }
}

// shell: mobile.html network first (a few seconds at most, then the cached copy), so a new build or
// a reinstalled app runs its own code on the first open, not the last build's; the hashed assets
// cache first, then network (and remember it)
async function shell(req) {
  const c = await caches.open(SHELL)
  const key = req.url.split('?')[0]
  if (key.endsWith('/mobile.html')) {
    const fresh = await Promise.race([fetch(req).catch(() => null), new Promise(ok => setTimeout(() => ok(null), 3000))])
    if (fresh && fresh.ok) { c.put(key, fresh.clone()); return fresh }
  }
  const hit = await c.match(key)
  if (hit) return hit
  try {
    const r = await fetch(req)
    if (r.ok) c.put(key, r.clone())
    return r
  } catch {
    return new Response('offline', { status: 503 })
  }
}

let trimming = null
async function thumb(req, clientId) {
  const c = await caches.open(THUMBS)
  const hit = await c.match(req.url)
  if (hit) return hit
  const id = new URL(req.url).pathname.split('/')[2]
  const kept = await (await caches.open(OFFLINE)).match('/offline/thumb/' + id)
  if (kept) return kept
  if (new URL(req.url).searchParams.has('m')) {           // the mirror: the page opens the pack
    if (await askPage(clientId, { type: 'need', kind: 'thumb', id: +id })) {
      const got = await c.match(req.url)
      if (got) return got
    }
    return new Response('', { status: 503 })
  }
  try {
    const r = await fetch(req)
    if (r.ok) { await c.put(req.url, r.clone()); trimThumbs() }
    return r
  } catch {
    return new Response('', { status: 503 })
  }
}

// /mirror/canvas-uploads/<name>: the mirror cache, a saved canvas's copy, or ask the page
async function mirrorFile(req, clientId) {
  const c = await caches.open(MIRROR)
  const hit = (await c.match(req.url)) || (await (await caches.open(OFFLINE)).match(req.url))
  if (hit) return hit
  const name = decodeURIComponent(new URL(req.url).pathname.split('/').pop() || '')
  // the page fetches canvas pictures a few at a time, so one of a large canvas may wait its turn
  if (await askPage(clientId, { type: 'need', kind: 'upload', name }, 120000)) {
    const got = await c.match(req.url)
    if (got) return got
  }
  return new Response('', { status: 503 })
}

// the page that asked for the image holds the mirror key: it fetches, opens and caches the file
async function askPage(clientId, msg, wait = 30000) {
  const cs = []
  const own = clientId ? await self.clients.get(clientId) : null
  if (own) cs.push(own)
  for (const c of await self.clients.matchAll({ type: 'window' })) if (!cs.includes(c)) cs.push(c)
  for (const c of cs) {
    const ok = await new Promise(res => {
      const ch = new MessageChannel()
      const t = setTimeout(() => res(false), wait)
      ch.port1.onmessage = ev => { clearTimeout(t); res(!!(ev.data && ev.data.ok)) }
      c.postMessage(msg, [ch.port2])
    })
    if (ok) return true
  }
  return false
}

// ── the share target ─────────────────────────────────────────────────────────
// same database as src/mobile/store.ts (keep VERSION and the stores in step with it)
function idb() {
  return new Promise((res, rej) => {
    const rq = indexedDB.open('brainamon-phone', 2)
    rq.onupgradeneeded = () => {
      const d = rq.result
      if (!d.objectStoreNames.contains('kv')) d.createObjectStore('kv')
      if (!d.objectStoreNames.contains('items')) d.createObjectStore('items', { keyPath: 'id' })
      if (!d.objectStoreNames.contains('outbox')) d.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true })
      if (!d.objectStoreNames.contains('files')) d.createObjectStore('files')
      if (!d.objectStoreNames.contains('changes')) d.createObjectStore('changes', { keyPath: 'id', autoIncrement: true })
    }
    rq.onsuccess = () => res(rq.result)
    rq.onerror = () => rej(rq.error)
    rq.onblocked = () => rej(new Error('blocked'))
  })
}

// One capture in progress: the shape of src/lib/capture.ts newDraft() (tests/test_phone_share_draft.py
// checks they agree). The id is only a key; the page never reads it as a date.
function newDraft(text, title, file) {
  return {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), at: Date.now(), origin: file ? 'file' : 'share',
    text, comment: '', dest: '', target: '', title, collection: '', type: '', tags: '', made: '',
    pic: file ? { name: file.name || 'shared', type: file.type || '', blob: file } : null, read: '',
  }
}

// what a share sheet sends: the link, often with the page title on its own line. A link with nothing but
// that title beside it is a lone link: the link is the content (it starts on Library) and the title names
// a note. = src/lib/capture.ts shareParts (tests/test_phone_share_draft.py checks they agree)
function shareParts(text) {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  const at = lines.findIndex(l => /^https?:\/\/\S+$/i.test(l))
  if (at < 0 || lines.length > 2) return { text, title: '' }
  const title = lines.length === 2 ? lines[1 - at] : ''
  if (/https?:\/\//i.test(title) || title.length > 200) return { text, title: '' }
  return { text: cleanLink(lines[at]), title: title.slice(0, 80) }
}

// one read-modify-write of kv 'drafts', so a draft the page is saving at the same moment is not lost
async function addDraft(draft) {
  const d = await idb()
  try {
    await new Promise((res, rej) => {
      const t = d.transaction('kv', 'readwrite'), s = t.objectStore('kv'), g = s.get('drafts')
      g.onsuccess = () => s.put([...(Array.isArray(g.result) ? g.result : []), draft], 'drafts')
      t.oncomplete = res; t.onerror = () => rej(t.error); t.onabort = () => rej(t.error)
    })
  } finally { d.close() }
}

async function share(req) {
  let text = ''
  let file = null
  try {
    const f = await req.formData()
    text = ['share_url', 'share_text', 'share_title'].map(k => f.get(k)).filter(v => typeof v === 'string' && v).join('\n')
    const sf = f.get('share_file')
    if (sf && typeof sf !== 'string' && sf.size) file = sf
  } catch { /* no form: open Add empty */ }
  // a lone link (alone or with only its page title) is stored as the cleaned link (no igsh, utm_...) and
  // the title; anything else as shared
  const parts = shareParts(text)
  if (parts.text || file) {
    try {
      await addDraft(newDraft(parts.text, parts.title, file))
      return Response.redirect('/mobile.html?shared=1#/cap', 303)
    } catch { /* fall through: Add shows the text to keep by hand */ }
  }
  return Response.redirect('/mobile.html?share_text=' + encodeURIComponent(text) + '#/cap', 303)
}

// drop the oldest unpinned thumbnails until the cache fits the limit (keys come back in insertion order)
function trimThumbs() {
  if (trimming) return trimming
  trimming = (async () => {
    try {
      const c = await caches.open(THUMBS)
      const keys = await c.keys()
      const max = Math.floor(capMB * 1024 / THUMB_KB)
      let over = keys.length - max
      for (const k of keys) {
        if (over <= 0) break
        if (k.url.includes('pin=1')) continue
        await c.delete(k)
        over--
      }
    } finally { trimming = null }
  })()
  return trimming
}
