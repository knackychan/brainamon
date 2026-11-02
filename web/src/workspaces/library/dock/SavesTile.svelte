<script lang="ts">
  // 14 Saves: items saved per day over the last 7 days (by `created`), as the V6 line chart.
  import Wg from './Wg.svelte'
  import { lib } from '../../../lib/library.svelte'

  const DAY = 24 * 3600 * 1000
  const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const days = $derived.by(() => {
    const t0 = new Date(); t0.setHours(0, 0, 0, 0)
    const start = t0.getTime() - 6 * DAY
    const v = Array(7).fill(0) as number[]
    for (const r of lib.pool) if (r.created >= start) { const i = Math.floor((r.created - start) / DAY); if (i >= 0 && i < 7) v[i]++ }
    return v.map((n, i) => ({ n, d: new Date(start + i * DAY) }))
  })
  const top = $derived(Math.max(6, Math.ceil(Math.max(...days.map(x => x.n)) / 6) * 6))
  const L = 17, R = 154, T = 6, B = 66
  const x = (i: number) => L + i * (R - L) / 6
  const y = (n: number) => B - (n / top) * (B - T)
  const pts = $derived(days.map((d, i) => `${x(i).toFixed(1)},${y(d.n).toFixed(1)}`))
  const label = $derived(`Saves per day, last 7 days: ${days.map(d => d.n).join(', ')}`)
</script>

<Wg cls="s3" id="saves" title="Saves" jp="保存 / 日" n={MON[new Date().getMonth()]}>
  <svg class="chart" id="chart" viewBox="0 0 160 84" role="img" aria-label={label}>
    {#each [0, 1, 2, 3] as g (g)}
      {@const n = top * g / 3}
      <line class="gl" x1={L} y1={y(n).toFixed(1)} x2={R} y2={y(n).toFixed(1)} /><text x={L - 7} y={(y(n) + 3).toFixed(1)} text-anchor="end">{n}</text>
    {/each}
    <path class="area" d={`M${x(0)},${B} L${pts.join(' L')} L${x(6)},${B} Z`} /><polyline class="ln" points={pts.join(' ')} />
    {#each days as d, i (i)}
      <circle cx={x(i).toFixed(1)} cy={y(d.n).toFixed(1)} r={i === 6 ? 3.6 : 2.8} class:last={i === 6}><title>{d.d.toDateString().slice(4, 10)}: {d.n} saves</title></circle>
      <text x={x(i).toFixed(1)} y="81" text-anchor="middle">{String(d.d.getDate()).padStart(2, '0')}</text>
    {/each}
  </svg>
</Wg>
