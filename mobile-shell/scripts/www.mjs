// The app's web files (Capacitor webDir): the phone page from the built front end (web/dist, after
// `npm run build` in web/) plus the locked card files it links at /cards, copied byte for byte from
// design/card-designs (never edited). The desktop pages (index.html, panel.html) are left out.
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const here = (p) => fileURLToPath(new URL(p, import.meta.url))
const dist = here('../../web/dist/'), cards = here('../../design/card-designs/'), www = here('../www/')
const CARDS = ['cards.css', 'engine.js', 'full-art-v2/fa2.css', 'full-art-v2/fa2.js']   // what web/mobile.html links

if (!existsSync(dist + 'mobile.html')) {
  console.error('web/dist/mobile.html is missing: run `npm run build` in web/ first.')
  process.exit(1)
}
rmSync(www, { recursive: true, force: true })
mkdirSync(www)
for (const name of readdirSync(dist)) {
  if (name === 'index.html' || name === 'panel.html') continue
  cpSync(dist + name, www + name, { recursive: true })
}
for (const f of CARDS) cpSync(cards + f, www + 'cards/' + f)
// the page's Content-Security-Policy is for the browser: Capacitor injects its bridge as an inline
// script, which that policy would block, and the app only ever loads its own files
const page = readFileSync(www + 'mobile.html', 'utf8')
const bare = page.replace(/\s*<meta http-equiv="Content-Security-Policy"[^>]*>/, '')
if (bare === page) { console.error('mobile.html: the Content-Security-Policy line was not found'); process.exit(1) }
writeFileSync(www + 'mobile.html', bare)
// Capacitor wants an index.html; the app starts at /mobile.html (capacitor.config.json appStartPath)
writeFileSync(www + 'index.html', '<!doctype html><meta charset="utf-8"><script>location.replace("/mobile.html" + location.hash)</script>\n')
console.log('www ready')
