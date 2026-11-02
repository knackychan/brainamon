// Recover a library (windows/RecoverWin.svelte): opened from the Backup & phones page, Settings' footer and the app menu.
import RecoverWin from '../windows/RecoverWin.svelte'
import { openWin } from './windows.svelte'

export function openRecover() { openWin({ id: 'recover', title: 'Recover a library', code: 'REC-00', w: 640, body: RecoverWin }) }
