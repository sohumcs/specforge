import { ArrowRight, GitBranch, ListChecks, Network, ShieldCheck, Sparkles, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { GithubIcon, LinkedinIcon } from '../components/BrandIcons'
import { Button, Card, errorMessage } from '../components/ui'
import { api } from '../lib/api'
import { LINKS, NODE_HEX } from '../lib/meta'
import { useSamples } from '../lib/queries'
import type { Blueprint, Page, Project } from '../lib/types'

/** Log in as the shared demo user and open the sandbox (or one sample in it). */
export function useTryDemo() {
  const { demoLogin, user } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const go = async (sampleSlug?: string) => {
    setBusy(sampleSlug ?? 'demo')
    setError(null)
    try {
      if (!user) await demoLogin()
      const projects = await api<Page<Project>>('/projects')
      const sandbox = projects.items.find((p) => p.is_sandbox) ?? projects.items[0]
      if (!sandbox) return navigate('/app')
      if (sampleSlug) {
        const bps = await api<Page<Blueprint>>(`/projects/${sandbox.id}/blueprints?limit=100`)
        const bp = bps.items.find((b) => b.settings?.sample === sampleSlug)
        if (bp) return navigate(`/app/b/${bp.id}`)
      }
      navigate(`/app/p/${sandbox.id}`)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }
  return { go, busy, error }
}

const FEATURES = [
  {
    icon: Network,
    title: 'A graph, not a document',
    text: 'Every requirement, story, module, endpoint, table, test and risk is a node. Edges trace why each one exists.',
  },
  {
    icon: ShieldCheck,
    title: 'Generate → verify → trace',
    text: '12 deterministic rules + embeddings (pgvector) for duplicates + an NLI model for contradictions, rolled into a 0–100 Quality Score.',
  },
  {
    icon: GitBranch,
    title: 'Change impact, live',
    text: 'Edit a requirement and watch the affected stories, APIs and tests light up hop by hop, then regenerate just that subgraph.',
  },
  {
    icon: ListChecks,
    title: 'Delivery tracking',
    text: 'Move stories and tests across a kanban board; progress rolls up per requirement and per module.',
  },
]

const STACK = ['FastAPI', 'Celery + Redis', 'PostgreSQL + pgvector', 'sentence-transformers', 'NLI cross-encoder', 'spaCy', 'React + TS', 'React Flow', 'Docker', 'k3s', 'Terraform', 'Ansible', 'GitHub Actions', 'AWS']

export default function Landing() {
  const { go, busy, error } = useTryDemo()
  const samples = useSamples()
  return (
    <div>
      <section className="relative overflow-hidden bg-gradient-to-b from-brand-900 via-indigo-950 to-slate-900 text-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 lg:grid-cols-[1.05fr_1fr] lg:py-24">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-sm text-indigo-100 ring-1 ring-white/20">
              <Sparkles className="size-4 text-amber-300" aria-hidden /> AI software architect, with receipts
            </p>
            <h1 className="mt-5 text-4xl font-bold tracking-tight sm:text-5xl">
              Turn a project brief into a blueprint <span className="text-amber-300">you can trace</span>.
            </h1>
            <p className="mt-5 max-w-xl text-lg text-indigo-100">
              SPECForge generates requirements, user stories, modules, REST APIs, a data model, tests and a risk register as one linked graph. Then it checks
              its own work and tracks delivery against it.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button size="lg" variant="spark" onClick={() => go()} loading={busy === 'demo'}>
                <Zap className="size-5" aria-hidden /> Try it instantly
              </Button>
              <a href="#how" className="inline-flex items-center gap-1 rounded-lg px-4 py-3 font-medium text-indigo-100 ring-1 ring-white/25 hover:bg-white/10">
                How it works <ArrowRight className="size-4" aria-hidden />
              </a>
            </div>
            <p className="mt-3 text-sm text-indigo-200">No sign-up. You get an editor seat in a shared sandbox that resets nightly.</p>
            {error && (
              <p role="alert" className="mt-3 rounded-md bg-rose-500/20 px-3 py-2 text-sm text-rose-100">
                {error}
              </p>
            )}
          </div>
          <HeroAnimation />
        </div>
      </section>

      <section id="how" className="mx-auto max-w-7xl px-4 py-16">
        <h2 className="text-2xl font-semibold">What makes it different</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <Card key={title} className="p-5">
              <Icon className="size-6 text-brand-600" aria-hidden />
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm text-slate-600">{text}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-16">
          <h2 className="text-2xl font-semibold">Sample blueprints</h2>
          <p className="mt-1 text-slate-600">Generated by a real LLM run, verified, and ready to explore in under a second.</p>
          <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {(samples.data ?? []).map((s) => (
              <Card key={s.slug} className="flex flex-col p-5">
                <h3 className="font-semibold">{s.title}</h3>
                <p className="mt-2 line-clamp-4 flex-1 text-sm text-slate-600">{s.brief}</p>
                <p className="mt-3 text-xs text-slate-500">
                  {s.nodes} nodes · {s.edges} links · by {s.generated_by}
                </p>
                <Button variant="secondary" className="mt-3" onClick={() => go(s.slug)} loading={busy === s.slug}>
                  Open in demo <ArrowRight className="size-4" aria-hidden />
                </Button>
              </Card>
            ))}
            {samples.isLoading && [0, 1, 2, 3].map((i) => <div key={i} className="h-56 animate-pulse rounded-xl bg-slate-100" />)}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-16">
        <h2 className="text-2xl font-semibold">Architecture</h2>
        <p className="mt-1 text-slate-600">
          Same images run on a free Oracle Cloud ARM VM (k3s) and on AWS on demand. Full write-up in{' '}
          <a className="text-brand-700 underline" href={`${LINKS.github}/blob/main/docs/ARCHITECTURE.md`} target="_blank" rel="noreferrer">
            ARCHITECTURE.md
          </a>
          .
        </p>
        <Card className="mt-6 overflow-x-auto p-4">
          <ArchitectureDiagram />
        </Card>
        <ul className="mt-6 flex flex-wrap gap-2" aria-label="Technology stack">
          {STACK.map((t) => (
            <li key={t} className="rounded-full bg-white px-3 py-1 text-sm text-slate-700 ring-1 ring-slate-200">
              {t}
            </li>
          ))}
        </ul>
        <div className="mt-8 flex flex-wrap gap-3">
          <a href={LINKS.github} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
            <GithubIcon className="size-4" /> Source on GitHub
          </a>
          <a href={LINKS.linkedin} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-[#0a66c2] px-4 py-2 text-sm font-medium text-white hover:brightness-110">
            <LinkedinIcon className="size-4" /> Sohum on LinkedIn
          </a>
          <Link to="/status" className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-white">
            System status
          </Link>
        </div>
      </section>
    </div>
  )
}

// ----------------------------------------------------------------- hero animation

const COLS = ['requirement', 'story', 'module', 'api', 'entity', 'test'] as const
const LABELS = ['REQ', 'US', 'MOD', 'API', 'ENT', 'TST']
const ROWS = [
  [1, 3],
  [0, 2, 4],
  [1, 3],
  [0, 2, 4],
  [1, 3],
  [0, 2, 4],
]

/** A ~12 s looping walkthrough: parse → generate graph → verify → edit → impact wave. */
function HeroAnimation() {
  const [cycle, setCycle] = useState(0)
  const [phase, setPhase] = useState(0)
  useEffect(() => {
    const timers = [0, 1800, 4200, 6200, 8200].map((t, i) => setTimeout(() => setPhase(i), t))
    const restart = setTimeout(() => {
      setPhase(0)
      setCycle((c) => c + 1)
    }, 12000)
    return () => [...timers, restart].forEach(clearTimeout)
  }, [cycle])
  const captions = ['Parsing the brief with spaCy…', 'Generating a linked graph (Gemini → Groq → fallback)…', 'Verifying: rules + embeddings + NLI…', 'Score 96/100: 2 issues, both fixable', 'Edit REQ-002 → impact ripples downstream']
  const x = (c: number) => 30 + c * 74
  const y = (r: number) => 30 + r * 46
  return (
    <div className="rounded-2xl bg-white/5 p-4 ring-1 ring-white/15" aria-label="Animated walkthrough of SPECForge" role="img">
      <svg key={cycle} viewBox="0 0 470 250" className="w-full">
        {phase >= 1 &&
          ROWS.slice(0, -1).flatMap((rows, c) =>
            rows.map((r) => {
              const nextRows = ROWS[c + 1]
              const r2 = nextRows[(r + c) % nextRows.length]
              const lit = phase >= 4 && c >= 0 && r === 1
              return (
                <path
                  key={`${c}-${r}`}
                  className="edge-draw"
                  style={{ animationDelay: `${0.2 + c * 0.25}s` }}
                  d={`M${x(c) + 22} ${y(r)} C ${x(c) + 48} ${y(r)}, ${x(c + 1) - 26} ${y(r2)}, ${x(c + 1) - 22} ${y(r2)}`}
                  stroke={lit ? '#fbbf24' : 'rgba(199,210,254,0.45)'}
                  strokeWidth={lit ? 2.2 : 1.4}
                  fill="none"
                />
              )
            }),
          )}
        {phase >= 1 &&
          COLS.flatMap((t, c) =>
            ROWS[c].map((r) => {
              const impacted = phase >= 4 && ((c === 0 && r === 1) || (c > 0 && (r === 0 || r === 2) && c % 2 === 1) || (c > 0 && r === 1))
              const issue = phase === 3 && ((c === 1 && r === 4) || (c === 3 && r === 2))
              return (
                <g key={`${t}${r}`} className="forge-in" style={{ animationDelay: `${c * 0.25 + r * 0.05}s` }}>
                  <rect
                    x={x(c) - 22}
                    y={y(r) - 13}
                    width="44"
                    height="26"
                    rx="6"
                    fill={impacted ? '#78350f' : '#1e1b4b'}
                    stroke={issue ? '#f43f5e' : impacted ? '#fbbf24' : NODE_HEX[t]}
                    strokeWidth={issue || impacted ? 2.4 : 1.5}
                    style={impacted ? { transition: 'all .4s', transitionDelay: `${c * 0.25}s` } : undefined}
                  />
                  <text x={x(c)} y={y(r) + 4} textAnchor="middle" fontSize="10" fill="#e0e7ff" fontFamily="ui-monospace, monospace">
                    {LABELS[c]}
                  </text>
                </g>
              )
            }),
          )}
        {phase === 0 && (
          <g>
            {[0, 1, 2, 3].map((i) => (
              <rect key={i} x={60} y={70 + i * 26} width={320 - i * 50} height="9" rx="4" fill="rgba(199,210,254,0.35)" className="forge-in" style={{ animationDelay: `${i * 0.2}s` }} />
            ))}
          </g>
        )}
        {phase >= 2 && phase < 4 && (
          <g className="forge-in">
            <circle cx="430" cy="215" r="26" fill="#022c22" stroke="#10b981" strokeWidth="4" />
            <text x="430" y="221" textAnchor="middle" fontSize="16" fontWeight="700" fill="#ecfdf5">
              {phase >= 3 ? 96 : '…'}
            </text>
          </g>
        )}
      </svg>
      <p className="mt-2 text-center font-mono text-sm text-indigo-100" aria-live="polite">
        {captions[phase]}
      </p>
    </div>
  )
}

function ArchitectureDiagram() {
  const box = (x: number, y: number, w: number, label: string, sub: string, color: string) => (
    <g>
      <rect x={x} y={y} width={w} height="52" rx="10" fill="#fff" stroke={color} strokeWidth="2" />
      <text x={x + w / 2} y={y + 22} textAnchor="middle" fontSize="13" fontWeight="600" fill="#0f172a">
        {label}
      </text>
      <text x={x + w / 2} y={y + 39} textAnchor="middle" fontSize="10.5" fill="#475569">
        {sub}
      </text>
    </g>
  )
  const arrow = (d: string) => <path d={d} stroke="#94a3b8" strokeWidth="1.6" fill="none" markerEnd="url(#arr)" />
  return (
    <svg viewBox="0 0 900 300" className="min-w-[760px]" role="img" aria-label="Architecture: browser to Traefik ingress, to the React frontend and FastAPI; FastAPI uses PostgreSQL with pgvector and Redis; Celery workers run generation and verification, calling Gemini, Groq or the offline demo provider; Prometheus and Grafana monitor everything.">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10z" fill="#94a3b8" />
        </marker>
      </defs>
      {box(10, 124, 110, 'Browser', 'React SPA', '#64748b')}
      {box(160, 124, 130, 'Traefik', 'TLS · Let’s Encrypt', '#0ea5e9')}
      {box(330, 40, 140, 'frontend', 'nginx (static)', '#6366f1')}
      {box(330, 124, 140, 'api', 'FastAPI · JWT · RBAC', '#4f46e5')}
      {box(530, 40, 160, 'PostgreSQL', 'graph + pgvector', '#0f766e')}
      {box(530, 124, 160, 'Redis', 'broker · limits · pub/sub', '#dc2626')}
      {box(530, 208, 160, 'Celery worker', 'LLM · spaCy · ML models', '#7c3aed')}
      {box(740, 172, 150, 'Gemini → Groq', '→ cache → demo', '#d97706')}
      {box(740, 248, 150, 'Prometheus', 'Grafana · alerts', '#ea580c')}
      {arrow('M120 150 H158')}
      {arrow('M290 140 C 310 140, 310 66, 328 66')}
      {arrow('M290 150 H328')}
      {arrow('M470 140 C 500 140, 500 66, 528 66')}
      {arrow('M470 150 H528')}
      {arrow('M610 176 V206')}
      {arrow('M690 220 C 715 220, 715 198, 738 198')}
      {arrow('M690 240 C 715 240, 715 274, 738 274')}
      <text x="400" y="200" textAnchor="middle" fontSize="10.5" fill="#64748b">
        SSE progress
      </text>
    </svg>
  )
}
