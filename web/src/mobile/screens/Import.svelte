<script lang="ts">
  // Add > Import saved posts (milestone-2026-10-14/mobile-import/PLAN.md): saved posts from a site's own data
  // export. The sources and their steps come from ../import-sources.json, so
  // the wording can follow Meta's menus without touching this screen. The file is read on the phone
  // (../imports.ts); new links go in as phone changes and the picture strip fetches their pictures.
  import { mirrorSource, patchRows, runPictures } from '../state.svelte'
  import { MAX_IMPORT_BYTES, readExport } from '../imports'
  import { t } from '../../lib/i18n/index.ts'
  import { importError, importResult } from '../import-words.ts'
  import { beginLanguageWork } from '../language-switch.ts'
  import SiteRead from './SiteRead.svelte'

  let busy = $state(false), error = $state(''), done = $state('')
  let input: HTMLInputElement | undefined = $state()

  async function picked() {
    const f = input?.files?.[0]
    if (input) input.value = ''
    if (!f || !mirrorSource) return
    error = ''; done = ''
    if (f.size > MAX_IMPORT_BYTES) { error = t('imports.error.tooBig'); return }
    const finishLanguageWork = beginLanguageWork()
    busy = true
    try {
      const { posts, skipped } = await readExport(new Uint8Array(await f.arrayBuffer()))
      const r = await mirrorSource.importLinks(posts)
      if (r.ids.length) { await patchRows(r.ids); runPictures() }
      done = importResult(r.ids.length, r.dups, skipped)
    } catch (e) {
      error = importError(e)
    } finally {
      busy = false
      finishLanguageWork()
    }
  }
</script>

<SiteRead canImport={!!mirrorSource} importing={busy} onfile={() => input?.click()} {error} {done} />
<input type="file" accept=".zip,.json,application/zip,application/json" hidden bind:this={input} onchange={picked} />
