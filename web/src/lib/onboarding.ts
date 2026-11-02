// First run, the rules the desktop and the phone share (docs/superpowers/specs/2026-10-25-newstart-ui-redo-design.md):
// the welcome's answers, the start action an answer picks, the Get started tasks (the first is always done),
// the phone's empty library and the focused Scrapers guide. No runes and no imports, so
// tests/test_onboarding_js.py runs it under Node.

export type Site = 'instagram' | 'facebook' | 'reddit' | 'youtube'
export const SITE_NAME: Record<Site, string> = { instagram: 'Instagram', facebook: 'Facebook', reddit: 'Reddit', youtube: 'YouTube' }
export const isSite = (a: string): a is Site => Object.prototype.hasOwnProperty.call(SITE_NAME, a)
export const SETUP_STEPS = ['library', 'tools', 'content', 'ai', 'drive', 'phone'] as const
export type SetupStep = typeof SETUP_STEPS[number] | 'summary'

// the desktop welcome, in order; server/routes/onboarding.py ANSWERS adds 'skip'
export const ANSWERS: { id: Site | 'links' | 'files'; label: string; note: string }[] = [
  { id: 'instagram', label: 'Instagram', note: 'Saved posts and reels' },
  { id: 'facebook', label: 'Facebook', note: 'Saved posts and reels' },
  { id: 'reddit', label: 'Reddit', note: 'Saved posts' },
  { id: 'youtube', label: 'YouTube', note: 'A playlist or Watch later' },
  { id: 'links', label: 'Links and notes', note: 'Paste a link or write a note' },
  { id: 'files', label: 'CSV or Brainamon JSON', note: 'Import an exported file' },
]

export interface Start { site: Site | null; task: string; key: string; line: string }
// what the second task, the empty library and Setup start: a site's saves (Scrapers) or Add
export function startFor(answer: string): Start {
  if (answer === 'files') return { site: null, task: 'Import CSV or Brainamon JSON', key: 'Choose a file', line: 'Import an exported file. Each saved item becomes a card you can sort and search.' }
  if (answer === 'youtube') return { site: 'youtube', task: 'Bring in a YouTube playlist', key: 'Bring in a YouTube playlist', line: 'Bring in a playlist. Each video becomes a card you can sort and search.' }
  if (isSite(answer)) {
    const n = SITE_NAME[answer]
    return { site: answer, task: `Bring in your ${n} saves`, key: `Bring in ${n} saves`, line: 'Bring in your saved posts. Each one becomes a card you can sort and search.' }
  }
  return { site: null, task: 'Save your first link or note', key: 'Add a link or note', line: 'Paste a link or write a note. Each one becomes a card you can sort and search.' }
}

export interface Task { id: 'install' | 'tools' | 'drive' | 'saves' | 'pc' | 'wiskit' | 'phone'; label: string; done: boolean; optional?: boolean }

export function desktopTasks(answer: string, s: { items: number; notes: number; wiskit: boolean; tools?: boolean; drive?: boolean; recovery?: boolean; phone?: boolean }): Task[] {
  return [
    { id: 'install', label: 'Your library', done: true },
    { id: 'tools', label: 'Tools & environment', done: !!s.tools, optional: true },
    { id: 'saves', label: startFor(answer).task, done: s.items > 0 || s.notes > 0 },
    { id: 'wiskit', label: 'Wiskit AI (optional)', done: s.wiskit, optional: true },
    { id: 'drive', label: 'Drive & recovery (optional)', done: !!s.drive && !!s.recovery, optional: true },
    { id: 'phone', label: 'Connect your phone (optional)', done: !!s.phone, optional: true },
  ]
}

// the phone's welcome answers 'pc' (connect my PC), 'phone' (just this phone) or 'skip'
export function phoneTasks(answer: string, s: { pc: boolean; items: number; ai: boolean }): Task[] {
  return [
    { id: 'install', label: 'Install Brainamon', done: true },
    answer === 'pc' ? { id: 'pc', label: 'Connect your PC', done: s.pc } : { id: 'saves', label: 'Save your first link', done: s.items > 0 },
    { id: 'wiskit', label: 'Turn on Wiskit', done: s.ai },
  ]
}

export function progressOf(tasks: Task[], includeOptional = false): { done: number; total: number; all: boolean } {
  if (!includeOptional) tasks = tasks.filter(t => !t.optional)
  const done = tasks.filter(t => t.done).length
  return { done, total: tasks.length, all: done === tasks.length }
}

