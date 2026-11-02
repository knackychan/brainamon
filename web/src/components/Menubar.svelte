<script lang="ts">
  // The menubar (V6 body.html header): Brainamon wordmark menu, File / Edit / Process / View, the folded
  // MENU key, workspace tabs, canvas chip, JOB lamp, LIB count, cookies lamp, clock, console, Night.
  import { MENUS, MENU_NAMES, runCmd, type MenuEntry, type MenuKey } from '../lib/commands'
  import { closeMenu, menu, openMenu } from '../lib/menu.svelte'
  import { JOB_SHORT, live } from '../lib/events.svelte'
  import { setWS, toggleConsole, toggleTheme, ui, WS_LIST, WS_NAME, WS_SHORT } from '../lib/ui.svelte'
  import Px from '../lib/Px.svelte'
  import Wordmark from './Wordmark.svelte'
  import { wins } from '../lib/windows.svelte'
  import { activeCount, cv } from '../lib/canvas.svelte'
  import { ck } from '../lib/io-commands.svelte'

  const BAR: MenuKey[] = ['file', 'edit', 'process', 'view']

  function show(btn: HTMLElement) {
    const m = btn.dataset.menu as MenuKey | 'all'
    if (m === 'all') {
      const all: MenuEntry[] = (Object.keys(MENUS) as MenuKey[]).flatMap(k => [{ head: MENU_NAMES[k] }, ...MENUS[k]])
      openMenu(all, btn)
    } else openMenu(MENUS[m], btn)
  }
  function onClick(e: MouseEvent) {
    const b = e.currentTarget as HTMLElement
    if (menu.open && menu.fromKey === b.dataset.menu) { closeMenu(); return }
    show(b)
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); show(e.currentTarget as HTMLElement) }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
      e.preventDefault()
      const buttons = [...document.querySelectorAll<HTMLElement>('.menubar [data-menu]')].filter(b => b.offsetParent !== null)
      const i = buttons.indexOf(e.currentTarget as HTMLElement)
      const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : buttons.length - 1)) % buttons.length
      buttons[next]?.focus()
    }
  }
  function onEnter(e: PointerEvent) {
    const b = e.currentTarget as HTMLElement
    if (menu.open && menu.fromKey && menu.fromKey !== b.dataset.menu) show(b)
  }

  // workspace tabs: arrows move between tabs (role=tablist)
  function tabKey(e: KeyboardEvent, i: number) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const n = (i + (e.key === 'ArrowRight' ? 1 : -1) + WS_LIST.length) % WS_LIST.length
    setWS(WS_LIST[n])
    document.getElementById('tab-' + WS_LIST[n])?.focus()
  }

  // Local time (the V6 clock showed Tokyo)
  const pad = (n: number) => String(n).padStart(2, '0')
  const localTime = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}` }
  let clock = $state(localTime())
  $effect(() => { const t = setInterval(() => (clock = localTime()), 15000); return () => clearInterval(t) })

  const job = $derived(live.jobs.current)
  const jobText = $derived(job ? `${job.state === 'paused' ? 'PAUSED ' : ''}${JOB_SHORT[job.kind] ?? job.kind.toUpperCase()} ${job.done + job.err}/${job.total}` : 'idle')
  const fmt = (n: number) => n.toLocaleString('en-US')
</script>

<header class="menubar" id="menubar" inert={wins.length > 0}>
  <button class="mlogo" type="button" data-menu="cmos" aria-label="Brainamon menu" aria-haspopup="menu" aria-controls="mnu" aria-expanded={menu.open && menu.fromKey === 'cmos'} onclick={onClick} onkeydown={onKey} onpointerenter={onEnter}><span class="bwm"><Wordmark /></span></button>
  <button class="tkey menu-ctl" type="button" id="open-pad" aria-controls="pad" aria-expanded={ui.drawer === 'pad'} onclick={() => (ui.drawer = ui.drawer === 'pad' ? null : 'pad')}><Px name="grid" />Rail</button>
  <nav class="mbar" aria-label="Menus">
    {#each BAR as m (m)}
      <button class="mbtn" type="button" data-menu={m} aria-haspopup="menu" aria-controls="mnu" aria-expanded={menu.open && menu.fromKey === m} onclick={onClick} onkeydown={onKey} onpointerenter={onEnter}>{MENU_NAMES[m]}</button>
    {/each}
  </nav>
  <button class="mbtn mmenu" type="button" data-menu="all" aria-haspopup="menu" aria-controls="mnu" aria-expanded={menu.open && menu.fromKey === 'all'} onclick={onClick} onkeydown={onKey}>Menu</button>
  <span class="msp"></span>
  <div class="wtabs" role="tablist" aria-label="Workspaces">
    {#each WS_LIST as k, i (k)}
      <button class="wt" type="button" role="tab" id={'tab-' + k} data-ws={k} aria-controls={'ws-' + k} aria-selected={ui.ws === k} tabindex={ui.ws === k ? 0 : -1} title={`${WS_NAME[k]} (${i + 1})`} onclick={() => setWS(k)} onkeydown={e => tabKey(e, i)}>
        <code>{String(i + 1).padStart(2, '0')}</code><span class="wt-l">{WS_NAME[k]}</span><span class="wt-s" aria-hidden="true">{WS_SHORT[k]}</span><span class="wt-b" id={'wtb-' + k}></span>
      </button>
    {/each}
  </div>
  <span class="msp"></span>
  <span class="rt">
    <button class="cvchip" type="button" id="cvchip" aria-haspopup="menu" aria-expanded="false" title="Active canvas: Add to canvas fills this one." onclick={() => runCmd('canvas-target')}><small>Canvas</small><b id="cvchip-n">{cv.doc?.name ?? 'none'}</b><em id="cvchip-c">{activeCount()}</em></button>
    <button class="mstat hide-m" type="button" id="mb-job" title="Running job: click for progress" onclick={() => runCmd('progress')}><span class="lamp" class:off={!job}></span>JOB&nbsp;<b id="mb-w">{jobText}</b></button>
    <span class="hide-m">LIB <b id="mb-l">{fmt(ui.libCount)}</b></span>
    <button class="mstat hide-m" type="button" id="mb-ck" title={`${ck.detail} Click for Settings > Imports & downloads.`} onclick={() => runCmd('settings-downloads')}><span class="lamp" class:g={ck.lamp === 'g'} class:off={ck.lamp === 'off'}></span>CK</button>
    <span id="mb-c" class="hide-s hide-m">{clock}</span>
    <button class="tkey sq" class:hot={ui.consoleHot} type="button" id="cons-key" aria-pressed={ui.consoleOpen} aria-controls="cons" aria-label="Console" title="Console (Ctrl+`)" onclick={() => toggleConsole()}><Px name="term" /></button>
    <button class="tkey" type="button" id="theme" aria-label="Switch day or night" onclick={toggleTheme}><Px name={ui.dark ? 'sun' : 'moon'} /><span id="theme-l">{ui.dark ? 'Day' : 'Night'}</span></button>
  </span>
</header>
