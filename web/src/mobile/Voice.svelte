<script lang="ts">
  // The record button of a My Note on the phone: record -> Whisper -> onText(text). Without signal the
  // recording is queued (voice.ts) and turned into text later (Notes.svelte flushes the queue).
  import { appendVoice, enqueue, MAX_BYTES } from './voice'
  import { source } from './state.svelte'
  import { onDestroy, onMount } from 'svelte'
  import MButton from './ui/MButton.svelte'
  import MHint from './ui/MHint.svelte'

  let { file, onText, onQueued }: { file: string; onText: (text: string) => void; onQueued: () => void } = $props()
  let mode = $state<'idle' | 'rec' | 'busy'>('idle')
  let secs = $state(0), msg = $state('')
  let rec: MediaRecorder | null = null
  let chunks: Blob[] = []
  let tick = 0
  let cancelled = false
  let alive = true
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
    msg = ''
    if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') { msg = 'This browser cannot record. Use the Brainamon app.'; return }
    let stream: MediaStream
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
    catch { msg = 'Microphone not allowed. Allow it in the phone settings for Brainamon.'; return }
    if (!alive) { stream.getTracks().forEach(t => t.stop()); return }
    chunks = []
    cancelled = false
    try { rec = new MediaRecorder(stream) }
    catch (e) { stream.getTracks().forEach(t => t.stop()); msg = `Recording could not start: ${(e as Error).message}`; return }
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    rec.onstop = () => {
      clearInterval(tick)
      stopMeter()
      stream.getTracks().forEach(t => t.stop())
      if (!cancelled) void finish(new Blob(chunks, { type: rec?.mimeType || 'audio/webm' }))
    }
    rec.start()
    samples = []
    startMeter(stream)
    secs = 0
    tick = window.setInterval(() => secs++, 1000)
    mode = 'rec'
  }
  async function finish(blob: Blob) {
    mode = 'busy'
    try {
      if (blob.size > MAX_BYTES) { msg = 'Too long for one go: record in parts.'; return }
      if (navigator.onLine === false) { await enqueue(file, blob); if (alive) onQueued(); msg = 'Saved on this phone. It becomes text when you are online.'; return }
      const text = await source.transcribe!(blob)
      if (text && alive) onText(text)
      else if (text) {
        try {
          const n = await source.myNote(file)
          await source.saveMyNote(n.file, n.title, n.category, appendVoice(n.body ?? '', text))
        } catch { await enqueue(file, blob) }
      } else msg = 'No speech was heard.'
    } catch (e) {
      const m = (e as Error).message
      const kept = await enqueue(file, blob).then(() => true).catch(() => false)
      if (kept && alive) onQueued()
      msg = !kept ? `${m} Recording could not be saved on this phone.`
        : /^No signal|could not be reached/.test(m) ? 'Saved on this phone. It becomes text when you are online.' : `${m} Recording kept on this phone.`
    } finally { mode = 'idle' }
  }
  function stop() { if (rec?.state === 'recording') { mode = 'busy'; rec.stop() } }
  function cancel() { cancelled = true; if (rec?.state === 'recording') rec.stop(); mode = 'idle'; msg = 'Recording discarded.' }
  async function picked(e: Event) {
    const input = e.currentTarget as HTMLInputElement, file = input.files?.[0]
    input.value = ''
    if (file) await finish(file)
  }
  const clock = $derived(`${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`)
</script>

{#if source.canTranscribe?.()}
  <div class="m-voice" data-mode={mode}>
    <MHint>Recording or choosing audio uploads it to OpenAI for transcription, through the PC in direct-PC mode. Provider charges apply separately; its terms and retention apply. Offline recordings may wait here and upload when connected.</MHint>
    {#if mode === 'rec'}
      <span class="m-voice-time" role="status"><i aria-hidden="true"></i> Recording {clock}</span>
      <div class="m-voice-wave" aria-label="Microphone level"><span class="m-voice-wave-bars">{#each samples as s}<i style:height={`${Math.max(8, s * 100)}%`}></i>{/each}</span></div>
      <div class="m-voice-acts"><MButton variant="pri" onclick={stop}>Stop and transcribe</MButton><MButton onclick={cancel}>Discard</MButton></div>
    {:else if mode === 'busy'}
      <span class="m-voice-time" role="status">Transcribing audio…</span>
      <div class="m-voice-wave busy" aria-label="Transcribing"><span class="m-voice-wave-bars">{#each samples as s}<i style:height={`${Math.max(8, s * 100)}%`}></i>{/each}</span></div>
    {:else}
      <div class="m-voice-acts"><MButton variant="pri" onclick={start}>Record</MButton><MButton onclick={() => picker.click()}>Audio file</MButton></div>
    {/if}
    {#if msg}<MHint role="status">{msg}</MHint>{/if}
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
