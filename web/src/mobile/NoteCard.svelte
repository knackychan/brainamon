<script lang="ts">
  // A My notes row as a note card (projects/note-organic-ui/plans/08-note-cards.md): the Library item
  // card's classic frame (design/card-designs/cards.css, read only) adapted for a note. The top of the
  // note on dot paper is its art; its word count stands where an item shows its rank. np-cd- classes
  // only (note.css), never the card engine's class names.
  import { esc } from '../lib/cards/card'
  import { blocksHTML, marksInline } from '../lib/note-format'
  import type { MyNote } from './source/types'

  let { n, tint, onopen }: { n: MyNote; tint: number; onopen: () => void } = $props()

  // lib/md.ts mdInline without its links and card chips (the page is inside the card's button):
  // code, bold, italics, a [text](url) link as its text, then the note marks
  const inline = (s: string) => marksInline(s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '$1'))
  const page = $derived(n.head ? blocksHTML(esc(n.head), inline)
    : n.snippet && n.snippet !== '(no content)' ? `<p>${esc(n.snippet)}</p>`         // a list cached before plan 08
    : '<p class="np-cd-empty">Empty note</p>')
  const when = (s: string) => (s ? new Date(s).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '')
</script>

<button type="button" class="np-cd" style={`--t:var(--np-cd-${tint})`} aria-label={n.title || 'Untitled'} onclick={onopen}>
  <span class="np-cd-win">
    <span class="np-cd-hd">
      <i class="np-cd-stage">Note</i>
      <span class="np-cd-rank">{#if n.words != null}<b>{n.words}</b> {n.words === 1 ? 'word' : 'words'}{/if}</span>
      <b class="np-cd-nm">{n.title || 'Untitled'}</b>
    </span>
    <span class="np-cd-page" aria-hidden="true">{@html page}</span>
    <span class="np-cd-pn">
      <span class="np-cd-stats">
        <span><small>shelf</small><b>{n.category}</b></span>
        <span><small>stamps</small><b>{n.stamps?.length ?? 0}</b></span>
        <span><small>edited</small><b>{when(n.updated || n.created)}</b></span>
      </span>
      <span class="np-cd-ft"><i></i><span>{n.file}</span><span class="np-cd-bc"></span></span>
    </span>
  </span>
</button>
