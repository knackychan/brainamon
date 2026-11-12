// The phone site reader's page runner (projects/phone-site-reader/plans/02-runner-facebook.md), shared by
// every site. The app joins one site file (facebook.js, ...) and this file inside one function and runs it
// at document start on that site's origins, in the Contributor build's site window (SiteActivity.java). It
// waits for the login, opens the saved list, reads the visible cards at a human pace, skips what this run
// already read, stops at posts already in the library, and sends what is new in batches over the
// "brainamonSite" channel. Only hashes of the library's links reach the page. Everything above "boot" is
// pure, so tests/test_phone_sites.py loads this file under Node with no page.
var KNOWN_STOP = 20      // known posts in a row that end a later run (only once the site had a complete run)
var END_PASSES = 10      // scrolls in a row with nothing new: the end of the list
var EMPTY_PASSES = 3     // scrolls with no card at all on the saved page: the page cannot be read
var SETTLE_MS = 4000     // the saved page's first cards load after the page itself
var MAX_ITEMS = 20000    // items one run sends at most (SiteRunFile.MAX_ITEMS)
var BATCH = 25           // items per message (SiteActivity accepts 25)
var MAX_OPENS = 6        // tries to open the saved list in one run
var AUTH_WORDS = ['login', 'accounts', 'checkpoint', 'challenge', 'two_factor', 'two_step', 'captcha', 'auth_platform', 'recover', 'signup']
var RUN_KEY = 'brainamon-site-run'

// a login, checkpoint or recovery page, by the first part of its path (as session_ready on the desktop)
function authPath(path) {
  var first = String(path || '').toLowerCase().split('/')[1] || ''
  for (var i = 0; i < AUTH_WORDS.length; i++) if (first.indexOf(AUTH_WORDS[i]) === 0) return true
  return false
}

// what the page is: 'signin' (no login cookie), 'check' (a login form, checkpoint or 2FA while signed in),
// 'saved' (the saved list) or 'other' (anything else: the runner opens the saved list)
function where(path, signed, authForm, onSaved) {
  if (!signed) return 'signin'
  if (authForm || (!onSaved && authPath(path))) return 'check'
  return onSaved ? 'saved' : 'other'
}

function newRun(id) {
  return { id: id, seen: {}, streak: 0, read: 0, known: 0, other: 0, opens: 0 }
}

function newDoc() {
  return { urls: {}, found: 0, passes: 0, empty: 0 }
}

// One pass over the visible cards ({url, kind, caption, creator, pic, h}; h is the hash of the post's key).
// `run` lives across page loads of this run (sessionStorage), `doc` only on this page. Returns the items to
// send and why the run stops ('' to go on).
function step(run, doc, cards, opt) {
  var send = [], fresh = 0, stop = ''
  for (var i = 0; i < cards.length; i++) {
    var c = cards[i]
    if (doc.urls[c.url]) continue
    doc.urls[c.url] = 1
    fresh++
    if (run.seen[c.h]) continue
    if (run.read + run.known + run.other >= MAX_ITEMS) { stop = 'cap'; break }
    run.seen[c.h] = 1
    if (c.kind === 'Other') { run.other++; continue }
    if (opt.known[c.h]) {
      run.known++
      run.streak++
      if (opt.complete && !opt.full && run.streak >= KNOWN_STOP) { stop = 'known'; break }
      continue
    }
    run.streak = 0
    if (run.read >= MAX_ITEMS) { stop = 'cap'; break }
    run.read++
    send.push({ url: c.url, kind: c.kind, caption: c.caption, creator: c.creator, pic: c.pic })
    if (run.read + run.known + run.other >= MAX_ITEMS) { stop = 'cap'; break }
  }
  doc.found += fresh
  doc.passes++
  doc.empty = fresh ? 0 : doc.empty + 1
  if (!stop && !doc.found && doc.passes >= EMPTY_PASSES) stop = 'empty'
  if (!stop && run.read + run.known + run.other >= MAX_ITEMS) stop = 'cap'
  if (!stop && doc.empty >= END_PASSES) stop = 'end'
  return { send: send, stop: stop }
}

// the first 16 hex characters of a SHA-256 (sites.ts hash16 gives the same)
function hex16(bytes) {
  var s = ''
  for (var i = 0; i < 8; i++) s += (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16)
  return s
}

