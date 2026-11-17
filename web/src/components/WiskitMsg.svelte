<script lang="ts">
  import { lib, thumbSrc } from '../lib/library.svelte'
  import Count from '../lib/motion/Count.svelte'
  import { arrive } from '../lib/motion/arrive.ts'
  import { POP_MS, motionOn } from '../lib/motion/motion.ts'
  // One Wiskit answer (V6 addWiskit / finalize / sourcesHTML): header, the retrieval line, the
  // Deep tool trace, the answer with citation chips, the Sources list, Save as note / Add to canvas.
  import Px from '../lib/Px.svelte'
  import { askHooks, saveAnswer, type WiskitMsg } from '../lib/ask.svelte'
  import { titleOf } from '../lib/cards/card'
  import { fmtAnswer } from '../lib/md'
  import { soonText } from '../lib/commands'
  import { toast } from '../lib/ui.svelte'
  import Button from './ui/Button.svelte'

  let { m }: { m: WiskitMsg } = $props()
  let more = $state(false)
  const SHOW = 4
  const body = $derived(fmtAnswer(m.text))
  const plainCites = (t: string) => t.replace(/\[\s*ids?\s*:?\s*([\d,\s]+)\]/gi, (_, g: string) => '(' + g.split(/[,\s]+/).filter(Boolean).map(n => 'No. ' + n).join(', ') + ')')
  function toCanvas(e: MouseEvent) {
    const text = `Wiskit · ${m.q}\n${plainCites(m.text).replace(/\[note:\s*([^\]]+)\]/g, '($1)')}`
    if (askHooks.attachText) askHooks.attachText(text, e.currentTarget as HTMLElement); else toast(soonText('09'), 'w')
  }

  // Deep research (motion language D4): the steps and source rows of lib/research.ts. While the answer streams,
  // each citation chip pops once; the negative delay keeps its pop going when the next chunk redraws the answer.
  const BADGE = { reading: 'READING', read: '✓ READ', unused: 'NOT USED' } as const
  const res = $derived(m.research)
  const rowsOf = (n: number) => res?.rows.filter(x => x.n === n) ?? []
  let ans: HTMLElement | undefined = $state()
  const seenAt = new Map<string, number>()
  $effect(() => {
    void body
    if (!ans || !m.streaming || !motionOn()) return
    const now = performance.now(), count = new Map<string, number>()
    for (const el of ans.querySelectorAll<HTMLElement>('.cite')) {
      const id = el.dataset.cid ?? el.dataset.note ?? el.textContent ?? ''
      const k = (count.get(id) ?? 0) + 1
      count.set(id, k)
      const t0 = seenAt.get(`${id}#${k}`) ?? now
      seenAt.set(`${id}#${k}`, t0)
      if (now - t0 >= POP_MS) continue
      el.classList.add('mo-pop')
      el.style.animationDelay = `${t0 - now}ms`
    }
  })
</script>

