// A frozen journal batch keeps this identity even when its delivery acknowledgement advances.
export async function transferId(doc: unknown): Promise<string> {
  const d = doc as { device: string; at: number; stream?: string; seq?: number; previous?: string }
  const bytes = new TextEncoder().encode(`${d.device}\n${d.at}\n${d.stream ?? ''}\n${d.seq ?? ''}\n${d.previous ?? ''}`)
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('')
}

export async function syncOwner(pair: { k: string; l?: string; g?: string; solo?: boolean }, device: string): Promise<string> {
  const bytes = new TextEncoder().encode(`${pair.k}:${pair.l ?? ''}:${(pair.g ?? '').toLowerCase()}:${!!pair.solo}:${device}`)
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('')
}
