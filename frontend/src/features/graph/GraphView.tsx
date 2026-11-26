import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
} from '@xyflow/react'
import clsx from 'clsx'
import { Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { NODE_HEX, NODE_META, NODE_TYPES } from '../../lib/meta'
import type { Graph, NodeType } from '../../lib/types'
import { layout, NODE_H, NODE_W } from './layout'
import { NodeCard, type ColorMode, type SFNode } from './NodeCard'

export interface ImpactWave {
  rootId: string
  depthById: Record<string, number>
  key: number
}

interface Props {
  graph: Graph
  selectedId: string | null
  onSelect: (id: string | null) => void
  issueCountById: Record<string, number>
  highlightIds: Set<string> // e.g. nodes of an issue chosen in the Quality panel
  traceIds: Set<string> | null // selected node's trace chain; others are dimmed
  impact: ImpactWave | null
}

const nodeTypes = { sf: NodeCard }

const EDGE_LABEL: Record<string, string> = {
  refines: 'refines',
  implemented_by: 'implemented by',
  exposes: 'exposes',
  persists: 'persists',
  relates_to: 'relates to',
  verified_by: 'verified by',
  threatens: 'threatens',
  depends_on: 'depends on',
}

function GraphCanvas({ graph, selectedId, onSelect, issueCountById, highlightIds, traceIds, impact }: Props) {
  const [visible, setVisible] = useState<Set<NodeType>>(new Set(NODE_TYPES))
  const [colorMode, setColorMode] = useState<ColorMode>('type')
  const [showRelations, setShowRelations] = useState(false)
  const [query, setQuery] = useState('')
  const flow = useReactFlow()

  const positions = useMemo(() => layout(graph.nodes, graph.edges), [graph])
  const q = query.trim().toLowerCase()

  const nodes: SFNode[] = useMemo(
    () =>
      graph.nodes
        .filter((n) => visible.has(n.type))
        .map((n) => {
          const p = positions.get(n.id)!
          const matches = !q || n.key.toLowerCase().includes(q) || n.title.toLowerCase().includes(q)
          return {
            id: n.id,
            type: 'sf' as const,
            position: { x: p.x, y: p.y },
            width: NODE_W,
            height: NODE_H,
            selected: n.id === selectedId,
            ariaLabel: `${NODE_META[n.type].label} ${n.key}: ${n.title}`,
            data: {
              node: n,
              colorMode,
              issueCount: issueCountById[n.id] ?? 0,
              dimmed: (traceIds !== null && !traceIds.has(n.id)) || !matches,
              highlighted: highlightIds.has(n.id) || (impact?.rootId === n.id),
              impactDepth: impact ? (impact.depthById[n.id] ?? null) : null,
              impactKey: impact?.key ?? 0,
            },
          }
        }),
    [graph.nodes, positions, visible, colorMode, issueCountById, traceIds, highlightIds, impact, selectedId, q],
  )

  const edges: Edge[] = useMemo(() => {
    const shown = new Set(nodes.map((n) => n.id))
    return graph.edges
      .filter((e) => shown.has(e.src_id) && shown.has(e.dst_id) && (showRelations || e.type !== 'relates_to'))
      .map((e) => {
        const src = graph.nodes.find((n) => n.id === e.src_id)!
        const inTrace = traceIds?.has(e.src_id) && traceIds?.has(e.dst_id)
        // An edge is part of the wave if both ends are the edited node or impacted by it.
        const inWaveNode = (id: string) => !!impact && (id === impact.rootId || impact.depthById[id] !== undefined)
        const inWave = inWaveNode(e.src_id) && inWaveNode(e.dst_id)
        const color = inWave ? '#f59e0b' : NODE_HEX[src.type]
        return {
          id: e.id,
          source: e.src_id,
          target: e.dst_id,
          animated: !!inWave,
          ariaLabel: `${src.key} ${EDGE_LABEL[e.type]}`,
          style: {
            stroke: color,
            strokeWidth: inTrace || inWave ? 2.2 : 1.2,
            opacity: traceIds && !inTrace ? 0.12 : 0.65,
            strokeDasharray: e.type === 'relates_to' || e.type === 'depends_on' ? '4 4' : undefined,
          },
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
        }
      })
  }, [graph, nodes, showRelations, traceIds, impact])

  // Centre on the selected node, e.g. when it's picked from the Quality panel.
  useEffect(() => {
    if (!selectedId) return
    const p = positions.get(selectedId)
    if (p) flow.setCenter(p.x + NODE_W / 2, p.y + NODE_H / 2, { zoom: Math.max(flow.getZoom(), 0.9), duration: 400 })
  }, [selectedId, positions, flow])

  const toggle = (t: NodeType) =>
    setVisible((v) => {
      const next = new Set(v)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-200 bg-white px-3 py-2">
        <fieldset className="flex flex-wrap items-center gap-1">
          <legend className="sr-only">Show node types</legend>
          {NODE_TYPES.map((t) => {
            const count = graph.nodes.filter((n) => n.type === t).length
            return (
              <label
                key={t}
                className={clsx(
                  'flex cursor-pointer select-none items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1',
                  visible.has(t) ? `${NODE_META[t].bg} ${NODE_META[t].color} ring-current/30` : 'bg-white text-slate-500 ring-slate-200',
                )}
              >
                <input type="checkbox" className="sr-only" checked={visible.has(t)} onChange={() => toggle(t)} />
                <span className="size-2 rounded-full" style={{ background: NODE_HEX[t] }} aria-hidden />
                {NODE_META[t].plural} <span className="tabular-nums opacity-70">{count}</span>
              </label>
            )
          })}
        </fieldset>
        <label className="ml-1 text-xs">
          <span className="sr-only">Colour nodes by</span>
          <select value={colorMode} onChange={(e) => setColorMode(e.target.value as ColorMode)} className="rounded-md border border-slate-300 px-1.5 py-0.5">
            <option value="type">Colour: type</option>
            <option value="status">Colour: delivery status</option>
            <option value="issues">Colour: quality issues</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-xs text-slate-700">
          <input type="checkbox" checked={showRelations} onChange={(e) => setShowRelations(e.target.checked)} />
          entity relations
        </label>
        <label className="relative text-xs">
          <span className="sr-only">Find a node</span>
          <Search className="pointer-events-none absolute left-1.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find REQ-003, login…" className="w-40 rounded-md border border-slate-300 py-0.5 pl-6 pr-1.5" />
        </label>
      </div>
      <div className="min-h-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => onSelect(n.id)}
          onPaneClick={() => onSelect(null)}
          onSelectionChange={({ nodes: sel }) => sel.length === 1 && sel[0].id !== selectedId && onSelect(sel[0].id)}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable
          edgesFocusable={false}
          fitView
          fitViewOptions={{ padding: 0.1 }}
          minZoom={0.1}
          proOptions={{ hideAttribution: true }}
          aria-label="Blueprint graph"
          forceColorMode="light"
        >
          <Background gap={24} color="#e2e8f0" />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap pannable zoomable nodeColor={(n) => NODE_HEX[(n.data as SFNode['data']).node.type]} position="bottom-right" ariaLabel="Graph overview" style={{ width: 150, height: 100 }} />
        </ReactFlow>
      </div>
    </div>
  )
}

export function GraphView(props: Props) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  )
}
