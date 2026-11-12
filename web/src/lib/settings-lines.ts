import type { Line } from './backup-state'
import type { JobSnap } from './events.svelte'
import { toolsReady } from './onboarding'
import { mapLine, statusLine, type ObsidianView } from './obsidian'
import type { BrowserRuntime, InstallView, ToolsView } from './setup'

const loading = (text: string): Line => ({ kind: 'loading', tone: 'todo', text })
const working = (text: string): Line => ({ kind: 'working', tone: 'busy', text })
const failed = (text: string): Line => ({ kind: 'failed', tone: 'next', text })
const empty = (text: string, detail?: string): Line => ({ kind: 'empty', tone: 'optional', text, detail })
const done = (text: string): Line => ({ kind: 'done', tone: 'done', text })

export function videoLine(f: { tools: ToolsView | null; install: InstallView | null; checking: boolean; starting: boolean; error: string }): Line {
  if (f.checking) return loading('Checking video tools…')
  if (f.starting || f.install?.state === 'running') return working(f.install?.step || 'Preparing video tools…')
  if (f.error || f.install?.error || f.install?.state === 'error') return failed(f.error || f.install?.error || 'Video tools setup stopped.')
  if (!f.tools) return loading('Checking video tools…')
  if (toolsReady(f.tools)) return done('Video tools are ready.')
  const names = [['ffmpeg', 'FFmpeg'], ['ffprobe', 'ffprobe'], ['yt-dlp', 'yt-dlp'], ['deno', 'Deno']]
  const missing = names.filter(([key]) => f.tools!.tools.find(t => t.name === key)?.state !== 'ready'
    || key === 'yt-dlp' && !f.tools!.youtube?.functional || key === 'deno' && !f.tools!.youtube?.deno).map(([, label]) => label)
  if (f.tools.youtube?.ejs !== 'detected') missing.push('YouTube EJS')
  return empty(`Optional: ${missing.join(', ')} ${missing.length === 1 ? 'needs' : 'need'} setup.`)
}

export function browserLine(f: { runtime: BrowserRuntime | null; checking: boolean; doing: string; error: string }): Line {
  if (f.checking) return loading('Checking browser tools…')
  if (f.doing || f.runtime?.state === 'installing') {
    const verb: Record<string, string> = { select: 'Checking the selected environment', install: 'Preparing browser tools', repair: 'Repairing browser tools', remove: 'Removing browser tools', python: 'Installing Python 3.14' }
    return working(f.runtime?.state === 'installing' && f.runtime.step ? f.runtime.step : verb[f.doing] || 'Preparing browser tools')
  }
  if (f.error) return failed(f.error)
  if (f.runtime?.workers === false) return failed('This Brainamon installation is incomplete: reinstall the latest version to repair it.')
  if (f.runtime?.state === 'failed') return failed(f.runtime.error || 'Browser tools failed their check. Retry, or keep working without them.')
  if (!f.runtime) return loading('Checking browser tools…')
  if (f.runtime.state === 'ready') return done(`Ready: Playwright ${f.runtime.version} passed a browser check on this PC`)
  if (f.runtime.state === 'older') return empty(`Found an older Playwright ${f.runtime.version}: Install browser tools updates it to 1.61.0`)
  return empty('Missing: install browser tools, or keep working without them')
}

export function vaultLine(f: { view: ObsidianView | null; pending: boolean; error: string }): Line {
  if (f.pending) return loading('Checking the vault…')
  if (f.error) return failed(f.error)
  const v = f.view
  if (!v) return loading('Checking the vault…')
  if (v.mode === 'owner' && (!v.exists || !v.is_vault || !v.status || v.status.missing)) return failed('Vault not found. It was moved, renamed or deleted.')
  if (v.status?.other_library) return failed('This vault belongs to another Brainamon library.')
  if (v.status?.error) return failed(statusLine(v.status))
  if (v.status?.busy || v.status?.pending || (v.status?.state && !['idle', 'pending'].includes(v.status.state))) return working(statusLine(v.status))
  if (v.legacy) return empty('Earlier vault', 'Move it to a new vault to continue using it.')
  if (v.mode !== 'owner') return empty('No vault set up', 'Optional: create or reconnect a vault.')
  if (!v.status.last_render) return empty(statusLine(v.status))
  return done(statusLine(v.status))
}

export function mapStatusLine(f: { view: ObsidianView | null; pending: boolean; error: string; job: JobSnap | null }): Line {
  if (f.pending) return loading('Checking the knowledge map…')
  if (f.error) return failed(f.error)
  const v = f.view
  if (!v) return loading('Checking the knowledge map…')
  if (!v.status) return failed('Map status could not be read.')
  if (f.job?.kind === 'refresh_map' && f.job.state === 'paused') return { kind: 'paused', tone: 'next', text: `Map refresh paused · ${f.job.done} of ${f.job.total} steps` }
  if (f.job?.kind === 'refresh_map' && f.job.state === 'running') return working(`Refreshing map · ${f.job.done} of ${f.job.total} steps`)
  if (v.status.error) return failed(`Stopped on an error: ${v.status.error}`)
  const map = { topics: v.status.topics, stale: v.status.stale, pending: v.status.pending_summaries }
  const text = mapLine(map)
  if (!map.topics) return empty(text)
  if (map.stale || map.pending) return empty(text, 'Refresh map to update it.')
  return done(text)
}
