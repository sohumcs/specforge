import clsx from 'clsx'
import { ArrowLeft, Download, FileJson, FileText, RefreshCw } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { JobProgress } from '../components/JobProgress'
import { Badge, Button, Card, ErrorState, ProviderBadge, ScoreGauge, Skeleton, Spinner, errorMessage } from '../components/ui'
import { Board } from '../features/board/Board'
import { GraphView, type ImpactWave } from '../features/graph/GraphView'
import { NodePanel } from '../features/graph/NodePanel'
import { QualityPanel } from '../features/quality/QualityPanel'
import { download } from '../lib/api'
import { NODE_META, NODE_TYPES } from '../lib/meta'
import { startJob, useBlueprint, useGraph, useInvalidateBlueprint, useProject, useQuality, useTrace } from '../lib/queries'
import type { Impact } from '../lib/types'
import { useJob } from '../lib/useJob'

const TABS = [
  { id: 'graph', label: 'Graph' },
  { id: 'quality', label: 'Quality' },
  { id: 'board', label: 'Delivery' },
  { id: 'outline', label: 'Outline' },
  { id: 'overview', label: 'Brief & export' },
] as const
type Tab = (typeof TABS)[number]['id']

export default function BlueprintPage() {
  const { blueprintId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'graph'
  const selectedId = params.get('node')
  const bp = useBlueprint(blueprintId)
  const graph = useGraph(blueprintId)
  const quality = useQuality(blueprintId)
  const project = useProject(bp.data?.project_id ?? '')
  const trace = useTrace(selectedId)
  const invalidate = useInvalidateBlueprint(blueprintId)
  const canEdit = project.data?.my_role === 'editor' || project.data?.my_role === 'owner'

  const [impact, setImpact] = useState<ImpactWave | null>(null)
  const [highlight, setHighlight] = useState<Set<string>>(new Set())
  const [regenJob, setRegenJob] = useState<string | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)
  const regen = useJob(regenJob, () => {
    setRegenJob(null)
    setImpact(null)
    invalidate()
  })

  const setParam = useCallback(
    (updates: Record<string, string | null>) =>
      setParams((p) => {
        const next = new URLSearchParams(p)
        Object.entries(updates).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)))
        return next
      }, { replace: true }),
    [setParams],
  )
  const select = useCallback((id: string | null) => setParam({ node: id }), [setParam])

  const openIssues = useMemo(() => (quality.data?.issues ?? []).filter((i) => !i.resolved), [quality.data])
  const issueCountById = useMemo(() => {
    const m: Record<string, number> = {}
    openIssues.forEach((i) => i.node_ids.forEach((id) => (m[id] = (m[id] ?? 0) + 1)))
    return m
  }, [openIssues])
  const traceIds = useMemo(() => {
    if (!selectedId || !trace.data) return null
    return new Set([selectedId, ...trace.data.upstream.map((t) => t.id), ...trace.data.downstream.map((t) => t.id)])
  }, [selectedId, trace.data])

  const staleCount = graph.data?.nodes.filter((n) => n.stale).length ?? 0
  const selected = graph.data?.nodes.find((n) => n.id === selectedId) ?? null

  const onImpact = (i: Impact) => {
    const depthById: Record<string, number> = {}
    Object.entries(i.by_depth).forEach(([d, ids]) => ids.forEach((id) => (depthById[id] = Number(d))))
    setImpact({ rootId: i.root_id, depthById, key: Date.now() })
    setParam({ tab: 'graph' })
  }

  const regenerate = async () => {
    setRegenError(null)
    try {
      setRegenJob((await startJob(`/blueprints/${blueprintId}/regenerate-subgraph`, impact ? { root_node_id: impact.rootId } : {})).job_id)
    } catch (e) {
      setRegenError(errorMessage(e))
    }
  }

  if (bp.isLoading) return <Spinner label="Loading blueprint" />
  if (bp.error || !bp.data) return <div className="mx-auto max-w-3xl p-6"><ErrorState error={bp.error} onRetry={() => bp.refetch()} /></div>

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2">
          <Link to={`/app/p/${bp.data.project_id}`} className="text-slate-500 hover:text-slate-900" aria-label="Back to project">
            <ArrowLeft className="size-5" aria-hidden />
          </Link>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold">{bp.data.title}</h1>
              <ProviderBadge provider={bp.data.provider} />
              <Badge className="bg-slate-100 text-slate-700">v{bp.data.version}</Badge>
              {!canEdit && project.data && <Badge className="bg-slate-100 text-slate-700">read-only ({project.data.my_role})</Badge>}
            </div>
            <p className="text-xs text-slate-500">{graph.data ? `${graph.data.nodes.length} nodes · ${graph.data.edges.length} links` : '…'}</p>
          </div>
          <button type="button" onClick={() => setParam({ tab: 'quality' })} className="ml-auto flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-50" aria-label={`Quality score ${bp.data.quality_score ?? 'not available'}, open quality panel`}>
            <ScoreGauge score={bp.data.quality_score} size={44} decorative />
            <span className="text-left text-xs leading-tight text-slate-600">Quality<br />{openIssues.length} open issues</span>
          </button>
        </div>
        {(staleCount > 0 || regenJob) && (
          <div role="status" className="mx-auto mt-3 flex max-w-[1600px] flex-wrap items-center gap-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950 ring-1 ring-amber-200">
            {regenJob ? (
              <div className="w-full max-w-xl"><JobProgress job={regen} steps={['regenerating', 'rule_check', 'ml_check', 'scoring']} /></div>
            ) : (
              <>
                <span><b>{staleCount}</b> item{staleCount === 1 ? '' : 's'} may be out of date after your edit.</span>
                {canEdit && (
                  <Button size="sm" onClick={regenerate}>
                    <RefreshCw className="size-4" aria-hidden /> Regenerate affected
                  </Button>
                )}
                {impact && (
                  <Button size="sm" variant="ghost" onClick={() => setImpact(null)}>
                    Clear highlight
                  </Button>
                )}
                {regenError && <span role="alert" className="text-rose-700">{regenError}</span>}
              </>
            )}
          </div>
        )}
        <div role="tablist" aria-label="Blueprint views" className="mx-auto mt-3 flex max-w-[1600px] gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              onClick={() => setParam({ tab: t.id })}
              className={clsx('whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium', tab === t.id ? 'bg-brand-600 text-white' : 'text-slate-700 hover:bg-slate-100')}
            >
              {t.label}
              {t.id === 'quality' && openIssues.length > 0 && <span className="ml-1.5 rounded-full bg-rose-500 px-1.5 text-xs text-white">{openIssues.length}</span>}
            </button>
          ))}
        </div>
      </div>

      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="min-h-0 flex-1 overflow-auto bg-slate-50">
        {graph.error ? (
          <div className="p-6"><ErrorState error={graph.error} onRetry={() => graph.refetch()} /></div>
        ) : !graph.data ? (
          <div className="p-6"><Skeleton className="h-[60vh]" /></div>
        ) : tab === 'graph' ? (
          <div className="relative flex h-full">
            <div className="relative min-w-0 flex-1">
              {graph.data.nodes.length === 0 ? (
                <p className="p-10 text-center text-slate-600">This blueprint has no nodes yet. Generate it from the project page.</p>
              ) : (
                <GraphView graph={graph.data} selectedId={selectedId} onSelect={select} issueCountById={issueCountById} highlightIds={highlight} traceIds={traceIds} impact={impact} />
              )}
            </div>
            {selected && (
              <div className="absolute inset-0 z-20 sm:static sm:w-[380px] sm:max-w-[45vw] sm:shrink-0">
                <NodePanel
                  key={selected.id}
                  node={selected}
                  blueprintId={blueprintId}
                  canEdit={canEdit}
                  issues={openIssues.filter((i) => i.node_ids.includes(selected.id))}
                  onClose={() => select(null)}
                  onSelect={select}
                  onImpact={onImpact}
                />
              </div>
            )}
          </div>
        ) : tab === 'quality' ? (
          <QualityPanel
            blueprintId={blueprintId}
            canEdit={canEdit}
            onShowNodes={(ids) => {
              setHighlight(new Set(ids))
              setParam({ tab: 'graph', node: ids[0] ?? null })
            }}
          />
        ) : tab === 'board' ? (
          <Board graph={graph.data} blueprintId={blueprintId} canEdit={canEdit} onOpen={(id) => setParam({ tab: 'graph', node: id })} />
        ) : tab === 'outline' ? (
          <Outline nodes={graph.data.nodes} onOpen={(id) => setParam({ tab: 'graph', node: id })} />
        ) : (
          <Overview brief={bp.data.brief} blueprintId={blueprintId} counts={NODE_TYPES.map((t) => [t, graph.data!.nodes.filter((n) => n.type === t).length] as const)} />
        )}
      </div>
    </div>
  )
}

