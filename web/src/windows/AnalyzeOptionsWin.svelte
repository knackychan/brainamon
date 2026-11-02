<script lang="ts">
  // Analyze options before an Analyze job (Qt AnalyzeOptionsDialog): defaults from
  // GET /api/settings/analyze, saved back as the new defaults, with the no-input guard
  // (check_inputs): no frames and no transcript with an AI provider offers transcript-only.
  import { onMount } from 'svelte'
  import AnalyzeOptionsForm, { type AO } from './AnalyzeOptionsForm.svelte'
  import { api } from '../lib/api'
  import { plural } from '../lib/jobs'
  import { confirmWin } from '../lib/windows.svelte'
  import Button from '../components/ui/Button.svelte'
  import Hint from '../components/ui/Hint.svelte'
  import WinBody from '../components/ui/WinBody.svelte'
  import WinFoot from '../components/ui/WinFoot.svelte'

  let { count, force = false, answer, close }: { count: number; force?: boolean; answer: (o: AO | null) => void; close: () => void } = $props()
  let o = $state<AO | null>(null)
  let err = $state('')

  onMount(async () => {
    try {
      const r = await api.get<{ options: AO }>('/api/settings/analyze')
      o = r.options
    }
    catch (e) { err = (e as Error).message }
  })

  async function go() {
    if (!o) return
    err = ''
    const noFrames = !(+o.frame_interval > 0), noTranscript = !o.transcribe
    if (noFrames && noTranscript) {
      if (o.analysis_provider === 'none') { err = 'Nothing to analyze: set a frame interval or turn transcription on.'; return }
      const ok = await confirmWin({
        title: 'No input for AI analysis', code: 'ANL-12', ok: 'Run transcript-only (no AI)',
        msg: 'You disabled both frame extraction and transcription, so the AI analysis would run with no frames and no transcript to summarize.',
        detail: 'Run transcript-only sets the AI provider to "none". Cancel goes back to the options.',
      })
      if (!ok) return
      o.analysis_provider = 'none'
    }
    try { await api.put('/api/settings/analyze', o) } catch { /* the run still uses these options */ }
    answer({ ...o, frame_interval: +o.frame_interval })
  }
</script>

<WinBody>
  <Hint style="margin-bottom:12px">Analyze videos examines the video’s content through sampled frames and/or audio transcription, according to your options. It uses the local video or downloads it if missing, and can produce an AI report. Describe uses the available post text, title and thumbnail for a static summary. This can take several minutes per video. Estimated AI report cost: about ${(count * 0.03).toFixed(2)}; actual cost varies by model and video length. Transcription and search indexing may add charges. {force ? 'Existing analysis may be replaced.' : 'Already analyzed videos are skipped.'}</Hint>
  {#if o}<AnalyzeOptionsForm bind:o {err} />{:else}<Hint>{err || 'Loading the options…'}</Hint>{/if}
</WinBody>
<WinFoot>
  <Button onclick={close}>Cancel</Button>
  <Button variant="pri" disabled={!o} onclick={go}>Analyze {plural(count, 'video')}</Button>
</WinFoot>