async function hashOf(text) {
  return hex16(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(text)))))
}

// the site's cards with their hash; a card the site file cannot name is left out
async function hashCards(cards) {
  var out = []
  for (var i = 0; i < Math.min((cards || []).length, MAX_ITEMS); i++) {
    var c = cards[i]
    if (!c || typeof c.url !== 'string' || !c.url) continue
    var key = c.kind === 'Other' ? '' : SITE.key(c.url)
    if (c.kind !== 'Other' && !key) continue
    out.push({ url: c.url, kind: c.kind, caption: String(c.caption || '').slice(0, 5000), creator: String(c.creator || '').slice(0, 120), pic: String(c.pic || '').slice(0, 2000),
      h: c.kind === 'Other' ? 'other:' + c.url : await hashOf(key) })
  }
  return out
}

// ── the page (Node never gets here) ──
function sleep(ms) {
  return new Promise(function (res) { setTimeout(res, ms) })
}

function visible(el) {
  return !!(el && el.getClientRects().length)
}

// a visible password, one-time-code or captcha field: the user is in a login or a check
function hasAuthForm(doc) {
  var els = doc.querySelectorAll('input[type="password"], input[autocomplete="one-time-code"], iframe[src*="captcha"]')
  for (var i = 0; i < els.length; i++) if (visible(els[i])) return true
  return false
}

function loadRun(id) {
  try {
    var r = JSON.parse(sessionStorage.getItem(RUN_KEY) || 'null')
    if (r && r.id === id && r.seen && typeof r.seen === 'object' && !Array.isArray(r.seen) &&
      ['read', 'known', 'other', 'streak', 'opens'].every(function (k) {
        return Number.isSafeInteger(r[k]) && r[k] >= 0 && r[k] <= MAX_ITEMS
      }) && r.read + r.known + r.other <= MAX_ITEMS && Object.keys(r.seen).length <= MAX_ITEMS) return r
  } catch (e) { /* storage off or unreadable: a fresh run */ }
  return newRun(id)
}

function saveRun(r) {
  try { sessionStorage.setItem(RUN_KEY, JSON.stringify(r)) } catch (e) { /* full or off: the app's run file still drops repeats */ }
}

function scroll() {
  if (typeof SITE.scroll === 'function') { SITE.scroll(document); return }
  var el = document.scrollingElement || document.documentElement
  var before = el.scrollTop
  window.scrollBy(0, Math.round(window.innerHeight * 0.85))
  if (el.scrollTop === before) window.scrollTo(0, el.scrollHeight)
}

