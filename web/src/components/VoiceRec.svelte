<script lang="ts">
  // Record (MediaRecorder) or pick/drop an audio file, then voiceNote() sends it to the PC.
  // The wave panel shows the level over time while recording (last WINDOW seconds, timeline
  // underneath), then the whole take with a scanning band and a progress bar while Whisper runs.
  // The server gives no progress for a transcription, so the bar eases toward 92% on the expected
  // time (roughly a fifth of the audio length plus the upload) and jumps to 100% when the answer lands.
  import { onDestroy } from 'svelte'
  import { newNote, nt, voiceNote } from '../lib/notes.svelte'
  import { toast } from '../lib/ui.svelte'
  import { pxPath, IC } from '../lib/px'
  import Hint from './ui/Hint.svelte'

  let { file = null, showNew = false, compact = false }: { file?: string | null; showNew?: boolean; compact?: boolean } = $props()
  let mode = $state<'idle' | 'rec' | 'busy'>('idle')
  let secs = $state(0)
  let rec: MediaRecorder | null = null
  let chunks: Blob[] = []
  let tick = 0
  let picker: HTMLInputElement
  let dropActive = $state(false)
  let newBusy = $state(false)

  // level history: one value (0..1) every 1000 / RATE ms, for the whole take
  const RATE = 12
  const WINDOW = 10          // seconds visible while recording
  let bars: number[] = []
  let duration = $state(0)   // seconds of audio to transcribe
  let audioCtx: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let raf = 0
  let canvas: HTMLCanvasElement | null = $state(null)
  let dataArray: Uint8Array | null = null
  let lastSample = 0
  let busyStart = 0
  let expected = 6
  let progress = $state(0)
  let busyText = $state('Uploading')

  const clock = $derived(fmt(secs))
  const pct = $derived(Math.round(progress * 100))
  function fmt(s: number) { return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` }

  // the canvas only exists once the panel renders, so start drawing then
  $effect(() => { if (mode !== 'idle' && canvas) { cancelAnimationFrame(raf); draw() } })

  // Wiskit's "Record a note" opened the Notes workspace: start straight away
  $effect(() => { if (nt.autoRecord && !file && mode === 'idle') { nt.autoRecord = false; void start() } })

  async function send(blob: Blob) {
    mode = 'busy'
    busyStart = performance.now()
    progress = 0
    busyText = 'Uploading'
    expected = Math.max(5, duration * 0.2 + blob.size / 400_000)
    try {
      await voiceNote(blob, file)
      progress = 1
      busyText = 'Done'
      await new Promise(r => setTimeout(r, 450))
    } finally {
      mode = 'idle'
      cancelAnimationFrame(raf)
      bars = []
      duration = 0
    }
  }

  async function start() {
    if (mode !== 'idle') return
    if (!navigator.mediaDevices || typeof MediaRecorder === 'undefined') {
      toast('Recording is not available here: use Audio file.', 'w')
      return
    }
    let stream: MediaStream
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) }
    catch {
      toast('The microphone is blocked. Allow it for this app, or use Audio file.', 'w')
      return
    }
    bars = []
    lastSample = 0
    try {
      audioCtx = new AudioContext()
      analyser = audioCtx.createAnalyser()
      analyser.fftSize = 1024
      sourceNode = audioCtx.createMediaStreamSource(stream)
      sourceNode.connect(analyser)
      dataArray = new Uint8Array(analyser.frequencyBinCount)
    } catch {
      // visualization is optional; keep recording without it
    }
    chunks = []
    rec = new MediaRecorder(stream)
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data) }
    rec.onstop = () => {
      clearInterval(tick)
      stream.getTracks().forEach(t => t.stop())
      duration = secs
      endMic()
      if (discard) { discard = false; bars = []; mode = 'idle'; cancelAnimationFrame(raf); return }
      send(new Blob(chunks, { type: rec?.mimeType || 'audio/webm' }))
    }
    rec.start()
    secs = 0
    tick = window.setInterval(() => secs++, 1000)
    mode = 'rec'
  }

  let discard = false
  function stop() { rec?.stop() }
  function cancel() { discard = true; rec?.stop() }

  async function picked() {
    const f = picker.files?.[0]
    picker.value = ''
    if (f) await fromFile(f)
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    dropActive = false
    const f = e.dataTransfer?.files[0]
    if (f) void fromFile(f)
  }

  // decode the file for its waveform (best effort), then send it
  async function fromFile(f: File) {
    if (mode !== 'idle') return
    bars = []
    duration = 0
    try {
      const ac = new AudioContext()
      const buf = await ac.decodeAudioData(await f.arrayBuffer())
      ac.close().catch(() => {})
      const ch = buf.getChannelData(0)
      duration = buf.duration
      const n = Math.max(1, Math.round(buf.duration * RATE))
      const per = Math.floor(ch.length / n)
      const out: number[] = []
      for (let i = 0; i < n; i++) {
        let sum = 0
        const from = i * per
        for (let j = from; j < from + per; j += 8) sum += ch[j] * ch[j]
        out.push(Math.min(1, Math.sqrt(sum / (per / 8)) * 3))
      }
      bars = out
    } catch {
      // not decodable here (some formats): a flat line is fine
    }
    await send(f)
  }

  function sample(now: number) {
    if (!analyser || !dataArray) return
    if (now - lastSample < 1000 / RATE) return
    lastSample = now
    analyser.getByteTimeDomainData(dataArray as any)
    let sum = 0
    for (let i = 0; i < dataArray.length; i++) { const v = (dataArray[i] - 128) / 128; sum += v * v }
    bars.push(Math.min(1, Math.sqrt(sum / dataArray.length) * 3))
  }

  function draw() {
    if (!canvas || mode === 'idle') return
    raf = requestAnimationFrame(draw)
    const now = performance.now()
    if (mode === 'rec') sample(now)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    const cw = canvas.clientWidth, chh = canvas.clientHeight
    if (canvas.width !== cw * dpr || canvas.height !== chh * dpr) { canvas.width = cw * dpr; canvas.height = chh * dpr }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    const cs = getComputedStyle(canvas)
    const ink = cs.getPropertyValue('--lcd-ink').trim() || '#ecebe2'
    const dim = cs.getPropertyValue('--lcd-dim').trim() || '#8d939a'
    const line = cs.getPropertyValue('--lcd-line').trim() || 'rgba(255,255,255,.2)'
    const accent = cs.getPropertyValue('--accent').trim() || '#ff5a1f'
    const sig = cs.getPropertyValue('--sig').trim() || '#ffd34d'
    const pad = 10, axisH = 18
    const w = cw - pad * 2, h = chh - axisH - pad
    const mid = pad + h / 2
    ctx.clearRect(0, 0, cw, chh)

    // grid: midline + faint horizontal rules
    ctx.strokeStyle = line
    ctx.lineWidth = 1
    ctx.setLineDash([2, 4])
    ctx.beginPath(); ctx.moveTo(pad, mid); ctx.lineTo(pad + w, mid); ctx.stroke()
    ctx.setLineDash([])

    // what is in view: the last WINDOW s while recording, the whole take while transcribing
    const total = bars.length / RATE
    let t0: number, span: number
    if (mode === 'rec') { span = WINDOW; t0 = Math.max(0, total - WINDOW) }
    else { span = Math.max(1, duration || total); t0 = 0 }
    const pxPerSec = w / span
    const barW = Math.max(1.5, Math.min(4, pxPerSec / RATE - 1))

    // timeline ticks
    const step = span <= 15 ? 1 : span <= 60 ? 5 : span <= 300 ? 30 : 60
    const label = span <= 15 ? 5 : step
    ctx.font = `500 9px ${cs.getPropertyValue('--mono') || 'monospace'}`
    ctx.fillStyle = dim
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    const y0 = pad + h + 4
    for (let s = Math.ceil(t0 / step) * step; s <= t0 + span + 1e-6; s += step) {
      const x = pad + (s - t0) * pxPerSec
      if (x > pad + w + 1) break
      const major = s % label === 0
      ctx.fillStyle = major ? dim : line
      ctx.fillRect(Math.round(x), y0 - 2, 1, major ? 4 : 2)
      if (major) { ctx.fillStyle = dim; ctx.fillText(fmt(s), x, y0 + 4) }
    }

    // bars
    const progX = pad + w * progress
    for (let i = Math.floor(t0 * RATE); i < bars.length; i++) {
      const x = pad + (i / RATE - t0) * pxPerSec
      if (x > pad + w) break
      const amp = Math.max(1, bars[i] * (h / 2 - 2))
      ctx.fillStyle = mode === 'busy' ? (x <= progX ? accent : ink) : accent
      ctx.fillRect(x, mid - amp, barW, amp * 2)
    }

    if (mode === 'rec') {
      // live head
      const x = pad + (total - t0) * pxPerSec
      ctx.fillStyle = ink
      ctx.fillRect(Math.min(x, pad + w) - 1, pad, 2, h)
    } else {
      // scanning band: a soft sweep that keeps moving, plus the eased progress estimate
      const el = (now - busyStart) / 1000
      if (progress < 0.92) progress = Math.min(0.92, 1 - Math.exp(-el / expected))
      if (busyText !== 'Done') busyText = el < 1.2 ? 'Uploading' : 'Transcribing'
      const sweepW = Math.max(24, w * 0.12)
      const sx = pad + ((el * 90) % (w + sweepW)) - sweepW
      const g = ctx.createLinearGradient(sx, 0, sx + sweepW, 0)
      g.addColorStop(0, 'rgba(0,0,0,0)')
      g.addColorStop(0.5, sig)
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.globalAlpha = 0.35
      ctx.fillStyle = g
      ctx.fillRect(Math.max(pad, sx), pad, Math.min(sweepW, pad + w - sx), h)
      ctx.globalAlpha = 1
      ctx.fillStyle = sig
      ctx.fillRect(progX - 1, pad, 2, h)
    }
  }

  function endMic() {
    dataArray = null
    analyser = null
    sourceNode = null
    audioCtx?.close().catch(() => {})
    audioCtx = null
  }

  async function makeNote() {
    if (newBusy) return
    newBusy = true
    const d = new Date(), p = (n: number) => String(n).padStart(2, '0')
    try { await newNote(`Note ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`) }
    catch (e) { toast((e as Error).message, 'w') }
    finally { newBusy = false }
  }

  onDestroy(() => {
    clearInterval(tick)
    rec?.stop()
    cancelAnimationFrame(raf)
    endMic()
  })
</script>

<div class="voice-control">
<div class="voice-rec" class:open={mode !== 'idle'} class:compact data-mode={mode}>
  {#if mode === 'idle'}
    {#if showNew}
      <button class="vrec-btn nn" type="button" disabled={newBusy} onclick={makeNote}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M12 12v6M9 15h6" /></svg>
        <span>New note</span>
      </button>
    {/if}
    <button class="vrec-btn rec" type="button" onclick={start}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" /></svg>
      <span>Record</span>
    </button>
    <button
      class="vrec-btn file"
      class:drop-active={dropActive}
      type="button"
      onclick={() => picker.click()}
      ondragover={(e: DragEvent) => { e.preventDefault(); dropActive = true }}
      ondragleave={() => dropActive = false}
      ondrop={onDrop}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V3M7 8l5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></svg>
      <span>{compact ? 'Audio file' : ''}{#if !compact}Audio file<br />or drop here{/if}</span>
    </button>
  {:else}
    {#if mode === 'rec'}
      <div class="vrec-col">
        <button class="vrec-btn stop" type="button" aria-pressed="true" aria-label="Stop recording and transcribe" onclick={stop}>
          <svg class="px" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(IC.stop)} /></svg>
          <span class="vrec-time"><i class="dot" aria-hidden="true"></i>{clock}</span>
        </button>
        <button class="vrec-cancel" type="button" onclick={cancel}>Cancel</button>
      </div>
    {:else}
      <div class="vrec-btn busy" role="status" aria-live="polite">
        <svg class="px spin" viewBox="0 0 8 8" aria-hidden="true"><path fill="currentColor" d={pxPath(IC.gear)} /></svg>
        <span class="vrec-time">{pct}%</span>
        <span class="vrec-sub">{busyText}…</span>
      </div>
    {/if}
    <div class="vrec-panel">
      <div class="vrec-head">
        <span class="lbl">{mode === 'rec' ? 'REC' : 'WHISPER'}</span>
        <span class="sp"></span>
        <span class="val">{mode === 'rec' ? `last ${WINDOW}s` : fmt(duration)}</span>
      </div>
      <canvas bind:this={canvas} class="vrec-wave" aria-label={mode === 'rec' ? 'Microphone level over time' : 'Recorded audio being transcribed'}></canvas>
      {#if mode === 'busy'}
        <div class="vrec-prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct} aria-label="Transcription">
          <i style:width="{pct}%"></i>
        </div>
      {/if}
    </div>
  {/if}
</div>
<Hint>Record or choose audio to send it to OpenAI for transcription through this PC's configured endpoint. Provider charges apply separately; its terms and retention apply.</Hint>
<input bind:this={picker} type="file" accept="audio/*,video/mp4,video/webm" hidden onchange={picked} />
</div>

<style>
  .voice-control { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; max-width: 48ch }
  .voice-control :global(.hint) { margin: 0; text-align: left }
  .voice-rec { display: inline-flex; align-items: stretch; justify-content: center; gap: 10px; max-width: 100%; }
  .vrec-btn {
    width: 116px; height: 104px; box-sizing: border-box; flex: none;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
    padding: 0 10px; border: 1.5px solid var(--rw-ink); border-radius: 14px;
    background: var(--rw); color: var(--rw-ink);
    font: 600 10.5px/1.3 var(--mono); letter-spacing: .08em; text-transform: uppercase; text-align: center;
    cursor: pointer; user-select: none;
    transition: background .12s, border-color .12s, transform .08s;
  }
  .vrec-btn:hover:not(:disabled) { background: var(--rw-2); }
  .vrec-btn:active:not(:disabled) { transform: translateY(1px); }
  .vrec-btn:focus-visible { outline: 2px solid var(--sig); outline-offset: 3px; }
  .vrec-btn:disabled { opacity: .5; cursor: default; }
  .vrec-btn svg { width: 26px; height: 26px; }
  .vrec-btn.nn svg { color: var(--sig); }
  .vrec-btn.rec svg { color: var(--danger); }
  .vrec-btn.file { border-style: dashed; }
  .vrec-btn.file svg { color: var(--accent, #ff5a1f); }
  .vrec-btn.file.drop-active { background: var(--sig); color: var(--sig-ink); border-color: var(--sig-ink); border-style: solid; }
  .vrec-btn.file.drop-active svg { color: inherit; }
  .vrec-btn.stop { background: var(--danger); color: #fff; border-color: var(--danger); }
  .vrec-btn.stop:hover { background: #b52b20; border-color: #b52b20; }
  .vrec-btn.busy { background: var(--lcd); color: var(--lcd-ink); cursor: default; gap: 6px; height: 136px; }
  .vrec-btn span { display: block; }
  .vrec-col { display: flex; flex-direction: column; gap: 6px; }
  .vrec-col .vrec-btn.stop { flex: 1; height: auto; }
  .vrec-cancel { border: 0; border-radius: 999px; padding: 5px 0; background: transparent; color: var(--rw-dim); font: 600 11px var(--display); cursor: pointer; }
  .vrec-cancel:hover { background: var(--rw-2); color: var(--rw-ink); }
  .vrec-time { display: inline-flex; align-items: center; gap: 8px; font: 700 20px/1 var(--mono); letter-spacing: .02em; font-variant-numeric: tabular-nums; }
  .vrec-sub { font: var(--type-chip); letter-spacing: .1em; color: var(--lcd-dim); }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #fff; animation: blink 1s steps(2, start) infinite; }
  .spin { animation: spin 1.6s steps(8) infinite; }

  .vrec-panel {
    width: min(420px, 100%); min-width: 0; height: 136px; box-sizing: border-box; flex: 1 1 320px;
    display: flex; flex-direction: column;
    border: 1.5px solid var(--rw-ink); border-radius: 14px;
    background: var(--lcd); color: var(--lcd-ink); overflow: hidden;
  }
  .vrec-head { display: flex; align-items: center; gap: 8px; padding: 6px 12px 0; font: 700 9.5px/1 var(--mono); letter-spacing: .12em; color: var(--lcd-dim); }
  .vrec-head .lbl { color: var(--danger); }
  [data-mode=busy] .vrec-head .lbl { color: var(--sig); }
  .vrec-head .sp { flex: 1; }
  .vrec-head .val { font-variant-numeric: tabular-nums; }
  .vrec-wave { flex: 1; min-height: 0; width: 100%; display: block; }
  .vrec-prog { height: 6px; margin: 0 10px 8px; border: 1px solid var(--lcd-line); border-radius: 999px; background: var(--lcd-2); overflow: hidden; }
  .vrec-prog i {
    display: block; height: 100%; background: var(--sig);
    background-image: repeating-linear-gradient(135deg, transparent 0 4px, rgba(0,0,0,.18) 4px 8px);
    background-size: 24px 24px; animation: march .6s linear infinite;
    transition: width .25s linear;
  }
  /* compact: in a note's header, pills like Summarize / Reformat */
  .compact { gap: 3px; align-items: center; }
  .compact .vrec-btn {
    width: auto; height: auto; flex-direction: row; gap: 6px; padding: 7px 10px;
    border: 0; border-radius: 999px; background: transparent; color: var(--np-dim, var(--rw-dim));
    font: var(--type-tool); letter-spacing: 0; text-transform: none;
  }
  .compact .vrec-btn:hover:not(:disabled) { transform: none; background: var(--np-tint, var(--rw-2)); color: var(--np-ink, var(--rw-ink)); }
  .compact .vrec-btn:active:not(:disabled) { transform: none; }
  .compact .vrec-btn svg { width: 14px; height: 14px; }
  .compact .vrec-btn.rec svg { color: var(--danger); }
  .compact .vrec-btn.file svg { color: var(--accent, #ff5a1f); }
  .compact .vrec-btn.file.drop-active { background: var(--sig); color: var(--sig-ink); }
  .compact .vrec-btn.stop { background: var(--danger); color: #fff; }
  .compact .vrec-col { flex-direction: row; align-items: center; gap: 2px; }
  .compact .vrec-cancel { padding: 5px 8px; }
  .compact .vrec-btn.stop:hover { background: #b52b20; color: #fff; }
  .compact .vrec-btn.busy { height: auto; background: var(--np-tint, var(--rw-2)); color: var(--np-ink, var(--rw-ink)); }
  .compact .vrec-time { font-size: 12px; gap: 6px; }
  .compact .vrec-sub { display: none; }
  .compact .dot { width: 7px; height: 7px; }
  .compact .vrec-panel { width: 220px; flex: none; height: 34px; border-radius: 10px; }
  .compact .vrec-head { display: none; }
  .compact .vrec-prog { height: 3px; margin: 0 6px 4px; }
  @keyframes blink { to { opacity: 0 } }
  @keyframes spin { to { transform: rotate(360deg) } }
  @keyframes march { to { background-position: 24px 0 } }
  @media (prefers-reduced-motion: reduce) { .dot, .spin, .vrec-prog i { animation: none } }
</style>
