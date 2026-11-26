import { Activity, BookOpen, LogOut } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { GithubIcon } from './BrandIcons'
import { LINKS } from '../lib/meta'
import { Logo } from './Logo'
import { Badge, Button } from './ui'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-2.5 py-1.5 text-sm font-medium ${isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-700 hover:bg-slate-100'}`

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const workspace = useLocation().pathname.startsWith('/app/b/')
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:shadow">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-3 sm:gap-4 sm:px-4">
          <Link to="/" className="flex items-center gap-2 font-semibold text-slate-900" aria-label="SPECForge home">
            <Logo className="size-7" />
            <span className="hidden min-[420px]:inline">SPECForge</span>
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1">
            {user && (
              <NavLink to="/app" end className={navClass}>
                Projects
              </NavLink>
            )}
            <NavLink to="/status" className={navClass}>
              <span className="inline-flex items-center gap-1">
                <Activity className="size-4" aria-hidden /> <span className="sr-only sm:not-sr-only">Status</span>
              </span>
            </NavLink>
            <a href="/docs" className={navClass({ isActive: false })} target="_blank" rel="noreferrer">
              <span className="inline-flex items-center gap-1">
                <BookOpen className="size-4" aria-hidden /> <span className="sr-only sm:not-sr-only">API docs</span>
              </span>
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <a href={LINKS.github} target="_blank" rel="noreferrer" className="rounded-md p-2 text-slate-600 hover:bg-slate-100" aria-label="SPECForge on GitHub">
              <GithubIcon />
            </a>
            {user ? (
              <>
                <span className="hidden text-sm text-slate-700 sm:inline">{user.display_name}</span>
                {user.is_demo && <Badge className="bg-amber-100 text-amber-900">demo</Badge>}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    await logout()
                    navigate('/')
                  }}
                >
                  <LogOut className="size-4" aria-hidden /> <span className="sr-only sm:not-sr-only">Sign out</span>
                </Button>
              </>
            ) : (
              <Link to="/login" className="rounded-md px-3 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-50">
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      {!workspace && <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-600">
        Built by{' '}
        <a className="font-medium text-brand-700 hover:underline" href={LINKS.linkedin} target="_blank" rel="noreferrer">
          Sohum
        </a>{' '}
        · FastAPI · Celery · PostgreSQL + pgvector · React · k3s ·{' '}
        <a className="hover:underline" href={LINKS.github} target="_blank" rel="noreferrer">
          source
        </a>
      </footer>}
    </div>
  )
}
