// Add a picture or file on the phone (projects/wiskit-files plan 04, folded into Add to Brainamon by
// projects/note-organic-ui/plans/09-add-to-brainamon.md): what a picked or shared file
// is, the prompts that read it (copies of knowledge/tasks.py DIGEST_PROMPT and ATTACH_PROMPT, kept
// equal by tests/test_phone_files.py), the section a note gets (= knowledge/filing.py heading +
// add_section), and the note a text most likely belongs in. No imports: the Python test runs this
// file under Node.

export type FileKind = 'image' | 'pdf' | 'text'
// data: base64 without the data: prefix
export interface Picked { name: string; type: string; kind: FileKind; data: string }

export const MAX_BYTES: Record<FileKind, number> = { image: 10 * 1024 * 1024, pdf: 30 * 1024 * 1024, text: 2 * 1024 * 1024 }
export const ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,application/pdf,.pdf,.md,.txt,text/markdown,text/plain'
export const UNREADABLE = 'Brainamon reads pictures (PNG, JPEG, WebP, GIF), PDFs and .md or .txt files.'

const IMAGE: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' }
const ext = (name: string) => (name.match(/\.([a-z0-9]+)$/i)?.[1] ?? '').toLowerCase()

// '' when Brainamon cannot read it
export function kindOf(name: string, type: string): FileKind | '' {
  const e = ext(name)
  if (IMAGE[e] || /^image\/(png|jpeg|webp|gif)$/.test(type)) return 'image'
  if (e === 'pdf' || type === 'application/pdf') return 'pdf'
  if (e === 'md' || e === 'txt' || type === 'text/markdown' || type === 'text/plain') return 'text'
  return ''
}

// a name with an extension the PC understands: shares can come without one, the type fills it in
export function fileName(name: string, type: string): string {
  const n = (name || '').trim() || 'shared'
  if (kindOf(n, '')) return n
  const e = type === 'application/pdf' ? 'pdf' : type === 'image/jpeg' ? 'jpg' : /^image\/(png|webp|gif)$/.test(type) ? type.slice(6)
    : type === 'text/markdown' ? 'md' : type === 'text/plain' ? 'txt' : ''
  return e ? `${n}.${e}` : n
}

export const mediaType = (name: string, type: string) => IMAGE[ext(name)] ?? (type || 'image/png')

export function decodeText(b64: string): string {
  return new TextDecoder().decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)))
}

// = knowledge/tasks.py DIGEST_PROMPT (verbatim, em dash included) and ATTACH_PROMPT
export const DIGEST_PROMPT = 'Transcribe all the text visible in this screenshot verbatim, including usernames/handles '
  + 'and comment text where present. Preserve line breaks between distinct comments. Do not '
  + 'summarize, paraphrase, or add commentary — output only the transcribed text. UI chrome '
  + '(icons, buttons, timestamps) that isn\'t meaningful content may be omitted.'
export const ATTACH_PROMPT = 'Describe this image for someone who will ask questions about it: what it shows, '
  + 'and every piece of text in it, transcribed exactly. Plain Markdown, no preamble.'
export const PDF_PROMPT = 'Turn this PDF into Markdown: every heading, paragraph, list and table, in order, with the '
  + 'wording kept. No summary, no commentary, no preamble.'

export function stamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// = knowledge/filing.py: the text under "## From <name> - <when>" at the end of the body
export function withSection(body: string, from: string, text: string, when = stamp()): string {
  const head = `## From ${from} - ${when}`
  const b = body.trimEnd()
  return (b ? b + '\n\n' : '') + `${head}\n\n${text.trim()}\n`
}

// the note a text most likely belongs in: the most shared content words (4+ letters), a title word
// counting double; '' when nothing shares at least two points. No AI call, works offline.
export function bestNote(text: string, notes: { file: string; title: string; body?: string }[]): string {
  const words = (s: string) => new Set(s.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu) ?? [])
  const want = words(text.slice(0, 4000))
  let best = '', top = 1
  for (const n of notes) {
    let s = 0
    for (const w of words(n.title)) if (want.has(w)) s += 2
    for (const w of words(n.body ?? '')) if (want.has(w)) s += 1
    if (s > top) { top = s; best = n.file }
  }
  return best
}

// a picked or shared file as a Picked; throws with the message to show when it cannot be read
export async function toPicked(blob: Blob, rawName: string, rawType: string): Promise<Picked> {
  const type = rawType || blob.type
  const name = fileName(rawName, type), kind = kindOf(name, type)
  if (!kind) throw new Error(UNREADABLE)
  if (blob.size > MAX_BYTES[kind]) throw new Error(`That file is over ${MAX_BYTES[kind] / 1024 / 1024} MB.`)
  const data = await new Promise<string>((res, rej) => {
    const r = new FileReader()
    r.onload = () => res(String(r.result).split(',')[1] ?? '')
    r.onerror = () => rej(r.error)
    r.readAsDataURL(blob)
  })
  return { name, type, kind, data }
}

