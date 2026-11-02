// Add to Brainamon: the rules the desktop window (windows/AddItemWin.svelte) and the phone screen
// (mobile/screens/Capture.svelte) share, so both ask the same things in the same order: incoming
// content, destination (Note or Library), destination fields, optional comment, Save. Pure functions
// and types, no DOM and no stores: tests/test_capture.py runs this file under Node.
// Plan: projects/note-organic-ui/plans/09-add-to-brainamon.md
import { cleanLink } from '../mobile/links'
import { bestNote, kindOf, MAX_BYTES, stamp, UNREADABLE, withSection, type FileKind } from '../mobile/files'
import type { LinkInfo } from '../mobile/linkinfo'

export type Dest = 'note' | 'library'
// a picture or file waiting in a capture; blob is the file itself (IndexedDB keeps it on the phone)
export interface Pic { name: string; type: string; blob: Blob }
// One capture in progress. The phone keeps a list of these in IndexedDB (kv 'drafts'); public/sw.js
// writes the same shape when something is shared to Brainamon, so keep newDraft() and the service
// worker's copy in step (tests/test_phone_share_draft.py checks it).
export interface Draft {
  id: string
  at: number
  origin: 'typed' | 'share' | 'file'
  text: string                    // the incoming content (and the text read from a picture), editable
  comment: string
  dest: Dest | ''                 // '' = not chosen yet: defaultDest()
  target: string                  // '' = a new note, else the file of the note to append to
  title: string                   // '' = titleFor() works one out
  category?: string               // new notes default to Inbox; old drafts and shares omit it
  collection: string
  type: string
  tags: string
  made: string                    // a new note's file when an earlier Save made it but did not finish
  pic: Pic | null
  read: '' | 'digest' | 'describe' // how the picture's text was read: names the section it makes
}

export const INBOX = 'Inbox'
export const RECENT = 5
export const LIBRARY_TYPES = ['Reel', 'Video', 'Post', 'Link', 'Recipe', 'Tutorial', 'Other']
export const KEPT = ' Your capture has been kept.'

export function newDraft(origin: Draft['origin'] = 'typed', text = '', pic: Pic | null = null): Draft {
  return {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), at: Date.now(), origin, text, comment: '',
    dest: '', target: '', title: '', collection: '', type: '', tags: '', made: '', pic, read: '',
  }
}

export const picKind = (p: Pic | null): FileKind | '' => (p ? kindOf(p.name, p.type) : '')
export const isEmpty = (d: Draft) => !d.text.trim() && !d.comment.trim() && !d.pic

// the link in the text: the same parser as the share sheet, Wiskit and the widget (knowledge/inbox.py,
// web/src/mobile/links.ts, public/sw.js, desktop/widget.py; tests/fixtures/share_links.json)
export const linkOf = (text: string) => cleanLink(text)
// the link when the whole text is one link, else ''
export function lone(text: string): string {
  const t = text.trim()
  return t && !/\s/.test(t) ? cleanLink(t) : ''
}

