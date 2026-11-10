<script lang="ts">
  // A My notes row as note card A (projects/phone-notes-manager, spec section 4): a page of the notebook (dot
  // paper, the keys' hard shadow) with the shelf as a coloured tab at its top, the title, then the note's 14-line
  // head fading into the paper. np-cd- classes only (note.css), never the card engine's class names.
  import { t } from '../lib/i18n/index.ts'
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
    : `<p class="np-cd-empty">${esc(t('notes.card.empty'))}</p>`)
</script>

<button type="button" class="np-cd" style={`--t:var(--np-cd-${tint})`} aria-label={n.title || t('notes.editor.untitled')} onclick={onopen}>
  <span class="np-cd-tab">{n.category || 'General'}</span>
  <b class="np-cd-nm">{n.title || t('notes.editor.untitled')}</b>
  <span class="np-cd-page" aria-hidden="true">{@html page}</span>
</button>
