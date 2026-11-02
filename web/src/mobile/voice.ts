// Voice notes on the phone (projects/voice-notes/plans/02-phone.md): the text section a recording
// becomes, and the queue of recordings made without signal (IndexedDB `brainamon-voice`).
// Run by Node in the tests (type stripping): no parameter properties, no imports.

const p2 = (n: number) => String(n).padStart(2, '0')

// the PC's stamp (knowledge/my_notes.py append_voice): local time, YYYY-MM-DD HH:MM
export function stamp(d = new Date()): string {
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
}

// the same text as my_notes.append_voice
export function appendVoice(body: string, text: string, at = stamp()): string {
  const head = body.trimEnd()
  return (head ? head + '\n\n' : '') + `## Voice note - ${at}\n\n${text.trim()}\n`
}

export const MAX_BYTES = 24 * 1024 * 1024

export interface Queued { id?: number; file: string; at: number; type: string; blob: Blob }

const DB = 'brainamon-voice', STORE = 'rec'
function open(): Promise<IDBDatabase> {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1)
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true })
    r.onsuccess = () => res(r.result)
    r.onerror = () => rej(r.error)
  })
}
function done<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error) })
}

export async function enqueue(file: string, blob: Blob): Promise<void> {
  const db = await open()
  await done(db.transaction(STORE, 'readwrite').objectStore(STORE).add({ file, at: Date.now(), type: blob.type, blob } satisfies Queued))
  db.close()
}
export async function queued(): Promise<Queued[]> {
  const db = await open()
  const all = await done(db.transaction(STORE, 'readonly').objectStore(STORE).getAll()) as Queued[]
  db.close()
  return all.sort((a, b) => a.at - b.at)
}
async function drop(id: number): Promise<void> {
  const db = await open()
  await done(db.transaction(STORE, 'readwrite').objectStore(STORE).delete(id))
  db.close()
}

// Transcribe and save every waiting recording, oldest first. `skip(file)` is true for a note the editor
// holds open (its text is added from the screen instead). Stops at the first failure and keeps the rest.
// Returns how many were saved.
export async function flush(
  transcribe: (b: Blob) => Promise<string>,
  save: (file: string, text: string) => Promise<void>,
  skip: (file: string) => boolean,
): Promise<number> {
  let n = 0
  for (const q of await queued()) {
    if (skip(q.file)) continue
    try {
      const text = await transcribe(q.blob)
      if (text) await save(q.file, text)
      await drop(q.id as number)
      n++
    } catch { break }
  }
  return n
}
