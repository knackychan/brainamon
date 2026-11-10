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
</script>

<script lang="ts">
  import Field from '../components/ui/Field.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import { t } from '../lib/i18n/index.ts'
  const frameLabels = ['shared.analysis.keepShow', 'shared.analysis.keepDisk', 'shared.analysis.deleteFrames'] as const
  let { o = $bindable(), err = '' }: { o: AO; err?: string } = $props()
  let frames = $state(Math.max(0, FRAME_CHOICES.findIndex(([, k, s]) => k === o.keep_frames && s === o.show_frames_in_canvas)))
  $effect(() => { const [, k, s] = FRAME_CHOICES[frames]; o.keep_frames = k; o.show_frames_in_canvas = s })
</script>

<div class="fg">
  <Field label={t('shared.analysis.interval')} for="ao-int"><div class="frow"><input class="inp" id="ao-int" type="number" min="0" max="60" step="0.5" bind:value={o.frame_interval} style="max-width:110px" /><Hint as="span">{t('shared.analysis.seconds')}</Hint></div></Field>
  <Field label={t('shared.analysis.transcription')} as="span"><label class="chk"><input type="checkbox" bind:checked={o.transcribe} />{t('shared.analysis.extract')}</label></Field>
  <Field label={t('shared.analysis.model')} for="ao-mod"><select class="inp" id="ao-mod" bind:value={o.transcribe_method} disabled={!o.transcribe}>
    <option value="whisper-api">{t('shared.analysis.openai')}</option>
  </select></Field>
  <Field label={t('shared.analysis.provider')} for="ao-pr"><select class="inp" id="ao-pr" bind:value={o.analysis_provider}>{#each ['claude', 'openai', 'freellmapi', 'none'] as p (p)}<option value={p}>{p === 'none' ? t('shared.analysis.none') : p}</option>{/each}</select></Field>
  <Field label={t('shared.analysis.budget')} for="ao-send"><select class="inp" id="ao-send" bind:value={o.ai_frame_budget}>{#each BUDGETS as [, v] (v)}<option value={v}>{v === 'auto' ? t('shared.analysis.auto') : v === '0' ? t('shared.analysis.off') : t('shared.analysis.upTo', { n: v })}</option>{/each}</select></Field>
  <Field label={t('shared.analysis.frames')} for="ao-keep"><select class="inp" id="ao-keep" bind:value={frames}>{#each FRAME_CHOICES as _, i (i)}<option value={i}>{t(frameLabels[i])}</option>{/each}</select></Field>
  <Field label={t('shared.analysis.after')} as="span"><span>
    <label class="chk"><input type="checkbox" bind:checked={o.delete_video} />{t('shared.analysis.deleteVideo')}</label>
    <label class="chk" style="margin-top:6px"><input type="checkbox" bind:checked={o.delete_audio} />{t('shared.analysis.deleteAudio')}</label>
  </span></Field>
  <span></span><Hint tone="error" hidden={!err}>{err}</Hint>
</div>
<Hint>{t('shared.analysis.disclosure')}</Hint>
