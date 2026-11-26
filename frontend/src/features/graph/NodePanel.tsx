import clsx from 'clsx'
import { ArrowDownRight, ArrowUpLeft, Clock, Pencil, Sparkles, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Badge, Button, errorMessage } from '../../components/ui'
import { NODE_META, STATUS_META, STATUSES } from '../../lib/meta'
import { useSetStatus, useSimilar, useTrace, useUpdateNode } from '../../lib/queries'
import type { GraphNode, Impact, ImpactedNode, NodeStatus, QualityIssue } from '../../lib/types'

interface Props {
  node: GraphNode
  blueprintId: string
  canEdit: boolean
  issues: QualityIssue[]
  onClose: () => void
  onSelect: (id: string) => void
  onImpact: (impact: Impact) => void
}

function TraceList({ title, items, icon: Icon, onSelect }: { title: string; items: ImpactedNode[]; icon: typeof ArrowUpLeft; onSelect: (id: string) => void }) {
  return (
    <div>
      <h4 className="flex items-center gap-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        <Icon className="size-3.5" aria-hidden /> {title} <span className="font-normal">({items.length})</span>
      </h4>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">None</p>
      ) : (
        <ul className="mt-1 max-h-40 space-y-0.5 overflow-auto">
          {items.map((t) => (
            <li key={t.id}>
              <button type="button" onClick={() => onSelect(t.id)} className="flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left text-sm hover:bg-slate-100">
                <span className={clsx('shrink-0 rounded px-1 font-mono text-[11px] font-semibold', NODE_META[t.type].bg, NODE_META[t.type].color)}>{t.key}</span>
                <span className="line-clamp-1 text-slate-700">{t.title}</span>
                <span className="ml-auto shrink-0 text-[11px] text-slate-400">{t.depth} hop{t.depth > 1 ? 's' : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Body({ node }: { node: GraphNode }) {
  const b = node.body as Record<string, unknown>
  const text = (b.description ?? b.responsibility ?? b.summary) as string | undefined
  const list = (k: string) => (Array.isArray(b[k]) ? (b[k] as unknown[]).map(String) : [])
  return (
    <div className="space-y-3 text-sm">
      {text && <p className="text-slate-700">{text}</p>}
      {node.type === 'requirement' && (
        <div className="flex flex-wrap gap-1.5">
          <Badge className="bg-slate-100 text-slate-700">{String(b.kind ?? 'functional').replace('_', '-')}</Badge>
          {b.nfr_category && b.nfr_category !== 'none' ? <Badge className="bg-slate-100 text-slate-700">{String(b.nfr_category)}</Badge> : null}
          {b.priority ? <Badge className="bg-slate-100 text-slate-700">priority: {String(b.priority)}</Badge> : null}
        </div>
      )}
      {node.type === 'api' && <p className="font-mono text-xs text-emerald-800">{String(b.method)} {String(b.path)}</p>}
      {list('acceptance_criteria').length > 0 && (
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Acceptance criteria</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-700">
            {list('acceptance_criteria').map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}
      {list('steps').length > 0 && (
        <div>
          <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Steps ({String(b.kind ?? '')})</h4>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-slate-700">
            {list('steps').map((c, i) => <li key={i}>{c}</li>)}
          </ol>
        </div>
      )}
      {node.type === 'entity' && Array.isArray(b.fields) && (
        <table className="w-full text-xs">
          <caption className="sr-only">Fields</caption>
          <thead><tr className="text-left text-slate-500"><th className="py-0.5">field</th><th>type</th><th /></tr></thead>
          <tbody>
            {(b.fields as { name: string; type: string; primary_key?: boolean; nullable?: boolean }[]).map((f) => (
              <tr key={f.name} className="border-t border-slate-100 font-mono">
                <td className="py-0.5">{f.name}</td>
                <td>{f.type}</td>
                <td className="text-slate-500">{f.primary_key ? 'PK' : f.nullable ? 'null' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {node.type === 'risk' && (
        <div className="space-y-1">
          <p className="text-xs text-slate-600">Likelihood <b>{String(b.likelihood)}</b> · impact <b>{String(b.impact)}</b></p>
          {b.mitigation ? <p className="text-slate-700"><span className="font-medium">Mitigation:</span> {String(b.mitigation)}</p> : null}
        </div>
      )}
    </div>
  )
}

export function NodePanel({ node, blueprintId, canEdit, issues, onClose, onSelect, onImpact }: Props) {
  const meta = NODE_META[node.type]
  const trace = useTrace(node.id)
  const similar = useSimilar(node.id)
  const setStatus = useSetStatus(blueprintId)
  const update = useUpdateNode(blueprintId)
  const [editing, setEditing] = useState(false)
  const [lastImpact, setLastImpact] = useState<Impact | null>(null)

  // Per-node state (editing, last impact) resets because the parent keys this panel by node id.
  const descField = node.type === 'module' ? 'responsibility' : node.type === 'api' ? 'summary' : 'description'
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const body = { ...node.body, [descField]: String(f.get('description') ?? '') }
    if (node.type === 'story') {
      body.acceptance_criteria = String(f.get('ac') ?? '')
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
    }
    const res = await update.mutateAsync({ id: node.id, title: String(f.get('title')), body })
    setEditing(false)
    setLastImpact(res.impact)
    onImpact(res.impact)
  }

  return (
    <aside aria-label={`${meta.label} ${node.key} details`} className="flex h-full w-full flex-col overflow-hidden border-l border-slate-200 bg-white">
      <div className="flex items-start gap-2 border-b border-slate-100 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={clsx('rounded px-1.5 font-mono text-xs font-semibold', meta.bg, meta.color)}>{node.key}</span>
            <span className="text-xs text-slate-500">{meta.label}</span>
            {node.stale && (
              <Badge className="bg-amber-100 text-amber-900" title="An upstream item changed; this may need rework">
                <Clock className="size-3" aria-hidden /> stale
              </Badge>
            )}
          </div>
          <h3 className="mt-1 font-semibold text-slate-900">{node.title}</h3>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close details">
          <X className="size-5" aria-hidden />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-auto p-4">
        {lastImpact && (
          <div role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950 ring-1 ring-amber-200">
            Saved. <b>{lastImpact.impacted.length}</b> downstream item{lastImpact.impacted.length === 1 ? '' : 's'} marked stale across{' '}
            {Object.keys(lastImpact.by_depth).length} hop(s). Use <b>Regenerate affected</b> at the top to update them.
          </div>
        )}

        {editing ? (
          <form onSubmit={save} className="space-y-3">
            <label className="block text-sm">
              <span className="font-medium">Title</span>
              <input name="title" defaultValue={node.title} required maxLength={300} className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5" />
            </label>
            <label className="block text-sm">
              <span className="font-medium">{descField[0].toUpperCase() + descField.slice(1)}</span>
              <textarea name="description" rows={3} defaultValue={String(node.body[descField] ?? '')} className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5" />
            </label>
            {node.type === 'story' && (
              <label className="block text-sm">
                <span className="font-medium">Acceptance criteria (one per line)</span>
                <textarea name="ac" rows={4} defaultValue={((node.body.acceptance_criteria as string[]) ?? []).join('\n')} className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5" />
              </label>
            )}
            {update.error && <p role="alert" className="text-sm text-rose-700">{errorMessage(update.error)}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" loading={update.isPending}>Save & show impact</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            </div>
          </form>
        ) : (
          <>
            <Body node={node} />
            {canEdit && (
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                <Pencil className="size-4" aria-hidden /> Edit
              </Button>
            )}
          </>
        )}

        {(node.type === 'story' || node.type === 'test') && (
          <label className="block text-sm">
            <span className="font-medium">Delivery status</span>
            <select
              value={node.status}
              disabled={!canEdit || setStatus.isPending}
              onChange={(e) => setStatus.mutate({ id: node.id, status: e.target.value as NodeStatus })}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-1.5"
            >
              {STATUSES.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
            </select>
          </label>
        )}

        {issues.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold tracking-wide text-rose-700 uppercase">Quality issues ({issues.length})</h4>
            <ul className="mt-1 space-y-1.5">
              {issues.map((i) => (
                <li key={i.id} className="rounded-md bg-rose-50 p-2 text-sm text-rose-950">
                  <span className="font-mono text-xs">{i.rule_code}</span> {i.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-3">
          <h4 className="text-sm font-semibold">Trace chain</h4>
          {trace.isLoading ? <p className="text-sm text-slate-500">Tracing…</p> : trace.data && (
            <>
              <TraceList title="Comes from" items={trace.data.upstream} icon={ArrowUpLeft} onSelect={onSelect} />
              <TraceList title="Leads to" items={trace.data.downstream} icon={ArrowDownRight} onSelect={onSelect} />
            </>
          )}
        </div>

        <div>
          <h4 className="flex items-center gap-1 text-sm font-semibold">
            <Sparkles className="size-4 text-violet-500" aria-hidden /> Semantically similar
          </h4>
          {similar.error ? (
            <p className="mt-1 text-sm text-slate-500">Available after verification embeds this node.</p>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {similar.data?.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => onSelect(s.id)} className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-sm hover:bg-slate-100">
                    <span className="font-mono text-[11px] font-semibold text-slate-600">{s.key}</span>
                    <span className="line-clamp-1 flex-1 text-slate-700">{s.title}</span>
                    <span className="text-[11px] tabular-nums text-slate-400">{s.similarity.toFixed(2)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </aside>
  )
}
