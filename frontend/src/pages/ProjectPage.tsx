import { ArrowLeft, FileText, Sparkles, Wand2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { JobProgress } from '../components/JobProgress'
import { Badge, Button, Card, EmptyState, ErrorState, ProviderBadge, Skeleton, errorMessage } from '../components/ui'
import { ApiError } from '../lib/api'
import { startJob, useBlueprints, useCreateBlueprint, useProject } from '../lib/queries'
import type { Job } from '../lib/types'
import { useJob } from '../lib/useJob'

const EXAMPLE =
  'A peer-to-peer book exchange for a university campus. Students list books they own, search by course code, request a swap or a short loan, and chat to arrange a handover. Admins moderate listings and resolve disputes. It should work well on phones and never expose students’ phone numbers.'

export default function ProjectPage() {
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const blueprints = useBlueprints(projectId)
  const canEdit = project.data?.my_role === 'editor' || project.data?.my_role === 'owner'

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <Link to="/app" className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="size-4" aria-hidden /> All projects
      </Link>
      {project.isLoading ? <Skeleton className="mt-3 h-8 w-64" /> : project.error ? (
        <div className="mt-4"><ErrorState error={project.error} onRetry={() => project.refetch()} /></div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold">{project.data?.name}</h1>
          {project.data?.is_sandbox && <Badge className="bg-amber-100 text-amber-900">sandbox · resets nightly</Badge>}
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_380px]">
        <section aria-labelledby="bp-heading">
          <h2 id="bp-heading" className="font-semibold">Blueprints</h2>
          <div className="mt-3 space-y-3">
            {blueprints.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="h-24" />)}
            {blueprints.error && <ErrorState error={blueprints.error} onRetry={() => blueprints.refetch()} />}
            {blueprints.data?.items.length === 0 && (
              <EmptyState title="No blueprints yet">Describe your project on the right and SPECForge will generate the first one.</EmptyState>
            )}
            {blueprints.data?.items.map((b) => (
              <Link
                key={b.id}
                to={`/app/b/${b.id}`}
                className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-brand-300 hover:shadow"
              >
                <FileText className="mt-0.5 size-5 shrink-0 text-brand-600" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{b.title}</span>
                    {b.is_sample && <Badge className="bg-violet-100 text-violet-800">sample</Badge>}
                    <ProviderBadge provider={b.provider} />
                    {b.status !== 'ready' && <Badge className="bg-slate-100 text-slate-700">{b.status}</Badge>}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm text-slate-600">{b.brief}</p>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold tabular-nums text-slate-900">{b.quality_score ?? '–'}</div>
                  <div className="text-xs text-slate-500">quality</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
        {canEdit && <NewBlueprint projectId={projectId} />}
      </div>
    </div>
  )
}

function NewBlueprint({ projectId }: { projectId: string }) {
  const create = useCreateBlueprint(projectId)
  const navigate = useNavigate()
  const [brief, setBrief] = useState('')
  const [title, setTitle] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [blueprintId, setBlueprintId] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const job = useJob(jobId, (j: Job) => {
    if (j.status === 'succeeded') setTimeout(() => navigate(`/app/b/${j.blueprint_id}`), 700)
  })

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const bp = blueprintId ? { id: blueprintId } : await create.mutateAsync({ title: title || 'Untitled blueprint', brief })
      setBlueprintId(bp.id)
      const j = await startJob(`/blueprints/${bp.id}/generate`)
      setJobId(j.job_id)
    } catch (err) {
      setError(err as Error)
    }
  }

  const running = !!jobId && job?.status !== 'failed' && job?.status !== 'dead'
  return (
    <Card className="h-fit p-5">
      <h2 className="flex items-center gap-2 font-semibold">
        <Sparkles className="size-5 text-amber-500" aria-hidden /> New blueprint from a brief
      </h2>
      {running ? (
        <div className="mt-4">
          <JobProgress job={job} />
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <label className="block text-sm">
            <span className="font-medium">Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="e.g. Campus book exchange" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label className="block text-sm">
            <span className="font-medium">Project brief</span>
            <textarea
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              required
              minLength={20}
              maxLength={4000}
              rows={8}
              placeholder="Who uses it, what they need to do, and any constraints…"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              aria-describedby="brief-help"
            />
            <span id="brief-help" className="mt-1 flex justify-between text-xs text-slate-500">
              <button type="button" className="text-brand-700 underline" onClick={() => { setBrief(EXAMPLE); setTitle('Campus book exchange') }}>
                Use an example
              </button>
              <span>{brief.length}/4000</span>
            </span>
          </label>
          {error && (
            <p role="alert" className="rounded-md bg-rose-50 p-2 text-sm text-rose-800">
              {errorMessage(error)}
              {error instanceof ApiError && error.code === 'RATE_LIMITED' && ' Meanwhile, the sample blueprints on the left are fully interactive.'}
            </p>
          )}
          {job && (job.status === 'failed' || job.status === 'dead') && <JobProgress job={job} />}
          <Button type="submit" className="w-full" loading={create.isPending} disabled={brief.trim().length < 20}>
            <Wand2 className="size-4" aria-hidden /> Generate blueprint
          </Button>
          <p className="text-xs text-slate-500">Takes ~20–60 s: three LLM stages, then rule + ML verification.</p>
        </form>
      )}
    </Card>
  )
}
