// What a phone screen asks for. Phase 2 (projects/mobile-app/PLAN.md): DesktopSource answers from the
// desktop's REST API over adb reverse. Phase 4: MirrorSource (./mirror.ts) answers from the encrypted
// Google Drive mirror behind the same interface, once the phone is paired. Types are shared with the desktop front end
// (type-only imports: nothing of the desktop stores is bundled through them).
import type { Category, Row as LibraryRow } from '../../lib/library.svelte'
import type { CanvasDocument, RawCanvasProposal } from '../ai/canvas'
import type { ItemText } from '../ai/describe'
import type { NoteRow, OpenNote } from '../../lib/knowledge.svelte'
import type { MyNote } from '../../lib/notes.svelte'
import type { Stamp } from '../../lib/note-format'
import type { CanvasDoc, CanvasRow } from '../../lib/canvas.svelte'
import type { PcStatus, Env as VaultEnv, Result as VaultResult } from '../vault/sync'
import type { Picked } from '../files'
import type { Preview } from '../../lib/capture'
import type { CanvasPreview } from '../../lib/job-requests'
import type { ToolsUndo } from '../tools'

export type Row = LibraryRow & { uid?: string }
export type { Category, NoteRow, OpenNote, MyNote, CanvasDoc, CanvasRow }
export interface CanvasDraftContext {
  opId: string; canvasId: string; at: number; base: CanvasDocument | null
  thumbs: { id: number; uid?: string; version: string; blob: Blob; size: [number, number] }[]
}

// GET /api/items/{id}: the whole row plus which files exist (server/routes/library.py)
export interface FullItem {
  id: number; url: string; description: string; short_desc: string; creator: string; type: string
  category: string; tags: string; ai_desc: string; notes: string; thumb_path: string; created: number; modified: number
  analysis_done?: number; transcript?: string; favourite?: number
  files: { thumb: boolean; report: boolean; transcript: boolean; frames: number; frame_names: string[]; video: boolean }
  [k: string]: unknown
}

export interface ChatRow { slug: string; name: string; created: string; updated: string; message_count: number; source_count: number }
export interface ChatTurn { role: 'user' | 'assistant'; content: string }
export interface Chat { slug: string; name: string; history: ChatTurn[]; sources: Row[]; [k: string]: unknown }
export interface CategoryProposal { requestId?: number; entries: { id: number; title: string; from: string; category: string }[] }
export type PhoneCanvasProposal = { mode: 'local'; token: string; preview: CanvasPreview }
  | { mode: 'pc'; requestId: number; preview: CanvasPreview }

// POST /api/ask events (server/routes/ask.py docstring)
export type AskEvent =
  | { ev: 'start'; run: string }
  | { ev: 'context'; line: string; ids: number[]; list?: boolean }
  | { ev: 'progress'; line: string }
  | { ev: 'chunk'; text: string }
  | { ev: 'reset' }
  | { ev: 'done'; text: string; cited: number[]; notes: string[]; sources: Row[]; chat: { slug: string; name: string } }
  | { ev: 'stopped' }
  | { ev: 'error'; message: string }
  | { ev: 'category_proposal'; proposal: CategoryProposal }
  | { ev: 'canvas_proposal'; proposal: PhoneCanvasProposal }

// the phone's own AI (PLAN.md Phase 5): the providers it holds a key for (from the pairing QR) with
// their models, the ones Wiskit uses now, whether Smart search can embed (an OpenAI key), and the
// provider / model Synthesize uses
export interface AiInfo {
  providers: { id: string; label: string; models: { id: string; label: string }[] }[]
  provider: string; model: string; label: string; smart: boolean; synth: string
}

