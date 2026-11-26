import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { Logo } from '../components/Logo'
import { Button, Card, errorMessage } from '../components/ui'
import { useTryDemo } from './Landing'

function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-slate-800">{label}</span>
      <input {...props} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 shadow-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30 focus:outline-none" />
    </label>
  )
}

function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  const demo = useTryDemo()
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-14">
      <Logo className="size-10" />
      <h1 className="mt-4 text-2xl font-semibold">{title}</h1>
      <Card className="mt-6 w-full p-6">{children}</Card>
      <div className="mt-6 w-full rounded-xl bg-amber-50 p-4 text-center text-sm text-amber-950 ring-1 ring-amber-200">
        Just looking around?{' '}
        <Button size="sm" variant="secondary" className="ml-1" onClick={() => demo.go()} loading={demo.busy === 'demo'}>
          Use the demo instead
        </Button>
        {demo.error && <p role="alert" className="mt-2 text-rose-700">{demo.error}</p>}
      </div>
    </div>
  )
}

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/app'
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      await login(String(f.get('email')), String(f.get('password')))
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Sign in to SPECForge">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <Button type="submit" className="w-full" loading={busy}>
          Sign in
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-600">
        No account? <Link className="font-medium text-brand-700 hover:underline" to="/register">Create one</Link>
      </p>
    </AuthShell>
  )
}

export function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      await register(String(f.get('email')), String(f.get('password')), String(f.get('name')))
      navigate('/app', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Create your account">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Name" name="name" autoComplete="name" required />
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password (8+ characters)" name="password" type="password" autoComplete="new-password" minLength={8} required />
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <Button type="submit" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-600">
        Already registered? <Link className="font-medium text-brand-700 hover:underline" to="/login">Sign in</Link>
      </p>
    </AuthShell>
  )
}
