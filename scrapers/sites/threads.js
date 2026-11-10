// Threads' saved posts for the phone site reader (projects/phone-site-reader/plans/05-threads.md), joined with
// _runner.js by the app. The list is threads.com/saved (the spike's S2 checks that address). A post is a
// block marked data-pressable-container; its link is /@<user>/post/<code>, and a quoted post inside it is not
// read on its own. canon() and key() have a copy in web/src/mobile/sites.ts (tests/test_phone_sites.py keeps
// them the same).
var SITE = {
  id: 'threads',
  // a post's buttons and labels, never its text; another language needs its own words here
  BUTTON_WORDS: ['like', 'reply', 'repost', 'share', 'translate', 'see translation', 'more', 'author', 'follow'],

  onSaved: function (loc) {
    return /^\/saved\/?$/.test(loc.pathname)
  },

  open: function () {
    return 'https://www.threads.com/saved'
  },

  // a post link in its one form (threads.com, no query), '' for anything else
  canon: function (href) {
    var u
    try { u = new URL(String(href)) } catch (e) { return '' }
    if (!/^https?:$/.test(u.protocol) || !/(^|\.)threads\.(com|net)$/i.test(u.hostname) || u.username || u.password || u.port) return ''
    var m = /^\/@([A-Za-z0-9_.]{1,40})\/post\/([A-Za-z0-9_-]{5,40})\/?$/.exec(u.pathname)
    return m ? 'https://www.threads.com/@' + m[1] + '/post/' + m[2] : ''
  },

  key: function (url) {
    var m = /^https:\/\/www\.threads\.com\/@[A-Za-z0-9_.]{1,40}\/post\/([A-Za-z0-9_-]{5,40})$/.exec(String(url))
    return m ? 'th:' + m[1] : ''
  },

  creatorOf: function (url) {
    var m = /^https:\/\/www\.threads\.com\/@([A-Za-z0-9_.]{1,40})\//.exec(String(url))
    return m ? m[1] : ''
  },

  // a line of a post block that is not its text: the name, the time, a count, a button
  isMeta: function (line, creator) {
    var t = String(line || '').trim(), l = t.toLowerCase()
    if (!t) return true
    if (l === String(creator || '').toLowerCase()) return true
    if (/^\d+\s*[smhdwy]$/.test(l)) return true
    if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(l)) return true
    if (/^[\d.,]+\s*[km]?$/.test(l)) return true
    return SITE.BUTTON_WORDS.indexOf(l) >= 0
  },

  caption: function (lines, creator) {
    var keep = []
    for (var i = 0; i < lines.length; i++) if (!SITE.isMeta(lines[i], creator)) keep.push(String(lines[i]).trim())
    return keep.join('\n')
  },

  read: function (doc) {
    var out = [], boxes = doc.querySelectorAll('[data-pressable-container="true"]')
    for (var i = 0; i < boxes.length; i++) {
      var box = boxes[i], url = ''
      if (!box.getClientRects().length) continue
      if (box.parentElement && box.parentElement.closest('[data-pressable-container="true"]')) continue
      var links = box.querySelectorAll('a[href*="/post/"]')
      for (var j = 0; j < links.length && !url; j++) {
        if (links[j].getClientRects().length && links[j].closest('[data-pressable-container="true"]') === box) url = SITE.canon(links[j].href)
      }
      if (!url) continue
      var creator = SITE.creatorOf(url), pic = '', imgs = box.querySelectorAll('img')
      for (var k = 0; k < imgs.length && !pic; k++) if (imgs[k].getClientRects().length && imgs[k].closest('[data-pressable-container="true"]') === box && !/profile picture/i.test(imgs[k].alt || '')) pic = imgs[k].src
      out.push({ url: url, kind: 'Post', caption: SITE.caption((box.innerText || '').split('\n'), creator), creator: creator, pic: pic })
    }
    return out
  },
}
