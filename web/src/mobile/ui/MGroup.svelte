<script lang="ts">
  // A settings row (projects/phone-settings, spec section 2.3; .m-group in settings.css). Three kinds:
  // - a group (children): the row opens its panel in place, one open at a time per page (groups.svelte.ts); the
  //   tapped row stays under the finger when a group above closes; the panel stays mounted while closed (hidden),
  //   so typed text and ids inside it survive; `onclose` resets a pending "Sure?" when the group closes;
  // - a page row (`href`): a link to another page, with a right chevron;
  // - a plain row (`action`): the name, the state line and one key, nothing opens.
  // The box keeps the MBox wrapper and the `id` the links and checks use. The (i) (`info`) sits beside the row
  // button, never inside it, and shows while the group is open. `title` is a static string at every call site.
  // shortcut: legacy accordion serves the separate redesign preview; remove after that preview migrates.
  import { onMount, tick, untrack, type Snippet } from 'svelte'
  import MBox from './MBox.svelte'
  import MInfo from './MInfo.svelte'
  import ShellIcon from '../ShellIcon.svelte'
  import MBadge from './MBadge.svelte'
  import type { Kind } from '../settings-steps'
  import type { ShellGlyph } from '../tabicons'
  import { getGroups, OPEN_GROUP } from './groups.svelte'

  type Tone = 'done' | 'todo' | 'next' | 'busy'
  let { title, line = '', tone, kind, glyph, letter, id, href, info, infoTitle = '', action, onclose, children }: {
    title: string; line?: string; tone?: Tone; kind?: Kind; glyph?: ShellGlyph; letter?: string; id?: string; href?: string; info?: Snippet; infoTitle?: string
    action?: Snippet; onclose?: () => void; children?: Snippet
  } = $props()
  const groups = getGroups()
  const panelId = $props.id()
  const open = $derived(!!groups && groups.open === title)
  let box: HTMLElement | undefined = $state()
  let row: HTMLButtonElement | undefined = $state()
  let panel: HTMLDivElement | undefined = $state()

  // a closing group forgets its pending second tap
  let was = false
  $effect(() => { const o = open; if (was && !o) untrack(() => onclose?.()); was = o })
  // a link into the group (onboard.svelte.ts reveal) opens it; the link scrolls itself
  onMount(() => {
    const show = () => { if (groups) groups.open = title }
    box?.addEventListener(OPEN_GROUP, show)
    return () => box?.removeEventListener(OPEN_GROUP, show)
  })

  const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches
  async function toggle() {
    if (!groups || !row) return
    const scroller = row.closest<HTMLElement>('.m-main')
    const before = row.getBoundingClientRect().top
    groups.open = open ? '' : title
    await tick()
    if (!scroller || !row) return
    // a group above closed: the page moves up by its height, so this row keeps its place on screen
    scroller.scrollTop += row.getBoundingClientRect().top - before
    if (groups.open !== title || !panel) return
    // the opened panel ends below the screen: scroll until its end shows, but never past this row sitting under
    // the 56 px band of the top keys
    const page = row.closest<HTMLElement>('.m-page')
    const pad = page ? parseFloat(getComputedStyle(page).paddingBottom) || 0 : 0
    const view = scroller.getBoundingClientRect()
    const need = panel.getBoundingClientRect().bottom - (view.bottom - pad)
    const most = row.getBoundingClientRect().top - view.top - 56
    if (need > 0) scroller.scrollBy({ top: Math.min(need, Math.max(0, most)), behavior: still() ? 'auto' : 'smooth' })
  }
</script>

<MBox bind:ref={box} {id} class={['m-group', open && 'open']}>
  {#if href}
    <a class="m-group-row" {href}>{#if glyph}<span class="m-group-glyph"><ShellIcon name={glyph} /></span>{:else if letter}<span class="m-group-letter">{letter}</span>{/if}<span class="m-group-words"><b>{title}</b>{#if line}<small>{line}</small>{/if}</span>{#if kind && !['done', 'empty'].includes(kind)}<MBadge {kind} small />{/if}<ShellIcon name="down" /></a>
  {:else if action}
    <div class="m-group-row">{#if glyph}<span class="m-group-glyph"><ShellIcon name={glyph} /></span>{:else if letter}<span class="m-group-letter">{letter}</span>{/if}<span class="m-group-words"><b>{title}</b>{#if line}<small>{line}</small>{/if}</span>{@render action()}</div>
  {:else}
    <div class="m-group-head">
      <h3><button type="button" class="m-group-row" bind:this={row} aria-expanded={open} aria-controls={panelId} onclick={toggle}><i class={['m-group-dot', tone]} aria-hidden="true"></i><span class="m-group-words"><b>{title}</b>{#if line}<small>{line}</small>{/if}</span><ShellIcon name="down" /></button></h3>
      {#if open && info}<MInfo title={infoTitle || title}>{@render info()}</MInfo>{/if}
    </div>
    <div class="m-group-panel" id={panelId} bind:this={panel} hidden={!open}>{@render children?.()}</div>
  {/if}
</MBox>
