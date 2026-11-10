// Item strip (phone-dock-shell plan 07): finger distance, continuous magnification and a frozen ID list.
export const stripLimit = (position: number, count: number) => Math.max(0, Math.min(Math.max(0, count - 1), position))
export const stripPosition = (start: number, dx: number, count: number) => stripLimit(start - dx / 28, count)
export const stripIndex = (position: number, count: number) => Math.round(stripLimit(position, count))
export const stripTap = (ms: number, distance: number) => ms < 380 && distance < 6

export function stripThumb(distance: number, dragging: boolean): { w: number; h: number; x: number } {
  const d = Math.abs(distance)
  // centre offsets: half widths + 4 px gaps + the centre's 4 px (rest) or 5 px (dragging) margin (item-strip.html)
  const knots = dragging ? [[42, 58, 0], [28, 39, 44], [26, 36, 75], [24, 34, 104]] : [[36, 50, 0], [28, 39, 40], [24, 34, 70]]
  const i = Math.min(Math.floor(d), knots.length - 1), a = knots[i], b = knots[Math.min(i + 1, knots.length - 1)]
  const f = Math.min(1, d - i)
  return { w: a[0] + (b[0] - a[0]) * f, h: a[1] + (b[1] - a[1]) * f,
    x: (distance < 0 ? -1 : 1) * (a[2] + (b[2] - a[2]) * f + Math.max(0, d - (knots.length - 1)) * 28) }
}

export function stripWindow(position: number, count: number): [number, number] {
  const i = stripIndex(position, count)
  return [Math.max(0, i - 20), Math.min(count, i + 21)]
}

export function stripList(id: number, visible: number[], all: number[], previous: number[] = []): number[] {
  const have = new Set(all)
  if (!have.has(id)) return []
  const kept = previous.filter(n => have.has(n))
  return kept.includes(id) ? kept : (visible.includes(id) ? visible : all).filter(n => have.has(n))
}
