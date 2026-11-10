// The phone shell's route rules (projects/phone-dock-shell): which routes are section pages (the top bar
// and the dock), which open as a sheet over a section, and the hash of a section. Run by Node in the tests
// (type stripping): type-only import, nothing else.
import type { Route } from './state.svelte'

export type Base = 'lib' | 'cv'
export type SheetKind = 'notes' | 'jv' | 'cap'

// the Library grid (searching or not) and the Canvas list
export const isSection = (r: Route): boolean => (r.tab === 'lib' && !r.item) || (r.tab === 'cv' && !r.canvas)
export const isCompose = (r: Route): boolean => r.tab === 'cv' && (r.canvas === 'new' || !!r.add)
export const sheetOf = (r: Route): SheetKind | null => (r.tab === 'notes' || r.tab === 'jv' || r.tab === 'cap' ? r.tab : null)
// a page inside a sheet (a note, the chats, Import, Add's recap, the Notes search): the sheet's Back walks to its root first
export const sheetSub = (r: Route): boolean => !!(r.note || r.mynote || r.synth !== undefined || r.find || r.chats || r.imp || r.save)
export const baseHash = (b: Base): string => (b === 'cv' ? '#/canvas' : '#/lib')
