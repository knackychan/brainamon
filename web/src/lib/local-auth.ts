// A trusted launcher supplies a per-run credential in the fragment, which is removed immediately.
// Headers cover fetch; a per-client service worker supplies headers for SSE, images and video.
export async function ready(): Promise<void> {
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname)) return
  const supplied = location.hash.startsWith('#cm-auth=') ? location.hash.slice(9) : ''
  if (supplied) history.replaceState(null, '', location.pathname + location.search)
  if (supplied && /^[A-Za-z0-9_-]{43}$/.test(supplied)) sessionStorage.setItem('cm-auth', supplied)
  const token = sessionStorage.getItem('cm-auth') || ''
  const original = window.fetch.bind(window)
  window.fetch = (input, init) => {
    const request = new Request(input, init)
    if (new URL(request.url).origin === location.origin && token) request.headers.set('Authorization', `Bearer ${token}`)
    if (new URL(request.url).origin === location.origin && location.pathname === '/mobile.html') request.headers.set('X-Brainamon-Phone', '1')
    return original(request)
  }
  if (!token || !('serviceWorker' in navigator)) return
  navigator.serviceWorker.addEventListener('message', e => {
    if (e.source === navigator.serviceWorker.controller && e.data?.type === 'local-auth-needed') e.ports[0]?.postMessage(token)
  })
  const phone = location.pathname === '/mobile.html'
  await navigator.serviceWorker.register(phone ? '/sw.js' : '/auth-sw.js', { scope: phone ? '/mobile.html' : '/' })
  await navigator.serviceWorker.ready
  if (!navigator.serviceWorker.controller) await new Promise<void>(resolve => navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true }))
  const authorize = () => new Promise<void>(resolve => {
    const channel = new MessageChannel()
    channel.port1.onmessage = () => { channel.port1.close(); resolve() }
    navigator.serviceWorker.controller?.postMessage({ type: 'local-auth', token }, [channel.port2])
  })
  await authorize()
  navigator.serviceWorker.addEventListener('controllerchange', authorize)
}
