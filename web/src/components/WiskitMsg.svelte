<script lang="ts">
  import { thumbSrc } from '../lib/library.svelte'
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
</script>

<article class="m-j dlg">
  <header class="m-hd"><Px name="core" /><span>Wiskit</span><em>{m.tag}</em><time>{m.t}</time></header>
  {#if m.ctx}<p class="ctx">{m.ctx}</p>{/if}
  {#if m.trace.length}<ol class="trace">{#each m.trace as line, i (i)}<li>{line}</li>{/each}</ol>{/if}
  <div class="ans">
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
