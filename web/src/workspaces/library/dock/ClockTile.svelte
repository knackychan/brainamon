<script lang="ts">
  // 01 Time: local clock (V6 clockTile + startClock, but local time instead of Tokyo).
  import { ui } from '../../../lib/ui.svelte'
  import { onRest, rest } from '../../../lib/rest'
  const DOW = ['日', '月', '火', '水', '木', '金', '土']
  const p = (v: number) => String(v).padStart(2, '0')
  const now = () => new Date()
  let t = $state(now())
  // Resting (lib/rest.ts, plan 10-footprint B4): the colon stays solid and the time changes once a
  // minute, on the minute, so nothing redraws every second while nobody looks.
  let resting = $state(rest.on)
  $effect(() => {
    let i = 0, w = 0
    const tick = () => (t = now())
    const start = (on: boolean) => {
      clearInterval(i); clearTimeout(w)
      const d = now()
      t = d
      resting = on
      if (!on) { i = setInterval(tick, 1000); return }
      w = setTimeout(() => { tick(); i = setInterval(tick, 60_000) }, 60_000 - d.getSeconds() * 1000 - d.getMilliseconds())
    }
    start(rest.on)
    const off = onRest(start)
    return () => { clearInterval(i); clearTimeout(w); off() }
  })
</script>

<section class="wg k s3" aria-label="Local time">
  <header class="wg-hd"><h2>Time</h2><span class="n">LOCAL</span><span class="jp" aria-hidden="true">現地</span></header>
  <p class="clk-t dotn"><span class="c-h">{p(t.getHours())}</span><i class="c-c" class:off={!ui.motionOff && !resting && t.getSeconds() % 2 === 1}>:</i><span class="c-m">{p(t.getMinutes())}</span></p>
  <p class="clk-row"><span class="jp c-w" aria-hidden="true">{DOW[t.getDay()]}曜日</span><span class="c-d">{t.getFullYear()}.{p(t.getMonth() + 1)}.{p(t.getDate())}</span></p>
</section>
