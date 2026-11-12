import { t } from '../lib/i18n/index.ts'
import { appInfo } from './native'
import { items, storageUse } from './store'
import { freeSpace, offline } from './offline.svelte'
import { driveStatus, measurePend, mirrorSource, phone, source } from './state.svelte'
import { syncPaused } from './network.svelte'
import { vault } from './vault/auto.svelte'

export const settings = $state({
  use: null as Awaited<ReturnType<typeof storageUse>> | null,
  kept: [] as Awaited<ReturnType<typeof items.all>>,
  free: 0,
  app: null as Awaited<ReturnType<typeof appInfo>> | null,
  infoError: '',
  health: null as { ok: boolean; items: number; licensed?: boolean } | null,
})
export async function readAppInfo() {
  settings.infoError = ''
  try { settings.app = await appInfo() }
  catch { settings.infoError = t('settings.about.infoFailed') }
}
export async function measureSettings() {
  settings.use = await storageUse(phone.rows)
  settings.kept = (await items.all()).filter(s => !s.saved).sort((a, b) => b.at - a.at)
  settings.free = await freeSpace()
  await offline.load()
  if (mirrorSource) await measurePend()
  else {
    try { settings.health = await source.health() } catch { settings.health = null }
  }
}
export const savedBytes = () => offline.saved.reduce((a, s) => a + (s.size ?? 0), 0) + offline.canvases.reduce((a, c) => a + c.size, 0)
export const storageTotal = () => settings.use ? settings.use.light + settings.use.thumbBytes + settings.use.fullBytes + savedBytes() : 0

export function vaultLamp(): string {
  return vault.opts.on && syncPaused() ? 'paused' : vault.stopping ? 'stopping' : vault.busy ? 'syncing' : vault.queued ? 'queued'
    : !vault.opts.uri ? 'no folder' : !vault.opts.on ? 'off' : !driveStatus().ok ? 'needs Drive' : vault.brake ? 'held'
    : vault.outcome === 'error' ? 'error' : vault.outcome === 'waiting' ? 'waiting for PC' : vault.outcome === 'ok' ? 'in step' : 'not run yet'
}
