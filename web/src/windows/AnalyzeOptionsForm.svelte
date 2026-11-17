<script lang="ts" module>
  // The video-analysis options (Qt ui/analyze_options_dialog.py AnalyzeOptionsWidget), shared by the
  // Analyze options window and Video Tools (plan 12). Values as the server's ANALYZE_DEFAULTS.
  export interface AO {
    frame_interval: number; transcribe: boolean; transcribe_method: string; analysis_provider: string
    keep_frames: boolean; show_frames_in_canvas: boolean; delete_video: boolean; delete_audio: boolean
    ai_frame_budget: string
  }
  export const FRAME_CHOICES: [string, boolean, boolean][] = [
    ['Keep & show in item canvas', true, true],
    ['Keep on disk only (hidden from canvas)', true, false],
    ['Delete frames after analysis', false, false],
  ]
  export const BUDGETS: [string, string][] = [
    ['Auto (scale with length)', 'auto'], ['Off (transcript only)', '0'], ['Up to 8', '8'], ['Up to 15', '15'], ['Up to 24', '24'],
  ]
  export const PROVIDERS: [string, string][] = [['claude', 'Claude'], ['openai', 'OpenAI'], ['freellmapi', 'FreeLLMAPI'], ['none', '']]
</script>

<script lang="ts">
  // Three steps, top to bottom: what the analysis reads (frames, audio), the AI report, then the
  // rarely changed file cleanup and the data disclosure folded away. The transcription model has a
  // single choice, so it is named, not offered.
  import Disclosure from '../components/ui/Disclosure.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import Label from '../components/ui/Label.svelte'
  import SectionTitle from '../components/ui/SectionTitle.svelte'
  import ToggleRow from '../components/ui/ToggleRow.svelte'
  import { t } from '../lib/i18n/index.ts'
  const frameLabels = ['shared.analysis.keepShow', 'shared.analysis.keepDisk', 'shared.analysis.deleteFrames'] as const
  let { o = $bindable(), err = '' }: { o: AO; err?: string } = $props()
  let frames = $state(Math.max(0, FRAME_CHOICES.findIndex(([, k, s]) => k === o.keep_frames && s === o.show_frames_in_canvas)))
  $effect(() => { const [, k, s] = FRAME_CHOICES[frames]; o.keep_frames = k; o.show_frames_in_canvas = s })

  // the frames switch is the interval: off stores 0, on restores the last interval used (2 s at first)
  let lastInterval = +o.frame_interval > 0 ? +o.frame_interval : 2
  const sampling = $derived(+o.frame_interval > 0)
  function setSampling(on: boolean) {
    if (!on && +o.frame_interval > 0) lastInterval = +o.frame_interval
    o.frame_interval = on ? lastInterval : 0
  }
  const reporting = $derived(o.analysis_provider !== 'none')
  const kept = $derived([
    t(frameLabels[frames]),
    ...(o.delete_video ? [] : [t('shared.analysis.keepVideo')]),
    ...(o.delete_audio ? [] : [t('shared.analysis.keepAudio')]),
  ].join(' · '))
</script>

<div class="ao">
  <SectionTitle>{t('shared.analysis.read')}</SectionTitle>
  <div class="ao-rows">
    <div class="ao-line">
      <ToggleRow label={t('shared.analysis.sample')} checked={sampling} onchange={setSampling} />
      {#if sampling}
        <span class="ao-every"><input class="inp" type="number" min="0.5" max="60" step="0.5" required value={o.frame_interval}
          oninput={e => { if (e.currentTarget.validity.valid) o.frame_interval = e.currentTarget.valueAsNumber }}
          onblur={e => { e.currentTarget.value = String(o.frame_interval) }}
          aria-label={t('shared.analysis.interval')} /><Hint as="span">{t('shared.analysis.secs')}</Hint></span>
      {/if}
    </div>
    <ToggleRow label={t('shared.analysis.extract')} note={t('shared.analysis.openai')} bind:checked={o.transcribe} />
  </div>

  <SectionTitle>{t('shared.analysis.report')}</SectionTitle>
  <div class="fg">
    <Label for="ao-pr">{t('shared.analysis.provider')}</Label>
    <select class="inp" id="ao-pr" bind:value={o.analysis_provider}>{#each PROVIDERS as [v, name] (v)}<option value={v}>{v === 'none' ? t('shared.analysis.none') : name}</option>{/each}</select>
    {#if reporting && sampling}
      <Label for="ao-send">{t('shared.analysis.budget')}</Label>
      <select class="inp" id="ao-send" bind:value={o.ai_frame_budget}>{#each BUDGETS as [, v] (v)}<option value={v}>{v === 'auto' ? t('shared.analysis.auto') : v === '0' ? t('shared.analysis.off') : t('shared.analysis.upTo', { n: v })}</option>{/each}</select>
    {/if}
  </div>
  {#if !reporting}<Hint class="ao-note">{t('shared.analysis.noReport')}</Hint>{/if}

  <Hint tone="error" hidden={!err}>{err}</Hint>

  <Disclosure summary={`${t('shared.analysis.files')}: ${kept}`}>
    <div class="ao-in">
      <div class="fg">
        <Label for="ao-keep">{t('shared.analysis.frames')}</Label>
        <select class="inp" id="ao-keep" bind:value={frames}>{#each FRAME_CHOICES as _, i (i)}<option value={i}>{t(frameLabels[i])}</option>{/each}</select>
      </div>
      <div class="ao-rows">
        <ToggleRow label={t('shared.analysis.deleteVideo')} bind:checked={o.delete_video} />
        <ToggleRow label={t('shared.analysis.deleteAudio')} bind:checked={o.delete_audio} />
      </div>
    </div>
  </Disclosure>
  <Disclosure summary={t('shared.analysis.privacy')}><Hint>{t('shared.analysis.disclosure')}</Hint></Disclosure>
</div>

<style>
  .ao :global(.fsec) { margin: 4px 0 8px }
  .ao :global(.fsec:not(:first-child)) { margin-top: 16px }
  .ao-rows { display: grid; gap: 8px }
  .ao-line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 14px; min-height: 30px }
  .ao-every { display: inline-flex; align-items: center; gap: 8px }
  .ao-every input { width: 72px }
  .ao :global(.ao-note) { margin-top: 6px }
  .ao-in { display: grid; gap: 10px; padding: 4px 0 2px }
</style>
