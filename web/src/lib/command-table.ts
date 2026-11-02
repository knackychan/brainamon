// Every command of the app, in menu order (V6 l-init.js). Commands that a later sub-plan builds
// are registered with soon('NN') and become live when that plan calls bind(id, run) from its
// own module. The menus show the grouping and order below.
import AboutBody from '../components/AboutBody.svelte'
import HelpBody from '../components/HelpBody.svelte'
import SetupHub from '../windows/SetupHub.svelte'
import KeysBody from '../components/KeysBody.svelte'
import PaletteBody from '../components/PaletteBody.svelte'
import { api } from './api'
import { cmd, head, sep, soon } from './commands'
import { live } from './events.svelte'
import { openWin, wins } from './windows.svelte'
import { setWS, toggleConsole, toggleMotion, toggleTheme, toast, ui, WS_LIST, WS_NAME } from './ui.svelte'

export function openAbout() { openWin({ id: 'about', title: 'About Brainamon', code: 'CMS-00', w: 540, body: AboutBody }) }
export function openHelp() { openWin({ id: 'help', title: 'Help', code: 'HLP-00', w: 680, body: HelpBody }) }
export function openSetup() {
  const existing = wins.find(w => w.id === 'setup' || w.id === 'welcome')
  if (existing) { wins.splice(wins.indexOf(existing), 1); wins.push(existing); return }
  openWin({ id: 'setup', title: 'Set up Brainamon', code: 'SETUP-00', w: 920, cls: 'setup-win', body: SetupHub })
}
export function openKeys() { openWin({ id: 'keys', title: 'Keyboard shortcuts', code: 'KEY-00', w: 520, body: KeysBody }) }
export function openPalette() { openWin({ id: 'palette', title: 'Command palette', code: 'CMD-00', w: 620, cls: 'pal', body: PaletteBody }) }

const noJob = () => !live.jobs.current
const noJobMsg = () => 'No job is running'

async function jobCall(path: 'pause' | 'resume' | 'stop') {
  try { await api.post(`/api/jobs/${path}`) } catch (e) { toast(String((e as Error).message), 'w') }
}

