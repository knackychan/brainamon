<script lang="ts">
  // Polished Expand (phone-dock-shell plan 05), with the shared site reader flow.
  import { onMount } from 'svelte'
  import { siteClear, siteForget, siteOpen, sitePending, siteState, type SiteReaderState, type SiteRunResult } from '../native'
  import { knownHashes, readPending, RULES, type SiteId } from '../sites'
  import { mirrorSource, patchRows, phone, runPictures } from '../state.svelte'
  import { kv } from '../store'
  import { beginLanguageWork } from '../language-switch.ts'
  import { t } from '../../lib/i18n/index.ts'
  import T from '../../lib/i18n/T.svelte'
  import { captureText } from '../capture-words.ts'
  import { importGuides } from '../import-words.ts'
  import MBox from '../ui/MBox.svelte'
  import MButton from '../ui/MButton.svelte'
  import MDisclosure from '../ui/MDisclosure.svelte'
  import MHint from '../ui/MHint.svelte'
  import MInfo from '../ui/MInfo.svelte'
  import MTextButton from '../ui/MTextButton.svelte'
  import '../import.css'

  let { canImport, importing, onfile, error, done }: {
    canImport: boolean; importing: boolean; onfile: () => void; error: string; done: string
  } = $props()
  const sources = $derived(importGuides(captureText))
  const id = $props.id()
  const WEBVIEW = 'Update Android System WebView to read sites.'
  const RUNS = 'site-runs', NOTE = 'bp-site-note'
  type RunInfo = { at: number; complete: boolean; line: string; bad: boolean }
  type Review = Awaited<ReturnType<typeof readPending>> & { res: SiteRunResult | null }
  const REASONS: Record<string, string> = {
    end: 'read to the end of the list', known: 'stopped at posts already in the library',
    stop: 'stopped', cap: 'stopped at 20,000 saved items',
    empty: 'Brainamon could not read this page; the site may have changed',
    failure: 'Reading could not finish. Saved results are kept; try Scan again after importing.',
  }
  const OPEN_ERRORS: Record<string, string> = { webview: WEBVIEW, busy: 'A site window is already open.' }
  const fail = (e: unknown) => OPEN_ERRORS[(e as { code?: string }).code ?? ''] ?? (e as Error).message
  let st = $state.raw<SiteReaderState | null>(null)
  let open = $state<SiteId | ''>('instagram')
  let busy = $state<SiteId | ''>(''), confirm = $state<SiteId | ''>('')
  let errors = $state<Record<string, string>>({}), messages = $state<Record<string, string>>({})
  let runs = $state.raw<Record<string, RunInfo>>({})
  let reviews = $state.raw<Partial<Record<SiteId, Review>>>({})
  let note = $state.raw<{ site: SiteId; full: boolean } | null>(null)
  const reader = (site: SiteId) => !!RULES[site] && !!st?.sites[site]?.reader
  let consent = false
  const noteSeen = () => { try { return consent || !!localStorage.getItem(NOTE) } catch { return consent } }
  const reason = (res: SiteRunResult | null) => res ? REASONS[res.reason] ?? REASONS.stop : 'from a read that was cut off'
  const badRun = (res: SiteRunResult | null) => res?.reason === 'empty' || res?.reason === 'failure'
  const count = (n: number | undefined) => Number.isSafeInteger(n) && n! > 0 ? Math.min(n!, 1_000_000) : 0

  onMount(() => {
    const finishLanguageWork = beginLanguageWork()
    busy = 'facebook'
    void (async () => {
      st = await siteState()
      runs = (await kv.get<Record<string, RunInfo>>(RUNS)) ?? {}
      const pending = sources.filter(s => reader(s.id) && st?.sites[s.id]?.pending && canImport)
      for (const s of pending) {
        busy = s.id
        try { await reviewRun(s.id, null) } catch (e) { errors[s.id] = fail(e) }
      }
      if (pending.length) st = await siteState()
    })().catch(e => { errors.facebook = fail(e) }).finally(() => { busy = ''; finishLanguageWork() })
  })

  async function finishRun(site: SiteId, review: Review, added: number, dups: number) {
    const res = review.res
    const parts = [`${sources.find(s => s.id === site)?.name}: ${added} added`]
    const known = count(res?.known) + dups
    if (known) parts.push(`${known} already there`)
    if (count(res?.other)) parts.push(`${count(res?.other)} other saved items not read`)
    const dropped = review.dropped + count(res?.dropped)
    if (dropped) parts.push(`${dropped} refused`)
    parts.push(reason(res))
    const next = { ...runs, [site]: { at: Date.now(), complete: !!runs[site]?.complete || res?.reason === 'end',
      line: parts.join(' · '), bad: badRun(res) } }
    await kv.setRequired(RUNS, next)
    await siteClear(site)
    runs = next
    reviews = { ...reviews, [site]: undefined }
    messages[site] = ''
  }

  async function reviewRun(site: SiteId, res: SiteRunResult | null) {
    const review = { ...await readPending(site, (offset, max) => sitePending(site, offset, max)), res }
    reviews = { ...reviews, [site]: review }
    messages[site] = ''
    if (!review.posts.length) await finishRun(site, review, 0, 0)
  }

  async function importRun(site: SiteId) {
    const review = reviews[site], source = mirrorSource
    if (!review || !source || busy || importing) return
    const finishLanguageWork = beginLanguageWork()
    busy = site; errors[site] = ''
    try {
      const result = await source.importLinks(review.posts)
      if (result.ids.length) await patchRows(result.ids)
      await source.addPicHints(review.pics)
      await finishRun(site, review, result.ids.length, result.dups)
      runPictures()
    } catch (e) { errors[site] = fail(e) }
    finally { try { st = await siteState(); busy = '' } finally { finishLanguageWork() } }
  }

  async function scan(site: SiteId, full = false) {
    if (busy || importing || note || !st?.supported || st.sites[site]?.forgetting) return
    errors[site] = ''; messages[site] = ''; confirm = ''
    if (!reader(site)) { await signIn(site); return }
    if (!mirrorSource || !canImport) return
    const pending = st.sites[site]?.pending || reviews[site]
    if (!pending && !noteSeen()) { note = { site, full }; return }
    const finishLanguageWork = beginLanguageWork()
    busy = site
    messages[site] = 'Reading saved posts in the site browser… Use Stop there to keep a partial read.'
    try {
      if (pending) await reviewRun(site, reviews[site]?.res ?? null)
      else {
        const known = await knownHashes(site, phone.rows.map(r => r.url))
        const res = await siteOpen(site, known, full, !!runs[site]?.complete)
        if (res.reason === 'unsupported') errors[site] = WEBVIEW
        else await reviewRun(site, res)
      }
    } catch (e) { errors[site] = fail(e) }
    finally { try { messages[site] = ''; st = await siteState(); busy = '' } finally { finishLanguageWork() } }
  }

  function accept() {
    const next = note
    consent = true
    try { localStorage.setItem(NOTE, String(Date.now())) } catch { /* asked again next time */ }
    note = null
    if (next) void scan(next.site, next.full)
  }

  async function signIn(site: SiteId) {
    const finishLanguageWork = beginLanguageWork()
    errors[site] = ''; messages[site] = ''; confirm = ''; busy = site
    try {
      const res = await siteOpen(site, [], false, false)
      if (res.reason === 'unsupported') errors[site] = WEBVIEW
    } catch (e) { errors[site] = fail(e) }
    finally { try { st = await siteState(); busy = '' } finally { finishLanguageWork() } }
  }
  async function forget(site: SiteId) {
    if (confirm !== site) { confirm = site; return }
    const finishLanguageWork = beginLanguageWork()
    confirm = ''; errors[site] = ''; messages[site] = ''; busy = site
    try { await siteForget(site) } catch (e) { errors[site] = fail(e) }
    finally { try { st = await siteState(); busy = '' } finally { finishLanguageWork() } }
  }
