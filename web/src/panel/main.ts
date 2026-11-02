// Wiskit's drop panel (projects/desktop-app plan 07). Opened by the desktop widget in its own small
// window (server/desktop.py --panel); also works at http://127.0.0.1:18765/panel.html in a browser.
import { mount } from 'svelte'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/600.css'
import '@fontsource/dotgothic16/400.css'
import Panel from './Panel.svelte'

export default mount(Panel, { target: document.body })
