import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useEffect, useRef, useState } from 'react'

import { API_BASE, api, getAccessToken, refreshAccessToken } from './api'
import type { Job } from './types'

const TERMINAL = new Set(['succeeded', 'failed', 'dead'])

/**
 * Follow a background job live.
 *
 * Uses Server-Sent Events via fetch (the native EventSource can't send an
 * Authorization header). If the stream fails, it falls back to polling
 * GET /jobs/{id} every 2 s, so progress always arrives.
 */
export function useJob(jobId: string | null, onDone?: (job: Job) => void): Job | null {
  const [job, setJob] = useState<Job | null>(null)
  const doneRef = useRef(onDone)

  useEffect(() => {
    doneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    if (!jobId) return
    const ctrl = new AbortController()
    let finished = false
    let poll: ReturnType<typeof setInterval> | undefined

    const accept = (j: Job) => {
      setJob(j)
      if (TERMINAL.has(j.status) && !finished) {
        finished = true
        ctrl.abort()
        if (poll) clearInterval(poll)
        doneRef.current?.(j)
      }
    }

    const startPolling = () => {
      if (poll || finished) return
      poll = setInterval(() => {
        api<Job>(`/jobs/${jobId}`).then(accept).catch(() => undefined)
      }, 2000)
    }

    fetchEventSource(`${API_BASE}/jobs/${jobId}/events`, {
      signal: ctrl.signal,
      openWhenHidden: true,
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
      async onopen(res) {
        if (res.status === 401 && (await refreshAccessToken())) throw new Error('retry with new token')
        if (!res.ok) throw new Error(`SSE ${res.status}`)
      },
      onmessage(ev) {
        if (ev.event === 'progress' && ev.data) accept(JSON.parse(ev.data) as Job)
      },
      onclose() {
        if (!finished) startPolling()
      },
      onerror() {
        startPolling()
        throw new Error('stop retrying SSE; polling instead') // stop fetchEventSource's own retry
      },
    }).catch(() => startPolling())

    return () => {
      finished = true
      ctrl.abort()
      if (poll) clearInterval(poll)
    }
  }, [jobId])

  return job
}
