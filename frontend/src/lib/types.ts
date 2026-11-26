// Mirrors the FastAPI response models (see /docs). Kept hand-written and small.

export type Role = 'viewer' | 'editor' | 'owner'
export type NodeType = 'requirement' | 'story' | 'module' | 'api' | 'entity' | 'test' | 'risk'
export type NodeStatus = 'todo' | 'in_progress' | 'in_review' | 'done'
export type EdgeType =
  | 'refines'
  | 'implemented_by'
  | 'exposes'
  | 'persists'
  | 'relates_to'
  | 'verified_by'
  | 'threatens'
  | 'depends_on'

export interface User {
  id: string
  email: string
  display_name: string
  is_admin: boolean
  is_demo: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Project {
  id: string
  name: string
  description: string
  is_sandbox: boolean
  created_at: string
  my_role: Role | null
}

export interface Blueprint {
  id: string
  project_id: string
  title: string
  brief: string
  settings: Record<string, unknown>
  status: 'draft' | 'generating' | 'ready' | 'failed'
  version: number
  quality_score: number | null
  provider: string | null
  is_sample: boolean
  created_at: string
  updated_at: string
}

export interface GraphNode {
  id: string
  blueprint_id: string
  type: NodeType
  key: string
  title: string
  body: Record<string, unknown>
  status: NodeStatus
  stale: boolean
}

export interface GraphEdge {
  id: string
  src_id: string
  dst_id: string
  type: EdgeType
  body: Record<string, unknown>
}

export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface ImpactedNode {
  id: string
  key: string
  type: NodeType
  title: string
  depth: number
}

export interface Impact {
  root_id: string
  impacted: ImpactedNode[]
  by_depth: Record<string, string[]>
}

export interface Trace {
  root_id: string
  upstream: ImpactedNode[]
  downstream: ImpactedNode[]
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'dead'

export interface Job {
  job_id: string
  blueprint_id: string
  kind: 'generate' | 'verify' | 'fix_issue' | 'regenerate_subgraph'
  status: JobStatus
  step: string
  progress: number
  result: Record<string, unknown> | null
  error: { code: string; message: string } | null
}

export interface QualityCategory {
  category: 'traceability' | 'completeness' | 'consistency' | 'uniqueness' | 'conventions'
  score: number
  weight: number
  checks: number
  issues: number
}

export interface QualityIssue {
  id: string
  rule_code: string
  category: QualityCategory['category']
  severity: 'low' | 'medium' | 'high'
  message: string
  fix_hint: string
  node_ids: string[]
  node_keys: string[]
  resolved: boolean
  fixable: boolean
  details: Record<string, unknown>
}

export interface QualityReport {
  report_id: string
  score: number
  created_at: string
  breakdown: { categories: QualityCategory[]; ml: 'ok' | 'unavailable'; node_count: number }
  issues: QualityIssue[]
}

export interface Rollup {
  total: number
  done: number
  percent: number
  by_status: Record<NodeStatus, number>
}

export interface Progress {
  overall: Rollup
  stories: Rollup
  tests: Rollup
  requirements: (Rollup & { id: string; key: string; title: string })[]
  modules: (Rollup & { id: string; key: string; title: string })[]
}

export interface Sample {
  slug: string
  title: string
  brief: string
  generated_by: string
  nodes: number
  edges: number
}

export interface StatusComponent {
  ok: boolean
  error?: string
  models_loaded?: boolean
  last_seen_seconds?: number
}

export interface SystemStatus {
  version: string
  commit: string
  ci_run_url: string
  environment: string
  components: Record<string, StatusComponent>
  llm_providers: Record<string, { configured: boolean; model: string; circuit_open_seconds: number }>
  llm_chain: string[]
}