<article class="m-j dlg">
  <header class="m-hd"><Px name="core" /><span>Wiskit</span><em>{m.tag}</em><time>{m.t}</time></header>
  {#if m.ctx}<p class="ctx">{m.ctx}</p>{/if}
  {#if m.trace.length}<ol class="trace">{#each m.trace as line, i (i)}<li>{line}</li>{/each}</ol>{/if}
  {#if res}
    <section class="mo-res" aria-label="Research" hidden={!res.steps.length}>
      <ol class="mo-steps">
        {#each res.steps as s (s.n)}
          {@const rows = rowsOf(s.n)}
          <li class="mo-step" data-st={s.state} in:arrive>
            <i class="mo-sdot" aria-hidden="true">{s.state === 'ok' ? '✓' : s.state === 'err' ? '!' : ''}</i>
            <span>{s.label}</span>{#if s.q}<q>{s.q}</q>{/if}
            {#if s.name === 'read_items'}
              {#if rows.length}<Count as="b" value={rows.filter(x => x.got && x.state !== 'reading').length} /><span>/ {rows.length}</span>{/if}
            {:else if s.hits !== null}<Count as="b" value={s.hits} from={0} /><span>{s.hits === 1 ? 'hit' : 'hits'}</span>{/if}
          </li>
        {/each}
      </ol>
      <ol class="mo-srcs">
        {#each res.rows as row (row.id)}
          {@const r = lib.byId.get(row.id)}
          <li class="mo-src" class:mo-read={row.state === 'reading'} data-st={row.state} data-id={row.id} style:--mo-d={`${row.d}ms`} in:arrive={{ x: 24, delay: row.d }}>
            <span class="mo-sbx">{#if r?.thumb}<img src={thumbSrc(row.id, 64)} alt="" />{/if}</span>
            <span class="mo-sid">[id {row.id}]</span>
            <span class="mo-stl">{r ? titleOf(r) : ''}</span>
            <b class="mo-sbd">{BADGE[row.state]}</b>
          </li>
        {/each}
      </ol>
      {#if !m.streaming && res.read !== null}<p class="mo-rsum">✓ {m.cited.length} cited · {res.read} read</p>{/if}
    </section>
  {/if}
  <div class="ans" bind:this={ans}>
    {#if m.text}{@html body}{#if m.streaming}<span class="cur"></span>{/if}
    {:else if m.streaming}<p class="think">Thinking<span class="cur"></span></p>{/if}
    {#if m.error}<p class="note">{m.error}</p>{/if}
    {#if m.note}<p class="note">{m.note}</p>{/if}
  </div>
  {#if !m.streaming && m.text && !m.error}
    <section class="srcs" aria-label="Sources">
      {#if !m.sources.length && !m.notes.length}
        <h4>Sources <b>00</b></h4><p class="ans note" style="margin:0">No library cards cited in this answer.</p>
      {:else}
        <h4>Sources <b>{String(m.sources.length + m.notes.length).padStart(2, '0')}</b></h4>
        <ol>
          {#each m.sources as r, i (r.id)}
            <li class="src" hidden={!more && i >= SHOW}>
              <button type="button" class="src-open" data-cid={r.id}>
                {#if r.thumb}<img src={thumbSrc(r.id)} alt="" style:object-position="50% 42%" />{:else}<span></span>{/if}
                <span class="src-t"><small>No.{r.id} · {r.cat}</small><b>{titleOf(r)}</b><span>{r.creator || 'unknown'}</span><em>{m.cited.includes(r.id) ? 'cited by Wiskit' : 'sent as context'}</em></span>
              </button>
              <button type="button" class="src-loc" data-loc={r.id} aria-label={`Find No.${r.id} on the mat`} title="Find on the mat">
                <svg viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="7" cy="7" r="4" /><path d="M7 0v3M7 11v3M0 7h3M11 7h3" /></svg>
              </button>
            </li>
          {/each}
          {#each m.notes as f (f)}
            <li class="src"><button type="button" class="src-open" data-note={f} style="grid-column:1/-1"><span class="nt"><Px name="note" /></span><span class="src-t"><small>Note</small><b>{f}</b><span>data/notes/{f}</span><em>cited note</em></span></button></li>
          {/each}
        </ol>
        {#if !more && m.sources.length > SHOW}<button type="button" class="more" onclick={() => (more = true)}>+{m.sources.length - SHOW} more</button>{/if}
      {/if}
    </section>
    {#if m.note !== 'Stopped.' && (m.task !== 'weekly_review' || m.complete === true)}
      <div class="afoot">
        <Button disabled={m.saving} title={m.saved ? `Open data/notes/${m.saved} in Knowledge` : undefined} onclick={() => (m.saved ? askHooks.openNote?.(m.saved) : saveAnswer(m))}>{m.saved ? 'Open note' : 'Save as note'}</Button>
        <Button onclick={toCanvas}>Add to canvas</Button>
      </div>
    {/if}
  {/if}
</article>
