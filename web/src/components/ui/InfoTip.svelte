<script lang="ts">
  // A small (i) at the end of the line it explains (.info-tip, app.css): a switch, a group title, a state
  // or a sentence. Hovering shows the explanation in a bubble; a click or Enter pins it until Escape or a
  // click elsewhere. `text` is one paragraph or several; richer content (links) comes as children, each
  // paragraph a <span> (the bubble sits inside running text, so never a <p>). Safe inside a label: its
  // click never moves the control.
  import type { Snippet } from 'svelte'
  const uid = $props.id()
  let { label, text = [], children }: { label: string; text?: string | string[]; children?: Snippet } = $props()
  let pinned = $state(false), hover = $state(false), el = $state<HTMLElement>()
  const paras = $derived(Array.isArray(text) ? text : [text])
  // near the bottom or right edge of the screen the bubble opens upward or to the left
  let up = $state(false), left = $state(false)
  function aim() {
    const r = el?.getBoundingClientRect()
    if (r) { up = r.bottom > innerHeight - 240; left = r.left > innerWidth - 380 }
  }
</script>

<svelte:window onclick={e => { if (pinned && !el?.contains(e.target as Node)) pinned = false }} />

<span bind:this={el} class="info-tip" role="presentation" onmouseenter={() => { aim(); hover = true }} onmouseleave={() => (hover = false)}>
  <button type="button" class="info-i" class:on={pinned} aria-label={label} aria-expanded={pinned || hover} aria-controls={uid}
    onclick={e => { e.preventDefault(); e.stopPropagation(); aim(); pinned = !pinned }}
    onkeydown={e => { if (e.key === 'Escape' && pinned) { e.stopPropagation(); pinned = false } }}>i</button>
  {#if pinned || hover}<span class="info-pop" class:up class:left id={uid} role="note">{#each paras as p, i (i)}<span>{p}</span>{/each}{@render children?.()}</span>{/if}
</span>
