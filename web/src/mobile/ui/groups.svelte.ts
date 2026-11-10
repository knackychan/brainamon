// The groups of one settings page (projects/phone-settings, spec section 2.3): at most one open at a time, by its
// title. Settings and Backup & phones each make their own when they mount, so leaving the page closes every group.
import { getContext, setContext } from 'svelte'

export interface Groups { open: string }
const KEY = Symbol('m-groups')

export function setGroups(): Groups {
  const groups = $state<Groups>({ open: '' })
  return setContext(KEY, groups)
}

export const getGroups = (): Groups | undefined => getContext<Groups | undefined>(KEY)

// the event a link into a group (onboard.svelte.ts reveal) sends to the group's box to open it without scrolling
export const OPEN_GROUP = 'm-group-open'
