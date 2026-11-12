// Presentation only: status and task facts in, badges and named steps out. Kept import-free for Node checks.
export type Kind = 'done' | 'working' | 'attention' | 'failed' | 'paused' | 'waiting' | 'empty'
type Tone = 'done' | 'todo' | 'next' | 'busy'
type Status = { id: string; tone: Tone; lamp?: string }
type Words = (key: string, params?: Record<string, unknown>) => string
export interface Step { label: string; line?: string; kind: Kind; tag?: string }
export const toneKind = (tone?: Tone): Kind => tone === 'done' ? 'done' : tone === 'busy' ? 'working' : tone === 'next' ? 'attention' : 'empty'
export function kindOf(st: Status | null, error = ''): Kind {
  if (!st) return 'empty'
  if (st.tone === 'next' && (['unreachable', 'access-invalid'].includes(st.id) || (st.id === 'backup-task' && error))) return 'failed'
  if (st.tone === 'todo' && st.id === 'paused') return 'paused'
  if (st.tone === 'todo' && ['offline', 'wifi', 'confirming', 'waiting-pc'].includes(st.id)) return 'waiting'
  return toneKind(st.tone)
}
export const rowKind = (st: Status | null, tone?: Tone, error = ''): Kind => st && st.tone === tone ? kindOf(st, error) : toneKind(tone)
const ACCESS = ['replaced', 'removed', 'confirming', 'waiting-pc', 'license', 'access-invalid', 'webview']
export const connectionGuide = (st: Status | null, pairing: boolean): boolean => pairing || !!st && ['connect', 'account-mismatch', ...ACCESS, 'first-backup', 'no-library', 'key', 'backup-off'].includes(st.id)
export function connectionSteps(st: Status, o: { signedIn: boolean; connecting: boolean; refreshing: boolean; reachable: boolean; account: string; pcAccount: string; connectStep: string; diagnosis: string; count: string }, t: Words): Step[] {
  const access = ['first-backup', 'no-library', 'key', 'backup-off', 'in-sync', 'resending'].includes(st.id)
  return [
    { label: t('backup.pair.step1'), line: t('backup.pair.useAccount', { account: o.pcAccount || t('backup.pair.pcAccount') }), kind: 'done' },
    { label: t('backup.pair.step2'), line: st.id === 'account-mismatch' ? t('backup.pair.mismatch', { account: o.pcAccount }) : o.connecting ? o.connectStep : o.signedIn ? t('backup.pair.connected', { account: o.account || t('backup.pair.signedIn') }) : t('backup.pair.connectAccount'), kind: o.connecting ? 'working' : ['connect', 'account-mismatch'].includes(st.id) ? 'attention' : o.signedIn ? 'done' : 'empty' },
    { label: t('backup.pair.step3'), line: ACCESS.includes(st.id) ? st.lamp : access ? t('backup.pair.confirmed') : o.refreshing ? t('backup.pair.checking') : t(o.signedIn ? 'backup.pair.waitConfirmation' : 'backup.pair.afterConnect'), kind: ACCESS.includes(st.id) ? kindOf(st) : access ? 'done' : o.refreshing ? 'working' : 'waiting' },
    { label: t('backup.pair.step4'), line: o.reachable ? t('backup.pair.ready', { n: o.count }) : o.diagnosis || t(access ? 'backup.pair.waitUpload' : 'backup.pair.waitLoad'), kind: o.reachable ? 'done' : st.id === 'first-backup' ? 'working' : ['no-library', 'key', 'backup-off'].includes(st.id) ? 'attention' : 'waiting' },
  ]
}
export function recoverySteps(fact: string, when: string, t: Words, savedWhen = when): Step[] {
  const set = fact !== 'none', saved = fact === 'saved' || fact === 'checked'
  return [
    { label: set ? t('recovery.state.passphraseAt', { when }) : t('recovery.method.passphraseLabel'), kind: set ? 'done' : 'empty', tag: set ? '' : t('settings.keys.recommended') },
    { label: saved ? t('recovery.step.fileSaved', { when: savedWhen }) : t('recovery.step.file'), line: fact === 'prepared' ? t('recovery.warning.alsoSave') : '', kind: saved ? 'done' : 'empty', tag: saved ? '' : t('settings.keys.optional') },
    { label: t(fact === 'checked' ? 'recovery.state.fileChecked' : 'recovery.step.check'), line: fact === 'checked' ? t('recovery.warning.keepOutside') : saved ? t('recovery.warning.openOnce') : '', kind: fact === 'checked' ? 'done' : saved ? 'attention' : 'empty' },
  ]
}
export function taskSteps(task: { kind: string; phase: string; uploaded?: boolean; paused?: boolean; items?: number }, busy: boolean, error: string, t: Words): Step[] {
  const active = task.kind === 'delete' ? ['disconnect', 'done'].includes(task.phase) ? 1 : 0
    : task.phase === 'prepare' ? 0 : task.phase === 'upload' ? task.uploaded ? 2 : 1 : task.phase === 'install' ? 2 : 3
  const labels = task.kind === 'delete' ? [t('backup.task.deleteSelected'), t('backup.task.disconnect')]
    : [t('backup.task.prepare'), t('backup.task.backupAgain', { items: task.items === undefined ? '' : t('backup.task.itemProgress', { n: task.items, done: task.uploaded ? task.items : 0, total: task.items }), files: task.uploaded ? '1 / 1' : '0 / 1' }), t('backup.task.checkReplacement'), t('backup.task.deleteOld')]
  return labels.map((label, i) => ({ label, kind: task.phase === 'done' || i < active ? 'done' : i > active ? 'empty' : error ? 'failed' : task.paused ? 'paused' : busy ? 'working' : 'waiting' }))
}
