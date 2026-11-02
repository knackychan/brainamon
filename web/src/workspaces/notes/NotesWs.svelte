<script lang="ts">
  import { onMount } from 'svelte'
  import { act } from '../../lib/cardmenu'
  import { edited, flush, installNotes, nt, reformat, setStamps, summarize } from '../../lib/notes.svelte'
  import { readyAfterPaint, ui } from '../../lib/ui.svelte'
  import VoiceRec from '../../components/VoiceRec.svelte'
  import NoteEditor from './NoteEditor.svelte'
  import ReformatWin from './ReformatWin.svelte'

  onMount(installNotes)
  onMount(() => readyAfterPaint('notes'))
  $effect(() => { if (ui.ws !== 'notes') void flush() })
  const cats = $derived(nt.categories.includes(nt.category) ? nt.categories : [...nt.categories, nt.category])
  const status = $derived({ saved: `Saved ${nt.savedAt}`, pending: 'Editing…', saving: 'Saving…', error: 'Not saved' }[nt.status])
  const created = $derived(nt.list.find(n => n.file === nt.file)?.created)
  const date = $derived(created && !Number.isNaN(Date.parse(created)) ? new Date(created).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '')
  function citation(e: MouseEvent) {
    const c = (e.target as HTMLElement).closest<HTMLElement>('#nt-md [data-cid]')
    if (c) act('open', +c.dataset.cid!)
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
<main class="ws ws-n" id="ws-notes" role="tabpanel" aria-labelledby="tab-notes" data-ws="notes" hidden={ui.ws !== 'notes'}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <section class="np" aria-labelledby="nt-h" onclick={citation}>
    <header class="np-top">
      <h2 class="sr" id="nt-h">My Notes</h2>
      {#if nt.file}
        <label class="np-pill"><span class="sr">Category</span><select id="nt-cat" bind:value={nt.category} onchange={edited}>{#each cats as c (c)}<option>{c}</option>{/each}</select></label>
        <span class="np-file" id="nt-file" title={nt.file}>{nt.file}</span>
        <small class="as-led" id="nt-led" data-s={nt.status} aria-live="polite"><i></i><span>{status}</span></small>
        <div class="np-acts"><button type="button" onclick={summarize}>Summarize</button><button type="button" onclick={reformat}>Reformat</button><VoiceRec file={nt.file} compact /></div>
      {/if}
    </header>
    {#if nt.file}
      {#key nt.file}
        <NoteEditor body={nt.body} stamps={nt.stamps} revision={nt.revision} meta={date}
          onbody={body => { if (nt.body !== body) { nt.body = body; edited() } }}
          onstamps={stamps => { if (JSON.stringify(nt.stamps) !== JSON.stringify(stamps)) setStamps(stamps) }}>
          {#snippet title()}
            <label class="sr" for="nt-title">Title</label><input class="np-title" id="nt-title" autocomplete="off" placeholder="Untitled" bind:value={nt.title} oninput={edited} />
          {/snippet}
        </NoteEditor>
      {/key}
    {:else}
      <div class="rwin-body"><div class="emp"><h3>No note open</h3><p>Pick a note on the rail, or New to start writing. Notes autosave as you type and show up in Knowledge and Wiskit.</p><div class="emp-acts"><VoiceRec showNew /></div></div></div>
    {/if}
  </section>
  <ReformatWin />
</main>

<style>
  #ws-notes { --np-paper: #f7f6f2; --np-edge: rgba(31,31,34,.11); --np-dot: rgba(42,34,208,.26); --np-ink: var(--ink-graphite); --np-dim: var(--rw-dim); --np-tint: color-mix(in srgb,var(--ink-indigo) 8%,transparent); --np-tint-2: color-mix(in srgb,var(--ink-indigo) 14%,transparent); --np-solid: #fcfbf8; padding: 2px 12px 12px 0; min-width: 0 }
  :global(:root[data-theme=dark]) #ws-notes { --np-paper: #1b1c21; --np-edge: rgba(233,227,211,.15); --np-dot: rgba(162,157,255,.24); --np-solid: #24252c }
  @media (prefers-color-scheme: dark) { :global(:root:not([data-theme=light])) #ws-notes { --np-paper: #1b1c21; --np-edge: rgba(233,227,211,.15); --np-dot: rgba(162,157,255,.24); --np-solid: #24252c } }
  .np { container-type: inline-size; display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--np-paper); color: var(--np-ink); border: 1px solid var(--np-edge); border-radius: 20px; box-shadow: 0 18px 40px -22px rgba(30,26,110,.25); overflow: hidden }
  .np :global(::selection) { background: var(--np-tint-2) }
  .np-top { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; min-width: 0; padding: 14px 20px 0 }
  .np-pill { display: inline-flex; flex: 0 1 auto; min-width: 0; max-width: min(280px,100%) }
  .np-pill select { max-width: 100%; border: 0; border-radius: 999px; padding: 7px 12px; background: var(--ink-indigo); color: var(--np-paper); font: var(--type-tool); text-overflow: ellipsis }
  .np-pill option { color: var(--np-ink); background: var(--np-paper) }
  .np-file { flex: 1 1 120px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--np-dim); font: var(--type-status) }
  .np-top .as-led { color: var(--np-dim); font: var(--type-status) }
  .np-acts { display: flex; flex-wrap: wrap; align-items: center; gap: 3px }
  .np-acts > button { border: 0; border-radius: 999px; padding: 7px 10px; background: transparent; color: var(--np-dim); font: var(--type-tool); cursor: pointer }
  .np-acts > button:hover { background: var(--np-tint); color: var(--np-ink) }
  .np-title { display: block; width: 100%; min-width: 0; height: 72px; box-sizing: border-box; padding: 12px 0; margin: 0; border: 0; background: transparent; color: var(--np-ink); font: 650 30px/48px var(--display); letter-spacing: -.02em; caret-color: var(--ink-indigo) }
  #ws-notes :global(.emp) { max-width: 640px }
  .emp-acts { margin-top: 8px; display: flex; justify-content: center; max-width: 100%; }
  :is(button,select,input):focus-visible { outline: 2px solid var(--ink-indigo); outline-offset: 2px }
</style>
