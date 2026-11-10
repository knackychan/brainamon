// The phone's Add recap (projects/phone-add-confirm): the page Save opens before anything is created (#/cap/save). It
// shows a preview of the result, the attachment's line and where it goes. These are the phone's own rules on top of
// the shared ones in web/src/lib/capture.ts, which the desktop Add window keeps as they are (its Inbox included).
// Pure functions, no DOM and no stores: tests/test_capture_recap.py runs this file under Node.
import { destOf, linkOf, lone, pageOf, picKind, type CaptureWords, type Dest, type Draft, type Preview } from '../lib/capture'

// a new note from the phone's Add goes to General, like every other new note in Brainamon (knowledge/my_notes.py
// DEFAULT_CATEGORY); Inbox stays in the list only while the source lists it (a note uses it)
export const GENERAL = 'General'

// the category list: General first, then the categories the notes use, then the draft's own (an old draft's Inbox)
export const categoriesFor = (listed: string[], own = ''): string[] => [...new Set([GENERAL, ...listed, ...(own ? [own] : [])])]

// why the Library cannot take this draft on the phone, '' when it can (the reasons verdict() gives, phone wording)
export function libraryBlock(d: Draft, known?: number, words?: CaptureWords): string {
  if (!linkOf(d.text)) return words?.('capture.recap.needsLink') ?? 'Library items need a web link.'
  if (known) return words?.('capture.recap.known', { id: known }) ?? `Already in your library as No. ${known}.`
  if (picKind(d.pic) === 'image') return words?.('capture.recap.picturePc') ?? 'A picture can only go into a Library item from the PC app. Choose Note, or remove the picture.'
  return ''
}

// where the recap stands: the draft's choice (a lone link starts on Library), Note whenever the Library cannot take it
export const phoneDest = (d: Draft, known?: number): Dest => (destOf(d) === 'library' && !libraryBlock(d, known) ? 'library' : 'note')

// the one line under the destination that is not chosen
export const noteHint = (d: Draft, p?: Preview | null, words?: CaptureWords): string =>
  pageOf(d, p) ? words?.('capture.recap.pageUnderLink') ?? 'The page\'s title and caption go under the link.' : words?.('capture.recap.linkAsText') ?? 'The link is kept as text.'
export const libraryHint = (d: Draft, words?: CaptureWords): string => (lone(d.text) ? words?.('capture.recap.cardLink') ?? 'A card from the link.' : words?.('capture.recap.cardText') ?? 'A card from the link; the text goes into its note.')

// a Library item's collection: there is no "PC decides". It starts on the collection used last on this phone (a new
// one made here may not be in the library's list yet), else INTERESTING, the library's own default; the recap shows it
// before Save, and Suggest asks Wiskit with this phone's key
export const INTERESTING = 'INTERESTING'
export const startCollection = (last: string): string => last.trim() || INTERESTING
// the collection list: the library's own, INTERESTING always, then the draft's own when the list lacks it
export const collectionsFor = (names: string[], own = ''): string[] => [...new Set([...names, INTERESTING, ...(own ? [own] : [])])]
export const NAME_IT = 'Name the new collection, or pick one.'
// Suggest's confirm line, what the recap says once Wiskit answered, and when it could not
export const SUGGEST = { name: 'Suggest', says: 'Wiskit reads the link and what its page says, then picks one of your collections and a few tags. It uses the AI key on this phone.' }
export const pickedLine = (category: string, tags: string, words?: CaptureWords): string =>
  words?.(tags ? 'capture.suggest.pickedTags' : 'capture.suggest.picked', tags ? { category, tags } : { category }) ?? `Wiskit picked ${category}${tags ? ` and the tags ${tags}` : ''}. Change them if you like.`
export const suggestFailed = (message: string, words?: CaptureWords): string =>
  words?.('capture.suggest.failed', { message: message.trim().replace(/\.+$/, '') }) ?? `Wiskit could not suggest a collection: ${message.trim().replace(/\.+$/, '')}. Pick one yourself.`

// the draft's help line: Save only opens the recap, so it says nothing about a destination
export const draftHelp = (d: Draft, words?: CaptureWords): string =>
  d.text.trim() || d.pic ? words?.('capture.draft.help') ?? 'Nothing is saved yet. Save shows what goes where.' : words?.('capture.draft.emptyHelp') ?? 'Add a link, some text or a picture to save.'

// the attachment, named for the recap: what it is and what happens to it
export const KIND_TAG: Record<string, string> = { image: 'IMG', pdf: 'PDF', text: 'TXT' }
export function attLine(d: Draft, words?: CaptureWords): string {
  if (words) return words(picKind(d.pic) === 'image' ? d.read ? 'capture.attachment.imageRead' : 'capture.attachment.imageUnread' : d.read ? 'capture.attachment.documentRead' : 'capture.attachment.documentUnread')
  const what = picKind(d.pic) === 'image' ? 'picture' : 'document'
  return d.read ? `1 ${what}. Its text is in the preview above. The ${what} itself is not kept.`
    : `1 ${what}, not read yet. Brainamon keeps the text, not the ${what}.`
}

// the end of an existing note, above the section an addition makes: its last lines that have words
export function tailOf(body: string, lines = 3): string {
  return body.split('\n').filter(l => l.trim()).slice(-lines).join('\n')
}
