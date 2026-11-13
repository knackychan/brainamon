// Instagram Saved (all posts), joined with _runner.js in the debug site window. Link rules are mirrored
// in web/src/mobile/sites.ts; synthetic fixtures keep both copies aligned. No account values leave here.
var SITE = {
  id: 'instagram',
  NOT_USERS: ['explore', 'reels', 'direct', 'accounts', 'p', 'reel', 'tv', 'stories', 'about', 'legal', 'saved'],
  PROFILE_WORDS: ['profile', 'profil', 'perfil', 'profilo'],

  isUser: function (user) {
    return /^[A-Za-z0-9._]{1,30}$/.test(user) && SITE.NOT_USERS.indexOf(user.toLowerCase()) < 0 && user !== '.' && user !== '..'
  },

  onSaved: function (loc) {
    var m = /^\/([A-Za-z0-9._]+)\/saved\/all-posts\/?$/.exec(loc.pathname)
    return !!(m && SITE.isUser(m[1]))
  },

  savedUrl: function (user) {
    return SITE.isUser(user) ? 'https://www.instagram.com/' + user + '/saved/all-posts/' : ''
  },

  user: function (doc) {
    var profiles = [], links = doc.querySelectorAll('a[href]')
    for (var i = 0; i < links.length; i++) {
      var a = links[i], u
      if (!a.getClientRects().length) continue
      try { u = new URL(a.href) } catch (e) { continue }
      if (!/^https?:$/.test(u.protocol) || !/(^|\.)instagram\.com$/i.test(u.hostname) || u.username || u.password || u.port) continue
      var saved = /^\/([A-Za-z0-9._]+)\/saved\/(?:all-posts\/?)?$/.exec(u.pathname)
      if (saved && SITE.isUser(saved[1])) return saved[1]
      var profile = /^\/([A-Za-z0-9._]+)\/$/.exec(u.pathname)
      if (profile && SITE.isUser(profile[1])) profiles.push([a, profile[1]])
    }
    for (var j = 0; j < profiles.length; j++) {
      if (SITE.PROFILE_WORDS.indexOf((profiles[j][0].innerText || '').trim().toLowerCase()) >= 0) return profiles[j][1]
    }
    var avatar = '', ambiguous = false
    for (var k = 0; k < profiles.length; k++) {
      var img = profiles[k][0].querySelector('img[alt]')
      if (profiles[k][0].closest('nav, [role="navigation"]') && img && img.alt.indexOf(profiles[k][1]) >= 0) return profiles[k][1]
      // Instagram's sidebar can omit a navigation role; never guess between different avatar owners.
      if (img && img.alt === profiles[k][1] + "'s profile picture") {
        if (avatar && avatar !== profiles[k][1]) ambiguous = true
        avatar = profiles[k][1]
      }
    }
    return ambiguous ? '' : avatar
  },

  open: function (doc) {
    var user = SITE.user(doc)
    return user ? SITE.savedUrl(user) : null
  },

  canon: function (href) {
    var u
    try { u = new URL(String(href)) } catch (e) { return '' }
    if (!/^https?:$/.test(u.protocol) || !/(^|\.)instagram\.com$/i.test(u.hostname) || u.username || u.password || u.port) return ''
    var m = /^\/(?:[A-Za-z0-9._]+\/)?(p|reels?|tv)\/([A-Za-z0-9_-]{5,40})\/?$/.exec(u.pathname)
    return m ? 'https://www.instagram.com/' + (m[1] === 'p' || m[1] === 'tv' ? 'p' : 'reel') + '/' + m[2] + '/' : ''
  },

  key: function (url) {
    var m = /^https:\/\/www\.instagram\.com\/(?:p|reel)\/([A-Za-z0-9_-]{5,40})\/$/.exec(String(url))
    return m ? 'ig:' + m[1] : ''
  },

  creatorOf: function (alt) {
    var m = /^(?:Photo|Video)(?: shared)? by (.{1,120}?) (?:on|in|with|tagging) /.exec(String(alt || ''))
    return m ? m[1] : ''
  },

  unsave: async function (doc, url, canRemove) {
    var link = Array.from(doc.querySelectorAll('a[href]')).find(function (a) {
      return visible(a) && SITE.canon(a.href) === url
    })
    if (!link) return false
    link.click()
    var scope = null
    function icon(label) {
      if (!scope) return null
      var post = Array.from(scope.querySelectorAll('article')).find(visible) || scope
      return Array.from(post.querySelectorAll('[aria-label]')).find(function (s) {
        return visible(s) && (label === 'Remove' ? /^(remove|unsave|remove from saved)$/i : /^save$/i)
          .test(s.getAttribute('aria-label') || '')
      })
    }
    for (var i = 0; i < 20; i++) {
      await sleep(500)
      var dialogs = Array.from(doc.querySelectorAll('[role="dialog"]')).filter(visible)
      scope = SITE.canon(location.href) === url && dialogs.length === 1 ? dialogs[0] : null
      if (icon('Remove') || icon('Save')) break
    }
    if (!scope) return false
    var saved = icon('Remove'), ok = !!icon('Save') && !saved
    if (saved) {
      if (!await canRemove()) return false
      var bookmark = saved.closest('[role="button"], button') || saved
      bookmark.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
      for (var j = 0; j < 20; j++) {
        await sleep(300)
        if (!icon('Remove') && icon('Save')) { ok = true; break }
      }
    }
    var close = Array.from(doc.querySelectorAll('[aria-label="Close"]')).find(visible)
    if (!close) return false
    var closeButton = close.closest('[role="button"], button') || close
    closeButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
    for (var k = 0; k < 20; k++) {
      await sleep(300)
      if (SITE.onSaved(location) && !visible(scope)) return ok
    }
    return false
  },

  read: function (doc) {
    var out = [], links = doc.querySelectorAll('a[href*="/p/"], a[href*="/reel/"], a[href*="/reels/"], a[href*="/tv/"]')
    for (var i = 0; i < links.length; i++) {
      if (!links[i].getClientRects().length) continue
      var url = SITE.canon(links[i].href)
      if (!url) continue
      var img = links[i].querySelector('img'), alt = img ? (img.alt || '').trim() : ''
      out.push({ url: url, kind: url.indexOf('/reel/') > 0 ? 'Reel' : 'Post', caption: alt,
        creator: SITE.creatorOf(alt), pic: img ? img.src : '' })
    }
    return out
  },
}
