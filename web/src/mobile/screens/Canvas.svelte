<script lang="ts">
  import { captureError } from '../capture-words.ts'
  import { t } from '../../lib/i18n/index.ts'
  import { toolText } from '../tools-words.ts'
  import { fmtDate } from '../../lib/i18n/format.ts'
  import { onMount, untrack } from 'svelte'
  import type { CanvasDoc, CanvasRow } from '../../lib/canvas.svelte'
  import { kv } from '../store'
  import { phone, source } from '../state.svelte'
  import { offline, removeCanvas, saveCanvas, savedCanvas } from '../offline.svelte'
  import { go, shell } from '../shell.svelte'
  import MButton from '../ui/MButton.svelte'
  import MKey from '../ui/MKey.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import CanvasBoard from '../canvas/CanvasBoard.svelte'

  let { id }: { id: string | null } = $props()
  const onMirror = source.kind === 'mirror'
  let saving = $state(false)
  const isSaved = $derived(!!id && offline.canvases.some(c => c.id === id))
  async function toggleSave() {
    if (!id) return
    saving = true
    try { if (isSaved) await removeCanvas(id); else await saveCanvas(id) } catch (e) { err = captureError(e) } finally { saving = false }
  }
  let list = $state<CanvasRow[]>([]), doc = $state<CanvasDoc | null>(null), err = $state('')
  let eligible = $state(false), status = $state(''), statusText = $state(''), notice = $state('')
  let noticeTimer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  onMount(() => { void offline.load(); return () => { generation++; clearTimeout(noticeTimer) } })
  $effect(() => {
    const cid = id, revision = phone.canvasRevision, n = ++generation
    untrack(() => {
      void revision; eligible = false; err = ''
      if (!cid) {
        doc = null
        void kv.get<CanvasRow[]>('canvases').then(cached => { if (n === generation) list = cached ?? [] })
        source.canvases().then(rows => { if (n === generation) { list = rows; void kv.set('canvases', rows) } })
          .catch(async e => { if (n === generation && !list.length) { list = offline.canvases.map(c => ({ id: c.id, name: c.name, count: c.doc.items.length, updated: c.at })); err = captureError(e) } })
        return
      }
      doc = null
      void (async () => {
        try {
          let d: CanvasDoc | null
          try { d = await source.canvas(cid) } catch (e) { d = await savedCanvas(cid); if (!d) throw e }
          if (n !== generation) return
          doc = d; status = source.canvasStatus?.(cid) || ''; statusText = source.canvasStatus?.(cid, toolText) || ''
          const problem = await source.canvasDraftProblem?.(cid, toolText)
          if (n !== generation) return
          eligible = !!source.applyCanvasDraft && !problem
        } catch (e) { if (n === generation) err = captureError(e) }
      })()
    })
  })
  $effect(() => {
    const cid = id, pending = shell.canvasNotice
    if (cid && pending?.canvasId === cid && !pending.until) untrack(() => {
      pending.until = Date.now() + 3200; notice = pending.text; shell.canvasNotice = null
      clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { notice = '' }, 3200)
    })
  })
  const when = (ms: number) => ms ? fmtDate(ms > 1e12 ? ms : ms * 1000, { day: '2-digit', month: 'short' }, 'en-GB') : ''
</script>

{#if !id}
  <div class="m-pad">
    <div class="m-row"><span class="m-lbl">{t('canvas.list')}</span><span class="m-sp"></span><span class="m-lbl">{list.length}</span></div>
    {#if err}<div class="m-err" style="margin:0">{t('canvas.error.detail', { detail: err })}</div>{/if}
    <div class="m-notes m-cv-list">
      {#if source.applyCanvasDraft}<button type="button" aria-label={t('canvas.new')} onclick={() => go('#/canvas/new')}><span class="m-cvi m-cp-new" aria-hidden="true">+</span><div><b>{t('canvas.new')}</b></div><span></span></button>{/if}
      {#each list as c (c.id)}
        <button type="button" onclick={() => go(`#/canvas/${encodeURIComponent(c.id)}`)}><span class="m-cvi">▦</span><div><b>{source.canvasTitle?.(c.id, toolText) || c.name || c.id}</b><small>{t('canvas.elements', { n: c.count })} · {when(c.updated)} · {source.canvasStatus?.(c.id, toolText) || (onMirror ? t('shell.where.drive') : t('shell.where.pc'))}</small></div>{#if offline.canvases.some(x => x.id === c.id)}<span class="m-badge ok">{t('canvas.saved')}</span>{:else}<span class="m-badge mute">{onMirror ? t('canvas.phone') : t('shell.where.pc')}</span>{/if}</button>
      {:else}<div class="m-empty">{t('canvas.empty')}</div>{/each}
    </div>
  </div>
{:else}
  <CanvasBoard {doc}>
    <div class="m-cv-ui"><div class="m-cp-view-tag"><span class="m-ro">{doc?.name ?? '…'} · {t('canvas.elements', { n: doc?.items.length ?? 0 })}</span>{#if status && status !== 'Synced'}<span class="m-badge wait">{statusText}</span>{/if}</div><span class="m-sp"></span>{#if err}<span class="m-badge bad">{t('canvas.error.detail', { detail: err })}</span>{/if}{#if onMirror && doc}<MButton size="sm" class={{ dk: isSaved }} disabled={saving} onclick={toggleSave}>{saving ? t('notes.save.saving') : isSaved ? t('canvas.offlineSaved') : t('canvas.offline')}</MButton>{/if}</div>
    {#if notice}<div class="m-cp-notice m-cp-success" role="status">{notice}</div>{/if}
    {#if doc && eligible}<MKey class="m-cp-view-add" size="dock" tone="add" wide onclick={() => go(`#/canvas/${encodeURIComponent(id!)}/add`)}><ShellIcon name="plus" />{t('common.add')}</MKey>{/if}
  </CanvasBoard>
{/if}
