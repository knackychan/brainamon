<script lang="ts">
  // COUNT (motion language): a number that ticks to its new value (motion.ts Tween) and lifts 3 px each time the
  // number shown changes. `jump`: any value that changes when the number means something else (another filter,
  // another job, the library loaded); the new number then shows at once. `from`: the number shown first (the
  // count before an import); without it the first value shows as it is. At rest this is one plain element with
  // the formatted number (tests/test_motion_blocks.py), so a screen keeps its markup and its CSS.
  import { untrack } from 'svelte'
  import type { HTMLAttributes } from 'svelte/elements'
  import { Tween } from './motion.ts'

  let { value, fmt = String, as = 'span', jump, from, ...rest }:
    { value: number; fmt?: (n: number) => string; as?: string; jump?: unknown; from?: number } & HTMLAttributes<HTMLElement> = $props()
  let shown = $state(untrack(() => from ?? value))
  let lift = $state(0)
  const tween = new Tween(untrack(() => from ?? value), (v, l) => { shown = v; lift = l })
  let seen = untrack(() => jump)
  $effect(() => {
    const target = value, j = jump
    const jumped = j !== seen
    seen = j
    untrack(() => tween.to(target, jumped))
  })
  $effect(() => () => tween.stop())
</script>

<svelte:element this={as} {...rest} style:position={lift ? 'relative' : undefined} style:top={lift ? `${(-lift).toFixed(2)}px` : undefined}>{fmt(shown)}</svelte:element>
