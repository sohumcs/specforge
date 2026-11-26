import { CheckCircle2, CircleAlert, ExternalLink } from 'lucide-react'

import { Card, ErrorState, Spinner } from '../components/ui'
import { useStatus } from '../lib/queries'

function Dot({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="size-5 text-emerald-600" aria-label="healthy" />
  ) : (
    <CircleAlert className="size-5 text-rose-600" aria-label="unhealthy" />
  )
}

const COMPONENT_LABEL: Record<string, string> = {
  api: 'API (FastAPI)',
  database: 'PostgreSQL + pgvector',
  redis: 'Redis (broker, limits, pub/sub)',
  worker: 'Celery worker',
}

export default function StatusPage() {
  const { data, error, isLoading, refetch, dataUpdatedAt } = useStatus()
  if (isLoading) return <Spinner label="Checking components" />
  if (error || !data) return <div className="mx-auto max-w-3xl p-6"><ErrorState error={error} onRetry={() => refetch()} title="Status unavailable" /></div>
  const allOk = Object.values(data.components).every((c) => c.ok)
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <div>
        <h1 className="text-2xl font-semibold">System status</h1>
        <p className={`mt-1 font-medium ${allOk ? 'text-emerald-700' : 'text-amber-700'}`}>
          {allOk ? 'All systems operational' : 'Degraded: some components need attention'}
        </p>
        <p className="text-xs text-slate-500">Refreshes every 15 s · last check {new Date(dataUpdatedAt).toLocaleTimeString()}</p>
      </div>

      <Card>
        <h2 className="border-b border-slate-100 px-5 py-3 font-semibold">Components</h2>
        <ul className="divide-y divide-slate-100">
          {Object.entries(data.components).map(([name, c]) => (
            <li key={name} className="flex items-center gap-3 px-5 py-3">
              <Dot ok={c.ok} />
              <span className="flex-1">{COMPONENT_LABEL[name] ?? name}</span>
              <span className="text-sm text-slate-600">
                {name === 'worker'
                  ? c.ok
                    ? `ML models ${c.models_loaded ? 'loaded' : 'loading'} · seen ${c.last_seen_seconds}s ago`
                    : c.error
                  : c.ok
                    ? 'OK'
                    : c.error}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2 className="border-b border-slate-100 px-5 py-3 font-semibold">LLM providers</h2>
        <p className="px-5 pt-3 text-sm text-slate-600">
          Fallback chain: <span className="font-mono">{data.llm_chain.join(' → ')}</span>. The demo never fails because a free quota ran out.
        </p>
        <ul className="divide-y divide-slate-100">
          {Object.entries(data.llm_providers).map(([name, p]) => (
            <li key={name} className="flex items-center gap-3 px-5 py-3">
              <Dot ok={p.configured && p.circuit_open_seconds === 0} />
              <span className="flex-1 font-medium">{name}</span>
              <span className="font-mono text-xs text-slate-600">{p.model}</span>
              <span className="w-44 text-right text-sm text-slate-600">
                {!p.configured ? 'no API key' : p.circuit_open_seconds ? `resting ${p.circuit_open_seconds}s (quota)` : 'available'}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="grid gap-2 p-5 text-sm sm:grid-cols-3">
        <div>
          <p className="text-slate-500">Version</p>
          <p className="font-mono">{data.version}</p>
        </div>
        <div>
          <p className="text-slate-500">Commit</p>
          <p className="font-mono">{data.commit.slice(0, 12)}</p>
        </div>
        <div>
          <p className="text-slate-500">Latest CI run</p>
          {data.ci_run_url ? (
            <a className="inline-flex items-center gap-1 text-brand-700 underline" href={data.ci_run_url} target="_blank" rel="noreferrer">
              GitHub Actions <ExternalLink className="size-3.5" aria-hidden />
            </a>
          ) : (
            <p className="text-slate-600">local build</p>
          )}
        </div>
      </Card>
    </div>
  )
}