/** Screen-reader and keyboard friendly alternative to the canvas. */
function Outline({ nodes, onOpen }: { nodes: { id: string; key: string; type: keyof typeof NODE_META; title: string; stale: boolean }[]; onOpen: (id: string) => void }) {
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4">
      {NODE_TYPES.map((t) => {
        const list = nodes.filter((n) => n.type === t)
        if (!list.length) return null
        return (
          <section key={t} aria-labelledby={`outline-${t}`}>
            <h2 id={`outline-${t}`} className={clsx('font-semibold', NODE_META[t].color)}>{NODE_META[t].plural} ({list.length})</h2>
            <ul className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
              {list.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => onOpen(n.id)} className="flex w-full gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50">
                    <span className="w-16 shrink-0 font-mono text-xs font-semibold text-slate-600">{n.key}</span>
                    <span className="flex-1">{n.title}</span>
                    {n.stale && <Badge className="bg-amber-100 text-amber-900">stale</Badge>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

function Overview({ brief, blueprintId, counts }: { brief: string; blueprintId: string; counts: readonly (readonly [keyof typeof NODE_META, number])[] }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const exp = async (fmt: 'md' | 'json' | 'pdf') => {
    setBusy(fmt)
    setError(null)
    try {
      await download(`/blueprints/${blueprintId}/export?format=${fmt}`)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="mx-auto grid max-w-5xl gap-4 p-4 md:grid-cols-[1fr_280px]">
      <Card className="p-5">
        <h2 className="font-semibold">Project brief</h2>
        <p className="mt-2 whitespace-pre-line text-slate-700">{brief}</p>
        <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {counts.map(([t, n]) => (
            <div key={t} className={clsx('rounded-lg p-3', NODE_META[t].bg)}>
              <dt className={clsx('text-xs font-medium', NODE_META[t].color)}>{NODE_META[t].plural}</dt>
              <dd className="text-xl font-bold tabular-nums">{n}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <Card className="h-fit space-y-2 p-5">
        <h2 className="font-semibold">Export</h2>
        <Button variant="secondary" className="w-full justify-start" onClick={() => exp('md')} loading={busy === 'md'}><FileText className="size-4" aria-hidden /> Markdown (.md)</Button>
        <Button variant="secondary" className="w-full justify-start" onClick={() => exp('pdf')} loading={busy === 'pdf'}><Download className="size-4" aria-hidden /> PDF document</Button>
        <Button variant="secondary" className="w-full justify-start" onClick={() => exp('json')} loading={busy === 'json'}><FileJson className="size-4" aria-hidden /> JSON (graph + quality)</Button>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      </Card>
    </div>
  )
}
