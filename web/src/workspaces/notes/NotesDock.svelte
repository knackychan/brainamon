<script lang="ts">
  // The Notes rail (V6 buildNotesDock): 01 time, 02 autosave, 03 categories (+ Add), 04 notes
  // (New, Digest screenshot, Delete), 05 AI summary.
  import ClockTile from '../library/dock/ClockTile.svelte'
  import Tr from '../library/dock/Tr.svelte'
  import Wg from '../library/dock/Wg.svelte'
  import Px from '../../lib/Px.svelte'
  import { addCategory, deleteMyNote, digestShots, newNote, nt, openMyNote, setCat, summarize, summaryLine } from '../../lib/notes.svelte'
  import { toast } from '../../lib/ui.svelte'
  import { confirmWin, promptWin } from '../../lib/windows.svelte'
  import Button from '../../components/ui/Button.svelte'

  const words = $derived(nt.body.trim() ? nt.body.trim().split(/\s+/).length : 0)
  const st = $derived({ saved: 'Saved', pending: 'Editing', saving: 'Saving', error: 'Not saved' }[nt.status])

  async function add() {
    const v = await promptWin({ title: 'New category', code: 'NTE-42', label: 'Category name', ok: 'Add' })
    if (v) { try { await addCategory(v) } catch (e) { toast((e as Error).message, 'w') } }
  }
  async function create() {
    const v = await promptWin({ title: 'New note', code: 'NTE-43', label: 'Note title', ok: 'Create' })
    if (v) { try { await newNote(v) } catch (e) { toast((e as Error).message, 'w') } }
  }
  async function del() {
    if (!nt.file) { toast('Open a note first', 'w'); return }
    const ok = await confirmWin({ title: `Delete “${nt.title}”?`, code: 'NTE-44', danger: true, ok: 'Delete note', msg: `Permanently delete data/notes/${nt.file}?`, detail: 'This cannot be undone.' })
    if (ok) await deleteMyNote()
  }
  async function shot() {
    if (!nt.file) {
      const v = await promptWin({ title: 'New note', code: 'NTE-43', label: 'Note title', hint: 'The screenshots are transcribed into this new note.', ok: 'Create' })
      if (!v) return
      await newNote(v)
    }
    const inp = document.createElement('input')
    inp.type = 'file'; inp.accept = 'image/png,image/jpeg,image/webp,image/bmp,image/gif'; inp.multiple = true
    inp.onchange = () => { if (inp.files?.length) digestShots([...inp.files]) }
    inp.click()
  }
</script>

<ClockTile />
<Wg cls="k s3" id="nas" title="Autosave" jp="自動保存" n="800 ms">
  <p class="as-big" data-s={nt.status}><i></i><span>{st}</span></p>
  <p class="wg-sub">{nt.file ? `data/notes/${nt.file}` : 'No note open'}</p>
  <p class="wg-ln"><span>{words} word{words === 1 ? '' : 's'}</span><span>{nt.savedAt}</span></p>
</Wg>
<Wg cls="s6" id="ncat" title="Categories" jp="分類" n={nt.categories.length}>
  <div class="rove" role="radiogroup" aria-label="Category" data-rove>
    <Tr label="All notes" checked={nt.cat === 'All'} onpick={() => setCat('All')} />
    {#each nt.categories as c (c)}<Tr label={c} checked={nt.cat === c} onpick={() => setCat(c)} />{/each}
  </div>
  <div class="tkeys"><Button kind="tool" variant="pri" onclick={add}><Px name="plus" />Add category</Button></div>
</Wg>
<Wg cls="s6" id="nlist" title="Notes" jp="ノート" n={nt.list.length}>
  <div class="tlist" role="list">
    {#each nt.list as n (n.file)}
      <button type="button" class="trow" aria-current={n.file === nt.file} title={`data/notes/${n.file}`} onclick={() => openMyNote(n.file)}><span class="l">{n.title || 'Untitled'}</span><span class="c">{n.category} · {n.updated.slice(5, 10)}</span></button>
    {:else}
      <p class="wg-sub">No notes in {nt.cat === 'All' ? 'any category' : nt.cat} yet.</p>
    {/each}
  </div>
  <div class="tkeys">
    <Button kind="tool" variant="pri" onclick={create}><Px name="plus" />New</Button>
    <Button kind="tool" onclick={shot}><Px name="img" />Digest screenshot</Button>
    <span class="sp"></span>
    <Button kind="tool" aria-disabled={nt.file ? undefined : 'true'} onclick={del}><Px name="trash" />Delete</Button>
  </div>
</Wg>
<Wg cls="y s6" id="nsum" title="AI summary" jp="要約">
  <p class="wg-sub">{!nt.file ? 'Open a note to summarize it.' : summaryLine() || 'No summary yet. The AI writes one “## AI summary” section and keeps it up to date.'}</p>
  <div class="tkeys"><Button kind="tool" variant="pri" aria-disabled={nt.file ? undefined : 'true'} onclick={summarize}>{summaryLine() ? 'Update summary' : 'Summarize'}</Button></div>
</Wg>
