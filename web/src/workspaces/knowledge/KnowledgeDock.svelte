<script lang="ts">
  // The Knowledge rail (V6 buildKnowDock): 01 time, 02 index coverage, 03 find sources, 04 topics I
  // follow, 05 saved notes, 06 connections, 07 model.
  import ClockTile from '../library/dock/ClockTile.svelte'
  import Wg from '../library/dock/Wg.svelte'
  import Px from '../../lib/Px.svelte'
  import { runCmd } from '../../lib/commands'
  import { startJob } from '../../lib/jobs'
  import {
    addTopic, CAPS, cxScanning, ks, loadCategory, loadNotes, openNote, refreshTopic, removeTopic, scanConnections, searchSources, setCap,
  } from '../../lib/knowledge.svelte'
  import { lib, NEED } from '../../lib/library.svelte'
  import { toast } from '../../lib/ui.svelte'
  import { confirmWin, promptWin } from '../../lib/windows.svelte'
  import Button from '../../components/ui/Button.svelte'

  let q = $state('')
  let cat = $state('')
  $effect(() => { if (!cat && lib.cats.length) cat = lib.cats[0].name })

  const total = $derived(lib.rows.length)
  const missing = $derived(lib.rows.reduce((s, r) => s + ((r.nd & NEED.index) ? 1 : 0), 0))
  const pct = $derived(total ? (total - missing) / total : 1)
  const N = 24
  const ring = $derived(Array.from({ length: N }, (_, i) => {
    const a = i / N * Math.PI * 2 - Math.PI / 2, c = Math.cos(a), s = Math.sin(a)
    return { x1: (40 + c * 24).toFixed(1), y1: (40 + s * 24).toFixed(1), x2: (40 + c * 38).toFixed(1), y2: (40 + s * 38).toFixed(1), lit: i < Math.round(pct * N) }
  }))
  const SORTS: [typeof ks.sort, string][] = [['updated', 'Updated'], ['created', 'Created'], ['az', 'A to Z']]
  const kindShort = (k: string) => (k === 'Personal' ? 'mine' : k === 'Topic digest' ? 'topic' : 'wiki')

  function find(e: SubmitEvent) { e.preventDefault(); if (!q.trim()) return; ks.topicId = null; searchSources(q) }
  function pickTopic(id: number) {
    const t = ks.topics.find(x => x.id === id)
    if (!t) return
    ks.topicId = id
    q = t.query
    searchSources(t.query)
    if (t.note_path) openNote(t.note_path)
  }
  async function add() {
    const v = await promptWin({
      title: 'Follow a topic', code: 'TOP-24', label: 'Topic', value: q || ks.q, ok: 'Follow',
      hint: 'Refresh digest writes a standing note, data/notes/topic-<name>.md, and only reads items it has not digested yet.',
      check: v => (!v ? 'Enter a topic.' : ks.topics.some(t => t.name.toLowerCase() === v.toLowerCase()) ? 'You already follow that topic.' : null),
    })
    if (!v) return
    try { await addTopic(v); toast(`Following “${v}”. Use Refresh digest to build its note.`) } catch (e) { toast((e as Error).message, 'w') }
  }
  async function remove() {
    const t = ks.topics.find(x => x.id === ks.topicId)
    if (!t) { toast('Pick a topic first', 'w'); return }
    const ok = await confirmWin({ title: `Stop following “${t.name}”?`, code: 'TOP-25', ok: 'Remove topic', danger: true, msg: 'The topic leaves the list.', detail: t.note_path ? `Its digest note, data/notes/${t.note_path}, is kept.` : undefined })
    if (!ok) return
    await removeTopic(t.id)
    ks.topicId = null
  }
  function sortBy(s: typeof ks.sort) { ks.sort = s; loadNotes() }
</script>

