import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockFetch } from '../test/utils'
import { api, ApiError, getAccessToken, setAccessToken } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  setAccessToken(null)
})

describe('api client', () => {
  it('prefixes /api/v1, sends the bearer token and JSON', async () => {
    const { calls } = mockFetch([{ match: /\/api\/v1\/projects$/, method: 'POST', body: { id: 'p1' } }])
    setAccessToken('tok')
    await expect(api('/projects', { method: 'POST', json: { name: 'x' } })).resolves.toEqual({ id: 'p1' })
    expect(calls[0].url).toBe('/api/v1/projects')
    expect(calls[0].headers.get('Authorization')).toBe('Bearer tok')
    expect(calls[0].headers.get('Content-Type')).toBe('application/json')
    expect(calls[0].body).toEqual({ name: 'x' })
  })

  it('maps the {code,message,details} error envelope to ApiError', async () => {
    mockFetch([{ match: /generate/, status: 429, body: { code: 'RATE_LIMITED', message: 'Slow down', details: { scope: 'ip' } } }])
    const err = await api('/blueprints/b/generate', { method: 'POST' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 429, code: 'RATE_LIMITED', message: 'Slow down', details: { scope: 'ip' } })
  })

  it('refreshes once on 401 and retries with the new token', async () => {
    let first = true
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) return new Response(JSON.stringify({ access_token: 'new' }), { status: 200 })
      const auth = new Headers(init?.headers).get('Authorization')
      if (first) {
        first = false
        return new Response(JSON.stringify({ code: 'TOKEN_EXPIRED', message: 'expired' }), { status: 401 })
      }
      return new Response(JSON.stringify({ auth }), { status: 200 })
    })
    vi.stubGlobal('fetch', fn)
    setAccessToken('old')
    await expect(api('/me')).resolves.toEqual({ auth: 'Bearer new' })
    expect(getAccessToken()).toBe('new')
  })

  it('concurrent 401s share one refresh call', async () => {
    let refreshes = 0
    const tokens = new Set<string>()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/refresh')) {
        refreshes++
        await new Promise((r) => setTimeout(r, 10))
        return new Response(JSON.stringify({ access_token: 'fresh' }), { status: 200 })
      }
      const auth = new Headers(init?.headers).get('Authorization') ?? ''
      if (auth !== 'Bearer fresh') return new Response('{}', { status: 401 })
      tokens.add(auth)
      return new Response('{}', { status: 200 })
    }))
    await Promise.all([api('/a'), api('/b'), api('/c')])
    expect(refreshes).toBe(1)
    expect(tokens).toEqual(new Set(['Bearer fresh']))
  })

  it('a failed refresh surfaces the original 401 and clears the token', async () => {
    mockFetch([
      { match: /auth\/refresh/, status: 401, body: { code: 'REFRESH_INVALID', message: 'nope' } },
      { match: /\/me/, status: 401, body: { code: 'TOKEN_EXPIRED', message: 'expired' } },
    ])
    setAccessToken('old')
    await expect(api('/me')).rejects.toMatchObject({ status: 401, code: 'TOKEN_EXPIRED' })
    expect(getAccessToken()).toBeNull()
  })

  it('does not try to refresh for auth endpoints', async () => {
    const { calls } = mockFetch([{ match: /auth\/login/, status: 401, body: { code: 'INVALID_CREDENTIALS', message: 'bad' } }])
    await expect(api('/auth/login', { method: 'POST', json: {} })).rejects.toMatchObject({ code: 'INVALID_CREDENTIALS' })
    expect(calls).toHaveLength(1)
  })

  it('sends Idempotency-Key when asked and handles 204', async () => {
    const { calls } = mockFetch([{ match: /x/, status: 204, body: null }])
    await expect(api('/x', { method: 'DELETE', idempotencyKey: 'k1' })).resolves.toBeUndefined()
    expect(calls[0].headers.get('Idempotency-Key')).toBe('k1')
  })
})
