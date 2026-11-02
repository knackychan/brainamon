<script lang="ts">
  import { onMount } from 'svelte'
  import { rest } from '../lib/rest'

  let { pose = 'idle', motionOff = false, id }: {
    pose?: string; motionOff?: boolean; id?: string
  } = $props()
  type Index = { cell: [number, number]; states: Record<string, { row: number; frames: number; fps: number }> }
  let cv: HTMLCanvasElement | undefined = $state()
  let sheet: { index: Index; image: HTMLCanvasElement } | null = $state.raw(null)
  let reduced = $state(false)

  onMount(() => {
    let alive = true
    const media = matchMedia('(prefers-reduced-motion: reduce)')
    const change = () => { reduced = media.matches }
    change(); media.addEventListener('change', change)
    Promise.all([fetch('/wiskit/sheet.json').then(r => { if (!r.ok) throw new Error('Wiskit sheet unavailable'); return r.json() }),
      new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = '/wiskit/sheet.png'
      })]).then(([index, image]) => {
        if (!alive) return
        const off = document.createElement('canvas'); off.width = image.width; off.height = image.height
        const ctx = off.getContext('2d')!
        ctx.drawImage(image, 0, 0)
        const pixels = ctx.getImageData(0, 0, off.width, off.height), d = pixels.data
        for (let i = 0; i < d.length; i += 4) if (d[i] === 255 && d[i + 1] === 0 && d[i + 2] === 255) d[i + 3] = 0
        ctx.putImageData(pixels, 0, 0)
        sheet = { index, image: off }
      }).catch(() => { /* Assistant controls remain usable without the decoration. */ })
    return () => { alive = false; media.removeEventListener('change', change) }
  })

  $effect(() => {
    const s = sheet, canvas = cv
    if (!s || !canvas) return
    const state = s.index.states[pose] ?? s.index.states.idle, [w, h] = s.index.cell
    canvas.width = w; canvas.height = h
    const ctx = canvas.getContext('2d')!
    ctx.imageSmoothingEnabled = false
    let frame = 0
    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      ctx.drawImage(s.image, (frame++ % state.frames) * w, state.row * h, w, h, 0, 0, w, h)
    }
    draw()
    if (motionOff || reduced) return
    const timer = window.setInterval(() => { if (!document.hidden && !rest.on) draw() }, 1000 / state.fps)
    return () => clearInterval(timer)
  })
</script>

<canvas bind:this={cv} {id} width={96} height={56} aria-hidden="true"></canvas>

<style>
  canvas { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated }
</style>
