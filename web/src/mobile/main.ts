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

// In the Android app (Phase 6) the pairing is read from the phone's encrypted storage first: the
// state module decides between the mirror and the desktop when it loads, so it is imported after.
const startup = document.getElementById('m-startup')!
const title = document.getElementById('m-startup-title')!
const message = document.getElementById('m-startup-message')!
const retry = document.getElementById('m-startup-retry') as HTMLButtonElement
let reloadOnRetry = false

async function start() {
  retry.hidden = true
  retry.disabled = true
  title.textContent = 'Opening Brainamon'
  message.textContent = 'Loading your saved sign-in...'
  try {
    const { ready } = await import('../lib/local-auth')
    await ready()
    await initNative()
    const pairing = await import('./mirror/pairing')
    await pairing.validateStoredPairing()
    const note = await pairing.takeFromUrl()
    if (note) sessionStorage.setItem('bp-url-note', note)
    await initNetwork()
    if (isApp) setFetch(aiFetch)
    reloadOnRetry = true                 // a failed module import is cached until the page reloads
    const [{ default: Mobile }, { initTheme, phone }] = await withTimeout(
      Promise.all([import('./Mobile.svelte'), import('./state.svelte')]), 10_000, 'The app did not load in 10 seconds.')

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
    title.textContent = 'Brainamon could not start'
    message.textContent = 'Your saved sign-in could not be loaded or the app did not finish opening. Retry to try again. Your pairing and credentials have not been reset.'
    retry.hidden = false
    retry.disabled = false
    retry.focus()
  }
}

retry.addEventListener('click', () => { if (reloadOnRetry) location.reload(); else void start() })
void start()