async function main(port) {
  var init = null, signed = false, active = true, last = '', batchId = 0, receipt = null, signedReplies = 0
  function on(e) {
    var m = null
    try { m = JSON.parse(typeof e.data === 'string' ? e.data : '') } catch (x) { return }
    if (!m || typeof m !== 'object') return
    if (m.t === 'init' && !init && Array.isArray(m.known)) { init = m; signed = !!m.signed; active = m.active !== false }
    else if (m.t === 'stored' && m.batch === batchId && Array.isArray(m.urls)) receipt = m.urls
    else if (m.t === 'signed') { signed = !!m.on; active = m.active !== false; signedReplies++ }
  }
  if (typeof port.addEventListener === 'function') port.addEventListener('message', on)
  else port.onmessage = on
  function post(m) {
    try { port.postMessage(JSON.stringify(m)) } catch (x) { /* the window is closing */ }
  }

  for (var tries = 0; tries < 3 && !init; tries++) {
    post({ t: 'hello' })
    for (var w = 0; w < 50 && !init; w++) await sleep(100)
  }
  if (!init) return
  var opt = { known: {}, full: !!init.full, complete: !!init.complete }
  for (var k = 0; k < init.known.length; k++) if (typeof init.known[k] === 'string') opt.known[init.known[k]] = 1
  var removing = init.unsave === true && !init.unsaveFailed && typeof SITE.unsave === 'function'
  var run = loadRun(String(init.run)), doc = newDoc()
  var settled = false, idle = 0, pinged = 0, unsaveFailed = init.unsaveFailed === true

  async function canRemove() {
    var before = signedReplies
    post({ t: 'ping' })
    for (var i = 0; i < 20 && signedReplies === before; i++) await sleep(100)
    return signedReplies > before && active && signed && document.visibilityState !== 'hidden' && navigator.onLine !== false && !hasAuthForm(document)
  }

  function status(phase) {
    var s = JSON.stringify({ t: 'status', phase: phase, known: run.known, other: run.other, unsaveFailed: unsaveFailed })
    if (s !== last) { last = s; post(JSON.parse(s)) }
  }
  function end(reason) {
    saveRun(run)
    post({ t: 'end', reason: reason })
  }

  for (;;) {
    if (Date.now() - pinged >= 2000) { pinged = Date.now(); post({ t: 'ping' }) }
    if (!active || document.visibilityState === 'hidden' || navigator.onLine === false) {
      status('wait')
      await sleep(1000)
      continue
    }
    var at = where(location.pathname, signed, hasAuthForm(document), !!SITE.onSaved(location, document))
    if (at === 'signin' || at === 'check') {
      settled = false
      status(at)
      await sleep(1000)
      continue
    }
    if (at === 'other') {
      settled = false
      status('open')
      var go = SITE.open(document)
      if (go === null || go === undefined) {          // the way to the list is not on the page yet
        if (++idle > 30) return end('empty')
        await sleep(1000)
        continue
      }
      idle = 0
      run.opens++
      saveRun(run)
      if (run.opens > MAX_OPENS) return end('empty')
      if (go) location.assign(go)
      await sleep(go ? 15000 : 3000)
      continue
    }
    if (!settled) {
      settled = true
      status('read')
      await sleep(SETTLE_MS)
      continue
    }
    var cards = await hashCards(SITE.read(document))
    // Hashing yields to the page; recheck visibility/auth before sending or scrolling.
    if (!active || document.visibilityState === 'hidden' || navigator.onLine === false ||
      where(location.pathname, signed, hasAuthForm(document), !!SITE.onSaved(location, document)) !== 'saved') continue
    var r = step(run, doc, cards, opt)
    for (var b = 0; b < r.send.length; b += BATCH) {
      var items = r.send.slice(b, b + BATCH)
      receipt = null
      post({ t: 'batch', batch: ++batchId, items: items })
      if (!removing) continue
      // The native reply is sent only after SiteRunFile.append has synced the results to disk.
      for (var ack = 0; ack < 150 && receipt === null; ack++) await sleep(100)
      if (!receipt || !items.every(function (item) { return receipt.indexOf(item.url) >= 0 })) return end('failure')
    }
    saveRun(run)
    if (removing) {
      var savedUrl = location.href
      for (var u = 0; u < r.send.length; u++) {
        if (!active || document.visibilityState === 'hidden' || navigator.onLine === false ||
          where(location.pathname, signed, hasAuthForm(document), !!SITE.onSaved(location, document)) !== 'saved') return end('stop')
        if (!await SITE.unsave(document, r.send[u].url, canRemove)) {
          if (!active || document.visibilityState === 'hidden' || navigator.onLine === false) return end('stop')
          // An uncertain removal must not be retried; keep collecting without changing Saved.
          removing = false
          unsaveFailed = true
          status('read')
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
          // Instagram may leave its post dialog open; return to Saved with Unsave still disabled.
          if (signed && !hasAuthForm(document) && !authPath(location.pathname) &&
            (!SITE.onSaved(location, document) || Array.from(document.querySelectorAll('[role="dialog"]')).some(visible))) {
            location.assign(savedUrl)
            return
          }
          break
        }
        await sleep(1500)
      }
    }
    status('read')
    if (r.stop) return end(r.stop)
    scroll()
    await sleep(1200 + Math.random() * 600)
  }
}

// boot: only in the site window's top frame, where the app put the channel (taken now, before the page's
// own scripts run)
if (typeof window !== 'undefined' && window.top === window && typeof brainamonSite !== 'undefined' && typeof SITE !== 'undefined') {
  var port = brainamonSite
  var start = function () { main(port).catch(function () {
    try { port.postMessage(JSON.stringify({ t: 'end', reason: 'failure' })) } catch (e) { /* closing */ }
  }) }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true })
  else start()
}
