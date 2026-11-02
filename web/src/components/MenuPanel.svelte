<script lang="ts">
  // The one CM-OS menu panel (V6 #mnu): keyboard navigation, clamped to the window, closes on
  // outside pointerdown, resize, Tab and Esc. Left / Right move between the menubar menus.
  import { isCmd, labelOf, MENUS, MENU_NAMES, type Cmd, type MenuEntry, type MenuKey, runEntry } from '../lib/commands'
  import { closeMenu, menu, menuItems, openMenu } from '../lib/menu.svelte'
  import { withActionAnchor } from '../lib/windows.svelte'
  import Px from '../lib/Px.svelte'

  let el: HTMLDivElement | undefined = $state()

  $effect(() => {
    if (!menu.open || !el) return
    const W = el.offsetWidth, H = el.offsetHeight
    el.style.left = Math.max(8, Math.min(innerWidth - W - 8, menu.x)) + 'px'
    el.style.top = Math.max(8, Math.min(innerHeight - H - 8, menu.y)) + 'px'
    if (menu.focus) el.querySelector<HTMLElement>('.mi:not([aria-disabled="true"])')?.focus({ preventScroll: true })
  })

  $effect(() => {
    if (!menu.open) return
    const down = (e: PointerEvent) => {
      const t = e.target as HTMLElement
      if (el && !el.contains(t) && !t.closest('[data-menu],#cvchip')) closeMenu(true)
    }
    const resize = () => closeMenu(true)
    document.addEventListener('pointerdown', down, true)
    addEventListener('resize', resize)
    return () => { document.removeEventListener('pointerdown', down, true); removeEventListener('resize', resize) }
  })

  function pick(c: Cmd, e: MouseEvent) {
    withActionAnchor(e.currentTarget as HTMLElement, () => {
      closeMenu()
      runEntry(c)               // a disabled command explains itself with a toast
    })
  }

  function onKey(e: KeyboardEvent) {
    if (!el) return
    const items = [...el.querySelectorAll<HTMLElement>('.mi:not([aria-disabled="true"])')]
    const i = items.indexOf(document.activeElement as HTMLElement)
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
    } else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus() }
    else if (e.key === 'End') { e.preventDefault(); items[items.length - 1]?.focus() }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu() }
    else if (e.key === 'Tab') closeMenu()
    else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && menu.fromKey && menu.fromKey !== 'all') {
      e.preventDefault()
      const bars = [...document.querySelectorAll<HTMLElement>('.menubar [data-menu]')].filter(b => b.offsetParent !== null && b.dataset.menu !== 'all')
      const k = bars.findIndex(b => b.dataset.menu === menu.fromKey)
      const nb = bars[(k + (e.key === 'ArrowRight' ? 1 : -1) + bars.length) % bars.length]
      if (nb) openMenu(MENUS[nb.dataset.menu as MenuKey], nb)
    }
  }

  const entries: MenuEntry[] = $derived((menu.rev, menuItems()))
</script>

{#if menu.open}
  <div class="mnu" id="mnu" role="menu" aria-label={menu.fromKey === 'all' ? 'All menus' : MENU_NAMES[menu.fromKey as MenuKey] ?? 'Actions'} tabindex="-1" bind:this={el} onkeydown={onKey}>
    {#each entries as x, i (i)}
      {#if 'sep' in x}
        <hr class="msep" />
      {:else if 'head' in x}
        <p class="mhd" role="presentation">{x.head}</p>
      {:else if isCmd(x)}
        {@const off = !!x.off?.()}
        <button type="button" class="mi" class:danger={x.danger} role={x.check ? 'menuitemcheckbox' : 'menuitem'}
          aria-checked={x.check ? !!x.check() : undefined} aria-disabled={off ? 'true' : undefined} tabindex="-1"
          onclick={e => pick(x, e)}>
          {#if x.check}<i class="tick" class:on2={x.check()} aria-hidden="true"></i>{:else if x.icon}<Px name={x.icon} />{:else}<i></i>{/if}
          <span>{labelOf(x)}{#if off}<small class="mi-state">Unavailable</small>{/if}</span><kbd>{x.key ?? ''}</kbd>
        </button>
      {/if}
    {/each}
  </div>
{/if}
