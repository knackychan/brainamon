// PLAN.md budget "first cards on screen after the page script starts": the perf harness measures
// from this mark to 'cm-first-cards' (VirtualGrid).
performance.mark('cm-script-start')
import { mount } from 'svelte'
import { prefetchLibrary } from './lib/library.svelte'
import { bootFail } from './lib/ui.svelte'
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'
import '@fontsource/dotgothic16/400.css'
import './lib/type.css'
import './lib/cards/small.css'
import './app.css'
import App from './App.svelte'

// The V6 stylesheet lays out <body>'s direct children (field canvas, menubar, shell, ...).
prefetchLibrary()
let app
try {
  app = mount(App, { target: document.body })
} catch (e) {
  bootFail(`Brainamon could not start its window: ${(e as Error).message}`)
  throw e
}
signalReady()
export default app

// Startup splash (desktop/splash.py): tell the desktop shell the first screen is up, once the first cards
// are drawn (including the empty state), or after 2.5 s if loading fails.
// window.pywebview exists only in the app window; in a browser tab this does nothing.
function signalReady() {
  const w = window as unknown as { pywebview?: { api?: { ready?: () => void } } }
  let apiUp = !!w.pywebview?.api?.ready
  let shown = false
  let sent = false
  const go = () => {
    if (apiUp && shown && !sent) {
      sent = true
      w.pywebview!.api!.ready!()
    }
  }
  let po: PerformanceObserver | undefined
  let timer = 0
  const show = () => { po?.disconnect(); clearTimeout(timer); shown = true; go() }
  window.addEventListener('pywebviewready', () => { apiUp = !!w.pywebview?.api?.ready; go() }, { once: true })
  const ready = (name: string) => name === 'cm-first-cards' || name === 'cm-first-screen'
  if (performance.getEntriesByType('mark').some(e => ready(e.name))) {
    show()
  } else {
    po = new PerformanceObserver((list) => {
      if (list.getEntries().some(e => ready(e.name))) show()
    })
    po.observe({ entryTypes: ['mark'] })
    timer = window.setTimeout(show, 2500)
  }
}
