<script lang="ts">
  // First-run setup for Claude Code (Wiskit's third mode): find, sign in, test, turn on. The same endpoints as
  // Settings > Wiskit & AI > Claude Code (server/routes/claude_code.py); model and approvals stay in Settings.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { refreshAskOptions } from '../lib/ask.svelte'
  import { isDesktop, pickPath } from '../lib/pick'
  import { toast } from '../lib/ui.svelte'
  import { openSettings } from '../lib/io-commands.svelte'
  import Button from './ui/Button.svelte'
  import Field from './ui/Field.svelte'
  import Hint from './ui/Hint.svelte'
  import Progress from './ui/Progress.svelte'
  import SectionTitle from './ui/SectionTitle.svelte'
  import Status from './ui/Status.svelte'
  import TextButton from './ui/TextButton.svelte'
  import ToggleRow from './ui/ToggleRow.svelte'

  interface Test { ok: boolean; state: string; version: string; message: string }
  interface View { available: boolean; path: string; detected: string; enabled: boolean; winget: boolean }
  let { onavailable }: { onavailable?: (available: boolean) => void } = $props()
  let cc = $state<View | null>(null), path = $state(''), test = $state<Test | null>(null)
  let busy = $state(false), testing = $state(false), error = $state('')
  const id = $props.id()
  const passed = $derived(!!(test?.ok && cc && path.trim() === cc.path))
  const line = $derived.by((): { on: boolean; text: string } => {
    if (!cc) return { on: false, text: '' }
    const t = test
    if (t) return { on: t.ok, text: `${t.ok ? 'Ready' : t.state === 'logged_out' ? 'Not logged in' : t.state === 'missing' ? 'Not found' : 'Error'}${t.version ? ` (${t.version})` : ''}: ${t.message}` }
    if (cc.enabled && cc.path) return { on: true, text: 'On in Wiskit. Press Test to check it again.' }
    if (!cc.path && cc.detected) return { on: false, text: 'Found on this PC. Press Test to use it.' }
    if (!cc.path) return { on: false, text: 'Not found on this PC. Install Claude Code and log in, or choose claude.exe or claude.cmd.' }
    return { on: false, text: 'Not tested yet. Press Test to check the program and its login.' }
  })
  async function load() {
    try {
      cc = await api.get<View>('/api/claude-code')
      path = cc.path || cc.detected
      onavailable?.(cc.available)
    } catch { cc = null; onavailable?.(false) }
  }
  onMount(() => { void load() })
  async function browse() {
    const p = await pickPath('claude')
    if (p) { path = p; test = null }
  }
  async function find() {
    error = ''
    await load()
    if (cc && !cc.path && !cc.detected) error = 'Claude Code was not found on this PC. Install it, or browse to claude.exe.'
    else if (cc?.detected) { path = cc.detected; test = null }
  }
  async function login() {
    busy = true; error = ''
    try { await api.post('/api/claude-code/login', { path: path.trim() }); toast('Finish signing in to Claude Code in the terminal window, then press Test') }
    catch (e) { error = (e as Error).message } finally { busy = false }
  }
  async function check() {
    busy = true; testing = true; error = ''
    try {
      const r = await api.post<View & { test: Test }>('/api/claude-code/test', { path: path.trim() })
      test = r.test; cc = r
    } catch (e) { error = (e as Error).message } finally { busy = false; testing = false }
  }
  async function enable(enabled: boolean) {
    busy = true; error = ''
    try {
      cc = await api.put<View>('/api/claude-code', { enabled })
      void refreshAskOptions()
      toast(enabled ? 'Claude Code mode is on in Wiskit' : 'Claude Code mode is off', enabled ? '' : 'off')
    } catch (e) { error = (e as Error).message; void load() } finally { busy = false }
  }
</script>

{#if cc?.available}
  <div class="claude-code">
    <SectionTitle>Claude Code (optional)</SectionTitle>
    <Hint>Use your Claude Code login to ask Wiskit about your library, on your Claude plan instead of an API key.</Hint>
    <Status on={line.on} role="status">{line.text}</Status>
    {#if !path.trim()}<Hint>Claude Code is a separate program from Anthropic and needs a Claude plan. <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener noreferrer">Install Claude Code</a>{cc.winget ? ', or run winget install Anthropic.ClaudeCode in a terminal' : ''}, then press Find.</Hint>{/if}
    <Field label="Program" for={`${id}-path`}>
      <div class="frow">
        <input class="inp" id={`${id}-path`} bind:value={path} oninput={() => (test = null)} placeholder={cc.detected || 'claude.exe or claude.cmd'} autocomplete="off" spellcheck="false" />
        {#if isDesktop()}<Button size="sm" disabled={busy} onclick={browse}>Browse</Button>{/if}
      </div>
    </Field>
    {#if testing}<Progress label="Testing Claude Code" />{/if}
    {#if error}<Hint tone="error" role="alert">{error}</Hint>{/if}
    <div class="frow">
      <Button size="sm" disabled={busy || !path.trim()} onclick={check}>{testing ? 'Testing…' : 'Test'}</Button>
      {#if !passed}<TextButton disabled={busy} onclick={find}>Find</TextButton>{/if}
      {#if path.trim() && !passed}<TextButton disabled={busy} onclick={login}>Sign in…</TextButton>{/if}
    </div>
    {#if path.trim() && !passed}<Hint>Sign in opens a terminal window for Claude Code's own sign-in. Finish it there, then press Test.</Hint>{/if}
    <ToggleRow id={`${id}-on`} label="Use in Wiskit" note={!cc.enabled && !passed ? 'turns on after a passing Test' : ''} checked={cc.enabled} disabled={busy || (!cc.enabled && !passed)} onchange={enable} />
    <div><TextButton onclick={() => openSettings('claude-code', 'set-s-cc-wiskit')}>Model and approvals in Settings</TextButton></div>
  </div>
{/if}

<style>
  .claude-code { display: grid; gap: 10px; margin-top: 8px }
  .claude-code :global(.fsec) { margin: 0 }
  .frow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px }
  .frow .inp { flex: 1 1 220px; min-width: 0 }
</style>
