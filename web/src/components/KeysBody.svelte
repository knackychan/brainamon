<script lang="ts">
  import Button from './ui/Button.svelte'
  import WinBody from './ui/WinBody.svelte'
  import WinFoot from './ui/WinFoot.svelte'
  let { close }: { close: () => void } = $props()
  const K: [string, string][] = [
    ['Ctrl+K', 'Command palette'], ['1 to 4', 'Library, Knowledge, Canvas, Notes'], ['/', 'Search the library'],
    ['Enter (in search, SMART on)', 'Re-rank by meaning'], ['Ctrl+A', 'Select every visible item'],
    ['Esc', 'Close a window, a menu, or clear the selection'], ['Delete', 'Delete the selection (asks first)'],
    ['+  −  0', 'Zoom in, out, fit (Library and Canvas)'], ['Ctrl+wheel', 'Zoom the Library grid'], ['Wheel', 'Zoom the canvas (drag the hand to move)'],
    ['Ctrl+,', 'Settings'], ['Ctrl+`', 'Console'], ['Shift+click', 'Select a range'], ['Right-click', 'Card menu, canvas menu'],
  ]
</script>

<WinBody>
  <div class="blist">
    {#each K as [k, d] (k)}
      <div class="brow" style="grid-template-columns:150px minmax(0,1fr);cursor:default"><b>{k}</b><span>{d}</span></div>
    {/each}
  </div>
</WinBody>
<WinFoot><Button variant="pri" onclick={close}>Close</Button></WinFoot>
