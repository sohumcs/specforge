import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Graph } from '../../lib/types'
import { edge, mockFetch, node, renderWithProviders } from '../../test/utils'
import { Board } from './Board'

afterEach(() => vi.unstubAllGlobals())

const r = node('requirement', { key: 'REQ-001', title: 'Order food' })
const s1 = node('story', { key: 'US-001', title: 'Customer orders', status: 'todo' })
const s2 = node('story', { key: 'US-002', title: 'Customer pays', status: 'done' })
const t1 = node('test', { key: 'TST-001', title: 'Order e2e', status: 'in_progress' })
const graph: Graph = { nodes: [r, s1, s2, t1], edges: [edge(r, s1, 'refines'), edge(s1, t1, 'verified_by')] }
const rollup = (done: number, total: number) => ({ done, total, percent: Math.round((100 * done) / total), by_status: { todo: 0, in_progress: 0, in_review: 0, done } })
const progress = {
  overall: rollup(1, 3), stories: rollup(1, 2), tests: rollup(0, 1),
  requirements: [{ id: r.id, key: 'REQ-001', title: 'Order food', ...rollup(1, 3) }],
  modules: [],
}

describe('Board', () => {
  it('places stories in their status columns and shows roll-ups', async () => {
    mockFetch([{ match: /progress$/, body: progress }])
    renderWithProviders(<Board graph={graph} blueprintId="bp" canEdit onOpen={() => {}} />)
    expect(within(screen.getByRole('region', { name: 'To do column' })).getByText('Customer orders')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Done column' })).getByText('Customer pays')).toBeInTheDocument()
    expect(screen.queryByText('Order e2e')).not.toBeInTheDocument() // tests hidden in "Stories" view
    await userEvent.click(screen.getByRole('button', { name: 'Tests' }))
    expect(within(screen.getByRole('region', { name: 'In progress column' })).getByText('Order e2e')).toBeInTheDocument()
    expect(await screen.findByRole('progressbar', { name: 'REQ-001 progress' })).toHaveAttribute('aria-valuenow', '33')
  })

  it('changing status (keyboard-accessible select) calls the API', async () => {
    const { calls } = mockFetch([
      { match: /progress$/, body: progress },
      { match: /nodes\/.+\/status/, method: 'PATCH', body: { ...s1, status: 'in_review' } },
    ])
    renderWithProviders(<Board graph={graph} blueprintId="bp" canEdit onOpen={() => {}} />)
    await userEvent.selectOptions(screen.getByLabelText('Status of US-001'), 'in_review')
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'in_review' }))
  })

  it('viewers see no drag handles or status selects', () => {
    mockFetch([{ match: /progress$/, body: progress }])
    renderWithProviders(<Board graph={graph} blueprintId="bp" canEdit={false} onOpen={() => {}} />)
    expect(screen.queryByLabelText('Status of US-001')).not.toBeInTheDocument()
  })
})