// What a share sheet sends: most apps put the page title on its own line next to the link (Android's
// subject, the PWA's share_title). A link with nothing but that title beside it is a lone link: the link
// is the content (so it starts on Library) and the title names a note. public/sw.js has the same rule
// (tests/test_phone_share_draft.py checks they agree).
export function shareParts(text: string): { text: string; title: string } {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  const at = lines.findIndex(l => /^https?:\/\/\S+$/i.test(l))
  if (at < 0 || lines.length > 2) return { text, title: '' }
  const title = lines.length === 2 ? lines[1 - at] : ''
  if (/https?:\/\//i.test(title) || title.length > 200) return { text, title: '' }
  return { text: cleanLink(lines[at]), title: title.slice(0, 80) }
}

// Library: the text around the link ("Look at this <link> please") goes into the card's note, before
// the comment, so nothing typed or shared is dropped. Not the description: that would stop the
// thumbnail and caption fetch (server/routes/items.py). '' when the text is only the link.
export function around(text: string): string {
  if (lone(text) || !linkOf(text)) return ''
  return text.replace(/https?:\/\/[^\s<>"']+/i, ' ').split('\n').map(l => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n')
}
export const libraryNote = (d: Draft) => [around(d.text), d.comment.trim()].filter(Boolean).join('\n\n')

// ── a lone link's page (POST /api/link/preview, or the phone's own reader; projects/link-preview) ──
// What the link's page says about itself (the rules of mobile/linkinfo.ts). `asked` is the link it was
// asked for: an answer for an earlier link is never used. Nothing here is saved until Save.
export interface Preview extends LinkInfo { asked: string; url: string; found: boolean }
export const pageOf = (d: Draft, p?: Preview | null): Preview | null =>
  p && p.found && p.asked === lone(d.text) && (p.title || p.desc) ? p : null
// what a note gets under the link: the page title, then its caption
export const pageLines = (d: Draft, p?: Preview | null): string => {
  const x = pageOf(d, p)
  return x ? [x.title, x.desc].filter(Boolean).join('\n') : ''
}
export const siteOf = (url: string): string => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return '' } }

// a lone link starts on Library (what the share sheet always did), anything else on Note
export const defaultDest = (d: Draft): Dest => (!d.pic && lone(d.text) ? 'library' : 'note')
export const destOf = (d: Draft): Dest => d.dest || defaultDest(d)

// thumb: a picture can become a Library item's thumbnail (the PC app only); known: the id of the
// Library item that already has this link
export interface Caps { thumb: boolean; known?: number }
export interface Verdict { ok: boolean; help: string }
const no = (help: string): Verdict => ({ ok: false, help })
const yes = (help: string): Verdict => ({ ok: true, help })

export function verdict(d: Draft, c: Caps): Verdict {
  const text = d.text.trim()
  if (!text && !d.pic) return no('Add a link, some text or a picture to save.')
  if (destOf(d) === 'library') {
    if (!linkOf(d.text)) return no('Library items need a web link. Choose Note to keep this text.')
    if (c.known) return no(`Already in your library as No. ${c.known}.`)
    if (picKind(d.pic) === 'image') {
      if (!c.thumb) return no('A picture can only go into a Library item from the PC app. Choose Note, or remove the picture.')
      return yes('Creates a Library card. The picture becomes its thumbnail and the text its description.')
    }
    return yes(lone(d.text) ? 'Creates a Library card.' : 'Creates a Library card from the link. The text around it goes into the card\'s note.')
  }
  if (!text) return no(picKind(d.pic) === 'image' ? 'Read the picture\'s text, or type it. Brainamon keeps the text, not the picture.' : 'Add some text to save.')
  return yes(d.target ? 'Adds a section at the end of the note. Nothing already there changes.' : `Creates a note in ${d.category || INBOX}.`)
}

// what the help line under the content says about it
export function sourceHelp(d: Draft, p?: Preview | null): string {
  if (picKind(d.pic) === 'image') return 'Reading a picture copies its text into the box. Review it before saving.'
  if (destOf(d) === 'library') return 'The Library card gets the link\'s thumbnail and caption after saving.'
  if (pageOf(d, p)) return 'The page\'s title and caption go under the link.'
  return linkOf(d.text) ? 'The link is kept as text.' : 'The content is kept as written.'
}

// ── what a note gets ──────────────────────────────────────────────────────────
export function label(d: Draft): string {
  if (d.read === 'digest') return 'Screenshot digest'
  if (d.pic && d.read) return d.pic.name.slice(0, 80)          // the PC keeps 80 characters of a section's name
  return lone(d.text) ? 'Link' : 'Note'
}
export const noteText = (d: Draft, p?: Preview | null) => [d.text.trim(), pageLines(d, p), d.comment.trim()].filter(Boolean).join('\n\n')
export const newBody = (d: Draft, p?: Preview | null) => noteText(d, p) + '\n'
// = knowledge/filing.py heading + add_section: a dated section at the end, the old text untouched
export const section = (d: Draft, when = stamp(), p?: Preview | null) => `## From ${label(d)} - ${when}\n\n${noteText(d, p)}`
export const appended = (old: string, d: Draft, when = stamp(), p?: Preview | null) => withSection(old, label(d), noteText(d, p), when)

export function titleFor(d: Draft, p?: Preview | null): string {
  const typed = d.title.trim().slice(0, 80)
  if (typed) return typed
  const page = pageOf(d, p)
  const named = page ? (page.title || page.desc.split('\n')[0]).trim() : ''
  if (named) return named.slice(0, 80).trim()
  const link = lone(d.text)
  if (link) {
    try { return `Link from ${new URL(link).hostname.replace(/^www\./, '')}` } catch { /* fall through */ }
  }
  const first = d.text.split('\n').map(l => l.replace(/^[#>\-*\s]+/, '').trim()).find(Boolean)
  if (first) return first.slice(0, 60).trim()
  return d.pic?.name.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ').trim() || 'Quick note'
}

// ── one picture or file at a time ─────────────────────────────────────────────
export type FileCheck = { ok: true; kind: FileKind } | { ok: false; msg: string }
export function checkFiles(files: { name: string; type: string; size: number }[]): FileCheck {
  if (files.length !== 1) return { ok: false, msg: 'Add one picture or file at a time.' + KEPT }
  const f = files[0], kind = kindOf(f.name, f.type)
  if (!kind) return { ok: false, msg: UNREADABLE + KEPT }
  if (f.size > MAX_BYTES[kind]) return { ok: false, msg: `That file is over ${MAX_BYTES[kind] / 1024 / 1024} MB.` + KEPT }
  return { ok: true, kind }
}

// text read from a picture or file goes after what is already in the box, never over it
export const joinText = (old: string, read: string) => (old.trim() ? old.trimEnd() + '\n\n' + read.trim() : read.trim())

// ── the note picker: the newest notes, or the ones matching the search ────────
export interface NoteRef { file: string; title: string; category?: string; updated?: string; head?: string; snippet?: string }
const hay = (n: NoteRef) => `${n.title} ${n.category ?? ''} ${n.head ?? n.snippet ?? ''}`.toLowerCase()
export function pickNotes(notes: NoteRef[], q: string, suggested = ''): NoteRef[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const found = notes.filter(n => words.every(w => hay(n).includes(w))).sort((a, b) => (b.updated ?? '').localeCompare(a.updated ?? ''))
  if (words.length) return found.slice(0, 8)
  const top = found.slice(0, RECENT), hit = found.find(n => n.file === suggested)
  return hit && !top.includes(hit) ? [hit, ...top.slice(0, RECENT - 1)] : top
}
export const suggestNote = (text: string, notes: NoteRef[]) =>
  bestNote(text, notes.map(n => ({ file: n.file, title: n.title, body: n.head ?? n.snippet ?? '' })))

// ── the saved result ──────────────────────────────────────────────────────────
// synced: the PC has it; pending: kept on this phone, it goes to the PC when it can; failed: not saved
export type SaveState = 'synced' | 'pending' | 'failed'
export interface Saved { state: SaveState; title: string; detail: string; page: string; meta: string; file?: string; itemId?: number; fetching?: boolean }
export const STATE_LABEL: Record<SaveState, string> = { synced: 'Saved', pending: 'Waiting for the PC', failed: 'Not saved' }
