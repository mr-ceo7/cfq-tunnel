// Vercel Routing Middleware that proxies /api and /auth to a backend behind a Cloudflare quick tunnel.
// cfq-tunnel keeps the tunnel's current address in Edge Config (item `api_origin`); this reads it,
// caches it for 30 s, and looks again (retrying once) when the tunnel has moved.
//
// Project settings: EDGE_CONFIG (the Edge Config connection string) and, optionally, API_ORIGIN as a fallback.
// Works with any framework Vercel hosts: save as middleware.js in the project root.

export const config = { matcher: ['/api/:path*', '/auth/:path*'] }

const DROP = ['host', 'connection', 'content-length']
const CACHE_MS = 30_000
let cached = { origin: '', at: 0 }

async function apiOrigin(fresh) {
  if (!fresh && cached.origin && Date.now() - cached.at < CACHE_MS) return cached.origin
  const store = process.env.EDGE_CONFIG
  if (store) {
    try {
      const url = new URL(store)
      url.pathname = `${url.pathname.replace(/\/$/, '')}/item/api_origin`
      const response = await fetch(url, { cache: 'no-store' })
      if (response.ok) cached = { origin: String(await response.json()).replace(/\/$/, ''), at: Date.now() }
    } catch { /* keep the last known address */ }
  }
  return cached.origin || (process.env.API_ORIGIN || '').replace(/\/$/, '')
}

/** @param {Request} request */
export default async function middleware(request) {
  const url = new URL(request.url)
  const headers = new Headers(request.headers)
  for (const name of DROP) headers.delete(name)
  const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer()

  const send = async (origin) => {
    const response = await fetch(origin + url.pathname + url.search, { method: request.method, headers, body, redirect: 'manual' })
    // Cloudflare compresses responses and fetch has already decompressed this one: passing the original
    // Content-Encoding on makes browsers fail with ERR_CONTENT_DECODING_FAILED.
    const out = new Headers(response.headers)
    out.delete('content-encoding')
    out.delete('content-length')
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers: out })
  }

  const origin = await apiOrigin(false)
  if (!origin) return new Response('The backend address is not configured', { status: 503 })
  try {
    const response = await send(origin)
    if (response.status !== 530) return response // 530: no tunnel at that address any more
  } catch { /* look the address up again */ }
  const fresh = await apiOrigin(true)
  if (fresh === origin) return new Response('The backend is restarting. Try again in a moment.', { status: 503 })
  return send(fresh)
}
