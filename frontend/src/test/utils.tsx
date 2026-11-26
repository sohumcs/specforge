import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import type { Graph, GraphNode, NodeType } from '../lib/types'

type Route = { match: RegExp; method?: string; status?: number; body: unknown }

/** Minimal fetch mock: first matching route wins; records every call. */
export function mockFetch(routes: Route[]) {
  const calls: { url: string; method: string; body?: unknown; headers: Headers }[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined, headers: new Headers(init?.headers) })
    const r = routes.find((x) => x.match.test(url) && (!x.method || x.method === method))
    if (!r) return new Response(JSON.stringify({ code: 'NOT_FOUND', message: `no mock for ${method} ${url}` }), { status: 404 })
    return new Response(r.status === 204 ? null : JSON.stringify(r.body), { status: r.status ?? 200, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return { fn, calls }
}

export function renderWithProviders(ui: ReactElement, { route = '/' } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

let n = 0
export function node(type: NodeType, extra: Partial<GraphNode> = {}): GraphNode {
  n += 1
  return { id: `n${n}`, blueprint_id: 'bp', type, key: `${type.slice(0, 3).toUpperCase()}-${String(n).padStart(3, '0')}`, title: `${type} ${n}`, body: {}, status: 'todo', stale: false, ...extra }
}

export function edge(src: GraphNode, dst: GraphNode, type: Graph['edges'][number]['type']) {
  return { id: `${src.id}-${dst.id}`, src_id: src.id, dst_id: dst.id, type, body: {} }
}
