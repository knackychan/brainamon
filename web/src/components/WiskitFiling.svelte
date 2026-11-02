<script lang="ts">
  // The Wiskit rail's files (projects/wiskit-files plan 02): attachment chips over the composer, the
  // filing choices of one chip, and a screenshot digest waiting to be placed. State: lib/filing.svelte.ts.
  import { ask } from '../lib/ask.svelte'
  import { closeFiling, copyDigest, digestAtts, dropAtt, fileAs, fileInto, fl, placeDigest, suggestFor } from '../lib/filing.svelte'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'

  let other = $state('')                     // the open chip's "Another note" picker
  let target = $state('')                    // the digest's "Add to note" picker
  const pics = $derived(ask.atts.filter(a => a.kind === 'image').length)
</script>

{#if ask.atts.length || fl.busy || fl.digest}
  <div class="jv-files">
    {#if ask.atts.length}
      <ul class="jv-atts" aria-label="Attached to your next question">
        {#each ask.atts as a (a.id)}
          <li class:on={fl.att?.id === a.id}>
            <span title={`${a.name} · ${a.chars} characters`}>{a.name}</span>
            {#if a.filed}<small>in {a.filed}</small>{/if}
            <Button size="sm" aria-expanded={fl.att?.id === a.id} onclick={() => suggestFor(a)}>File</Button>
            <button type="button" class="jv-att-x" aria-label={`Remove ${a.name}`} onclick={() => dropAtt(a.id)}>×</button>
          </li>
        {/each}
      </ul>
      <div class="frow">
        {#if pics}<Button size="sm" disabled={!!fl.busy} onclick={digestAtts}>Digest text ({pics})</Button>{/if}
        <span class="sp"></span><Hint as="small">Ask about them, or file them.</Hint>
      </div>
    {/if}
    {#if fl.busy}<Hint class="jv-busy" aria-live="polite">{fl.busy}</Hint>{/if}
    {#if fl.att && fl.opts.length}
      <div class="jv-file" role="group" aria-label={`File ${fl.att.name}`}>
        <h4><span>File {fl.att.name}</span><span>{fl.ai ? 'Wiskit picked' : 'Best keyword match'}</span></h4>
        {#each fl.opts as o (o.action + o.file)}
          <button type="button" class="jv-opt" class:best={o.best} onclick={() => fl.att && fileAs(fl.att, o)}>
            <b>{o.label}</b>{#if o.best}<em>Recommended</em>{/if}<small>{o.why}</small>
          </button>
        {/each}
        <div class="frow">
          <select class="inp" bind:value={other} aria-label="Another note">
            <option value="">Another note…</option>
            {#each fl.notes as n (n.file)}<option value={n.file}>{n.title}</option>{/each}
          </select>
          <Button size="sm" disabled={!other} onclick={() => { if (fl.att) fileInto(fl.att, other); other = '' }}>Add</Button>
          <Button size="sm" onclick={closeFiling}>Close</Button>
        </div>
      </div>
    {/if}
    {#if fl.digest}
      <div class="jv-dig" role="group" aria-label="Screenshot digest">
        <h4><span>Digest of {fl.digest.from}</span><span>{fl.digest.text.length} chars</span></h4>
        <textarea class="inp" rows="6" bind:value={fl.digest.text} aria-label="Digest text"></textarea>
        <div class="frow">
          <select class="inp" bind:value={target} aria-label="Note to add the digest to">
            <option value="">Add to note…</option>
            {#each fl.notes as n (n.file)}<option value={n.file}>{n.title}</option>{/each}
          </select>
          <Button size="sm" disabled={!target} onclick={() => { placeDigest('append', target); target = '' }}>Add</Button>
          <Button size="sm" onclick={() => placeDigest('new')}>New note</Button>
          <Button size="sm" onclick={copyDigest}>Copy</Button>
          <button type="button" class="jv-att-x" aria-label="Discard the digest" onclick={() => (fl.digest = null)}>×</button>
        </div>
      </div>
    {/if}
  </div>
{/if}
