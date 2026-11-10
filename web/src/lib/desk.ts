// The Wiskit desk's dithered ripple field (#field), ported from archive/2026-11-09/design/web-look/os.js `dither`
// and the V4 template's `drawField`. Static: drawn on start, resize, theme change and when fonts
// load, never animated, so it costs nothing per frame.
const BAYER = [0, 32, 8, 40, 2, 34, 10, 42, 48, 16, 56, 24, 50, 18, 58, 26, 12, 44, 4, 36, 14, 46, 6, 38, 60, 28, 52, 20, 62, 30, 54, 22, 3, 35, 11, 43, 1, 33, 9, 41, 51, 19, 59, 27, 49, 17, 57, 25, 15, 47, 7, 39, 13, 45, 5, 37, 63, 31, 55, 23, 61, 29, 53, 21]

type Ink = number[]   // r, g, b, a (0..255)

function dither(cv: HTMLCanvasElement, px: number, fn: (x: number, y: number) => number, ink: Ink) {
  const w = Math.max(1, Math.ceil(cv.clientWidth / px)), h = Math.max(1, Math.ceil(cv.clientHeight / px))
  cv.width = w
  cv.height = h
  const ctx = cv.getContext('2d')
  if (!ctx) return
  const img = ctx.createImageData(w, h), d = img.data
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const r = fn(x, y)
    if (!(r > 0)) continue
    if (r > (BAYER[(y & 7) * 8 + (x & 7)] + 0.5) / 64) {
      const i = (y * w + x) * 4
      d[i] = ink[0]; d[i + 1] = ink[1]; d[i + 2] = ink[2]; d[i + 3] = ink[3] === undefined ? 255 : ink[3]
    }
  }
  ctx.putImageData(img, 0, 0)
}

// The ripple spreads from Wiskit's pet screen (#pet); off screen (drawer closed) it sits top right.
export function drawField() {
  const cv = document.getElementById('field') as HTMLCanvasElement | null
  if (!cv) return
  const pet = document.getElementById('pet')
  const o = pet?.getBoundingClientRect()
  const px = 4
  const vis = !!o && o.width > 0 && o.left < innerWidth && o.right > 0 && o.top < innerHeight
  const ink = getComputedStyle(document.documentElement).getPropertyValue('--field').split(',').map(Number)
  const ox = (vis ? o!.left + o!.width / 2 : innerWidth - 80) / px
  const oy = (vis ? o!.top + o!.height * 0.62 : 110) / px
  dither(cv, px, (x, y) => {
    const dx = x - ox, dy = y - oy, d = Math.hypot(dx, dy) * px, a = Math.atan2(dy, dx)
    const dd = d + 16 * Math.sin(a * 6 + d * 0.011) + 9 * Math.sin(a * 11 - d * 0.019)
    const ring = Math.pow(Math.max(0, Math.cos(dd * Math.PI * 2 / 46)), 5)
    return ring * Math.max(0, 1 - d / 1500) * 0.95
  }, ink)
}

// Redraw after resize, theme change (data-theme or the OS scheme) and font load; debounced 120 ms.
export function startField() {
  let t = 0
  const go = () => { clearTimeout(t); t = window.setTimeout(drawField, 120) }
  addEventListener('resize', go)
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', go)
  new MutationObserver(go).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  document.fonts?.ready.then(go)
  go()
}
