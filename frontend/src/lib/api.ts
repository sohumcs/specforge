/**
 * Fetch wrapper for the SPECForge API.
 *
 * Tokens: the short-lived access token lives only in memory (never
 * localStorage, so XSS can't steal a long-lived credential). The refresh token
 * is an httpOnly cookie the browser sends to /api/v1/auth/* automatically.
 * On a 401 we refresh once, de-duplicated across concurrent requests, and retry.
 */

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null
const listeners = new Set<(token: string | null) => void>()

export function setAccessToken(token: string | null): void {
  accessToken = token
  listeners.forEach((l) => l(token))
}

export function getAccessToken(): string | null {
  return accessToken
}

export function onTokenChange(listener: (token: string | null) => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Ask for a new access token using the refresh cookie. Never throws. */
export function refreshAccessToken(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
    .then(async (r) => {
      if (!r.ok) {
        setAccessToken(null)
        return false
      }
      setAccessToken((await r.json()).access_token)
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

async function toError(r: Response): Promise<ApiError> {
  try {
    const body = await r.json()
    return new ApiError(r.status, body.code ?? 'HTTP_ERROR', body.message ?? r.statusText, body.details)
  } catch {
    return new ApiError(r.status, 'HTTP_ERROR', r.statusText || 'Request failed')
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  json?: unknown
  idempotencyKey?: string
  raw?: boolean // return the Response (downloads)
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const { json, idempotencyKey, raw, headers, ...init } = opts
  const h = new Headers(headers)
  if (accessToken) h.set('Authorization', `Bearer ${accessToken}`)
  if (json !== undefined) h.set('Content-Type', 'application/json')
  if (idempotencyKey) h.set('Idempotency-Key', idempotencyKey)

  const r = await fetch(path.startsWith('/') && !path.startsWith(API_BASE) ? `${API_BASE}${path}` : path, {
    ...init,
    headers: h,
    credentials: 'include',
    body: json !== undefined ? JSON.stringify(json) : undefined,
  })

  if (r.status === 401 && !retried && !path.startsWith('/auth/')) {
    if (await refreshAccessToken()) return api<T>(path, opts, true)
  }
  if (!r.ok) throw await toError(r)
  if (raw) return r as unknown as T
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

/** Download a binary/text export with auth and save it under the server's filename. */
export async function download(path: string): Promise<void> {
  const r = await api<Response>(path, { raw: true })
  const blob = await r.blob()
  const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? 'export'
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.append(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
