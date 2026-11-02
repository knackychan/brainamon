// The card engine (/cards/engine.js, locked) reads THUMBS[item.key]; src/mobile/cards.ts swaps the
// URL for the cached one. A file, not an inline script, so mobile.html's Content-Security-Policy can
// keep scripts to the page's own files.
window.THUMBS = new Proxy({}, { get: function (_, k) { return '/thumb/' + String(k) } });
