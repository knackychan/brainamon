// Plan 12: the remaining File and CM-OS windows become live: Import, Scrapers, Export (CSV,
// Obsidian; Export for phone retired with the Google Drive mirror), Settings (Ctrl+,) and Video
// Tools, plus the menubar CK lamp (yt-dlp cookies).
import ExportWin from '../windows/ExportWin.svelte'
import ImportWin from '../windows/ImportWin.svelte'
import ScrapersWin from '../windows/ScrapersWin.svelte'
import SettingsWin from '../windows/SettingsWin.svelte'
import VideoToolsWin from '../windows/VideoToolsWin.svelte'
import { api } from './api'
import { bind } from './commands'
import { on } from './events.svelte'
import { newToObsidianText } from './obsidian'
import { toast } from './ui.svelte'
import { openRecover } from './recover'
import { openWin, wins } from './windows.svelte'

export const ck = $state({ lamp: 'off' as 'g' | 'a' | 'off', detail: 'yt-dlp cookies: checking…' })

export function openImport() { openWin({ id: 'import', title: 'Import CSV or JSON', code: 'IMP-07', w: 600, body: ImportWin }) }
export function openScrapers() { openWin({ id: 'scrapers', title: 'Scrapers', code: 'SCR-08', w: 700, body: ScrapersWin }) }
// the first run's start action (onboarding.svelte.ts runStart): Scrapers with one site's guide on top
export function openScrapersFor(site: string) { openWin({ id: 'scrapers', title: 'Scrapers', code: 'SCR-08', w: 700, body: ScrapersWin, props: { focus: site } }) }
export function openExport(tab = 0) { openWin({ id: 'export', title: 'Export', code: 'EXP-09', w: 660, body: ExportWin, props: { tab } }) }
export type SettingsTab = 'overview' | 'general' | 'ai' | 'imports' | 'backup' | 'phone' | 'keys' | 'models' | 'local' | 'claude-code' | 'downloads' | 'tools' | 'sync' | 'app' | 'license' | 'obsidian'
export function openSettings(tab: SettingsTab = 'overview', section = '') {
  const existing = wins.find(w => w.id === 'settings')
  if (existing) {
    existing.props = { ...existing.props, tab, section, navigation: (Number(existing.props?.navigation) || 0) + 1 }
    wins.splice(wins.indexOf(existing), 1); wins.push(existing)
    return
  }
  openWin({ id: 'settings', title: 'Settings', code: 'SET-10', w: 920, cls: 'set-win', body: SettingsWin, props: { tab, section } })
}
export function openVideoTools() { openWin({ id: 'vt', title: 'Video Tools', code: 'VID-12', w: 660, body: VideoToolsWin }) }

// See my knowledge graph: the server opens Obsidian on the exported vault (POST /api/obsidian/graph).
// Obsidian has no link for its graph view, so the toast names the shortcut.
export async function openGraph() {
  try {
    const r = await api.post<{ opened: boolean; vault: string }>('/api/obsidian/graph')
    toast(r.opened ? 'Opening Obsidian. Press Ctrl+G there for the graph view.' : newToObsidianText(r.vault))
  } catch (e) {
    const msg = (e as Error).message
    toast(msg, 'w', /Export to Obsidian/.test(msg) ? { label: 'Export', run: () => openExport(1) } : undefined)
  }
}

async function loadLamp() {
  try { Object.assign(ck, await api.get<typeof ck>('/api/settings/cookies-state')) } catch { /* keep */ }
}

let installed = false
export function installIo() {
  if (installed) return
  installed = true
  bind('import', openImport)
  bind('scrape', openScrapers)
  bind('export-csv', () => openExport(0))
  bind('export-obs', () => openExport(1))
  bind('obs-graph', openGraph)
  bind('settings', () => openSettings())
  bind('recover', openRecover)
  bind('settings-downloads', () => openSettings('downloads'))
  bind('video-tools', openVideoTools)
  loadLamp()
  on('settings_changed', (d: { cookies?: typeof ck }) => { if (d.cookies) Object.assign(ck, d.cookies); else loadLamp() })
}
