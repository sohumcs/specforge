import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Brain, EyeOff, LocateFixed, RotateCcw, ShieldCheck, Wand2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JobProgress } from '../../components/JobProgress'
import { Badge, Button, Card, EmptyState, ErrorState, ScoreGauge, Skeleton, errorMessage } from '../../components/ui'
import { ApiError } from '../../lib/api'
import { CATEGORY_LABELS } from '../../lib/meta'
import { startJob, useDismissIssue, useInvalidateBlueprint, useQuality } from '../../lib/queries'
import type { Job, QualityIssue } from '../../lib/types'
import { useJob } from '../../lib/useJob'

const SEVERITY_STYLE = {
  high: 'bg-rose-100 text-rose-800',
  medium: 'bg-amber-100 text-amber-900',
  low: 'bg-slate-100 text-slate-700',
}

interface Props {
  blueprintId: string
  canEdit: boolean
  onShowNodes: (ids: string[]) => void
}

export function QualityPanel({ blueprintId, canEdit, onShowNodes }: Props) {
  const quality = useQuality(blueprintId)
  const invalidate = useInvalidateBlueprint(blueprintId)
  const [verifyJob, setVerifyJob] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const job = useJob(verifyJob, () => {
    setVerifyJob(null)
    invalidate()
  })
  const verify = async () => {
    setError(null)
    try {
      setVerifyJob((await startJob(`/blueprints/${blueprintId}/verify`)).job_id)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  if (quality.isLoading) return <div className="space-y-3 p-4"><Skeleton className="h-40" /><Skeleton className="h-64" /></div>
  if (quality.error instanceof ApiError && quality.error.code === 'NOT_VERIFIED') {
    return (
      <div className="p-4">
        <EmptyState title="Not verified yet" action={canEdit && <Button onClick={verify} loading={!!verifyJob}><ShieldCheck className="size-4" aria-hidden /> Verify now</Button>}>
          Verification runs 12 rules plus duplicate (embeddings) and contradiction (NLI) checks, then scores the blueprint 0–100.
        </EmptyState>
        {verifyJob && <Card className="mt-4 p-4"><JobProgress job={job} steps={['rule_check', 'ml_check', 'scoring']} /></Card>}
      </div>
    )
  }
  if (quality.error || !quality.data) return <div className="p-4"><ErrorState error={quality.error} onRetry={() => quality.refetch()} /></div>

  const q = quality.data
  return (
    <div className="grid gap-4 p-4 xl:grid-cols-[320px_1fr]">
      {notice && (
        <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 ring-1 ring-emerald-200 xl:col-span-2">
          {notice}
        </p>
      )}
      <div className="space-y-4">
        <Card className="p-4">
          <div className="flex items-center gap-4">
            <ScoreGauge score={q.score} />
            <div className="text-sm">
              <p className="font-semibold">Blueprint Quality Score</p>
              <p className="text-slate-600">{q.breakdown.node_count} nodes checked</p>
              <p className="mt-1 flex items-center gap-1 text-slate-600">
                <Brain className="size-4" aria-hidden /> ML checks: {q.breakdown.ml === 'ok' ? 'on' : 'unavailable (rules only)'}
              </p>
              <p className="text-xs text-slate-500">{new Date(q.created_at).toLocaleString()}</p>
            </div>
          </div>
          {canEdit && (
            <Button variant="secondary" size="sm" className="mt-3 w-full" onClick={verify} loading={!!verifyJob}>
              <RotateCcw className="size-4" aria-hidden /> Re-verify
            </Button>
          )}
          {verifyJob && <div className="mt-3"><JobProgress job={job} steps={['rule_check', 'ml_check', 'scoring']} /></div>}
          {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
        </Card>
        <Card className="p-4">
          <h3 className="text-sm font-semibold">Breakdown</h3>
          <ul className="mt-3 space-y-3">
            {q.breakdown.categories.map((c) => (
              <li key={c.category}>
                <div className="flex justify-between text-sm">
                  <span>{CATEGORY_LABELS[c.category]} <span className="text-xs text-slate-500">×{c.weight}%</span></span>
                  <span className="tabular-nums font-medium">{c.score}</span>
                </div>
                <div className="mt-1 h-2 rounded-full bg-slate-200" role="meter" aria-label={`${CATEGORY_LABELS[c.category]} score`} aria-valuenow={c.score} aria-valuemin={0} aria-valuemax={100}>
                  <div className={clsx('h-2 rounded-full', c.score >= 90 ? 'bg-emerald-500' : c.score >= 75 ? 'bg-amber-500' : 'bg-rose-500')} style={{ width: `${c.score}%` }} />
                </div>
                <p className="mt-0.5 text-xs text-slate-500">{c.issues} issue{c.issues === 1 ? '' : 's'}{c.checks > 0 ? ` · ${c.checks} checks` : ''}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <IssueList issues={q.issues} blueprintId={blueprintId} canEdit={canEdit} onShowNodes={onShowNodes} onFixed={setNotice} />
    </div>
  )
}

function IssueList({ issues, blueprintId, canEdit, onShowNodes, onFixed }: { issues: QualityIssue[]; blueprintId: string; canEdit: boolean; onShowNodes: (ids: string[]) => void; onFixed: (msg: string) => void }) {
  const [category, setCategory] = useState('all')
  const [showResolved, setShowResolved] = useState(false)
  const shown = useMemo(
    () => issues.filter((i) => (category === 'all' || i.category === category) && (showResolved || !i.resolved)),
    [issues, category, showResolved],
  )
  const open = issues.filter((i) => !i.resolved).length
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
        <h3 className="font-semibold">Issues <span className="text-slate-500">({open} open)</span></h3>
        <label className="ml-auto text-sm">
          <span className="sr-only">Filter by category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1">
            <option value="all">All categories</option>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1 text-sm text-slate-700">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> show resolved
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="p-6 text-center text-sm text-slate-600">{open === 0 ? 'No open issues. This blueprint passes every check. 🎉' : 'Nothing matches this filter.'}</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {shown.map((i) => <IssueRow key={i.id} issue={i} blueprintId={blueprintId} canEdit={canEdit} onShowNodes={onShowNodes} onFixed={onFixed} />)}
        </ul>
      )}
    </Card>
  )
}

function IssueRow({ issue, blueprintId, canEdit, onShowNodes, onFixed }: { issue: QualityIssue; blueprintId: string; canEdit: boolean; onShowNodes: (ids: string[]) => void; onFixed: (msg: string) => void }) {
  const qc = useQueryClient()
  const invalidate = useInvalidateBlueprint(blueprintId)
  const dismiss = useDismissIssue(blueprintId)
  const [jobId, setJobId] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const job = useJob(jobId, (j) => {
    setJobId(null)
    setOutcome(j)
    if (j.status === 'succeeded' && j.result) {
      onFixed(`Fixed ${issue.rule_code} (${issue.node_keys.join(', ')}): ${String(j.result.action)} · via ${String(j.result.provider)} · score ${String(j.result.score_before)} → ${String(j.result.score_after)}`)
    }
    invalidate()
    qc.invalidateQueries({ queryKey: ['similar'] })
  })
  const fix = async () => {
    setError(null)
    setOutcome(null)
    try {
      setJobId((await startJob(`/issues/${issue.id}/fix`)).job_id)
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  const nli = issue.details.nli_contradiction as number | undefined
  const sim = issue.details.similarity as number | undefined
  return (
    <li className={clsx('p-3', issue.resolved && 'bg-slate-50 opacity-70')}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={SEVERITY_STYLE[issue.severity]}>{issue.severity}</Badge>
        <span className="font-mono text-xs text-slate-600">{issue.rule_code}</span>
        <span className="text-xs text-slate-500">{CATEGORY_LABELS[issue.category]}</span>
        {issue.resolved && <Badge className="bg-emerald-100 text-emerald-800">resolved</Badge>}
      </div>
      <p className="mt-1 text-sm text-slate-900">{issue.message}</p>
      <p className="text-sm text-slate-600">→ {issue.fix_hint}</p>
      {(nli !== undefined || sim !== undefined) && (
        <p className="mt-1 text-xs text-slate-500">
          {nli !== undefined && <>NLI contradiction {nli.toFixed(2)} · cue: {String(issue.details.cue)} · </>}
          {sim !== undefined && <>cosine similarity {sim.toFixed(2)}</>}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {issue.node_ids.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => onShowNodes(issue.node_ids)}>
            <LocateFixed className="size-4" aria-hidden /> Show {issue.node_keys.join(', ')}
          </Button>
        )}
        {canEdit && !issue.resolved && issue.fixable && (
          <Button size="sm" onClick={fix} loading={!!jobId}>
            <Wand2 className="size-4" aria-hidden /> Fix with AI
          </Button>
        )}
        {canEdit && (
          <Button size="sm" variant="ghost" onClick={() => dismiss.mutate({ id: issue.id, restore: issue.resolved })} loading={dismiss.isPending}>
            <EyeOff className="size-4" aria-hidden /> {issue.resolved ? 'Restore' : 'Dismiss'}
          </Button>
        )}
      </div>
      {jobId && <div className="mt-2 text-sm text-slate-600" aria-live="polite">{job?.step === 'fixing' ? 'Applying fix…' : job?.step ? `Re-checking (${job.step.replace('_', ' ')})…` : 'Queued…'}</div>}
      {outcome?.status === 'succeeded' && outcome.result && (
        <p role="status" className="mt-2 rounded-md bg-emerald-50 p-2 text-sm text-emerald-900">
          {String(outcome.result.action)} · via {String(outcome.result.provider)} · score {String(outcome.result.score_before)} → <b>{String(outcome.result.score_after)}</b>
        </p>
      )}
      {outcome && outcome.status !== 'succeeded' && <p role="alert" className="mt-2 rounded-md bg-amber-50 p-2 text-sm text-amber-900">{outcome.error?.message}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
    </li>
  )
}
