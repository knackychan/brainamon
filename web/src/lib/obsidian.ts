// Settings > Obsidian copy (spec docs/superpowers/specs/2026-10-28-map-engine-owner-vault-design.md, decision 1).
// Pure: no DOM, no fetch; tests/test_obsidian_copy_js.py reads it under Node. The components render these
// strings through the ui/ blocks and never hold copy of their own.

// Task 0 Check B of the plan: true when obsidian://open?path= opens a folder Obsidian has never opened.
export const OPEN_DIRECT = false

export const COPY = {
  existing: 'Use existing vault',
  upcoming: '(upcoming)',
  existingHint: 'Connect your own notes vault: coming in a later update. Your vault stays untouched. Have an empty vault, or one Brainamon made before? Use the link under Create a new vault.',
  create: 'Create a new vault',
  emptyLink: 'Or use one you already created',
  willCreate: 'Brainamon will create:',
  changeFolder: 'Change folder',
  createButton: 'Create',
  folderHint: 'Change folder picks where the vault goes: Brainamon makes the Brainamon Vault folder inside it. You can edit the name in the field.',
  pickTitle: 'Pick the vault you already created',
  pickHint: 'An empty vault you made in Obsidian, or a vault Brainamon made before. Brainamon never changes its settings.',
  browse: 'Browse for the folder',
  knownVaults: 'Vaults Obsidian knows:',
  use: 'Use this vault',
  copyPath: 'Copy path',
  openObsidian: OPEN_DIRECT ? 'Open in Obsidian' : 'Start Obsidian',
  done: 'Done',
  firstOpenTitle: 'Open it in Obsidian once',
  ownerSync: 'Phone: press Sync my Obsidian vault under Vault sync with phone, below. The pages Brainamon generates go one way, PC to phone; your own files, and anything you add inside the Brainamon folder, sync both ways.',
  syncOnHint: 'Vault sync is on: the new vault reaches your phone too, as long as every phone runs the current Brainamon app. Vault sync pauses otherwise and names the phone to update.',
  pictures: 'Include pictures',
  picturesHint: 'Copies each item\u2019s thumbnail into the vault (about 45 KB per item). Off by default.',
  openVault: 'Open in Obsidian',
  changeVault: 'Use another folder',
  reset: 'Reset to generated',
  reclaim: 'Reclaim generated pages',
  takeOver: 'Take over this vault',
  takeOverKeep: 'Take over, keep them',
  takeOverRemove: 'Take over and remove them',
  takeOverHint: 'Take over makes this library the vault’s owner. Pages that match your library are refreshed, pages you edited stay yours, and the others stay as they are until you remove them. Your own files are never touched.',
  removeLeftovers: 'Remove leftovers',
  removeDetail: 'Only pages Brainamon generated and nobody changed since are deleted. Pages you edited and your own files stay.',
  reclaimDetail: 'Brainamon then updates the pages it can prove it generated, and removes those whose item is gone. Your own files stay yours.',
  viewHint: 'The Brainamon folder is a view of your library: change items in Brainamon. Write your own notes anywhere else in the vault; Brainamon never touches them.',
  earlierTitle: 'Earlier vault',
  earlierHint: 'Brainamon found a vault it made before at',
  reconnect: 'Reconnect this vault',
  otherFolder: 'Choose another folder',
  missingTitle: 'Vault not found',
  missingHint: 'The vault folder was moved, renamed or deleted. Brainamon writes nothing until you locate it or create a new one.',
  locate: 'Locate the folder',
  locateTitle: 'Find the vault you moved or renamed',
  locateHint: 'Pick the folder where the vault is now. Brainamon checks it before using it.',
  cancel: 'Cancel',
  moveTitle: 'Move to a new vault',
  moveHint: 'Your vault still sits inside the Brainamon data folder. The move copies your own files, .obsidian and .trash into the new folder (never the generated Content Manager folder), checks every copy, and renders the Brainamon folder there. The old folder is left as it is: delete it by hand once you are happy.',
  moveButton: 'Move to a new vault',
  moveDone: 'Moved. The old folder is no longer used; delete it by hand when you are satisfied.',
  mapTitle: 'Knowledge map',
  mapHint: 'Wiskit uses the map even without Obsidian. Refresh map runs the paid parts: tag cleanup, summaries for new and changed topics, and a full rebuild when ticked.',
  rebuild: 'Rebuild the topics (regroups everything; kept ids keep their summaries)',
  refresh: 'Refresh map',
  finish: 'Finish the map',
  indexNow: 'Index now',
  upToDate: 'The map is up to date.',
}

export const VAULT_NAME = 'Brainamon Vault'

// The folder dialog picks a place that exists; the new vault goes in a folder of its own inside it
// (unless the picked folder already carries that name).
export function vaultIn(parent: string): string {
  const p = parent.replace(/[\\/]+$/, '')
  return p.split(/[\\/]/).pop() === VAULT_NAME ? p : `${p}\\${VAULT_NAME}`
}

// Obsidian only opens folders it already knows; for a new one the server just starts it (opened: false).
export function newToObsidianText(path: string): string {
  return `Obsidian is starting. It has not opened this folder yet: choose Open folder as vault and pick ${path}. After that, Open in Obsidian goes straight to your map.`
}

export function firstOpenText(path: string): string {
  return `In Obsidian, choose Open folder as vault and pick ${path}. Ctrl+G shows the graph.`
}

export function useAnyway(n: number): string {
  return `Use it anyway (${n} other item${n === 1 ? '' : 's'} ${n === 1 ? 'stays' : 'stay'} untouched)`
}

export interface MapStatus {
  seq?: number; state: string; pending: boolean; error: string; busy: string; waiting: boolean
  last_maintenance: number; last_render: number; written: number; removed: number
  adopted: string[]; unlisted: number; other_library: boolean; missing?: boolean; leftovers?: number
  topics: number; stale: number; pending_summaries: number
}

export function leftoversText(n: number): string {
  return `${n === 1 ? '1 page from an earlier library covers' : `${n} pages from an earlier library cover`} items or topics this library does not have. Kept as they were until you remove them.`
}

export function removeText(n: number): string {
  return `Delete ${n === 1 ? '1 leftover page' : `${n} leftover pages`} from the vault?`
}

export function unlistedText(n: number): string {
  return `${n === 1 ? '1 file in the Brainamon folder is' : `${n} files in the Brainamon folder are`} not in the manifest (it was lost). They stay exactly as they are until you reclaim them.`
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

export function statusLine(st: MapStatus): string {
  if (st.busy && st.waiting) return 'Waiting for the vault to be free.'
  if (st.missing) return 'Vault not found. It was moved, renamed or deleted.'
  if (st.other_library) return 'This vault belongs to another Brainamon library.'
  if (st.pending) return 'Render pending: the vault is busy, Brainamon retries every minute.'
  if (st.error) return `Stopped on an error: ${st.error}`
  if (!st.last_render) return 'Not rendered yet.'
  const parts = [`Last refresh ${new Date(st.last_render).toLocaleString()}`]
  if (st.stale) parts.push(`${plural(st.stale, 'topic')} out of date`)
  if (st.adopted.length) parts.push(`${plural(st.adopted.length, 'adopted page')}`)
  return parts.join(', ') + '.'
}

export function mapLine(m: { topics: number; stale: number; pending: number }): string {
  if (!m.topics) return 'No AI topics yet. Refresh map builds them.'
  const parts = [plural(m.topics, 'topic')]
  if (m.stale) parts.push(`${m.stale} out of date`)
  if (m.pending) parts.push(`${m.pending} waiting for a summary`)
  return parts.join(', ') + '.'
}
