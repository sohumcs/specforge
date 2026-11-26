import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import clsx from 'clsx'
import { useMemo, useState } from 'react'

import { Card, ProgressBar, Skeleton } from '../../components/ui'
import { NODE_META, STATUS_META, STATUSES } from '../../lib/meta'
import { useProgress, useSetStatus } from '../../lib/queries'
import type { Graph, GraphNode, NodeStatus } from '../../lib/types'

interface Props {
  graph: Graph
  blueprintId: string
  canEdit: boolean
  onOpen: (id: string) => void
}

function CardItem({ node, canEdit, onOpen, onMove }: { node: GraphNode; canEdit: boolean; onOpen: (id: string) => void; onMove: (s: NodeStatus) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: node.id, disabled: !canEdit })
  const meta = NODE_META[node.type]
  return (
    <li
      ref={setNodeRef}
      style={transform ? { transform: `translate(${transform.x}px, ${transform.y}px)` } : undefined}
      className={clsx('rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm', isDragging && 'z-10 shadow-lg ring-2 ring-brand-500')}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          {...listeners}
          {...attributes}
          aria-label={`Drag ${node.key}. Press space, then arrow keys to move between columns.`}
          className={clsx('mt-0.5 cursor-grab rounded px-0.5 text-slate-400 hover:bg-slate-100', !canEdit && 'hidden')}
        >
          ⠿
        </button>
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onOpen(node.id)}>
          <span className={clsx('rounded px-1 font-mono text-[11px] font-semibold', meta.bg, meta.color)}>{node.key}</span>
          <span className="mt-1 line-clamp-3 block text-sm text-slate-800">{node.title}</span>
        </button>
      </div>
      {canEdit && (
        <label className="mt-2 block">
          <span className="sr-only">Status of {node.key}</span>
          <select value={node.status} onChange={(e) => onMove(e.target.value as NodeStatus)} className="w-full rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-xs">
            {STATUSES.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
          </select>
        </label>
      )}
    </li>
  )
}

function Column({ status, nodes, children }: { status: NodeStatus; nodes: GraphNode[]; children: React.ReactNode }) {
  const { isOver, setNodeRef } = useDroppable({ id: status })
  return (
    <section ref={setNodeRef} aria-label={`${STATUS_META[status].label} column`} className={clsx('flex min-h-48 flex-col rounded-xl bg-slate-100 p-2', isOver && 'ring-2 ring-brand-500')}>
      <h3 className="flex items-center gap-2 px-1 pb-2 text-sm font-semibold">
        <span className={clsx('size-2.5 rounded-full', STATUS_META[status].dot)} aria-hidden /> {STATUS_META[status].label}
        <span className="ml-auto text-xs font-normal text-slate-500">{nodes.length}</span>
      </h3>
      <ul className="flex flex-1 flex-col gap-2">{children}</ul>
    </section>
  )
}

export function Board({ graph, blueprintId, canEdit, onOpen }: Props) {
  const [kind, setKind] = useState<'all' | 'story' | 'test'>('story')
  const setStatus = useSetStatus(blueprintId)
  const progress = useProgress(blueprintId)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor))
  const items = useMemo(() => graph.nodes.filter((n) => (kind === 'all' ? n.type === 'story' || n.type === 'test' : n.type === kind)), [graph, kind])

  const onDragEnd = (e: DragEndEvent) => {
    const to = e.over?.id as NodeStatus | undefined
    const node = items.find((n) => n.id === e.active.id)
    if (to && node && node.status !== to) setStatus.mutate({ id: node.id, status: to })
  }

  return (
    <div className="grid gap-4 p-4 xl:grid-cols-[1fr_340px]">
      <div>
        <div className="mb-3 flex items-center gap-2">
          <span className="text-sm font-medium">Show</span>
          {(['story', 'test', 'all'] as const).map((k) => (
            <button key={k} type="button" onClick={() => setKind(k)} aria-pressed={kind === k} className={clsx('rounded-full px-3 py-1 text-sm', kind === k ? 'bg-brand-600 text-white' : 'bg-white ring-1 ring-slate-300')}>
              {k === 'all' ? 'Stories + tests' : k === 'story' ? 'Stories' : 'Tests'}
            </button>
          ))}
        </div>
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {STATUSES.map((s) => {
              const col = items.filter((n) => n.status === s)
              return (
                <Column key={s} status={s} nodes={col}>
                  {col.map((n) => <CardItem key={n.id} node={n} canEdit={canEdit} onOpen={onOpen} onMove={(st) => setStatus.mutate({ id: n.id, status: st })} />)}
                </Column>
              )
            })}
          </div>
        </DndContext>
      </div>
      <aside className="space-y-4" aria-label="Progress roll-ups">
        {progress.isLoading || !progress.data ? <Skeleton className="h-64" /> : (
          <>
            <Card className="space-y-3 p-4">
              <h3 className="font-semibold">Delivery</h3>
              {(['overall', 'stories', 'tests'] as const).map((k) => (
                <div key={k}>
                  <div className="flex justify-between text-sm"><span className="capitalize">{k}</span><span className="tabular-nums">{progress.data[k].done}/{progress.data[k].total} · {progress.data[k].percent}%</span></div>
                  <ProgressBar percent={progress.data[k].percent} label={`${k} done`} />
                </div>
              ))}
            </Card>
            {(['requirements', 'modules'] as const).map((group) => (
              <Card key={group} className="p-4">
                <h3 className="font-semibold capitalize">By {group.slice(0, -1)}</h3>
                <ul className="mt-2 max-h-80 space-y-2 overflow-auto">
                  {progress.data[group].map((r) => (
                    <li key={r.id}>
                      <button type="button" onClick={() => onOpen(r.id)} className="w-full text-left text-sm hover:text-brand-700">
                        <span className="flex justify-between gap-2">
                          <span className="line-clamp-1"><span className="font-mono text-xs text-slate-500">{r.key}</span> {r.title}</span>
                          <span className="shrink-0 tabular-nums text-slate-600">{r.percent}%</span>
                        </span>
                      </button>
                      <ProgressBar percent={r.percent} label={`${r.key} progress`} />
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </>
        )}
      </aside>
    </div>
  )
}
