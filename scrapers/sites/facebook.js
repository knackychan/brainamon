// Facebook's saved list for the phone site reader (projects/phone-site-reader/plans/02-runner-facebook.md),
// joined with _runner.js by the app. The card reader ports the desktop's EXTRACT_VISIBLE_JS
// (scrapers/fb_saved_playwright.py): a card is the nearest block around a reel or video link that holds
// one "Add to collection"; other saved kinds (text posts, outside links) are counted, not read. canon() and
// key() have a copy in web/src/mobile/sites.ts (tests/test_phone_sites.py keeps them the same).
var SITE = {
  id: 'facebook',
  // the words of each saved card's button; another language needs its own words here (plan 02, Troubleshooting)
  ROW_WORDS: ['Add to collection'],

  onSaved: function (loc) {
    return /^\/saved\/?$/.test(loc.pathname)
  },

  open: function () {
    return 'https://www.facebook.com/saved/'
  },

  // a reel or video link in its one form, '' for anything else
  canon: function (href) {
    var u
    try { u = new URL(String(href)) } catch (e) { return '' }
    if (!/^https?:$/.test(u.protocol) || !/(^|\.)facebook\.com$/i.test(u.hostname) || u.username || u.password || u.port) return ''
    var p = u.pathname, v = u.searchParams.get('v') || '', m = /^\/reel\/(\d{5,25})\/?$/.exec(p)
    if (m) return 'https://www.facebook.com/reel/' + m[1] + '/'
    if (/^\/watch\/?$/.test(p) && /^\d{5,25}$/.test(v)) return 'https://www.facebook.com/watch/?v=' + v
    m = /^\/watch\/(\d{5,25})\/?$/.exec(p) || /^\/[^/]+\/videos\/(?:[^/]+\/)?(\d{5,25})\/?$/.exec(p) || /^\/videos\/(\d{5,25})\/?$/.exec(p)
    return m ? 'https://www.facebook.com/watch/?v=' + m[1] : ''
  },

  // the post's id from its canonical link
  key: function (url) {
    var m = /^https:\/\/www\.facebook\.com\/(?:reel\/(\d{5,25})\/|watch\/\?v=(\d{5,25}))$/.exec(String(url))
    return m ? 'fb:' + (m[1] || m[2]) : ''
  },

  // a card line that is not the caption (the desktop's isMeta)
  isMeta: function (raw, creator) {
    var t = String(raw || '').toLowerCase().trim(), cl = String(creator || '').toLowerCase().trim()
    if (t.length <= 5) return true
    if (t.indexOf('saved from') >= 0 || t.indexOf('add to collection') >= 0) return true
    if (t.indexOf('see more') >= 0 || t.indexOf('see less') >= 0) return true
    if (/^(reels?|videos?)\s*[•·]/.test(t)) return true
    if (cl && t === cl) return true
    if (/^\d+(\.\d+)?[kmb]?\s*(views?|likes?|comments?|shares?|plays?)/.test(t)) return true
    if (/^\d+\s*(s|m|h|d|w|y|hr|hrs|min|mins)\b/.test(t)) return true
    if (/'s (video|reel|post)$/.test(t)) return true
    return false
  },

  // the first card line that is not meta
  caption: function (lines, creator) {
    for (var i = 0; i < lines.length; i++) {
      var s = String(lines[i] || '').trim()
      if (s && !SITE.isMeta(s, creator)) return s
    }
    return ''
  },

  read: function (doc) {
    var counts = new Map()
    function words(el) {
      if (counts.has(el)) return counts.get(el)
      var t = el.innerText || '', n = 0
      for (var i = 0; i < SITE.ROW_WORDS.length; i++) n += t.split(SITE.ROW_WORDS[i]).length - 1
      counts.set(el, n)
      return n
    }
    // the nearest block holding the button once; a block holding it more than once is the whole list
    function rowOf(a) {
      for (var el = a.parentElement, i = 0; el && i < 20; el = el.parentElement, i++) {
        var n = words(el)
        if (n === 1) return el
        if (n > 1) return null
      }
      return null
    }
    var rows = new Map(), links = doc.querySelectorAll('a[href]')
    for (var i = 0; i < links.length; i++) {
      if (!links[i].getClientRects().length) continue
      var row = rowOf(links[i])
      if (!row) continue
      if (!rows.has(row)) rows.set(row, [])
      rows.get(row).push(links[i])
    }
    var out = []
    rows.forEach(function (as, row) {
      var url = '', a = null
      for (var j = 0; j < as.length && !url; j++) { url = SITE.canon(as[j].href); a = as[j] }
      if (!url) { out.push({ url: as[0].href, kind: 'Other', caption: '', creator: '', pic: '' }); return }
      var text = row.innerText || ''
      var m = /(?:Reels?|Videos?)\s*[•·]\s*([^\n]+)/i.exec(text)
      var creator = m ? m[1].trim() : ''
      var lines = text.split('\n')
      if (a.getAttribute('aria-label')) lines.push(a.getAttribute('aria-label'))
      row.querySelectorAll('[aria-label]').forEach(function (el) { lines.push(el.getAttribute('aria-label') || '') })
      row.querySelectorAll('img[alt]').forEach(function (el) { lines.push(el.getAttribute('alt') || '') })
      var img = row.querySelector('img[src*="fbcdn"], img[src*="scontent"]')
      out.push({ url: url, kind: url.indexOf('/reel/') > 0 ? 'Reel' : 'Video', caption: SITE.caption(lines, creator),
        creator: creator, pic: img ? img.src : '' })
    })
    return out
  },
}
