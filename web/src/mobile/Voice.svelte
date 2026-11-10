<script lang="ts">
  // The record button of a My Note on the phone: record -> transcription -> onText(text). Without signal the
  // recording is queued (voice.ts) and turned into text later (Notes.svelte flushes the queue).
  import { appendVoice, enqueue, MAX_BYTES } from './voice'
  import { source } from './state.svelte'
  import { t } from '../lib/i18n/index.ts'
  import { captureError } from './capture-words.ts'
  import { beginLanguageWork } from './language-switch.ts'
  import { discardVoice, retainVoice, retryVoice, unsavedVoice } from './voice-pending.svelte'
  import { onDestroy, onMount } from 'svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'
  import MInfo from './ui/MInfo.svelte'

  let { file, onText, onQueued }: { file: string; onText: (text: string) => void; onQueued: () => void } = $props()
  let mode = $state<'idle' | 'rec' | 'busy'>('idle')
  let secs = $state(0), msg = $state('')
  let rec: MediaRecorder | null = null
  let chunks: Blob[] = []
  let tick = 0
  let cancelled = false
  let alive = true
  let starting = $state(false), retrying = $state('')
  let picker = $state<HTMLInputElement>()!
  let samples = $state<number[]>([])
  let audio: AudioContext | null = null, meter = 0

  function stopMeter() { cancelAnimationFrame(meter); meter = 0; void audio?.close().catch(() => {}); audio = null }
  function startMeter(stream: MediaStream) {
    try {
      audio = new AudioContext()
      const analyser = audio.createAnalyser()
      analyser.fftSize = 1024
      audio.createMediaStreamSource(stream).connect(analyser)
      const data = new Uint8Array(analyser.frequencyBinCount)
      let last = 0
      const draw = (now: number) => {
        meter = requestAnimationFrame(draw)
        if (now - last < 50) return
        last = now
        analyser.getByteTimeDomainData(data as any)
        let sum = 0
        for (const v of data) sum += ((v - 128) / 128) ** 2
        samples = [...samples.slice(-31), Math.min(1, Math.sqrt(sum / data.length) * 4)]
      }
      meter = requestAnimationFrame(draw)
    } catch { stopMeter() }
  }

  onMount(() => {
    if (sessionStorage.getItem('bp-record-note') === file) {
      sessionStorage.removeItem('bp-record-note')
      void start()
    }
  })
  onDestroy(() => { alive = false; clearInterval(tick); stopMeter(); if (rec?.state === 'recording') rec.stop() })

  async function start() {
    if (starting) return
    msg = ''
    if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') { msg = t('voice.record.unsupported'); return }
    const done = beginLanguageWork(), release = () => done()
    starting = true
    let started = false
    try {
      let stream: MediaStream
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
      catch { msg = t('voice.record.denied'); return }
      if (!alive) { stream.getTracks().forEach(t => t.stop()); return }
      chunks = []
      cancelled = false
      try { rec = new MediaRecorder(stream) }
      catch (e) { stream.getTracks().forEach(t => t.stop()); msg = t('voice.record.startFailed', { message: (e as Error).message }); return }
      rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
      rec.onstop = () => {
        clearInterval(tick)
        stopMeter()
        stream.getTracks().forEach(t => t.stop())
        if (!cancelled) void finish(new Blob(chunks, { type: rec?.mimeType || 'audio/webm' })).finally(release)
        else release()
      }
      try { rec.start() }
      catch (e) { stream.getTracks().forEach(t => t.stop()); msg = t('voice.record.startFailed', { message: (e as Error).message }); return }
      started = true
      samples = []
      startMeter(stream)
      secs = 0
      tick = window.setInterval(() => secs++, 1000)
      mode = 'rec'
    } finally { starting = false; if (!started) release() }
  }
  async function finish(blob: Blob) {
    const done = beginLanguageWork()
    mode = 'busy'
    try {
      if (blob.size > MAX_BYTES) { msg = t('voice.record.tooLong'); return }
      if (navigator.onLine === false) { await enqueue(file, blob); if (alive) onQueued(); msg = t('voice.queue.waiting'); return }
      const text = await source.transcribe!(blob)
      if (text && alive) onText(text)
      else if (text) {
        try {
          const n = await source.myNote(file)
          await source.saveMyNote(n.file, n.title, n.category, appendVoice(n.body ?? '', text))
        } catch { await enqueue(file, blob) }
      } else msg = t('voice.record.noSpeech')
    } catch (e) {
      const m = captureError(e)
      const kept = await enqueue(file, blob).then(() => true).catch(() => false)
      if (kept && alive) onQueued()
      if (!kept) retainVoice(file, blob)
      msg = !kept ? t('voice.queue.notSaved', { message: m })
        : (e as { code?: string }).code === 'network' ? t('voice.queue.waiting') : t('voice.queue.kept', { message: m })
    } finally { mode = 'idle'; done() }
  }
  function stop() { if (rec?.state === 'recording') { mode = 'busy'; rec.stop() } }
  function cancel() { cancelled = true; if (rec?.state === 'recording') rec.stop(); mode = 'idle'; msg = t('voice.record.discarded') }
  async function picked(e: Event) {
    const input = e.currentTarget as HTMLInputElement, file = input.files?.[0]
    input.value = ''
    if (file) await finish(file)
  }
  async function retry(id: string) {
    retrying = id
    try { if (await retryVoice(id) && alive) onQueued() }
    finally { retrying = '' }
  }
  const clock = $derived(`${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`)
