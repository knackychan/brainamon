<script lang="ts">
  // The import run of a scan's results (projects/motion-language plan 07), in place of SiteRead's "N posts ready"
  // block: ready (the count, why the scan ended, Import / Later), work (the links are added: a busy bar, then the
  // fill and the count of added posts ticking up), pictures (a grid of the first 24 posts: skeleton while waiting,
  // scanned while the slow queue fetches the picture, landed once it has), then the finish (a green tick, how many
  // posts are in the library, whether the pictures came) with Open in Library. The import itself stays in the
  // parent (`onimport`): this component only shows it and starts the picture queue's view of it. Motion off,
  // rest and reduced motion: every step shows its numbers at once (motion.css, lib/motion).
  import type { Snippet } from 'svelte'
  import Bar from '../lib/motion/Bar.svelte'
  import Count from '../lib/motion/Count.svelte'
  import { motionOn } from '../lib/motion/motion.ts'
  import { t } from '../lib/i18n/index.ts'
  import { recordArrival } from './arrival.svelte.ts'
  import { gotCount, picsFinished, readySub, squares } from './import-run.ts'
  import { phone, pics, source } from './state.svelte'
  import { closeSheet, go, shell } from './shell.svelte'
  import { work } from './work.svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'
  import MTextButton from './ui/MTextButton.svelte'

  let { site, name, posts, reason, known, refused, disabled, onimport, onlater, ondone, extra }: {
    site: string; name: string; posts: number; reason: string; known: number; refused: number; disabled: boolean
    onimport: () => Promise<{ ids: number[]; dups: number } | null>
    onlater: () => void; ondone: () => void; extra?: Snippet
  } = $props()

  const ALL = 'all'
  type Step = 'ready' | 'work' | 'pics' | 'done'
  let step = $state<Step>('ready')
  let ids = $state.raw<number[]>([])
  let dups = $state(0)
  let filled = $state(false)          // the links are added: the bar fills and the count ticks up
  let picsStarted = $state(false)     // set right after the picture queue was started for this import
  const has = (id: number) => !!phone.byId.get(id)?.thumb
  const running = (id: number) => { const m = work.get(id); return m?.lane === 'pics' && m.st === 'run' }
  const marks = $derived(squares(ids, has, running))
  const got = $derived(gotCount(ids, has))
  const finished = $derived(picsFinished(ids, has, picsStarted, pics.state))
  const pause = (ms: number) => new Promise<void>(res => setTimeout(res, ms))
  let alive = true
  $effect(() => () => { alive = false })

  async function start() {
    if (disabled || step !== 'ready') return
    step = 'work'
    const result = await onimport().catch(() => null)
    if (!alive) return
    if (!result) { step = 'ready'; return }
    ids = result.ids
    dups = result.dups
    picsStarted = true
    filled = true
    if (!ids.length) { step = 'done'; return }
    await pause(motionOn() ? 900 : 0)
    if (alive && step === 'work') step = 'pics'
  }

  // the pictures are finished: a short beat so the last square lands before the finish replaces the grid
  $effect(() => {
    if (step !== 'pics' || !finished) return
    const timer = setTimeout(() => { step = 'done' }, motionOn() ? 650 : 0)
    return () => clearTimeout(timer)
  })

  function open() {
    recordArrival(site, name, ids, phone.rows.length)
    phone.cat = ALL
    phone.fav = false
    phone.sort = 'new'
    phone.scroll.lib = 0
    ondone()
    if (shell.base === 'lib') closeSheet()
    else go('#/lib', true)
  }
</script>

<div class="m-ir" data-step={step}>
  {#if step === 'ready'}
    <b class="m-ir-t" role="status">{t('importrun.ready', { n: posts })}</b>
    <MHint as="p">{readySub(reason, known, refused, t)}</MHint>
    <div class="m-row">
      <MButton variant="pri" size="sm" {disabled} onclick={start}>{t('importrun.import', { n: posts })}</MButton>
      <MTextButton {disabled} onclick={onlater}>{t('importrun.later')}</MTextButton>
      {@render extra?.()}
    </div>
  {:else if step === 'work'}
    <b class="m-ir-t" role="status">{t('importrun.adding')}</b>
    <Bar label={t('importrun.adding')} mode={filled ? 'fill' : 'busy'} value={filled ? 1 : 0} />
    <span class="m-ir-n"><Count value={filled ? ids.length : 0} from={0} fmt={v => t('importrun.added', { added: v, n: posts })} /></span>
  {:else if step === 'pics'}
    <b class="m-ir-t" role="status">{t('importrun.pictures')}</b>
    <Bar label={t('importrun.pictures')} mode="fill" value={ids.length ? got / ids.length : 1} />
    <span class="m-ir-n"><Count value={got} from={0} fmt={v => t('importrun.picsOf', { pics: v, n: ids.length })} /></span>
    <div class="m-ir-grid" aria-hidden="true">
      {#each marks as s, i (ids[i])}
        {@const row = phone.byId.get(ids[i])}
        <span class="m-ir-sq mo-pop" data-s={s} style:--i={i}>
          {#if s === 'done' && row?.thumb}<img class="m-ir-img" src={source.thumbUrl(row)} alt="" />{/if}
          {#if s === 'run'}<span class="mo-scan"></span>{/if}
        </span>
      {/each}
    </div>
  {:else}
    <div class="m-ir-row">
      {#if ids.length}<span class="m-ir-tick mo-pop" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6" /></svg></span>{/if}
      <b class="m-ir-t m-ir-ok" role="status">{ids.length ? t('importrun.finish', { n: ids.length }) : t('importrun.wereThere', { n: dups, k: dups })}</b>
    </div>
    {#if ids.length}
      <MHint as="p">{(got >= ids.length ? t('importrun.picsReady') : t('importrun.picsSome', { got, n: ids.length })) + (dups > 0 ? ` · ${t('importrun.wereThere', { n: dups, k: dups })}` : '')}</MHint>
      <div class="m-row"><MButton variant="pri" size="sm" class="mo-nudge" onclick={open}>{t('importrun.open')}</MButton></div>
    {/if}
  {/if}
</div>
