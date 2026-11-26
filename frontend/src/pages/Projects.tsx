import { FolderKanban, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, errorMessage } from '../components/ui'
import { useCreateProject, useProjects } from '../lib/queries'

export default function Projects() {
  const { user } = useAuth()
  const projects = useProjects()
  const create = useCreateProject()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const p = await create.mutateAsync({ name: String(f.get('name')), description: String(f.get('description') ?? '') })
    navigate(`/app/p/${p.id}`)
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Projects</h1>
        {!user?.is_demo && (
          <Button onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <Plus className="size-4" aria-hidden /> New project
          </Button>
        )}
      </div>
      {open && (
        <Card className="mt-4 p-4">
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1 text-sm">
              <span className="font-medium">Name</span>
              <input name="name" required maxLength={200} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
            </label>
            <label className="flex-[2] text-sm">
              <span className="font-medium">Description (optional)</span>
              <input name="description" maxLength={5000} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
            </label>
            <Button type="submit" loading={create.isPending}>
              Create
            </Button>
          </form>
          {create.error && <p role="alert" className="mt-2 text-sm text-rose-700">{errorMessage(create.error)}</p>}
        </Card>
      )}
      <div className="mt-6">
        {projects.isLoading && <div className="grid gap-3 sm:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-24" />)}</div>}
        {projects.error && <ErrorState error={projects.error} onRetry={() => projects.refetch()} />}
        {projects.data && projects.data.items.length === 0 && (
          <EmptyState title="No projects yet" action={<Button onClick={() => setOpen(true)}>Create your first project</Button>}>
            A project holds blueprints and the people who work on them (owner, editor, viewer).
          </EmptyState>
        )}
        <ul className="grid gap-3 sm:grid-cols-2">
          {projects.data?.items.map((p) => (
            <li key={p.id}>
              <Link to={`/app/p/${p.id}`} className="block rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-300 hover:shadow">
                <div className="flex items-center gap-2">
                  <FolderKanban className="size-5 text-brand-600" aria-hidden />
                  <span className="font-semibold">{p.name}</span>
                  {p.is_sandbox && <Badge className="bg-amber-100 text-amber-900">sandbox · resets nightly</Badge>}
                  {p.my_role && <Badge className="ml-auto bg-slate-100 text-slate-700">{p.my_role}</Badge>}
                </div>
                {p.description && <p className="mt-2 text-sm text-slate-600">{p.description}</p>}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
