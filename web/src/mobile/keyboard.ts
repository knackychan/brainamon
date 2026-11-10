// The keyboard is up when the page lost a fifth of its tallest height at this width: the viewport resizes
// with it (interactive-widget=resizes-content in mobile.html, the app's insets). html.kb lets mobile.css fold a
// screen around the text (the dock and the item strip hide, the bare sheet drops its bottom inset). The same
// rule as Capture.svelte's, shared from projects/phone-wiskit-chat plan 01 (Capture keeps its copy until a
// follow-up). Returns the stop function.
export function watchKeyboard(onchange?: (up: boolean) => void): () => void {
  let width = 0, tallest = 0, was = false
  const fit = () => {
    if (innerWidth !== width) { width = innerWidth; tallest = 0 }
    tallest = Math.max(tallest, innerHeight)
    const up = innerHeight < tallest * 0.8
    document.documentElement.classList.toggle('kb', up)
    if (up !== was) { was = up; onchange?.(up) }
  }
  fit()
  addEventListener('resize', fit)
  return () => { removeEventListener('resize', fit); document.documentElement.classList.remove('kb') }
}
