import type { GraphEdge, GraphNode, NodeType } from '../../lib/types'

/**
 * Deterministic layered layout (no layout library).
 *
 * Columns follow the trace direction: risk | requirement | story | module | api |
 * entity, with tests after the APIs they verify. Inside each column, nodes are
 * ordered by the barycentre (mean row) of their neighbours in the adjacent
 * columns: a few down/up sweeps of the classic Sugiyama heuristic. It cuts
 * edge crossings a lot, and the same graph always gets the same layout.
 */
export const COLUMN: Record<NodeType, number> = {
  risk: 0,
  requirement: 1,
  story: 2,
  module: 3,
  api: 4,
  entity: 5,
  test: 6,
}

export const NODE_W = 210
export const NODE_H = 62
const COL_GAP = 300
const ROW_GAP = 82

export interface Positioned {
  id: string
  x: number
  y: number
}

export function layout(nodes: GraphNode[], edges: GraphEdge[], sweeps = 4): Map<string, Positioned> {
  const cols = new Map<number, GraphNode[]>()
  for (const n of nodes) {
    const c = COLUMN[n.type]
    if (!cols.has(c)) cols.set(c, [])
    cols.get(c)!.push(n)
  }
  const neighbours = new Map<string, string[]>()
  const ids = new Set(nodes.map((n) => n.id))
  for (const e of edges) {
    if (!ids.has(e.src_id) || !ids.has(e.dst_id) || e.type === 'relates_to') continue
    ;(neighbours.get(e.src_id) ?? neighbours.set(e.src_id, []).get(e.src_id)!).push(e.dst_id)
    ;(neighbours.get(e.dst_id) ?? neighbours.set(e.dst_id, []).get(e.dst_id)!).push(e.src_id)
  }

  const order = [...cols.keys()].sort((a, b) => a - b)
  const row = new Map<string, number>()
  for (const c of order) cols.get(c)!.forEach((n, i) => row.set(n.id, i))

  const reorder = (c: number) => {
    const list = cols.get(c)!
    const bary = (n: GraphNode) => {
      const rs = (neighbours.get(n.id) ?? []).map((m) => row.get(m)).filter((r): r is number => r !== undefined)
      return rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : (row.get(n.id) ?? 0)
    }
    const scored = list.map((n, i) => ({ n, b: bary(n), i }))
    scored.sort((a, b) => a.b - b.b || a.i - b.i)
    cols.set(c, scored.map((s) => s.n))
    cols.get(c)!.forEach((n, i) => row.set(n.id, i))
  }
  for (let s = 0; s < sweeps; s++) {
    for (const c of s % 2 === 0 ? order.slice(1) : [...order].reverse().slice(1)) reorder(c)
  }

  const tallest = Math.max(1, ...order.map((c) => cols.get(c)!.length))
  const out = new Map<string, Positioned>()
  order.forEach((c, ci) => {
    const list = cols.get(c)!
    const offset = ((tallest - list.length) * ROW_GAP) / 2 // centre shorter columns
    list.forEach((n, i) => out.set(n.id, { id: n.id, x: ci * COL_GAP, y: offset + i * ROW_GAP }))
  })
  return out
}

/** Count edges whose endpoints are in non-monotonic order (used by tests). */
export function crossings(pos: Map<string, Positioned>, edges: GraphEdge[]): number {
  const es = edges
    .map((e) => [pos.get(e.src_id), pos.get(e.dst_id)] as const)
    .filter((p): p is readonly [Positioned, Positioned] => !!p[0] && !!p[1] && p[0].x !== p[1].x)
  let count = 0
  for (let i = 0; i < es.length; i++) {
    for (let j = i + 1; j < es.length; j++) {
      const [a1, a2] = es[i]
      const [b1, b2] = es[j]
      if (a1.x === b1.x && a2.x === b2.x && (a1.y - b1.y) * (a2.y - b2.y) < 0) count++
    }
  }
  return count
}