</script>

{#snippet glyph(site: string)}
  <i class="m-import-glyph" aria-hidden="true"><svg viewBox="0 0 24 24">
    {#if site === 'instagram'}<rect x="3.5" y="3.5" width="17" height="17" rx="5" /><circle cx="12" cy="12" r="3.8" /><path d="M17 7h.01" />
    {:else if site === 'facebook'}<circle cx="12" cy="12" r="8.5" /><path d="M14.6 8.2h-1.4a1.9 1.9 0 0 0-1.9 1.9v10.4M9.2 12.6h5" />
    {:else if site === 'threads'}<circle cx="12" cy="12" r="3.6" /><path d="M15.6 8.4v4.4a2.7 2.7 0 0 0 5.4 0V12a9 9 0 1 0-3.6 7.2" />
    {:else}<path d="M14 3.5v11a3.75 3.75 0 1 1-3.75-3.75M14 3.5c.5 2.6 2.4 4.4 5 4.7" />{/if}
  </svg></i>
{/snippet}

<div class="m-pad m-import-screen">
  <div class="m-import-intro"><h1>{t('imports.title')}</h1><MHint as="p">{t('imports.intro')}</MHint></div>
  <div class="m-import-expand" class:m-import-still={phone.motionOff} aria-label={t('imports.platforms')}>
    {#each sources as s (s.id)}
      {@const x = st?.sites[s.id]}
      <MBox as="section" class="m-import-fold" aria-label={s.name}>
        <MButton class="m-import-toggle" aria-expanded={open === s.id} aria-controls={`${id}-${s.id}`} onclick={() => (open = open === s.id ? '' : s.id)}>
          <span>{@render glyph(s.id)}{s.name}</span>
          <span class="m-import-chevron" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="m4 6 4 4 4-4" /></svg></span>
        </MButton>
        <div id={`${id}-${s.id}`} class="m-import-reveal" class:open={open === s.id} aria-hidden={open !== s.id} inert={open !== s.id}>
          <div class="m-import-clip">
            <div class="m-import-platform m-import-expanded">
              <div class="m-import-actions compact" role="group" aria-label={t('imports.actions', { name: s.name })}>
                <div class="m-import-action">
                  <MButton as="a" href={s.page} target="_blank" rel="noopener noreferrer" aria-label={t('imports.export.request')}
                    onclick={() => { messages[s.id] = t('imports.export.opened', { name: s.name }) }}>
                    <span class="m-import-action-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M10 5H5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1v-5" /></svg></span>
                  </MButton>
                  <div class="m-import-action-caption"><MInfo title={t('imports.export.title', { name: s.name })} label={t('imports.export.label')}>
                    <p><T id="imports.export.help" params={{ name: s.name }} /></p>
                    <ol>{#each s.steps as step}<li>{step}</li>{/each}</ol>
                    <p>{t('imports.export.signIn')}</p>
                  </MInfo></div>
                </div>
                <div class="m-import-action">
                  <MButton disabled={!st?.supported || !!busy || importing || !!note || x?.forgetting || (reader(s.id) && !canImport)} aria-label={t('imports.scan.action')} aria-describedby={`${id}-${s.id}-reader`}
                    aria-busy={busy === s.id} onclick={() => scan(s.id)}>
                    <span class="m-import-action-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M7 6.5h.01M10 6.5h.01M8 13h8M8 16h5" /></svg></span>
                  </MButton>
                  <div class="m-import-action-caption"><MInfo title={t('imports.scan.title', { name: s.name })} label={t('imports.scan.label')}>
                    <p>{t('imports.scan.help', { name: s.name })}</p>
                    {#if x?.signedIn && !x.forgetting}<p>Signed in.</p>{/if}
                    {#if reader(s.id)}
                      <p>Reads your saved {s.id === 'instagram' ? 'posts and reels from All posts' : s.id === 'threads' ? 'posts' : 'reels and videos'}. The first scan reads the full list; after a complete scan, later scans stop after 20 posts already in your library. Review the results before importing.</p>
                      <p>Use Stop in the browser to keep a partial read. Reading waits while offline, in the background, or while you finish a login check.</p>
                      {#if !canImport}<p>Scan needs the phone's own library. Pair with a PC, or start without one in Settings.</p>{/if}
                    {:else}<p>{t('imports.scan.unavailable')}</p>{/if}
                    {#if !st?.supported}<p>{t('imports.scan.browserUnavailable')}</p>{/if}
                    {#if st && !st.supported}<p>{WEBVIEW}</p>{/if}
                    {#if st?.supported && !x?.forgetting}
                      <MTextButton tone="danger" disabled={!!busy || importing || !!note || x?.forgetting} onclick={() => forget(s.id)}>{confirm === s.id ? 'Tap again to forget login' : 'Forget login'}</MTextButton>
                    {/if}
                    {#if confirm === s.id}<MTextButton onclick={() => (confirm = '')}>Cancel</MTextButton>{/if}
                    {#if errors[s.id]}<MHint as="p" tone="error" role="alert">{errors[s.id]}</MHint>{/if}
                  </MInfo></div>
                </div>
                <div class="m-import-action">
                  <MButton variant={s.file ? 'pri' : 'default'} disabled={!s.file || !canImport || importing || !!busy || !!note} aria-label={t('imports.file.action')} aria-describedby={`${id}-${s.id}-file`}
                    aria-busy={s.file && importing} onclick={onfile}>
                    <span class="m-import-action-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M12 18v-7M9 14l3-3 3 3" /></svg></span>
                  </MButton>
                  <div class="m-import-action-caption"><MInfo title={t('imports.file.title', { name: s.name })} label={t('imports.file.label')}>
                    {#if s.file}
                      <p><T id="imports.file.help" /></p>
                      <p>{t('imports.file.formats')}</p>
                      <p>{t('imports.file.local')}</p>
                      {#if !canImport}<p>{t('imports.file.needsLibrary')}</p>{/if}
                    {:else}
                      <p><T id="imports.file.unsupported" params={{ name: s.name }} /></p>
                    {/if}
                  </MInfo></div>
                </div>
              </div>
              <span id={`${id}-${s.id}-reader`} class="m-sr">{reader(s.id) ? 'Scan saved posts, then review and import.' : st?.supported ? t('imports.scan.signInOnly') : t('imports.scan.browserUnavailable')}</span>
              <span id={`${id}-${s.id}-file`} class="m-sr">{!s.file ? t('imports.file.unavailable') : canImport ? t('imports.file.cap') : t('imports.file.needsLibraryShort')}</span>
              {#if messages[s.id]}<MHint as="p" role="status">{messages[s.id]}</MHint>{/if}
              {#if note?.site === s.id}
                <MHint as="p" role="status">Uses your login on this phone. Sites may check accounts that read fast. Brainamon only reads, slowly; you can stop anytime. Imported links follow your library's existing sync settings.</MHint>
                <div class="m-row"><MButton variant="pri" size="sm" onclick={accept}>Continue</MButton><MTextButton onclick={() => (note = null)}>Cancel</MTextButton></div>
              {/if}
              {#if reviews[s.id]}
                {@const review = reviews[s.id]!}
                <MHint as="p" role="status">{review.posts.length} post{review.posts.length === 1 ? '' : 's'} ready to import · {reason(review.res)}{review.dropped ? ` · ${review.dropped} refused` : ''}</MHint>
                <MDisclosure summary="Review saved posts">
                  <MHint>Other saved items: {count(review.res?.other)}. Already in your library: {count(review.res?.known)}. Only validated {s.name} links enter your library.</MHint>
                  {#each review.posts.slice(0, 5) as post}<MHint as="p">{post.creator ? `${post.creator}: ` : ''}{post.caption || post.url}</MHint>{/each}
                  {#if review.posts.length > 5}<MHint>Showing the first 5 of {review.posts.length} posts.</MHint>{/if}
                </MDisclosure>
                <div class="m-row">
                  <MButton variant="pri" size="sm" disabled={!!busy || importing || !canImport} onclick={() => importRun(s.id)}>Import {review.posts.length} post{review.posts.length === 1 ? '' : 's'}</MButton>
                  <MTextButton disabled={!!busy || importing} onclick={() => { reviews = { ...reviews, [s.id]: undefined }; messages[s.id] = 'Saved results kept on this phone. Tap Scan to review them later.' }}>Later</MTextButton>
                </div>
              {:else if !messages[s.id] && runs[s.id]?.line}
                <MHint as="p" tone={runs[s.id].bad ? 'error' : 'hint'} role={runs[s.id].bad ? 'alert' : 'status'}>{runs[s.id].line}</MHint>
              {/if}
              {#if reader(s.id) && runs[s.id]?.complete && !reviews[s.id] && !x?.pending}
                <MTextButton disabled={!!busy || importing || !!note || !canImport || x?.forgetting} onclick={() => scan(s.id, true)}>Read all again</MTextButton>
              {/if}
              {#if errors[s.id]}<MHint as="p" tone="error" role="alert">{errors[s.id]}</MHint>{/if}
              {#if s.file}
                {#if importing}<MHint as="p" role="status">{t('imports.file.importing')}</MHint>{/if}
                {#if error}<MHint as="p" tone="error" role="alert">{error}</MHint>{/if}
                {#if done}<MHint as="p" role="status">{done}</MHint>{/if}
              {/if}
            </div>
          </div>
        </div>
      </MBox>
    {/each}
  </div>
  <MDisclosure summary={t('imports.how.title')}>
    <MHint>{t('imports.how.export')}</MHint>
    <MHint>{t('imports.how.scan')}</MHint>
    <MHint>{t('imports.file.local')}</MHint>
  </MDisclosure>
</div>
