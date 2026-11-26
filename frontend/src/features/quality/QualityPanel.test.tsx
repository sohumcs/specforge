import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { QualityReport } from '../../lib/types'
import { mockFetch, renderWithProviders } from '../../test/utils'
import { QualityPanel } from './QualityPanel'

afterEach(() => vi.unstubAllGlobals())

const report: QualityReport = {
  report_id: 'r1',
  score: 92,
  created_at: '2026-11-26T10:00:00Z',
  breakdown: {
    ml: 'ok',
    node_count: 49,
    categories: [
      { category: 'traceability', score: 100, weight: 35, checks: 81, issues: 0 },
      { category: 'completeness', score: 90, weight: 25, checks: 18, issues: 1 },
      { category: 'consistency', score: 75, weight: 20, checks: -1, issues: 1 },
      { category: 'uniqueness', score: 100, weight: 10, checks: -1, issues: 0 },
      { category: 'conventions', score: 100, weight: 10, checks: 69, issues: 0 },
    ],
  },
  issues: [
    { id: 'i1', rule_code: 'CON-001', category: 'consistency', severity: 'high', message: 'REQ-004 and REQ-006 may contradict each other', fix_hint: 'Rewrite one', node_ids: ['a', 'b'], node_keys: ['REQ-004', 'REQ-006'], resolved: false, fixable: true, details: { nli_contradiction: 0.998, cue: 'negation in one statement only' } },
    { id: 'i2', rule_code: 'CP-002', category: 'completeness', severity: 'low', message: 'Entity Payment has no delete endpoint', fix_hint: 'Add it', node_ids: ['c'], node_keys: ['ENT-003'], resolved: false, fixable: true, details: {} },
    { id: 'i3', rule_code: 'TR-004', category: 'traceability', severity: 'medium', message: 'Old orphan', fix_hint: 'Link it', node_ids: ['d'], node_keys: ['MOD-009'], resolved: true, fixable: true, details: {} },
  ],
}

describe('QualityPanel', () => {
  it('shows score, breakdown and open issues with ML evidence', async () => {
    mockFetch([{ match: /quality$/, body: report }])
    renderWithProviders(<QualityPanel blueprintId="bp" canEdit onShowNodes={() => {}} />)
    expect(await screen.findByLabelText('Quality score 92 out of 100')).toBeInTheDocument()
    expect(screen.getByRole('meter', { name: 'Consistency score' })).toHaveAttribute('aria-valuenow', '75')
    expect(screen.getByText(/2 open/)).toBeInTheDocument()
    expect(screen.getByText(/NLI contradiction 1.00/)).toBeInTheDocument()
    expect(screen.queryByText('Old orphan')).not.toBeInTheDocument() // resolved hidden by default
    await userEvent.click(screen.getByLabelText(/show resolved/i))
    expect(screen.getByText('Old orphan')).toBeInTheDocument()
  })

  it('filters by category and jumps to nodes', async () => {
    mockFetch([{ match: /quality$/, body: report }])
    const onShow = vi.fn()
    renderWithProviders(<QualityPanel blueprintId="bp" canEdit onShowNodes={onShow} />)
    await screen.findByText(/may contradict/)
    await userEvent.selectOptions(screen.getByLabelText('Filter by category'), 'completeness')
    expect(screen.queryByText(/may contradict/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Show ENT-003/ }))
    expect(onShow).toHaveBeenCalledWith(['c'])
  })

  it('dismiss calls the API; viewers get no edit buttons', async () => {
    const { calls } = mockFetch([
      { match: /quality$/, body: report },
      { match: /issues\/i2\/dismiss/, method: 'POST', body: { score: 95 } },
    ])
    const { unmount } = renderWithProviders(<QualityPanel blueprintId="bp" canEdit onShowNodes={() => {}} />)
    await screen.findByText(/no delete endpoint/)
    await userEvent.click(screen.getAllByRole('button', { name: /dismiss/i })[1])
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/issues/i2/dismiss') && c.method === 'POST')).toBe(true))
    unmount()

    renderWithProviders(<QualityPanel blueprintId="bp" canEdit={false} onShowNodes={() => {}} />)
    await screen.findByText(/no delete endpoint/)
    expect(screen.queryByRole('button', { name: /fix with ai/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /re-verify/i })).not.toBeInTheDocument()
  })

  it('offers verification when the blueprint was never verified', async () => {
    mockFetch([{ match: /quality$/, status: 404, body: { code: 'NOT_VERIFIED', message: 'not yet' } }])
    renderWithProviders(<QualityPanel blueprintId="bp" canEdit onShowNodes={() => {}} />)
    expect(await screen.findByText('Not verified yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /verify now/i })).toBeInTheDocument()
  })
})