// Only the local probes establish readiness. Finding a file alone is not enough.
export function toolsReady(t: { tools: { state?: string }[]; youtube?: { ejs: string; functional: boolean; deno: boolean } }): boolean {
  return t.tools.length === 4 && t.tools.every(t => t.state === 'ready') && !!t.youtube?.functional && t.youtube.deno && t.youtube.ejs === 'detected'
}

export function toolState(t: { name: string; state?: string }, install?: { state: string; step: string } | null): string {
  const packages: Record<string, string> = { ffmpeg: 'yt-dlp.FFmpeg', ffprobe: 'yt-dlp.FFmpeg', 'yt-dlp': 'yt-dlp.yt-dlp', deno: 'DenoLand.Deno' }
  if (install?.state === 'running' && packages[t.name] === install.step) return 'Installing'
  if (t.state === 'ready') return 'Ready: found and working'
  if (t.state === 'older') return 'Found an older version: update in Settings > Imports & downloads'
  if (t.state === 'missing') return 'Missing'
  return 'Could not verify: check again or open Settings > Imports & downloads'
}

export interface DriveState { seq: number; state: string; signed_in: boolean; running: boolean; configured: boolean; token_expired?: boolean }
export function driveStep(c: DriveState | null): { ready: boolean; busy: boolean; line: string } {
  if (!c) return { ready: false, busy: false, line: 'Checking Google Drive' }
  if (c.signed_in && c.token_expired && c.state !== 'signing-in') {
    return { ready: false, busy: false, line: 'Google stopped accepting this PC\'s sign-in. Open Settings > Backup & phones and choose Sign in again.' }
  }
  const busy = ['signing-in', 'starting', 'stopping', 'disconnecting'].includes(c.state)
  const ready = c.signed_in && c.running && ['idle', 'publishing'].includes(c.state)
  const lines: Record<string, string> = {
    'signing-in': 'Signing in: finish in the browser window that opened.',
    starting: 'Starting Google Drive uploads.', publishing: 'Uploading your encrypted library to Google Drive.',
    stopping: 'Stopping Google Drive uploads.', disconnecting: 'Disconnecting from Google Drive.',
    error: 'Google Drive upload could not finish. Open Settings > Backup & phones to review the error and retry.',
    'signed-out': 'Signed out of Google Drive. Connect again to resume uploads.',
  }
  return { ready, busy, line: lines[c.state] ?? (c.signed_in ? (c.running ? 'Google Drive uploads are on.' : 'Google Drive uploads are off.') : 'Signed out of Google Drive. Uploads are off.') }
}

// the phone's empty library: one line and one key
export function phoneEmpty(answer: string, paired: boolean): { pc: boolean; line: string; key: string } {
  if (answer === 'pc' && !paired) return { pc: true, line: 'Connect your PC and its library shows up here.', key: 'Connect your PC' }
  return { pc: false, line: 'Share a post to Brainamon from any app, or add one here.', key: 'Add your first save' }
}

export interface Guide { title: string; steps: string[]; key: string }
// the page each manual scraper opens (library/scrape_watch.py PLATFORMS): Facebook and Reddit open the
// Saved page, Instagram its home page (Saved is per user), YouTube the playlists page
const STEP2: Record<Site, string> = {
  instagram: 'Open your profile, then Saved, then All posts. Press F12, choose Console, paste with Ctrl+V, press Enter.',
  facebook: 'On the Saved page that opens, press F12, choose Console, paste with Ctrl+V, press Enter.',
  reddit: 'On the Saved page that opens, press F12, choose Console, paste with Ctrl+V, press Enter.',
  youtube: 'Choose View full playlist / Afficher la playlist complète for one playlist, not the overview. Press F12, choose Console, paste with Ctrl+V, press Enter.',
}
// the focused Scrapers window: the browser helper when it is installed (Facebook, Instagram, Reddit),
// else the manual script pasted in the browser console. Closing the Scrapers window stops both, so the
// last step says to keep it open.
export function scrapeGuide(site: Site, auto: boolean): Guide {
  const n = SITE_NAME[site]
  const title = site === 'youtube' ? 'Bring in a YouTube playlist' : `Bring in your ${n} saves`
  if (auto && site !== 'youtube') {
    return { title, key: `Start the ${n} helper`, steps: [
      'Press the button below. A separate browser window opens.',
      `Sign in to ${n} there if it asks. Brainamon never sees your password.`,
      'Keep this window open. Brainamon imports your saves when the browser window finishes.',
    ] }
  }
  return { title, key: `Copy script and open ${n}`, steps: [
    `Press the button below. Brainamon copies a small script and opens ${n}.`,
    STEP2[site],
    'Keep that page and this window open. Brainamon imports the file the script saves.',
  ] }
}
