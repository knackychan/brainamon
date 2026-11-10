<script lang="ts">
  import { t } from '../lib/i18n/index.ts'
  import { proposalKind, layoutName } from './canvas/words.ts'
  import type { PhoneCanvasProposal } from './source/types'
  import type { PreviewElement } from './ai/canvas'
  import MInfo from './ui/MInfo.svelte'
  let { preview, imageUrl, busy, error, onApply, onDecline }:
    { preview: PhoneCanvasProposal['preview']; imageUrl: (e: PreviewElement) => string;
      busy: boolean; error: string; onApply: () => void; onDecline: () => void } = $props()
</script>

<section class="m-canvas-review" tabindex="-1" aria-label={t('canvas.proposal.label')}>
  <h3>{preview.target.new ? t('canvas.new') : t('canvas.proposal.add')}: {preview.target.name} <MInfo title={t('canvas.proposal.helpTitle')}><p>{t('canvas.proposal.help')}</p></MInfo></h3>
  <p>{preview.target.new ? t('canvas.proposal.newBoard') : t('canvas.proposal.existing', { n: preview.target.count })} · {t('canvas.proposal.summary', { layout: layoutName(preview.layout), thumbs: preview.counts.thumbnail, frames: preview.counts.frame, notes: preview.counts.text, moves: preview.counts.moves })}</p>
  {#each preview.sections as section}
    <div class="m-review-section">
      <h4>{section.title || t('canvas.proposal.ungrouped')}</h4>
      {#each section.elements as el}
        <div class="m-review-element">
          {#if imageUrl(el)}<img src={imageUrl(el)} alt="" />{/if}
          <div><b>{el.kind === 'existing' ? t('canvas.proposal.move') : el.kind === 'text' ? t('canvas.proposal.text') : el.kind === 'frame' ? t('canvas.proposal.frame') : t('canvas.proposal.thumbnail')}</b>
            {#if el.title}<span>{el.title}</span>{/if}
            {#if el.label}<span>{el.label}</span>{/if}
            {#if el.text}<p>{el.text}</p>{/if}</div>
        </div>
      {/each}
    </div>
  {/each}
  {#if preview.explicit.length}<div class="m-review-section"><h4>{t('canvas.proposal.placed')}</h4>
    {#each preview.explicit as el}<div class="m-review-element"><div><b>{proposalKind(el.kind)}</b>{#if el.title}<span>{el.title}</span>{/if}{#if el.text}<p>{el.text}</p>{/if}</div></div>{/each}
  </div>{/if}
  {#if error}<p role="alert" class="m-review-error">{t('canvas.error.detail', { detail: error })}</p>{/if}
  <div class="m-review-actions"><button type="button" disabled={busy} onclick={onDecline}>{t('canvas.proposal.decline')}</button><button type="button" disabled={busy} onclick={onApply}>{busy ? t('canvas.proposal.applying') : t('canvas.proposal.apply')}</button></div>
</section>

<style>
  .m-canvas-review{margin:12px;padding:16px;border:1px solid var(--m-line,#777);border-radius:12px;overflow-wrap:anywhere}
  h3,h4{margin:0 0 8px}h4{font-size:14px}.m-canvas-review>p{line-height:1.4}
  .m-review-section{margin-top:14px}.m-review-element{display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--m-line,#777);min-width:0}
  .m-review-element img{width:64px;height:64px;object-fit:cover;flex:none}.m-review-element div{min-width:0;display:grid;gap:3px}.m-review-element span{display:block}.m-review-element p{white-space:pre-wrap;margin:3px 0}
  .m-review-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.m-review-actions button{min-width:44px;min-height:44px;padding:8px 16px;flex:1}
  .m-review-error{color:var(--m-warn,#c34)}
</style>