export function registerCommands() {
  cmd('cmos', 'settings', 'Settings…', () => {}, { icon: 'gear', key: 'Ctrl+,', ...soon('12') })
  cmd('cmos', 'setup', 'Set up Brainamon…', openSetup)
  cmd('cmos', 'recover', 'Recover a library…', () => {}, { ...soon('12') })
  sep('cmos')
  cmd('cmos', 'console', 'Console', () => toggleConsole(), { key: 'Ctrl+`', check: () => ui.consoleOpen })
  cmd('cmos', 'palette', 'Command palette…', openPalette, { icon: 'menu', key: 'Ctrl+K' })
  sep('cmos')
  cmd('cmos', 'motion', 'Motion', toggleMotion, { check: () => !ui.motionOff })
  cmd('cmos', 'night', 'Night', toggleTheme, { check: () => ui.dark })
  cmd('cmos', 'sound', 'Sound', () => {}, { ...soon('15 (after parity)') })
  sep('cmos')
  cmd('cmos', 'help', 'Help…', openHelp)
  cmd('cmos', 'keys', 'Keyboard shortcuts…', openKeys, { key: '?' })
  cmd('cmos', 'about', 'About Brainamon…', openAbout, { icon: 'term' })

  cmd('file', 'add', 'Add to Brainamon…', () => {}, { icon: 'plus', ...soon('06') })
  cmd('file', 'import', 'Import CSV or JSON…', () => {}, { icon: 'up', ...soon('12') })
  cmd('file', 'scrape', 'Scrapers…', () => {}, { icon: 'magnet', ...soon('12') })
  sep('file')
  cmd('file', 'new-canvas', 'New canvas…', () => {}, { icon: 'canvas', ...soon('09') })
  cmd('file', 'new-note', 'New note…', () => {}, { icon: 'note', ...soon('10') })
  sep('file')
  cmd('file', 'export-csv', 'Export item CSV…', () => {}, { icon: 'down', ...soon('12') })
  cmd('file', 'export-obs', 'Export to Obsidian…', () => {}, { icon: 'folder', ...soon('12') })
  cmd('file', 'obs-graph', 'Open knowledge graph', () => {}, { icon: 'folder', ...soon('12') })
  sep('file')
  cmd('file', 'video-tools', 'Video Tools…', () => {}, { icon: 'film', ...soon('12') })

  cmd('edit', 'select-all', 'Select all visible', () => {}, { icon: 'check', key: 'Ctrl+A', ...soon('05') })
  cmd('edit', 'clear-sel', 'Clear the selection', () => {}, { key: 'Esc', ...soon('05') })
  sep('edit')
  cmd('edit', 'bulk', 'Bulk edit…', () => {}, { icon: 'edit', ...soon('06') })
  cmd('edit', 'delete-sel', 'Delete selected…', () => {}, { icon: 'trash', key: 'Del', danger: true, ...soon('06') })
  sep('edit')
  cmd('edit', 'sel-canvas', 'Add selection to the canvas', () => {}, { icon: 'canvas', ...soon('09') })
  sep('edit')
  cmd('edit', 'new-col', 'New collection…', () => {}, { icon: 'plus', ...soon('06') })
  cmd('edit', 'edit-col', 'Edit this collection…', () => {}, { icon: 'edit', ...soon('06') })
  sep('edit')
  cmd('edit', 'clear-status', 'Clear the status filter', () => {}, { ...soon('05') })
  cmd('edit', 'clear-filters', 'Clear every filter', () => {}, { ...soon('05') })

  cmd('process', 'process-items', 'Process items…', () => {}, { icon: 'core', ...soon('07') })
  head('process', 'Enrich and organize')
  cmd('process', 'job-thumb', 'Fetch link info…', () => {}, { icon: 'img', ...soon('07') })
  cmd('process', 'job-describe', 'Describe…', () => {}, { icon: 'note', ...soon('05') })
  cmd('process', 'job-categorize', 'Auto-categorize…', () => {}, { icon: 'tag', ...soon('07') })
  cmd('process', 'job-analyze', 'Analyze videos…', () => {}, { icon: 'film', ...soon('07') })
  cmd('process', 'job-index', 'Index for search…', () => {}, { icon: 'check', ...soon('07') })
  head('process', 'Use saved content')
  cmd('process', 'sel-ask', 'Ask Wiskit about the selection', () => {}, { icon: 'note', ...soon('11') })
  cmd('process', 'job-note', 'Synthesize a note…', () => {}, { icon: 'note', ...soon('07') })
  sep('process')
  cmd('process', 'pause', () => (live.jobs.current?.state === 'paused' ? 'Resume the job' : 'Pause the job'),
    () => jobCall(live.jobs.current?.state === 'paused' ? 'resume' : 'pause'), { off: noJob, offMsg: noJobMsg })
  cmd('process', 'stop', 'Stop the job', () => jobCall('stop'), { icon: 'stop', off: noJob, offMsg: noJobMsg })
  cmd('process', 'progress', 'Show progress…', () => {}, { ...soon('07') })

  WS_LIST.forEach((k, i) => cmd('view', 'ws-' + k, WS_NAME[k], () => setWS(k), { key: String(i + 1), check: () => ui.ws === k }))
  sep('view')
  cmd('view', 'view-list', 'List view', () => {}, { ...soon('05') })
  cmd('view', 'variant', 'Cover card style', () => {}, { ...soon('05') })
  cmd('view', 'smart', 'Smart search', () => {}, { ...soon('05') })
  cmd('view', 'favs', 'Favourites only', () => {}, { ...soon('05') })
  sep('view')
  cmd('view', 'zin', 'Zoom in', () => {}, { key: '+', ...soon('05') })
  cmd('view', 'zout', 'Zoom out', () => {}, { key: '−', ...soon('05') })
  cmd('view', 'zfit', 'Fit', () => {}, { key: '0', ...soon('05') })
  cmd('view', 'pop', 'Pop-out canvas', () => {}, { ...soon('15 (after parity)') })

  // Not in the menus or the palette (hide): run by the menubar chips.
  cmd('view', 'canvas-target', 'Choose the active canvas…', () => {}, { hide: true, ...soon('09') })
  cmd('process', 'sel-note', 'Synthesize a note from the selection…', () => {}, { hide: true, ...soon('07') })
  cmd('cmos', 'settings-downloads', 'Settings > Downloads…', () => {}, { hide: true, ...soon('12') })
}
