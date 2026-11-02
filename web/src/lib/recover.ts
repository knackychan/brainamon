// Recover a library (windows/RecoverWin.svelte): opened from the Backup & phones page, Settings' footer and the app menu.
import RecoverWin from '../windows/RecoverWin.svelte'
import { openWin } from './windows.svelte'

export function openRecover() { openRecoveryMethod('pass') }
export function openRecoveryMethod(initialMethod: 'pass' | 'file' | 'code') {
  openWin({ id: 'recover', title: 'Recover a library', code: 'REC-00', w: 640, body: RecoverWin, props: { initialMethod } })
}
