// The phone (projects/mobile-app/PLAN.md Phase 2): http://localhost:18765/mobile.html on a phone over
// `adb reverse tcp:18765 tcp:18765`, or any browser tab at that URL. Development only until the Google
// Drive mirror (Phase 3 and 4) replaces DesktopSource.
import { mount } from 'svelte'
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import '@fontsource/dotgothic16/400.css'
import '../lib/type.css'
import '../lib/cards/small.css'
import './mobile.css'
import { aiFetch, initNative, isApp } from './native'
import { setFetch } from './ai/providers'
import { withTimeout } from './wait'
import { initNetwork } from './network.svelte'
import { LANGS, setup, t } from '../lib/i18n/index.ts'
import { messages as french } from '../lib/i18n/fr/index.ts'
import { messages as traditionalChinese } from '../lib/i18n/zh-Hant/index.ts'

// In the Android app (Phase 6) the pairing is read from the phone's encrypted storage first: the
// state module decides between the mirror and the desktop when it loads, so it is imported after.
let choice: string | null = null
try { choice = localStorage.getItem('bp-lang') } catch { /* unavailable storage uses Auto */ }
const selected = setup({ fr: french, 'zh-Hant': traditionalChinese }, choice,
  navigator.languages?.length ? navigator.languages : [navigator.language])
document.documentElement.lang = LANGS.find(entry => entry.id === selected)!.html

const startup = document.getElementById('m-startup')!
const title = document.getElementById('m-startup-title')!
const message = document.getElementById('m-startup-message')!
const retry = document.getElementById('m-startup-retry') as HTMLButtonElement
retry.textContent = t('common.retry')
let reloadOnRetry = false

async function start() {
  retry.hidden = true
  retry.disabled = true
  title.textContent = t('shell.startup.title')
  message.textContent = t('shell.startup.loading')
  try {
    const { ready } = await import('../lib/local-auth')
    await ready()
    await initNative()
    const pairing = await import('./mirror/pairing')
    await pairing.validateStoredPairing()
    const note = await pairing.takeFromUrl((key, params) => t(key as Parameters<typeof t>[0], params))
    if (note) sessionStorage.setItem('bp-url-note', note)
    await initNetwork()
    if (isApp) setFetch(aiFetch)
    reloadOnRetry = true                 // a failed module import is cached until the page reloads
    const [{ default: Mobile }, { initTheme, phone }] = await withTimeout(
      Promise.all([import('./Mobile.svelte'), import('./state.svelte')]), 10_000, t('shell.startup.timeout'))

    initTheme()
    mount(Mobile, { target: document.body })
    startup.remove()

    // The service worker controls only the phone page, never the desktop. Skip on the Vite server.
    if ('serviceWorker' in navigator && !import.meta.env.DEV) {
      navigator.serviceWorker.register('/sw.js', { scope: '/mobile.html' })
        .then(reg => { (reg.active ?? reg.installing ?? reg.waiting)?.postMessage({ type: 'cap', mb: phone.capMB }) })
        .catch(() => { /* no offline shell; the page still works online */ })
    }
  } catch {
    title.textContent = t('shell.startup.failedTitle')
    message.textContent = t('shell.startup.failed')
    retry.hidden = false
    retry.disabled = false
    retry.focus()
  }
}

retry.addEventListener('click', () => { if (reloadOnRetry) location.reload(); else void start() })
void start()
