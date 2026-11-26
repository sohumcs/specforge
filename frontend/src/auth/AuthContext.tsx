import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api, refreshAccessToken, setAccessToken } from '../lib/api'
import type { User } from '../lib/types'

interface AuthState {
  user: User | null
  ready: boolean // the initial silent refresh has finished
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string) => Promise<void>
  demoLogin: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const qc = useQueryClient()

  const loadMe = useCallback(async () => setUser(await api<User>('/me')), [])

  useEffect(() => {
    // Restore a session from the refresh cookie, if there is one.
    let cancelled = false
    refreshAccessToken()
      .then(async (ok) => {
        if (ok && !cancelled) await loadMe()
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setReady(true))
    return () => {
      cancelled = true
    }
  }, [loadMe])

  const signIn = useCallback(
    async (path: string, json?: unknown) => {
      const t = await api<{ access_token: string }>(path, { method: 'POST', json })
      setAccessToken(t.access_token)
      qc.clear()
      await loadMe()
    },
    [loadMe, qc],
  )

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      login: (email, password) => signIn('/auth/login', { email, password }),
      register: (email, password, display_name) => signIn('/auth/register', { email, password, display_name }),
      demoLogin: () => signIn('/auth/demo'),
      logout: async () => {
        await api('/auth/logout', { method: 'POST' }).catch(() => undefined)
        setAccessToken(null)
        setUser(null)
        qc.clear()
      },
    }),
    [user, ready, signIn, qc],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
