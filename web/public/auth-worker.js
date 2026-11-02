// Credentials stay in worker memory, indexed by the sending client. No discovery message exists.
const localCredentials = new Map()
self.addEventListener('message', e => {
  if (e.data?.type === 'local-auth' && e.source?.id && /^[A-Za-z0-9_-]{43}$/.test(e.data.token)) {
    localCredentials.set(e.source.id, e.data.token)
    e.ports[0]?.postMessage('ready')
  }
})
function authenticatedLocal(e) {
  const url = new URL(e.request.url)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.searchParams.get('m') === '1') return false
  if (url.origin !== location.origin || !/^\/(api|thumb|files)\//.test(url.pathname)) return false
  e.respondWith((async () => {
    let token = localCredentials.get(e.clientId)
    if (!token) {
      const client = await self.clients.get(e.clientId)
      if (client) token = await new Promise(resolve => {
        const channel = new MessageChannel()
        const timer = setTimeout(() => { channel.port1.close(); resolve('') }, 2000)
        channel.port1.onmessage = e => { clearTimeout(timer); channel.port1.close(); resolve(e.data) }
        client.postMessage({ type: 'local-auth-needed' }, [channel.port2])
      })
    }
    const headers = new Headers(e.request.headers)
    const source = await self.clients.get(e.clientId)
    if (source && new URL(source.url).pathname === '/mobile.html') headers.set('X-Brainamon-Phone', '1')
    if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) headers.set('Authorization', `Bearer ${token}`)
    return fetch(new Request(e.request, { headers, mode: 'same-origin', redirect: 'error', cache: 'no-store' }))
  })())
  return true
}