<ClockTile />
<Wg cls="k s3" id="kidx" title="Index" jp="索引" n="3-small">
  <div class="dring">
    <svg viewBox="0 0 80 80" aria-hidden="true">{#each ring as l, i (i)}<line x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} class:lit={l.lit} />{/each}</svg>
    <div><p class="dotn sm">{Math.round(pct * 100)}%</p><p class="wg-sub">{total - missing} of {total} items embedded</p></div>
  </div>
  <div class="tkeys"><Button kind="tool" variant="pri" wide aria-disabled={missing ? undefined : 'true'}
    onclick={() => (missing ? startJob('index', { ids: lib.rows.filter(r => r.nd & NEED.index).map(r => r.id) }) : null)}>{missing ? `Index ${missing} missing` : 'All indexed'}</Button></div>
</Wg>
<Wg cls="s6" id="kfind" title="Find sources" jp="検索">
  <form class="kq" onsubmit={find}><label class="sr" for="kq">Topic</label><input class="tin" id="kq" placeholder="a topic, e.g. knee" autocomplete="off" spellcheck="false" enterkeyhint="search" bind:value={q} /><Button kind="tool" variant="pri" type="submit">Search</Button></form>
  <div class="krow"><span class="wg-l">Cap</span><div class="wseg" role="group" aria-label="Most sources to load">{#each CAPS as c (c)}<button type="button" aria-pressed={ks.cap === c} onclick={() => setCap(c)}>{c}</button>{/each}</div></div>
  <div class="krow"><label class="wg-l" for="kcat">Or a collection</label><select class="tsel" id="kcat" bind:value={cat}>{#each lib.cats as c (c.name)}<option>{c.name}</option>{/each}</select><Button kind="tool" onclick={() => loadCategory(cat)}>Load</Button></div>
</Wg>
<Wg cls="s6" id="ktop" title="Topics I follow" jp="フォロー" n={ks.topics.length}>
  <div class="tlist" role="list">
    {#each ks.topics as t (t.id)}
      <button type="button" class="trow" aria-current={t.id === ks.topicId} title={`Query: ${t.query}`} onclick={() => pickTopic(t.id)}><span class="l">{t.name}</span><span class="c">{#if t.new}<b class="bdg nw">{t.new} new</b>{:else}up to date{/if}</span></button>
    {:else}
      <p class="wg-sub">No topics yet. Add one to get a standing digest.</p>
    {/each}
  </div>
  <div class="tkeys">
    <Button kind="tool" variant="pri" onclick={add}><Px name="plus" />Add</Button>
    <Button kind="tool" aria-disabled={ks.topicId === null ? 'true' : undefined} onclick={() => (ks.topicId !== null ? refreshTopic(ks.topicId) : toast('Pick a topic first', 'w'))}>Refresh digest</Button>
    <span class="sp"></span>
    <Button kind="tool" onclick={remove}><Px name="trash" />Remove</Button>
  </div>
</Wg>
<Wg cls="s6" id="knotes" title="Saved notes" jp="ノート" n={ks.notes.length}>
  <div class="wseg" role="group" aria-label="Sort the notes">{#each SORTS as [v, l] (v)}<button type="button" aria-pressed={ks.sort === v} onclick={() => sortBy(v)}>{l}</button>{/each}</div>
  <div class="tlist" role="list">
    {#each ks.notes as n (n.file)}
      <button type="button" class="trow" aria-current={ks.note?.file === n.file} title={`data/notes/${n.file}\n${n.snippet}`} onclick={() => openNote(n.file)}>
        <span class="l">{#if ks.noteMatches.includes(n.file)}<b class="bdg nw">match</b> {/if}{n.title}</span>
        <span class="c">{kindShort(n.kind)} · {(ks.sort === 'created' ? n.created : n.updated).slice(5, 10)}</span>
      </button>
    {/each}
  </div>
  <div class="tkeys"><Button kind="tool" wide title="Open Obsidian on the vault Export to Obsidian writes" onclick={() => runCmd('obs-graph')}>See my knowledge graph</Button></div>
</Wg>
<Wg cls="y s3" id="kcx" title="Connections" jp="関連">
  <p class="dotn">{String(ks.cards.length).padStart(2, '0')}</p><p class="wg-sub">insights · last scan {ks.lastScan ? new Date(ks.lastScan).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : 'never'}</p>
  <div class="tkeys"><Button kind="tool" variant="pri" wide disabled={cxScanning()} onclick={scanConnections}>{cxScanning() ? 'Scanning…' : 'Find'}</Button></div>
</Wg>
<Wg cls="s s3" id="kmod" title="Model" jp="モデル">
  <p class="wg-sub">Synthesis, digests and connections use the models in</p><p class="kmod"><b>Settings</b><span>AI models: Synthesize, Connections</span></p>
  <div class="tkeys"><Button kind="tool" wide onclick={() => runCmd('settings')}><Px name="gear" />Models</Button></div>
</Wg>
