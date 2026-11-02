<script lang="ts">
  // Drop panel: whatever is dropped or pasted is filed with the workflows Brainamon already has
  // (server/routes/inbox.py): screenshot -> Inbox note digest, link -> library item + thumbnail,
  // text -> Inbox note, other file -> data/inbox/; a question goes to Wiskit (POST /api/ask).
  import { onMount } from 'svelte'
  import WiskitSprite from '../components/WiskitSprite.svelte'

  type Entry = { id: number; kind: string; text: string; state: 'busy' | 'ok' | 'err'; itemId?: number }
  let entries = $state<Entry[]>([])
  let input = $state('')
  let over = $state(false)
  let answer = $state('')
  let asking = $state(false)
  let problem = $state('')           // why Wiskit cannot answer (no API key), '' when he can
  let ta: HTMLTextAreaElement | undefined = $state()
  let seq = 0
  // Ask attachments (plan 11): ids from the widget (?attach=a|b, or the panel_attach event)
  type Att = { id: string; name: string }
  let atts = $state<Att[]>([])
  let chat = ''           // this panel's chat: follow-up questions keep the attachments
  function addAtts(ids: string[]) {
    for (const id of ids) {
      if (id && !atts.some(a => a.id === id)) atts.push({ id, name: id.startsWith('video:') ? `${id.slice(6)} (video analysis)` : id })
    }
  }
  const H = { 'X-CM': '1' }

  function log(kind: string, text: string): Entry {
    const e: Entry = { id: ++seq, kind, text, state: 'busy' }
    entries.unshift(e)
    entries = entries.slice(0, 20)
    return entries[0]
  }
  async function post(url: string, body: unknown): Promise<any> {
    const r = await fetch(url, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(d.detail || r.statusText)
    return d
  }
  // = knowledge/inbox.py link(): http(s)://... as it is, a bare address (text.com, www.x.com/a) gets https://
  const BARE = /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24})(:\d{1,5})?([/?#]\S*)?$/i
  const FILE_ENDINGS = new Set(['md', 'txt', 'py', 'js', 'ts', 'json', 'csv', 'html', 'css', 'xml', 'yaml', 'yml', 'log', 'ini',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'pdf', 'mp4', 'mov', 'mkv', 'webm', 'avi', 'zip', 'exe', 'doc', 'docx'])
  function link(text: string): string | null {
    const t = text.trim()
    if (/^https?:\/\/\S+$/i.test(t)) return t
    const m = BARE.exec(t)
    if (!m || (FILE_ENDINGS.has(m[1].toLowerCase()) && !/^www\./i.test(t) && !m[3])) return null
    return 'https://' + t
  }
  const isUrl = (t: string) => link(t) !== null
  const b64 = (f: File) => new Promise<string>((res, rej) => {
    const fr = new FileReader()
    fr.onload = () => res(String(fr.result).split(',')[1] ?? '')
    fr.onerror = () => rej(fr.error)
    fr.readAsDataURL(f)
  })

  async function fileScreenshot(f: File) {
    const e = log('Screenshot', f.name || 'pasted image')
    try {
      await post('/api/inbox/screenshot', { images: [{ name: f.name || 'screenshot.png', type: f.type || 'image/png', data: await b64(f) }] })
      e.state = 'ok'; e.text += ': reading it into your Inbox note'
    } catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}` }
  }
  async function fileOther(f: File) {
    const e = log('File', f.name)
    try {
      const r = await fetch(`/api/inbox/file?name=${encodeURIComponent(f.name)}`, { method: 'POST', headers: H, body: f })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || r.statusText)
      e.state = 'ok'; e.text += ': saved to data/inbox and listed in your Inbox note'
    } catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}` }
  }
  async function fileLink(raw: string) {
    const url = link(raw) ?? raw.trim()
    const e = log('Link', url)
    try {
      const d = await post('/api/inbox/link', { url })
      e.state = 'ok'; e.itemId = d.id
      e.text = d.new ? `${url}: added to the library, fetching its thumbnail` : `${url}: already in the library`
    } catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}` }
  }
  async function fileText(text: string) {
    const e = log('Note', text.length > 90 ? text.slice(0, 90) + '…' : text)
    try { await post('/api/inbox/text', { text }); e.state = 'ok' } catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}` }
  }
  async function describe(e: Entry) {
    try {
      await post('/api/jobs', { kind: 'describe', ids: [e.itemId], force: true })
      e.text += ' · describing'
    } catch (err) { e.text += ` · ${(err as Error).message}` }
  }

  async function checkKey() {
    try {
      const o = await (await fetch('/api/ask/options')).json()
      problem = o.problems?.[o.default_provider] ?? ''
    } catch { /* the server is not answering: ask() will say so */ }
  }

  async function ask(q: string) {
    if (asking || !q.trim()) return
    if (problem) await checkKey()                      // a key may have been added in the main window
    if (problem) { input = q; answer = problem; return }
    asking = true
    answer = ''
    const e = log('Ask', q)
    try {
      const body = { question: q, attachments: atts.map(a => a.id), ...(chat ? { chat } : {}) }
      const r = await fetch('/api/ask', { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!r.ok || !r.body) throw new Error(r.statusText)
      const rd = r.body.getReader(), dec = new TextDecoder()
      let buf = '', ev = ''
      for (;;) {
        const { value, done } = await rd.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let i
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i).replace(/\r$/, ''); buf = buf.slice(i + 1)
          if (line.startsWith('event:')) ev = line.slice(6).trim()
          else if (line.startsWith('data:')) {
            const d = JSON.parse(line.slice(5))
            if (ev === 'chunk') answer += d.text
            else if (ev === 'done') { answer = d.text; chat = d.chat?.slug || chat; atts = [] }
            else if (ev === 'error') throw new Error(d.message)
          }
        }
      }
      e.state = 'ok'
    } catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}`; answer = (err as Error).message } finally { asking = false }
  }

  function submit(asNote = false) {
    const t = input.trim()
    if (!t) return
    input = ''
    if (isUrl(t)) fileLink(t)
    else if (asNote) fileText(t)
    else ask(t)
  }
  // the main window's Add to Brainamon: choose Note or Library before anything is saved
  async function chooseWhere() {
    const t = input.trim()
    if (!t) return
    const e = log('Add to Brainamon', t.length > 90 ? t.slice(0, 90) + '…' : t)
    try { await post('/api/app/capture', { text: t }); input = ''; e.state = 'ok'; e.text += ': opened in the main window, nothing is saved yet' }
    catch (err) { e.state = 'err'; e.text += `: ${(err as Error).message}` }
  }
  function key(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(e.ctrlKey) }
  }

  function handle(dt: DataTransfer | null) {
    if (!dt) return
    const files = [...dt.files]
    if (files.length) {
      for (const f of files) (f.type.startsWith('image/') ? fileScreenshot : fileOther)(f)
      return
    }
    const uri = (dt.getData('text/uri-list') || '').split('\n').find(l => l && !l.startsWith('#'))
    const text = dt.getData('text/plain') || ''
    if (uri && isUrl(uri)) fileLink(uri.trim())
    else if (isUrl(text)) fileLink(text.trim())
    else if (text.trim()) fileText(text.trim())
  }
  function drop(e: DragEvent) { e.preventDefault(); over = false; handle(e.dataTransfer) }
  function paste(e: ClipboardEvent) {
    const img = [...(e.clipboardData?.files ?? [])].find(f => f.type.startsWith('image/'))
    if (img) { e.preventDefault(); fileScreenshot(img); return }
    const text = e.clipboardData?.getData('text/plain') ?? ''
    if (e.target !== ta && isUrl(text)) { e.preventDefault(); fileLink(text.trim()) }     // a link pasted outside the box is added at once
    // other text pastes go into the box as usual
  }
  async function openApp() { try { await post('/api/app/open', {}) } catch { /* the window will not open from a browser tab */ } }
  function close() {
    const api = (window as any).pywebview?.api
    if (!api?.close) { window.close(); return }
    entries = []; input = ''; answer = ''; atts = []; chat = ''     // hidden, not ended (PanelApi): the next open starts fresh
    api.close()
  }

  // Keep panel lifecycle and attachments independent of its decorative sprite.
  onMount(() => {
    const params = new URLSearchParams(location.search)
    addAtts((params.get('attach') || '').split('|'))
    checkKey()
    if (params.has('ask')) ta?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    addEventListener('keydown', onKey)
    const es = new EventSource('/api/events')
    const attach = (ids: string[]) => { addAtts(ids); ta?.focus(); checkKey() }
    es.addEventListener('panel_attach', ev => attach(JSON.parse((ev as MessageEvent).data).ids || []))
    ;(window as any).panelAttach = attach      // PanelApi.reopen: the page was at rest and may have missed the event
    return () => { removeEventListener('keydown', onKey); es.close() }
  })
</script>

<svelte:window onfocus={checkKey} onpaste={paste} ondragover={e => { e.preventDefault(); over = true }} ondragleave={e => { if (!e.relatedTarget) over = false }} ondrop={drop} />

<main class:over>
  <header class="pywebview-drag-region">
    <div class="sprite"><WiskitSprite pose={asking || entries.some(e => e.state === 'busy') ? 'processing' : 'hover'} /></div>
    <div class="who">
      <h1>Wiskit</h1>
      <p>{asking ? 'Thinking…' : over ? 'Let go, I have it.' : 'Drop it on me, or ask.'}</p>
    </div>
    <button class="x" type="button" onclick={close} aria-label="Close">×</button>
  </header>

  <section class="zone" aria-label="Drop zone">
    <p><b>Drop</b> a screenshot, a link, a file or some text anywhere here.</p>
    <p class="dim">Paste a screenshot or a link with Ctrl+V. Screenshots and notes go to your Inbox note; links join the library.</p>
  </section>

  <div class="ask">
    {#if problem}
      <p class="warn" role="alert">{problem} <button type="button" class="link" onclick={openApp}>Open Brainamon</button></p>
    {/if}
    {#if atts.length}
      <ul class="atts" aria-label="Attached to your next question">
        {#each atts as a (a.id)}
          <li><span>{a.name}</span><button type="button" class="rm" aria-label={`Remove ${a.name}`} onclick={() => (atts = atts.filter(x => x.id !== a.id))}>×</button></li>
        {/each}
      </ul>
    {/if}
    <textarea bind:this={ta} bind:value={input} onkeydown={key} rows="3" placeholder={atts.length ? 'Ask Wiskit about the attachment…' : 'Ask Wiskit about your library, or write a note…'} aria-label="Question or note"></textarea>
    <div class="row">
      <button type="button" class="pri" disabled={!input.trim() || asking} onclick={() => submit(false)}>{isUrl(input) ? 'Add link' : 'Ask'}</button>
      <button type="button" disabled={!input.trim() || isUrl(input)} onclick={() => submit(true)}>Save to Inbox</button>
      <button type="button" disabled={!input.trim()} onclick={chooseWhere}>Choose where…</button>
      <span class="hint">Enter asks · Ctrl+Enter saves</span>
    </div>
  </div>

  {#if answer || asking}
    <article class="answer" aria-live="polite">{answer || '…'}
      {#if !asking}<button type="button" class="link" onclick={openApp}>Open in Brainamon</button>{/if}
    </article>
  {/if}

  <ul class="log" aria-label="What Wiskit did">
    {#each entries as e (e.id)}
      <li class={e.state}><b>{e.kind}</b> <span>{e.text}</span>
        {#if e.kind === 'Link' && e.state === 'ok' && e.itemId}<button type="button" class="link" onclick={() => describe(e)}>Describe it</button>{/if}
      </li>
    {/each}
  </ul>
</main>

<style>
  :global(:root) { --bg: #f5f5f1; --in: #e8e8e3; --ink: #17181b; --dim: #66696d; --hair: rgba(23, 24, 27, .16); --accent: #ff5a1f; --ok: #3f8f6a; --err: #c2412b }
  @media (prefers-color-scheme: dark) { :global(:root) { --bg: #131417; --in: #0d0e10; --ink: #e8e8e1; --dim: #8a8d92; --hair: rgba(232, 232, 225, .14); color-scheme: dark } }
  :global(body) { margin: 0; background: var(--bg); color: var(--ink); font: 13px/1.45 'IBM Plex Mono', ui-monospace, Consolas, monospace; overflow: hidden }
  main { height: 100vh; box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; padding: 0 14px 14px; border: 2px solid var(--hair) }
  main.over { border-color: var(--accent) }
  header { display: flex; align-items: center; gap: 10px; padding: 10px 0 6px; border-bottom: 1px solid var(--hair) }
  .sprite { width: 96px; height: 56px; flex: none }
  .who { flex: 1; min-width: 0 }
  h1 { margin: 0; font: 400 20px/1 'DotGothic16', 'IBM Plex Mono', monospace; letter-spacing: .03em }
  .who p { margin: 4px 0 0; color: var(--dim) }
  .x { align-self: flex-start; margin-top: 8px; font-size: 18px; line-height: 1; padding: 4px 8px }
  .zone { border: 1.5px dashed var(--hair); border-radius: 4px; padding: 14px; text-align: center }
  main.over .zone { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent) }
  .zone p { margin: 0 }
  .dim, .hint { color: var(--dim); font-size: 12px }
  .zone .dim { margin-top: 6px }
  textarea { width: 100%; box-sizing: border-box; resize: none; background: var(--in); color: var(--ink); border: 1px solid var(--hair); border-radius: 3px; padding: 8px; font: inherit }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px }
  button { font: 500 12px/1 'IBM Plex Mono', monospace; color: var(--ink); background: transparent; border: 1px solid var(--hair); border-radius: 3px; padding: 7px 10px; cursor: pointer }
  button:disabled { opacity: .45; cursor: default }
  button.pri { background: var(--accent); border-color: var(--accent); color: #fff }
  button.link { border: 0; padding: 2px 0; color: var(--accent); text-decoration: underline }
  button:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
  .answer { white-space: pre-wrap; overflow: auto; max-height: 34vh; padding: 10px; background: var(--in); border-radius: 3px; border: 1px solid var(--hair) }
  .answer .link { display: block; margin-top: 8px }
  .warn { margin: 0 0 6px; padding: 6px 8px; border: 1px solid var(--err); border-radius: 3px; color: var(--err) }
  .log { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; min-height: 0; display: grid; gap: 6px; align-content: start }
  .log li { padding-left: 10px; border-left: 3px solid var(--hair); overflow-wrap: anywhere }
  .log li.ok { border-color: var(--ok) }
  .log li.err { border-color: var(--err) }
  .log li.busy { border-color: var(--accent) }
  .atts { list-style: none; margin: 0 0 6px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px }
  .atts li { display: flex; align-items: center; gap: 4px; max-width: 100%; padding: 3px 4px 3px 8px; border: 1px solid var(--accent); border-radius: 3px; font-size: 12px }
  .atts span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
  .atts .rm { border: 0; padding: 2px 4px; font-size: 14px }
</style>
