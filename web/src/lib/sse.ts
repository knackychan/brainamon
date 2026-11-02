// Incremental byte framing only; callers own terminal-event policy.
export async function* sse(r: Response): AsyncGenerator<[string, string]> {
  if (!r.body) throw new Error('Missing response body.')
  const rd = r.body.getReader(), dec = new TextDecoder('utf-8', { fatal: true })
  let buf = '', ev = 'message', data: string[] = [], skipLF = false
  try {
    for (;;) {
      const { value, done } = await rd.read()
      const text = done ? dec.decode() : dec.decode(value, { stream: true })
      for (const c of text) {
        if (skipLF && c === '\n') { skipLF = false; continue }
        skipLF = c === '\r'
        if (c !== '\r' && c !== '\n') { buf += c; continue }
        const line = buf; buf = ''
        if (!line) {
          if (data.length) yield [ev, data.join('\n')]
          ev = 'message'; data = []
        } else if (!line.startsWith(':')) {
          const at = line.indexOf(':'), field = at < 0 ? line : line.slice(0, at)
          const val = at < 0 ? '' : line.slice(at + 1).replace(/^ /, '')
          if (field === 'event') ev = val
          else if (field === 'data') data.push(val)
        }
      }
      if (done) break
    }
  } finally {
    try { await rd.cancel() } finally { rd.releaseLock() }
  }
}

