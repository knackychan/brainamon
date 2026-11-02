<script lang="ts">
  import { api } from '../lib/api'
  import { openSettings } from '../lib/io-commands.svelte'
  import { startJob } from '../lib/jobs'
  import { live } from '../lib/events.svelte'
  import { toast } from '../lib/ui.svelte'
  import { openItem } from '../lib/edit-commands'
  import Button from './ui/Button.svelte'
  import Hint from './ui/Hint.svelte'
  let { action, itemId, kind, thumbnailOnly }: { action?: string; itemId: number; kind: string; thumbnailOnly?: boolean } = $props()
  async function source() { try { await api.post('/api/open', { what: 'url', id: itemId }) } catch (e) { toast((e as Error).message, 'w') } }
  async function retry() {
    if (kind !== 'download') { await startJob(kind, { ids: [itemId], force: true }); return }
    if (thumbnailOnly === undefined) { openItem(itemId); return }
    const { downloadItem } = await import('../lib/job-commands')
    await downloadItem(itemId, thumbnailOnly)
  }
</script>

<div class="frow">
  {#if action === 'tools' || action === 'youtube'}<Button size="sm" onclick={() => openSettings('tools')}>{action === 'youtube' ? 'Check YouTube setup' : 'Install / Check tools'}</Button>
  {:else if action === 'sessions'}<Button size="sm" onclick={() => openSettings('downloads')}>Replace saved login</Button>
  {:else if action === 'wait'}<Hint as="span">Wait before retrying.</Hint>
  {:else if action === 'retry'}<Button size="sm" disabled={!!live.jobs.current} onclick={retry}>{kind === 'download' && thumbnailOnly === undefined ? 'Review download' : 'Retry this item'}</Button>{/if}
  <Button size="sm" onclick={source}>Open source</Button>
</div>