export interface MobileSource {
  readonly kind: 'desktop' | 'mirror'
  readonly label: string                                   // "PC" for the desktop, "Mirror" later
  health(): Promise<{ ok: boolean; items: number }>
  // the light copy
  // `step` names where a refresh is (the pull widget, state.svelte.ts syncNow); `progress` counts
  // the library parts fetched (the Library's first-load bar)
  rows(step?: (key: 'read' | 'lib', note?: string) => void, progress?: (done: number, total: number) => void): Promise<{ rows: Row[]; cats: Category[] }>
  rowsByIds(ids: number[]): Promise<Row[]>
  tints(): Promise<Record<string, string>>
  // the heavy parts, fetched when opened
  thumbUrl(r: Row, w?: number): string
  item(id: number): Promise<FullItem>
  itemText(id: number, which: 'report' | 'transcript'): Promise<string>
  related(id: number): Promise<Row[]>
  // search (keyword on the server's FTS, Smart by meaning)
  search(q: string): Promise<number[]>
  smart(q: string): Promise<number[]>
  // the phone's few writes
  favourite(id: number, on: boolean): Promise<Row>
  edit(id: number, fields: Record<string, string>): Promise<Row>
  saveLink(url: string): Promise<{ id: number | null; new: boolean }>
  // Add to Brainamon's preview card (projects/link-preview): what a lone link's page says; nothing is kept
  linkPreview?(url: string): Promise<Preview>
  // notes
  notes(): Promise<NoteRow[]>
  note(file: string): Promise<OpenNote>
  myNotes(): Promise<MyNote[]>
  myNote(file: string): Promise<MyNote>
  myNoteCategories(): Promise<string[]>
  // the Notes search (projects/phone-notes-manager): file to the note's whole plain text; the Drive mirror only
  // (a phone straight to the PC searches the lists' text)
  noteBodies?(): Promise<Record<string, string>>
  createMyNote(title: string, category: string): Promise<MyNote>
  // `stamps` (undefined: keep the note's existing stamps line) is the plan 01 stamp list; carried
  // to the PC over the REST API or a mirror change, and applied by server/intake.py.
  saveMyNote(file: string, title: string, category: string, body: string, stamps?: Stamp[]): Promise<MyNote>
  // Add to Brainamon (plans/09-add-to-brainamon.md): one "## From <name> - <when>" section at the end of a
  // note. Only the new text travels, so what the PC wrote into the note since this phone read it stays.
  appendMyNote(file: string, title: string, name: string, text: string): Promise<MyNote>
  deleteMyNote?(file: string): Promise<void>
  // My Notes categories (spec 2026-11-07 phone note page, section 4): '' when this source can rename one, else
  // why not; the rename moves every note filed under `from` and returns the categories after it
  renameBlocked?(words?: import('../tools').ToolWords): string
  renameMyNoteCategory?(from: string, to: string): Promise<string[]>
  // voice notes: present on a source that can reach OpenAI transcription (needs the paired OpenAI key)
  canTranscribe?(): boolean
  transcribe?(audio: Blob, signal?: AbortSignal): Promise<string>
  // Add a picture or file (projects/wiskit-files plan 04): its text, nothing kept. A picture is
  // transcribed (digest) or described; a PDF or text file is read. The desktop reads it on the PC
  // (POST /api/filing/read); the mirror with the phone's own key
  readFile(f: Picked, how: 'digest' | 'describe'): Promise<string>
  syncVault?(force?: boolean, progress?: VaultEnv['progress'], signal?: { aborted: boolean }, words?: (key: string, params?: Record<string, unknown>) => string): Promise<VaultResult>
  vaultPc?(): Promise<PcStatus | null>
  // Remove old Brainamon pages (spec 1b decision 3): what is left of the classic Content Manager/ folder goes
  // to .trash/, on the user's click; how many files moved
  vaultRemoveLegacy?(): Promise<number>
  // canvases
  canvases(): Promise<CanvasRow[]>
  canvasTitle?(id: string, words?: (key: string, params?: Record<string, unknown>) => string): string
  canvas(id: string): Promise<CanvasDoc>
  canvasImageUrl(name: string): string
  canvasStatus?(id: string, words?: (key: string, params?: Record<string, unknown>) => string): string
  canvasDraftProblem?(id: string, words?: (key: string, params?: Record<string, unknown>) => string): Promise<string | null>
  applyCanvasDraft?(raw: RawCanvasProposal, context: CanvasDraftContext): Promise<string>
  lastCanvasRefusal?(): { id: string; reason: string } | null
  // pc: delete it in the PC library too (the desktop always does), else only from the phone's copy
  deleteItem(id: number, pc: boolean): Promise<void>
  // Wiskit
  chats(): Promise<{ chats: ChatRow[]; active: string }>
  chat(slug: string): Promise<Chat>
  newChat(name?: string): Promise<Chat>
  // on the PC as well: the desktop at once, the mirror through a change file
  deleteChat(slug: string): Promise<void>
  // mode 'deep': the librarian agent researches with tools (on the PC, or on the phone with its own key)
  ask(question: string, chat: string, onEvent: (e: AskEvent, display?: string) => void, signal: AbortSignal, mode?: 'quick' | 'deep', words?: (key: string, params?: Record<string, unknown>) => string): Promise<void>
  stopAsk(run: string): Promise<void>
  saveAnswer(md: string, ids: number[]): Promise<{ file: string }>
  categoryProposal?(): Promise<CategoryProposal | null>
  applyCategoryProposal?(proposal: CategoryProposal): Promise<void>
  declineCategoryProposal?(): Promise<void>
  canvasProposal?(): Promise<PhoneCanvasProposal | null>
  applyCanvasProposal?(proposal: PhoneCanvasProposal): Promise<string>
  declineCanvasProposal?(proposal: PhoneCanvasProposal): Promise<void>
  // live changes while the source is reachable (the desktop's SSE stream); returns a stop function
  watch(onItems: (ids: number[]) => void, onNotes: () => void, onCanvas?: () => void): () => void
  // the PC only: its one request slot changed (a new request, or one answered elsewhere)
  watchRequests?(onChange: () => void): () => void
  // the mirror only: the item's video when the PC mirrored it (bytes, 0 = none), Save for offline
  videoSize?(id: number): number
  video?(id: number, onProgress?: (got: number, total: number) => void): Promise<Blob>
  thumbBlob?(r: Row): Promise<Blob | null>
  canvasImage?(name: string): Promise<Blob>
  // the mirror only (milestone-2026-10-14/plans/E-phone-fixes.md): Describe and Categorize one item with
  // the phone's own key. Both queue an `edit` change for the PC. describe returns the new text or null when skipped;
  // categorize returns the updated row.
  describe?(id: number, undo?: (t: ToolsUndo) => void): Promise<string | null>
  fetchInfo?(id: number, onRow?: (id: number) => Promise<void>): Promise<Row | null>
  categorize?(id: number, categories: string[]): Promise<Row>
  // the mirror only (projects/phone-processing-flow): the Tools panel's Undo of one single-item result (one more `edit`
  // change, refused when the card changed since), and the sentence it shows when the phone has no AI key
  undoTool?(t: ToolsUndo): Promise<Row>
  noKeyText?(words?: (key: string, params?: Record<string, unknown>) => string): string
  // the mirror only (projects/phone-add-confirm): Add's Suggest, the same Categorize prompt for a link that is not a
  // card yet; nothing is written or queued, the recap shows the answer and Save sends it with the link
  suggestCategory?(item: ItemText, categories: string[]): Promise<{ category: string; tags: string }>
  // the mirror only (Phase 5): the phone's own AI; null when the pairing carried no AI key
  ai?(): AiInfo | null
  setAi?(provider: string, model: string): void
  // Synthesize a note from these items: on the phone (the mirror, up to synthMax sources; more are
  // queued for the PC), or as a job on the PC (the desktop). `file` is the note to open, '' if queued
  synthesize?(topic: string, ids: number[], onLine: (line: string) => void, signal: AbortSignal, words?: (key: string, params?: Record<string, unknown>) => string): Promise<{ file: string; queued: boolean }>
  synthTextless?(ids: number[]): Promise<number[]>
  readonly synthMax?: number
  // the mirror only (Phase 6): the PC's Obsidian vault folder name, the default for Open in Obsidian
  obsidianVault?(): string
  // the mirror only: the notes folder inside that vault ('' = the classic Content Manager/notes/)
  obsidianNotes?(): string
}
