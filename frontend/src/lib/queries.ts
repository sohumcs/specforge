import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, newIdempotencyKey } from './api'
import type {
  Blueprint,
  Graph,
  GraphNode,
  Impact,
  Job,
  NodeStatus,
  Page,
  Progress,
  Project,
  QualityReport,
  Sample,
  SystemStatus,
  Trace,
} from './types'

export const keys = {
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  blueprints: (pid: string) => ['blueprints', pid] as const,
  blueprint: (id: string) => ['blueprint', id] as const,
  graph: (id: string) => ['graph', id] as const,
  quality: (id: string) => ['quality', id] as const,
  progress: (id: string) => ['progress', id] as const,
  trace: (id: string) => ['trace', id] as const,
  similar: (id: string) => ['similar', id] as const,
  jobs: (id: string) => ['jobs', id] as const,
}

export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: () => api<Page<Project>>('/projects?limit=100') })

export const useProject = (id: string) =>
  useQuery({ queryKey: keys.project(id), queryFn: () => api<Project>(`/projects/${id}`) })

export const useBlueprints = (pid: string) =>
  useQuery({
    queryKey: keys.blueprints(pid),
    queryFn: () => api<Page<Blueprint>>(`/projects/${pid}/blueprints?limit=100`),
  })

export const useBlueprint = (id: string) =>
  useQuery({ queryKey: keys.blueprint(id), queryFn: () => api<Blueprint>(`/blueprints/${id}`) })

export const useGraph = (id: string) =>
  useQuery({ queryKey: keys.graph(id), queryFn: () => api<Graph>(`/blueprints/${id}/graph`) })

export const useQuality = (id: string) =>
  useQuery({
    queryKey: keys.quality(id),
    queryFn: () => api<QualityReport>(`/blueprints/${id}/quality`),
    retry: (n, err: unknown) => (err as { code?: string })?.code !== 'NOT_VERIFIED' && n < 2,
  })

export const useProgress = (id: string) =>
  useQuery({ queryKey: keys.progress(id), queryFn: () => api<Progress>(`/blueprints/${id}/progress`) })

export const useTrace = (nodeId: string | null) =>
  useQuery({
    queryKey: keys.trace(nodeId ?? ''),
    queryFn: () => api<Trace>(`/nodes/${nodeId}/trace`),
    enabled: !!nodeId,
  })

export const useSimilar = (nodeId: string | null) =>
  useQuery({
    queryKey: keys.similar(nodeId ?? ''),
    queryFn: () => api<{ id: string; key: string; type: string; title: string; similarity: number }[]>(
      `/nodes/${nodeId}/similar?k=4`,
    ),
    enabled: !!nodeId,
    retry: false,
  })

export const useActiveJobs = (id: string) =>
  useQuery({ queryKey: keys.jobs(id), queryFn: () => api<Job[]>(`/blueprints/${id}/jobs`) })

export const useSamples = () => useQuery({ queryKey: ['samples'], queryFn: () => api<Sample[]>('/samples') })

export const useStatus = () =>
  useQuery({ queryKey: ['status'], queryFn: () => api<SystemStatus>('/status'), refetchInterval: 15000 })

/** Invalidate everything that depends on a blueprint's graph. */
export function useInvalidateBlueprint(id: string) {
  const qc = useQueryClient()
  return () =>
    Promise.all(
      [keys.blueprint(id), keys.graph(id), keys.quality(id), keys.progress(id), keys.jobs(id)].map((k) =>
        qc.invalidateQueries({ queryKey: k }),
      ),
    ).then(() => qc.invalidateQueries({ queryKey: ['trace'] }))
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description: string }) => api<Project>('/projects', { method: 'POST', json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}

export function useCreateBlueprint(pid: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { title: string; brief: string }) =>
      api<Blueprint>(`/projects/${pid}/blueprints`, { method: 'POST', json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.blueprints(pid) }),
  })
}

export const startJob = (path: string, json?: unknown) =>
  api<Job>(path, { method: 'POST', json, idempotencyKey: newIdempotencyKey() })

export function useUpdateNode(blueprintId: string) {
  const invalidate = useInvalidateBlueprint(blueprintId)
  return useMutation({
    mutationFn: ({ id, title, body }: { id: string; title?: string; body?: Record<string, unknown> }) =>
      api<{ node: GraphNode; impact: Impact }>(`/nodes/${id}`, { method: 'PATCH', json: { title, body } }),
    onSuccess: () => invalidate(),
  })
}

export function useSetStatus(blueprintId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: NodeStatus }) =>
      api<GraphNode>(`/nodes/${id}/status`, { method: 'PATCH', json: { status } }),
    onMutate: async ({ id, status }) => {
      // Optimistic: move the card immediately, roll back on error.
      await qc.cancelQueries({ queryKey: keys.graph(blueprintId) })
      const prev = qc.getQueryData<Graph>(keys.graph(blueprintId))
      if (prev) {
        qc.setQueryData<Graph>(keys.graph(blueprintId), {
          ...prev,
          nodes: prev.nodes.map((n) => (n.id === id ? { ...n, status } : n)),
        })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(keys.graph(blueprintId), ctx.prev),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.graph(blueprintId) })
      qc.invalidateQueries({ queryKey: keys.progress(blueprintId) })
    },
  })
}

export function useDismissIssue(blueprintId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, restore }: { id: string; restore?: boolean }) =>
      api<{ score: number }>(`/issues/${id}/${restore ? 'restore' : 'dismiss'}`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.quality(blueprintId) })
      qc.invalidateQueries({ queryKey: keys.blueprint(blueprintId) })
    },
  })
}
