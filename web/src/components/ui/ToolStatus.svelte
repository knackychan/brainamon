<script lang="ts">
  // A tool's state chip (.tool-status, app.css). With `name`, the chip shows the mark and the tool's name,
  // and the words only when the tool needs attention ("yt-dlp: Update needed"); otherwise screen readers
  // read the state after the name. Without, the chip says the state itself. Not a live region: each group
  // announces its own status line.
  let { state, name = '' }: { state: string; name?: string } = $props()
  const labels: Record<string, string> = { checking: 'Checking…', ready: 'Ready', missing: 'Not set up', older: 'Update needed', failed: 'Needs attention', installing: 'Installing…', off: 'Not set up' }
  const mark = $derived(state === 'ready' ? '✓' : state === 'checking' || state === 'installing' ? '…' : state === 'missing' || state === 'off' ? '○' : '!')
  const text = $derived(labels[state] ?? 'Needs attention')
  const attention = $derived(mark === '!')
</script>
<span class="tool-status" class:ready={state === 'ready'} class:pending={state === 'checking' || state === 'installing'}><span aria-hidden="true">{mark}</span> {#if name}{name}{#if attention}: {text}{:else}<span class="sr">: {text}</span>{/if}{:else}{text}{/if}</span>
