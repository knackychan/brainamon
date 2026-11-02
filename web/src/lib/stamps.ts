// The 20 line stamps of the My Notes format (projects/note-organic-ui/plans/01-note-format-agents.md,
// STAMPS names), copied verbatim from mockup-v2-build/organic.js. SVG markup comes only from this
// static map; note data never supplies SVG or HTML. Shared by the desktop and phone editors and the
// phone's note list, so the drawings exist once.
const petals = [0, 72, 144, 216, 288].map(a => `<ellipse cx="24" cy="10.5" rx="4.6" ry="6.4" transform="rotate(${a} 24 18)"/>`).join('')
const rays = [0, 45, 90, 135, 180, 225, 270, 315].map((a, i) => `<path d="M24 ${i % 2 ? 9.5 : 7.5}V${i % 2 ? 13 : 12.5}" transform="rotate(${a} 24 24)"/>`).join('')

export const STAMP_DRAWINGS: Record<string, string> = {
  flower: `${petals}<circle cx="24" cy="18" r="3.4"/><path d="M24 25c-.8 6 1 11.5-.4 18"/><path d="M23.8 35c4-3.6 7.6-4 10-3-1.6 3.6-5.6 4.8-10 3"/>`,
  sun: `<circle cx="24" cy="24" r="7.5"/>${rays}`,
  star: `<path d="M24 8.5 28.2 19.2 39.4 20 30.8 27.3 33.6 38.2 24 32.2 14.4 38.2 17.2 27.3 8.6 20 19.8 19.2Z"/>`,
  heart: `<path d="M24 39.5C11 31 8.5 23 11.2 17c2.8-6 9.8-5.4 12.8.6 3-6 10-6.6 12.8-.6C39.5 23 37 31 24 39.5Z"/>`,
  check: `<path d="M24 8.5c8.8-.2 15.6 6.6 15.5 15.6 0 8.6-7 15.4-15.6 15.4C15.2 39.6 8.4 32.8 8.5 24 8.6 16 14 9.6 21.6 8.7"/><path d="m16.5 24.5 5.5 5.8 10-12"/>`,
  arrow: `<path d="M8 33c6-9.6 15-14 29.5-11"/><path d="M30.5 15.5 38 22l-7.6 6"/>`,
  sprout: `<path d="M24 42V25"/><path d="M24 29c-7.4.2-12.6-5-12.8-12.2 7.2 0 12.6 4.6 12.8 12.2Z"/><path d="M24 25c-.2-8.4 5-14 13-14.2.3 8-5.2 13.6-13 14.2Z"/>`,
  mushroom: `<path d="M8 26.5C8 15 15.4 8.5 24 8.5S40 15 40 26.5Z"/><path d="M18.4 26.5c-1.2 6.6-1 11.6.8 14h9.6c1.8-2.4 2-7.4.8-14"/><circle class="f" cx="17" cy="18" r="2.4"/><circle class="f" cx="29.5" cy="15.5" r="2.4"/><circle class="f" cx="25" cy="22" r="1.7"/>`,
  cloud: `<path d="M14.5 34.5c-6 .2-8.4-6.2-4.2-9.4-.8-6 6-9.4 10-6.2 2-6.4 11-7.4 13.8-1 6-1 9.4 4.6 6.4 9 3.4 4 .4 7.8-4.4 7.6Z"/>`,
  bolt: `<path d="M27.5 6 14 27h9.2L19.5 42 34.5 20h-9.2Z"/>`,
  coffee: `<path d="M11.5 20.5h22.5l-2 17c-.2 2-1.8 3.5-3.8 3.5H17.3c-2 0-3.6-1.5-3.8-3.5Z"/><path d="M33.6 24.5c6.4-1.4 8 6.4.6 8.6"/><path d="M19 15.5c-2.4-3 1.8-4.8-.4-8M26.5 15.5c-2.4-3 1.8-4.8-.4-8"/>`,
  bulb: `<path d="M24 7c-7.6 0-12 5.6-12 11.8 0 5.8 4.8 8.6 5.8 14.2h12.4c1-5.6 5.8-8.4 5.8-14.2C36 12.6 31.6 7 24 7Z"/><path d="M19 37h10M20.5 41h7"/><path d="m20.5 26 3.5-4.5 3.5 4.5"/>`,
  kettlebell: `<path d="M16.4 23C14.6 17.4 14.4 11.6 17.2 9.6c1-.7 12.6-.7 13.6 0 2.8 2 2.6 7.8.8 13.4"/><path d="M20.4 20.8c-.9-3-.9-5.6.4-6.6.6-.4 5.8-.4 6.4 0 1.3 1 1.3 3.6.4 6.6"/><path d="M15.6 40C11 36.6 10.6 28.6 14.8 24c4.2-4.6 14.2-4.6 18.4 0 4.2 4.6 3.8 12.6-.8 16Z"/>`,
  pin: `<circle cx="24" cy="15" r="7.4"/><path d="M24 22.4V41.5"/><path d="M20.6 12.4c.8-1.2 2-1.8 3.2-1.8"/>`,
  note: `<path d="M10.5 10.5h27c1.6 0 2.5.9 2.5 2.5v17.6c0 1.6-.9 2.5-2.5 2.5H22.4l-8 7 .8-7h-4.7c-1.6 0-2.5-.9-2.5-2.5V13c0-1.6.9-2.5 2.5-2.5Z"/><path d="M24 16v8.5"/><circle class="f" cx="24" cy="28.6" r="1.4"/>`,
  question: `<path d="M17 16.5c0-5.4 3.8-8.5 7.6-8.5 4.6 0 7.8 3 7.8 7 0 6.4-8.4 7.2-8.4 14"/><circle class="f" cx="24" cy="37.5" r="1.8"/>`,
  snail: `<path d="M26 27c0-2.6 3.8-2.6 3.8 0 0 3.6-6.6 4.2-7.4-.4-.8-5.4 6.8-8 10.4-4 4.4 4.8 1.6 12-6 12.6-8.4.6-12.4-6.6-10.6-12.6"/><path d="M6.5 38.5h32c3 0 4-2.8 1.4-3.8"/><path d="M8.5 38.5c-2.4-3.8-1.4-8.4 1.8-8.4"/><path d="M9.6 30.4 7.4 24.6M12 30.6l2-5.6"/>`,
  sparkle: `<path d="M22 8c.6 9 4.6 13.4 14 14.2-9.4.8-13.4 5-14 14.4-.6-9.4-4.6-13.6-14-14.4C17.4 21.4 21.4 17 22 8Z"/><path d="M37 7v7M33.5 10.5h7"/>`,
  flag: `<path d="M14 42V7.5"/><path d="M14 9c6-3.4 12 4 20-.6v16.4c-8 4.4-14-3-20 .6"/>`,
  smile: `<path d="M24 8.6c8.8 0 15.4 6.6 15.4 15.4S32.8 39.4 24 39.4 8.6 32.8 8.6 24c0-7.6 5-13.6 12.2-15"/><circle class="f" cx="19" cy="20.5" r="1.7"/><circle class="f" cx="29" cy="20.5" r="1.7"/><path d="M17.5 28c3.4 4.4 9.6 4.4 13 0"/>`,
}

export const stampSVG = (k: string) => `<svg viewBox="0 0 48 48" aria-hidden="true">${STAMP_DRAWINGS[k] || ''}</svg>`
