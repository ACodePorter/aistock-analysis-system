// Unified API client
// Uses VITE_API_BASE if provided; otherwise relies on same-origin (dev proxy in vite.config.ts)

export const API_BASE = (import.meta as any).env?.VITE_API_BASE?.replace(/\/$/,'') || ''

export interface ApiOptions extends RequestInit {
  json?: any
}

export async function apiFetch<T=any>(path:string, opts:ApiOptions = {}): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const headers: Record<string,string> = {
    Accept: 'application/json',
    ...(opts.headers as any || {})
  }
  let body = opts.body
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  }
  const res = await fetch(url, { ...opts, headers, body })
  if (!res.ok) {
    const txt = await res.text().catch(()=> res.statusText)
    throw new Error(`API ${res.status} ${res.statusText}: ${txt}`)
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  // fallback text
  return (await res.text()) as any
}
