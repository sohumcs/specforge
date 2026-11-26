import clsx from 'clsx'
import { Check, Loader2, X } from 'lucide-react'

import { GENERATE_STEPS, STEP_LABELS } from '../lib/meta'
import type { Job } from '../lib/types'
import { ProviderBadge } from './ui'

/** Live step list for a generation job (parsing → … → scoring). */
export function JobProgress({ job, steps = GENERATE_STEPS }: { job: Job | null; steps?: string[] }) {
  const current = job?.step ?? 'queued'
  const idx = job?.status === 'succeeded' ? steps.length : steps.indexOf(current)
  const failed = job && (job.status === 'failed' || job.status === 'dead')
  const provider = (job?.result?.provider as string | undefined) ?? null
  return (
    <div aria-live="polite" className="space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{failed ? 'Failed' : job?.status === 'succeeded' ? 'Done' : STEP_LABELS[current] ?? current}</span>
        <span className="tabular-nums text-slate-600">{job?.progress ?? 0}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200" aria-hidden>
        <div className={clsx('h-full rounded-full transition-all duration-500', failed ? 'bg-rose-500' : 'bg-brand-600')} style={{ width: `${job?.progress ?? 2}%` }} />
      </div>
      <ol className="grid gap-1.5 text-sm sm:grid-cols-2">
        {steps.map((s, i) => {
          const state = failed && i === idx ? 'failed' : i < idx ? 'done' : i === idx ? 'active' : 'todo'
          return (
            <li key={s} className={clsx('flex items-center gap-2', state === 'todo' && 'text-slate-400')}>
              {state === 'done' && <Check className="size-4 text-emerald-600" aria-hidden />}
              {state === 'active' && <Loader2 className="size-4 animate-spin text-brand-600" aria-hidden />}
              {state === 'failed' && <X className="size-4 text-rose-600" aria-hidden />}
              {state === 'todo' && <span className="size-4 rounded-full border border-slate-300" aria-hidden />}
              <span>{STEP_LABELS[s] ?? s}</span>
              <span className="sr-only">({state})</span>
            </li>
          )
        })}
      </ol>
      {provider && (
        <p className="text-sm text-slate-600">
          Answered by <ProviderBadge provider={provider} />
        </p>
      )}
      {failed && job?.error && <p role="alert" className="text-sm text-rose-700">{job.error.message}</p>}
    </div>
  )
}