</script>

{#if source.canTranscribe?.() || unsavedVoice.items.some(item => item.file === file)}
  <div class="m-voice" data-mode={mode}>
    {#if source.canTranscribe?.() && mode === 'rec'}
      <span class="m-voice-time" role="status"><i aria-hidden="true"></i> {t('voice.record.clock', { clock })}</span>
      <div class="m-voice-wave" aria-label={t('voice.record.level')}><span class="m-voice-wave-bars">{#each samples as s}<i style:height={`${Math.max(8, s * 100)}%`}></i>{/each}</span></div>
      <div class="m-voice-acts"><MButton variant="pri" onclick={stop}>{t('voice.record.stop')}</MButton><MButton onclick={cancel}>{t('voice.record.discard')}</MButton></div>
    {:else if source.canTranscribe?.() && mode === 'busy'}
      <span class="m-voice-time" role="status">{t('voice.record.busy')}</span>
      <div class="m-voice-wave busy" aria-label={t('voice.record.transcribing')}><span class="m-voice-wave-bars">{#each samples as s}<i style:height={`${Math.max(8, s * 100)}%`}></i>{/each}</span></div>
    {:else if source.canTranscribe?.()}
      <div class="m-voice-acts"><MButton variant="pri" onclick={start} disabled={starting}>{t('voice.record.start')}</MButton><MButton onclick={() => picker.click()} disabled={starting}>{t('voice.record.file')}</MButton><MInfo title={t('voice.record.info')}>
        <p>{t('voice.record.upload')}</p>
        <p>{t('voice.record.retention')}</p>
      </MInfo></div>
    {/if}
    {#if msg}<MHint role="status">{msg}</MHint>{/if}
    {#each unsavedVoice.items.filter(item => item.file === file) as item (item.id)}
      <MHint tone="error" role="alert">{t('voice.unsaved')}</MHint>
      <div class="m-voice-acts"><MButton size="sm" disabled={!!retrying} onclick={() => retry(item.id)}>{t('voice.retrySave')}</MButton><MButton size="sm" disabled={!!retrying} onclick={() => discardVoice(item.id)}>{t('voice.discard')}</MButton></div>
    {/each}
  </div>
  <input bind:this={picker} type="file" accept="audio/*,video/mp4,video/webm" hidden onchange={picked} />
{/if}

<style>
  .m-voice { display: grid; gap: 8px; padding: 10px; border: 1px solid var(--wg-edge); border-radius: 10px; background: var(--wg-2); color: var(--wg-ink) }
  .m-voice[data-mode=rec] { border-color: var(--danger) }
  .m-voice-acts { display: flex; flex-wrap: wrap; gap: 8px }
  .m-voice-time { display: flex; align-items: center; gap: 7px; font: 700 12px var(--mono); font-variant-numeric: tabular-nums }
  .m-voice-time i { width: 8px; height: 8px; border-radius: 50%; background: var(--danger) }
  .m-voice-wave { height: 54px; overflow: hidden; display: flex; align-items: center; padding: 5px 8px; border-radius: 6px; background: var(--lcd); color: var(--danger) }
  .m-voice-wave-bars { width: 100%; height: 100%; display: flex; align-items: center; justify-content: flex-end; gap: 2px }
  .m-voice-wave-bars i { width: 5px; min-height: 4px; border-radius: 2px; background: currentColor }
  .m-voice-wave.busy { color: var(--sig) }
</style>
