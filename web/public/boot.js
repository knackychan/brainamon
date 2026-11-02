// The desktop startup bar. server/desktop.py inlines this file in the window's loading page (with
// window.CM_BOOT = {t0}, or {t0, error} when the backend failed), then opens index.html as
// /?boot=<t0>-<t1>, where this file runs again and keeps the bar until the first screen is drawn
// (performance mark cm-first-cards or cm-first-screen). A plain browser tab has no ?boot: nothing shows.
// Each step owns a slice of the bar, small early and wide late. Inside a step the bar eases toward CAP
// of its slice, so it never claims a milestone that has not happened; only the first screen reaches 100 %.
(function (root) {
  var STEPS = [
    { label: 'Starting backend…', end: 12, ms: 2500 },          // desktop.py boot(): the server answers
    { label: 'Opening Brainamon…', end: 28, ms: 700 },           // index.html, styles, scripts (cm-script-start)
    { label: 'Loading your library…', end: 60, ms: 900 },       // /api/items + /api/categories (cm-library-loaded)
    { label: 'Drawing the first screen…', end: 100, ms: 300 },  // cm-first-cards / cm-first-screen
  ]
  var CAP = 0.85
  var MARKS = { 'cm-script-start': 2, 'cm-library-loaded': 3 }

  // the estimate `elapsed` ms into a step: from the previous step's end toward CAP of this one's slice
  function goal(step, elapsed) {
    var lo = step ? STEPS[step - 1].end : 0
    var s = STEPS[step]
    // A long tail keeps moving during slow imports/IO instead of flattening after a few seconds.
    var age = Math.max(0, elapsed)
    return lo + (s.end - lo) * CAP * age / (age + s.ms)
  }

  function state(step, since, shown) {
    return { step: step, since: since, shown: shown, last: since, done: false, failed: false, error: '' }
  }

  function enter(s, step, now) {
    if (step > s.step && !s.done) { s.step = step; s.since = now }
  }

  // the first screen is up: the rest of the bar fills in a short ease, longer for a longer way
  function complete(s, now) {
    if (s.done) return
    s.done = { at: now, from: s.shown, ms: 200 + 5 * (100 - s.shown) }
  }

  // the shown value at `now`: chases the estimate, never backwards, never past it, at most (30 + shown) %
  // a second, so a step that ends early slides on, faster the further it is; `still` (reduced motion)
  // shows the estimate itself. A failure freezes it until the first screen.
  function advance(s, now, still) {
    var dt = Math.max(0, now - s.last)
    s.last = now
    var d = s.done
    if (d) {
      var x = still ? 1 : Math.min(1, Math.max(0, now - d.at) / d.ms)
      s.shown = Math.max(s.shown, d.from + (100 - d.from) * x * x * (3 - 2 * x))
      return s.shown
    }
    if (s.failed) return s.shown
    var target = goal(s.step, now - s.since)
    if (target > s.shown) {
      s.shown = still ? target : s.shown + Math.min((target - s.shown) * (1 - Math.exp(-dt / 160)), (30 + s.shown) * dt / 1000)
    }
    return s.shown
  }

  root.cmBootModel = { STEPS: STEPS, CAP: CAP, goal: goal, state: state, enter: enter, complete: complete, advance: advance }

  var cfg = root.CM_BOOT
  if (!cfg && typeof location !== 'undefined') {
    var q = new URLSearchParams(location.search), m = /^(\d+)-(\d+)$/.exec(q.get('boot') || '')
    if (m) {
      cfg = { t0: +m[1], t1: +m[2] }
      q.delete('boot')                  // a reload is a plain page load
      var rest = q.toString()
      history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash)
    }
  }
  if (!cfg || typeof document === 'undefined') return

  var page = !!cfg.t1                   // index.html after the hand-over, not the loading page
  var now = Date.now()
  var s = page ? state(1, cfg.t1, goal(0, cfg.t1 - cfg.t0)) : state(0, cfg.t0, goal(0, now - cfg.t0))
  s.last = now
  var still = !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches)

  var box = document.createElement('div')
  box.id = 'cm-boot'
  box.innerHTML = '<style>' +
    '#cm-boot{position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;background:#17181b;color:#e8e8e1;font:14px "Segoe UI",sans-serif;transition:opacity .2s}' +
    '#cm-boot.out{opacity:0}' +
    '#cm-boot .cmb{width:min(360px,80vw);text-align:center}' +
    '#cm-boot h1{margin:16px 0;line-height:0}' +
    '#cm-boot h1 svg{height:30px;width:auto;overflow:visible}' +
    '#cm-boot .cmb-row{display:flex;align-items:center;gap:12px;margin:32px 0 14px}' +
    '#cm-boot .cmb-bar{flex:1;height:4px;background:#383b42;border-radius:4px;overflow:hidden}' +
    '#cm-boot .cmb-bar i{display:block;height:100%;background:#ff5a1f;transform:scaleX(0);transform-origin:left}' +
    '#cm-boot .cmb-pct{min-width:4ch;text-align:right;font:600 14px Consolas,monospace;font-variant-numeric:tabular-nums}' +
    '#cm-boot .cmb-step{margin:0;min-height:1.4em;color:#b4b5ae}' +
    '#cm-boot.err .cmb-bar i{background:#a8442c}' +
    '#cm-boot.err .cmb-pct{visibility:hidden}' +
    '#cm-boot.err .cmb-step{color:#ffb39c}' +
    '#cm-boot .cmb-act{display:flex;gap:8px;justify-content:center;margin-top:18px}' +
    '#cm-boot .cmb-act[hidden]{display:none}' +
    '#cm-boot button{font:inherit;color:#e8e8e1;background:none;border:1px solid #4a4d55;border-radius:4px;padding:6px 14px;cursor:pointer}' +
    '#cm-boot button:first-child{border-color:#ff5a1f}' +
    '#cm-boot button:focus-visible{outline:2px solid #ff5a1f;outline-offset:2px}' +
    '@media (prefers-reduced-motion:reduce){#cm-boot{transition:none}}' +
    // the wordmark of design/logo (web/public/brand/wordmark-reverse.svg), in this screen's colours
    '</style><div class="cmb"><h1><svg viewBox="0 -2 486 82" role="img" aria-label="Brainamon">' +
    '<g fill="none" stroke-width="16" stroke-linecap="butt" stroke-linejoin="miter">' +
    '<path stroke="#e8e8e1" d="M8 0V80 M8 8H26L36 18V30L26 40H8 M8 40H30L40 50V62L30 72H8 M64 24V80 M64 48L80 32H92 M118 32H132L142 42V62L132 72H118L108 62V42Z M142 24V80 M166 24V80 M190 24V80 M190 44L202 32H212L222 42V80 M256 32H270L280 42V62L270 72H256L246 62V42Z M280 24V80"/>' +
    '<path stroke="#ff5a1f" d="M304 24V80 M304 44L316 32H324L334 42V80 M334 44L346 32H354L364 42V80 M398 32H412L422 42V62L412 72H398L388 62V42Z M446 24V80 M446 44L458 32H468L478 42V80"/></g>' +
    '<path fill="#e8e8e1" d="M166 -2L176 8L166 18L156 8Z"/></svg></h1>' +
    '<div class="cmb-row"><div class="cmb-bar" role="progressbar" aria-label="Starting Brainamon" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div><b class="cmb-pct">0%</b></div>' +
    '<p class="cmb-step" role="status" aria-live="polite"></p>' +
    '<div class="cmb-act" hidden><button type="button" data-a="reload">Reload</button><button type="button" data-a="go">Continue</button></div></div>'
  document.documentElement.appendChild(box)   // not in <body>: the V6 stylesheet lays out its children

  var bar = box.querySelector('.cmb-bar'), fill = bar.firstChild, pct = box.querySelector('.cmb-pct')
  var label = box.querySelector('.cmb-step'), act = box.querySelector('.cmb-act')
  var n = -1, text = '', timer = 0, raf = 0, ended = false

  function paint() {
    var v = advance(s, Date.now(), still)
    fill.style.transform = 'scaleX(' + v / 100 + ')'
    if (Math.floor(v) !== n) {
      n = Math.floor(v)
      pct.textContent = n + '%'
      bar.setAttribute('aria-valuenow', n)
    }
    var t = s.failed && !s.done ? s.error : STEPS[s.step].label
    if (t !== text) label.textContent = text = t
    if (v >= 100) finish()
  }
  function loop() { paint(); if (!ended) raf = requestAnimationFrame(loop) }
  function finish() {
    if (ended) return
    ended = true
    clearInterval(timer)
    cancelAnimationFrame(raf)
    box.style.pointerEvents = 'none'    // the app is usable while the bar fades
    if (still) box.remove()
    else { box.classList.add('out'); setTimeout(function () { box.remove() }, 220) }
  }
  function done() { complete(s, Date.now()); box.classList.remove('err'); act.hidden = true }
  function fail(message) {
    if (s.done || ended) return
    advance(s, Date.now(), still)
    s.failed = true
    s.error = message
    box.classList.add('err')
    act.hidden = !page                  // the loading page: nothing to reload, the window has the message
    paint()
  }
  root.cmBoot = { fail: fail }

  act.addEventListener('click', function (e) {
    var a = e.target.getAttribute && e.target.getAttribute('data-a')
    if (a === 'reload') location.reload()
    else if (a === 'go') { s.done = { at: 0, from: 100, ms: 1 }; paint() }
  })

  if (cfg.error) { s.shown = goal(0, now - cfg.t0); fail(cfg.error) }
  if (page) {
    // a module script or stylesheet that failed to load: the app will not come up
    root.addEventListener('error', function (e) {
      var t = e.target
      if (t && /^(SCRIPT|LINK)$/.test(t.tagName || '')) fail('Part of Brainamon did not load. Reload to try again.')
    }, true)
    setTimeout(function () {
      fail('Brainamon is taking longer than expected to load. Reload, or continue to the app.')
    }, 60000)
    var seen = function (list) {
      list.forEach(function (e) {
        if (e.name === 'cm-first-cards' || e.name === 'cm-first-screen') done()
        else if (MARKS[e.name]) enter(s, MARKS[e.name], Date.now())
      })
    }
    if (root.PerformanceObserver) new PerformanceObserver(function (l) { seen(l.getEntries()) }).observe({ type: 'mark', buffered: true })
  }
  if (still) { paint(); timer = setInterval(paint, 250) } else loop()
})(this)
