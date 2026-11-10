// Evaluated on local Vite with synthetic objects; setFetch intercepts every provider request.
async ({ language = 'en', drift = false } = {}) => {
  const { MirrorSource } = await import('/src/mobile/source/mirror.ts')
  const { DesktopSource } = await import('/src/mobile/source/desktop.ts')
  const providers = await import('/src/mobile/ai/providers.ts')
  const { PhoneLibrary } = await import('/src/mobile/ai/library.ts')
  const { setup } = await import('/src/lib/i18n/index.ts')
  const { messages: fr } = await import('/src/lib/i18n/fr/index.ts')
  const { messages: zh } = await import('/src/lib/i18n/zh-Hant/index.ts')
  const prompts = await import('/src/mobile/ai/prompts.ts')
  const { fmtAnswer, mdHTML, setCardLookup } = await import('/src/lib/md.ts')
  const { kv } = await import('/src/mobile/store.ts')
  const basePrompts = JSON.stringify([prompts.ASK, prompts.SYNTH, prompts.DEEP, prompts.PHONE_AI])
  const select = l => setup({ fr, 'zh-Hant': zh }, l, [])
  let driftCount = 0
  // The run is already waiting when the resolved app language changes.
  const held = () => new Promise(resolve => queueMicrotask(() => {
    if (drift) { select(language === 'fr' ? 'zh-Hant' : 'fr'); driftCount++ }
    resolve()
  }))
  const records = {}, effects = {}
  const raw = '## Sources / Sources citées / 來源\nConseil 繁體 [id 1] [id 999] [note: safe.md] (general knowledge)\n<script>window.__bad=1</script> & "quoted"'
  const row = { id: 1, uid: 'pc-uid-1', cat: 'SPORT', tags: 'ancien, 保留', title: 'Saved <title>', desc: 'Knee drill', url: 'https://example.test/1', created: 1 }
  const full = { id: 1, category: 'SPORT', tags: row.tags, creator: 'Coach', type: 'Post', short_desc: row.title,
    description: 'Knee drill caption', transcript: 'Original 简体 text', report: 'Report 原文', notes: 'My note', url: row.url, ai_desc: 'Previous description' }
  const lib = new PhoneLibrary([{ id: 1, s: full.short_desc, d: full.description, a: full.ai_desc, t: full.transcript, c: full.creator, g: full.tags, k: full.report }], [row], [])
  const make = provider => {
    const source = Object.create(MirrorSource.prototype)
    Object.assign(source, {
      pair: { solo: true, f: '07-synthetic' }, rowsNow: [row], byId: new Map([[1, row]]), texts: new Map([[1, { report: full.report, transcript: full.transcript }]]),
      manifest: { files: {} }, ready: held, item: async () => { await held(); return { ...full } },
      library: async () => { await held(); return lib }, vectors: async () => null,
      deepFiles: async () => ({ topics: [], resources: [], aux: null }), noteTexts: async () => [],
      canvases: async () => [{ id: 'existing', name: 'Canvas 原文', count: 1, updated: 1 }],
      cats: () => [{ name: 'SPORT' }, { name: 'CUISINE 原文' }],
      keys: () => ({ [provider]: 'synthetic-key', ...(provider === 'anthropic' ? { openai: '' } : {}) }),
      endpoints: () => providers.CLOUD, settings: () => ({ agent_max_rounds: 3 }), cap: n => n,
      ai: () => ({ provider, model: 'synthetic-model', label: 'Synthetic model' }),
      synthChoice: () => [provider, 'synthetic-model'], thumbBlob: async () => null,
      flushSoon() {}, setRows() {}, newNoteFile: async () => 'synthetic.md',
      chat: async () => { await held(); return { slug: 'fixture', history: [] } },
      changes: { add: async e => { effects[current].push(e) } },
      proposalLocked: fn => fn(), categoryProposal: async () => null, canvasProposal: async () => null, canvasSizes: async () => new Map(),
      edit: async (id, fields) => { effects[current].push({ id, fields }); return { ...row, cat: fields.category, tags: fields.tags } },
      finish: async (q, text, ids, base, history, info, onEvent, signal, notes) => {
        effects[current].push({ reply: text, ids, notes }); onEvent({ ev: 'done', text })
      },
    })
    return source
  }
  let current = '', result = 'Synthetic description 原文 简体', toolNames = [], round = 0, completions = []
  const respond = async (url, init) => {
    const body = init.body instanceof FormData ? await Promise.all([...init.body].map(async ([key, value]) => [key,
      typeof value === 'string' ? value : { name: value.name, type: value.type, bytes: [...new Uint8Array(await value.arrayBuffer())] }])) : String(init.body)
    records[current].push({ url, method: init.method, headers: init.headers, redirect: init.redirect ?? null, body })
    await held()
    const anthropic = url.includes('anthropic')
    const j = typeof body === 'string' ? JSON.parse(body) : {}
    if (j.stream) {
      const name = toolNames[round++]
      const args = name === 'list_canvases' ? {} : name === 'read_items' ? { ids: [1] }
        : { new_name: 'Nouveau 畫布', layout: 'rows', elements: [{ kind: 'text', text: 'Texte 新內容', group: 'Groupe 群組' }] }
      if (anthropic) {
        const content = name ? { type: 'tool_use', id: `tool-${round}`, name, input: args } : { type: 'text', text: raw }
        const events = [{ type: 'message_start', message: {} }, { type: 'content_block_start', index: 0, content_block: content },
          { type: 'content_block_stop', index: 0 }, { type: 'message_delta', delta: { stop_reason: name ? 'tool_use' : 'end_turn' } }, { type: 'message_stop' }]
        return new Response(events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''))
      }
      const output = name ? [{ type: 'function_call', call_id: `tool-${round}`, name, arguments: JSON.stringify(args) }]
        : [{ type: 'message', status: 'completed', content: [{ type: 'output_text', text: raw }] }]
      const event = { type: 'response.completed', response: { status: 'completed', output } }
      return new Response(`event: response.completed\ndata: ${JSON.stringify(event)}\n\n`)
    }
    const text = completions.length ? completions.shift() : result
    return Response.json(url.includes('/audio/') ? { text: 'Original speech 简体' } : anthropic ? { content: [{ type: 'text', text }] }
      : url.endsWith('/responses') ? { output: [{ type: 'message', content: [{ type: 'output_text', text }] }] } : { choices: [{ message: { content: text } }] })
  }
  providers.setFetch(respond)
  const run = async (name, fn) => {
    current = name; records[name] = []; effects[name] = []; round = 0; toolNames = []; completions = []; result = 'Synthetic description 原文 简体'
    select(language)
    const value = await fn()
    if (value !== undefined) effects[name].push({ value })
  }
  try {
    for (const provider of ['anthropic', 'openai']) {
      const s = make(provider), p = provider + ':'
      for (const mode of ['quick', 'deep']) await run(p + mode, async () => {
        toolNames = ['read_items']
        await s.ask('Knee? 请回答', 'fixture', () => {}, new AbortController().signal, mode)
      })
      await run(p + 'canvas', async () => {
        toolNames = ['list_canvases', 'propose_canvas']
        await s.ask('Create a canvas', 'fixture', () => {}, new AbortController().signal, 'deep')
        const pending = await kv.get('wiskit-canvas-proposal:07-synthetic')
        effects[current].push({ pending: !!pending })
      })
      await run(p + 'describe-text', () => s.describe(1))
      await run(p + 'describe-vision', async () => {
        s.thumbBlob = async () => { await held(); return new Blob(['ABC'], { type: 'image/png' }) }
        return s.describe(1)
      })
      await run(p + 'describe-no-content', () => { result = 'NO_CONTENT'; return s.describe(1) })
      await run(p + 'categorize', () => { result = '{"category":"CUISINE 原文","tags":"training, knee"}'; return s.categorize(1, ['SPORT', 'CUISINE 原文']) })
      await run(p + 'suggest', () => { result = '{"category":"SPORT","tags":"training, knee"}'; return s.suggestCategory(full, ['SPORT', 'CUISINE 原文']) })
      for (const kind of ['image', 'pdf', 'text']) for (const how of ['digest', 'describe']) await run(p + kind + '-' + how,
        () => s.readFile({ kind, name: 'Original.' + (kind === 'image' ? 'png' : kind === 'pdf' ? 'pdf' : 'txt'),
          type: kind === 'image' ? 'image/png' : kind === 'pdf' ? 'application/pdf' : 'text/plain', data: 'QUJD' }, how))
      const sources = Array.from({ length: 36 }, (_, i) => ({ ...full, id: i % 2 ? -i : i + 1 }))
      s.synthItems = async () => { await held(); return sources }
      for (const scenario of ['empty-first', 'empty-later', 'all-empty']) await run(p + 'synth-' + scenario, async () => {
        completions = scenario === 'empty-first' ? ['', '## Note\nFrançais 繁中 [id 1]', 'Later note [id 1]']
          : scenario === 'empty-later' ? ['Existing English / 中文 [id 1]', '', 'Final English / 中文 [id 1]'] : ['', '', '']
        try { return await s.synthesize('Topic 原文', sources.map(s => s.id), () => {}, new AbortController().signal) }
        catch (e) { if (scenario !== 'all-empty') throw e; effects[current].push({ error: e.message }) }
      })
      await run(p + 'paired-queue', async () => {
        s.pair.solo = false
        return s.synthesize('Topic 原文', Array.from({ length: 37 }, (_, i) => i + 1), () => {}, new AbortController().signal)
      })
      await run(p + 'solo-limit', async () => {
        s.pair.solo = true
        try { await s.synthesize('Topic 原文', Array.from({ length: 37 }, (_, i) => i + 1), () => {}, new AbortController().signal) }
        catch (e) { effects[current].push({ error: e.message }) }
      })
    }
    const s = make('openai')
    await run('voice', () => s.transcribe(new Blob(['audio'], { type: 'audio/webm' })))
    const originalFetch = window.fetch
    window.fetch = async (url, init) => {
      records[current].push({ url, method: init.method, headers: init.headers,
        body: typeof init.body === 'string' ? init.body : [...new Uint8Array(init.body)] })
      return url === '/api/ask' ? new Response('event: done\ndata: {"text":"Original PC reply"}\n\n') : Response.json({ text: 'Original PC text' })
    }
    try {
      const pc = new DesktopSource()
      for (const mode of ['quick', 'deep']) await run('pc-' + mode, () => pc.ask('Question 原文', 'original-chat', () => {}, new AbortController().signal, mode))
      await run('pc-synth', () => pc.synthesize('Topic 原文', [1, -2], () => {}))
      for (const how of ['digest', 'describe']) await run('pc-file-' + how, () => pc.readFile({ kind: 'image', name: '原文.png', type: 'image/png', data: 'QUJD' }, how))
    } finally { window.fetch = originalFetch }
    select(language)
    setCardLookup(n => n === 1 ? { title: '<img src=x onerror=alert(1)>', cat: 'SPORT' } : undefined)
    const rendered = { answer: fmtAnswer(raw), markdown: mdHTML('# 來源\n[id 1] [id 999]\n[unsafe](javascript:alert(1))\nhttps://example.test/') }
    if (basePrompts !== JSON.stringify([prompts.ASK, prompts.SYNTH, prompts.DEEP, prompts.PHONE_AI])) throw Error('Base prompts mutated')
    return { records, effects, rendered, raw, driftCount, basePrompts }
  } finally { providers.setFetch((url, init) => fetch(url, init)) }
}
