import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import { AlertTriangle, Clock } from 'lucide-react'
import { memo } from 'react'

import { NODE_META, STATUS_META } from '../../lib/meta'
import type { GraphNode } from '../../lib/types'

export type ColorMode = 'type' | 'status' | 'issues'

export interface NodeCardData extends Record<string, unknown> {
  node: GraphNode
  colorMode: ColorMode
  issueCount: number
  dimmed: boolean
  highlighted: boolean
  impactDepth: number | null // hop distance in the current impact wave
  impactKey: number // changes on every new wave so the animation replays
}

export type SFNode = Node<NodeCardData, 'sf'>

const STATUS_RING: Record<string, string> = {
  todo: 'border-slate-300',
  in_progress: 'border-sky-500',
  in_review: 'border-amber-500',
  done: 'border-emerald-500',
}

function NodeCardImpl({ data, selected }: NodeProps<SFNode>) {
  const { node, colorMode, issueCount, dimmed, highlighted, impactDepth, impactKey } = data
  const meta = NODE_META[node.type]
  const tracked = node.type === 'story' || node.type === 'test'
  const ring =
    colorMode === 'status'
      ? tracked
        ? STATUS_RING[node.status]
        : 'border-slate-200'
      : colorMode === 'issues'
        ? issueCount
          ? 'border-rose-500'
          : 'border-emerald-300'
        : meta.ring
  return (
    <div
      key={impactKey}
      className={clsx(
        'w-[210px] rounded-lg border-2 bg-white px-2.5 py-1.5 text-left shadow-sm transition-opacity',
        ring,
        node.stale && 'border-dashed !border-amber-500',
        selected && 'ring-2 ring-brand-600 ring-offset-1',
        highlighted && !selected && 'ring-2 ring-amber-400',
        dimmed && 'opacity-25',
        impactDepth !== null && 'impact-pulse',
      )}
      style={impactDepth !== null ? { animationDelay: `${impactDepth * 0.35}s` } : undefined}
      title={node.title}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-slate-400" />
      <div className="flex items-center gap-1.5 text-[11px]">
        <span className={clsx('rounded px-1 font-mono font-semibold', meta.bg, meta.color)}>{node.key}</span>
        {tracked && (
          <span className="flex items-center gap-1 text-slate-500">
            <span className={clsx('size-2 rounded-full', STATUS_META[node.status].dot)} aria-hidden />
            {STATUS_META[node.status].label}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {node.stale && <Clock className="size-3.5 text-amber-600" aria-label="stale" />}
          {issueCount > 0 && (
            <span className="inline-flex items-center gap-0.5 rounded bg-rose-100 px-1 text-rose-700" aria-label={`${issueCount} quality issues`}>
              <AlertTriangle className="size-3" aria-hidden />
              {issueCount}
            </span>
          )}
        </span>
      </div>
      <p className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-slate-800">{node.title}</p>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-slate-400" />
    </div>
  )
}

export const NodeCard = memo(NodeCardImpl)
