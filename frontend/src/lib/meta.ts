import type { NodeStatus, NodeType } from './types'

/** Visual identity per node type. Colours pass WCAG AA on white for text. */
export const NODE_META: Record<NodeType, { label: string; plural: string; color: string; bg: string; ring: string; column: number }> = {
  requirement: { label: 'Requirement', plural: 'Requirements', color: 'text-indigo-700', bg: 'bg-indigo-50', ring: 'border-indigo-300', column: 0 },
  story: { label: 'Story', plural: 'Stories', color: 'text-sky-700', bg: 'bg-sky-50', ring: 'border-sky-300', column: 1 },
  module: { label: 'Module', plural: 'Modules', color: 'text-violet-700', bg: 'bg-violet-50', ring: 'border-violet-300', column: 2 },
  api: { label: 'API', plural: 'APIs', color: 'text-emerald-700', bg: 'bg-emerald-50', ring: 'border-emerald-300', column: 3 },
  entity: { label: 'Entity', plural: 'Entities', color: 'text-amber-800', bg: 'bg-amber-50', ring: 'border-amber-300', column: 4 },
  test: { label: 'Test', plural: 'Tests', color: 'text-teal-700', bg: 'bg-teal-50', ring: 'border-teal-300', column: 5 },
  risk: { label: 'Risk', plural: 'Risks', color: 'text-rose-700', bg: 'bg-rose-50', ring: 'border-rose-300', column: 6 },
}

export const NODE_TYPES = Object.keys(NODE_META) as NodeType[]

/** Hex colours for React Flow edges/minimap (Tailwind classes don't reach SVG fills). */
export const NODE_HEX: Record<NodeType, string> = {
  requirement: '#4f46e5',
  story: '#0284c7',
  module: '#7c3aed',
  api: '#059669',
  entity: '#d97706',
  test: '#0d9488',
  risk: '#e11d48',
}

export const STATUS_META: Record<NodeStatus, { label: string; dot: string }> = {
  todo: { label: 'To do', dot: 'bg-slate-400' },
  in_progress: { label: 'In progress', dot: 'bg-sky-500' },
  in_review: { label: 'In review', dot: 'bg-amber-500' },
  done: { label: 'Done', dot: 'bg-emerald-500' },
}

export const STATUSES = Object.keys(STATUS_META) as NodeStatus[]

export const STEP_LABELS: Record<string, string> = {
  queued: 'Queued',
  parsing: 'Parsing the brief',
  generating_requirements: 'Generating requirements & stories',
  generating_design: 'Designing modules, data & API',
  generating_tests: 'Writing tests',
  saving: 'Saving the graph',
  rule_check: 'Rule check',
  ml_check: 'ML check (duplicates, contradictions)',
  scoring: 'Scoring',
  fixing: 'Applying fix',
  regenerating: 'Regenerating affected nodes',
  done: 'Done',
}

export const GENERATE_STEPS = [
  'parsing',
  'generating_requirements',
  'generating_design',
  'generating_tests',
  'saving',
  'rule_check',
  'ml_check',
  'scoring',
]

export const CATEGORY_LABELS: Record<string, string> = {
  traceability: 'Traceability',
  completeness: 'Completeness',
  consistency: 'Consistency',
  uniqueness: 'Uniqueness',
  conventions: 'Conventions',
}

export const LINKS = {
  github: 'https://github.com/sohumcs/specforge',
  linkedin: 'https://www.linkedin.com/in/sohumcs',
}
