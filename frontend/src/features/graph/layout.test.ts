import { describe, expect, it } from 'vitest'

import { edge, node } from '../../test/utils'
import { COLUMN, crossings, layout } from './layout'

describe('layered layout', () => {
  it('puts each node type in its own column, in trace order', () => {
    const r = node('requirement')
    const s = node('story')
    const m = node('module')
    const a = node('api')
    const e = node('entity')
    const t = node('test')
    const k = node('risk')
    const pos = layout([t, e, a, m, s, r, k], [])
    const xs = [k, r, s, m, a, e, t].map((n) => pos.get(n.id)!.x)
    expect(xs).toEqual([...xs].sort((p, q) => p - q))
    expect(new Set(xs).size).toBe(7)
    expect(COLUMN.risk).toBeLessThan(COLUMN.requirement)
  })

  it('is deterministic', () => {
    const nodes = [node('requirement'), node('requirement'), node('story'), node('story')]
    const edges = [edge(nodes[0], nodes[3], 'refines'), edge(nodes[1], nodes[2], 'refines')]
    expect([...layout(nodes, edges)]).toEqual([...layout(nodes, edges)])
  })

  it('barycentre sweeps remove crossings a naive order would have', () => {
    // r1 -> s2, r2 -> s1 crosses if stories keep input order.
    const r1 = node('requirement')
    const r2 = node('requirement')
    const s1 = node('story')
    const s2 = node('story')
    const s3 = node('story')
    const edges = [edge(r1, s2, 'refines'), edge(r2, s1, 'refines'), edge(r2, s3, 'refines')]
    const naive = layout([r1, r2, s1, s2, s3], edges, 0)
    const swept = layout([r1, r2, s1, s2, s3], edges)
    expect(crossings(naive, edges)).toBeGreaterThan(0)
    expect(crossings(swept, edges)).toBe(0)
  })

  it('ignores entity relations and edges to hidden nodes', () => {
    const a = node('entity')
    const b = node('entity')
    const ghost = node('story')
    const pos = layout([a, b], [edge(a, b, 'relates_to'), edge(ghost, a, 'refines')])
    expect(pos.size).toBe(2)
  })
})
