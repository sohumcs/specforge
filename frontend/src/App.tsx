import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import Landing from './pages/Landing'
import { LoginPage, RegisterPage } from './pages/Login'

// Heavier, signed-in pages are code-split so the landing page loads fast.
const Projects = lazy(() => import('./pages/Projects'))
const ProjectPage = lazy(() => import('./pages/ProjectPage'))
const BlueprintPage = lazy(() => import('./pages/BlueprintPage'))
const StatusPage = lazy(() => import('./pages/StatusPage'))

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()
  if (!ready) return <Spinner label="Restoring your session" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route path="status" element={<StatusPage />} />
          <Route path="app" element={<RequireAuth><Projects /></RequireAuth>} />
          <Route path="app/p/:projectId" element={<RequireAuth><ProjectPage /></RequireAuth>} />
          <Route path="app/b/:blueprintId" element={<RequireAuth><BlueprintPage /></RequireAuth>} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

function NotFound() {
  return (
    <div className="mx-auto max-w-lg p-10 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-slate-600">That page doesn't exist.</p>
      <a className="mt-4 inline-block text-brand-700 underline" href="/">
        Go home
      </a>
    </div>
  )
}
