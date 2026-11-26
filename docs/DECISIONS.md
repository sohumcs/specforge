# Architecture Decision Records

Short ADRs: context → decision → rejected alternatives. Status `Proposed` until Phase 1 is approved.

---

## ADR-001 — Target A host: Oracle Cloud Always Free Ampere A1 VM
**Status:** Proposed · 2026-11-26

**Context.** We need a free, always-on host for Postgres + Redis + Celery + two CPU ML models + k3s. Oracle **cut** the Always Free A1 allowance in 2026: the official page now says 1,500 OCPU-h + 9,000 GB-h/month, i.e. **2 OCPUs and 12 GB RAM** (it used to be 4 OCPU / 24 GB). 200 GB block storage, 20 GB object storage and 10 TB/month egress are also included.

**Decision.** One `VM.Standard.A1.Flex` instance at 2 OCPU / 12 GB, Ubuntu 24.04 arm64, single-node k3s. The memory budget in ARCHITECTURE §5 fits in about 7.5 GB of limits.

**Risks and how we handle them.**
- *Idle reclamation*: Oracle reclaims instances where CPU, network and memory are all under 20 % (p95) for 7 days. Our resident memory stays above 20 %, and we add uptime checks.
- *"Out of host capacity"* when creating A1 in popular regions: Terraform retries, and the RUNBOOK documents picking another availability domain.
- *The allowance shrinking again*: the split-PaaS fallback below stays documented.
- ARM only, so CI builds multi-arch images (amd64 + arm64).

**Rejected.**
- *Split PaaS* (free frontend host + free container host + managed Postgres/Redis): free container hosts sleep or cap RAM at 512 MB, so the ML models don't fit. It also drops k3s/Terraform/Ansible from the live path, which breaks resume accuracy. Kept as the fallback.
- *AWS 24/7*: not free. See ADR-009.

## ADR-002 — Async: Celery + Redis, progress via SSE
**Decision.** Celery workers with Redis as broker. Job state is persisted in Postgres (`jobs` table), and progress events go over Redis pub/sub to a FastAPI **SSE** endpoint. `acks_late=True`, `task_reject_on_worker_lost=True`, exponential-backoff retries, soft/hard time limits, and a dead-letter queue (`dlq`) for tasks that exhaust retries.
**Why SSE over WebSocket.** Progress only flows one way (server → client). SSE works over plain HTTP through Traefik, reconnects automatically (`Last-Event-ID`), and is simpler to test. If SSE drops, the UI falls back to polling `GET /jobs/{id}`.
**Rejected.** RQ/Arq (the resume says Celery). WebSockets (two-way channel we don't need).

## ADR-003 — Blueprint graph stored relationally (nodes + typed edges) in Postgres
**Decision.** `nodes` and `edges` tables. Traversal uses recursive CTEs with cycle guards and depth caps. pgvector lives in the same DB, on `nodes.embedding`.
**Why.** One datastore covers transactions (graph writes are atomic with job state), embeddings, and ordinary CRUD. Blueprints are small (~50–300 nodes), so CTE traversal takes milliseconds.
**Rejected.** Neo4j (another service, and the free tier is too small to self-host alongside everything else). Storing the blueprint as a JSONB document (can't index edges or traverse them in SQL).

## ADR-004 — LLM providers: Gemini (primary) → Groq (secondary) → cache → DemoProvider
**Context (checked 2026-11-26, see COSTS.md).**
- Gemini API free tier covers Flash / Flash-Lite models (e.g. `gemini-3.5-flash-lite`, `gemini-3.8-flash`). Google doesn't publish per-model free RPM/RPD; they show up in AI Studio. **Free-tier prompts may be used to improve Google products.** That's acceptable here because briefs are demo content, and the landing page says so. Gemini 2.5 models are being deprecated (requests re-routed from 2026-12-01), which is why model IDs are config.
- Groq free plan: production models `openai/gpt-oss-120b` / `openai/gpt-oss-20b` support **strict `json_schema`** structured output. The docs table shows roughly 30 RPM / 1K RPD / 8K TPM / 200K TPD (the docs label is ambiguous; verify in the console). Llama 3.x models are on Groq's deprecation list, so we avoid them.

**Decision.** `LLMProvider` protocol + adapters. Primary is Gemini (`gemini-3.5-flash-lite` by default, env-overridable), secondary is Groq `openai/gpt-oss-120b`, then the generation cache, then the deterministic `DemoProvider`. Pydantic validation with up to 2 repair retries. A per-provider circuit breaker sits in Redis.
**Why this order.** Gemini Flash-Lite has a larger context and a more generous free budget for long briefs. Groq is fast, and strict schemas make it a reliable second. The demo can never crash, because the last two links have no external dependency.
**Rejected.** OpenAI/Anthropic APIs (no free tier). Local LLM via Ollama on the VM (a usable 7B model needs about 5 GB RAM and is slow on 2 ARM cores; it would starve the rest of the stack).

## ADR-005 — ML models (CPU, loaded once per worker)
**Decision.**
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`: 22.7M params, 384-d, Apache-2.0.
- NLI: `cross-encoder/nli-deberta-v3-xsmall`: 70.8M params, Apache-2.0, label order `contradiction, entailment, neutral`.
- NLP: spaCy `en_core_web_sm`, for noun chunks, entities and actor/term extraction from the brief.
- Models are baked into the worker image at build time, so a pod never downloads them at startup.

All model pages were verified on Hugging Face on 2026-11-26. The exact spaCy model version gets pinned when it's installed in Phase 3.
**Rejected.** `nli-deberta-v3-small` (larger, little gain for short requirement sentences). `nli-MiniLM2-L6-H768` (82M, slightly bigger). An LLM-as-judge for contradictions (not deterministic, burns quota). ONNX/int8 is held in reserve and only used if measured memory is too high (it's planned for the small AWS instance, ADR-009).

## ADR-006 — Auth: JWT access + rotating refresh, Argon2id, project-scoped RBAC
**Decision.** 15-minute access JWT (HS256, `sub`, `exp`, `jti`) in memory on the client. 7-day refresh token in an httpOnly, Secure, SameSite=Strict cookie, stored hashed, **rotated on each use, with reuse detection that revokes the token family**. Roles `owner > editor > viewer` live per project in `project_members`, plus a global `is_admin`. Enforcement is a FastAPI dependency, never the frontend.
**Rejected.** Sessions in Redis (the resume says JWT). Storing tokens in localStorage (XSS exposure).

## ADR-007 — Frontend: React + TS + Vite, React Flow, TanStack Query, Tailwind
**Decision.** React Flow (`@xyflow/react`) for the graph, with dagre/ELK auto-layout. TanStack Query for server state. Small local state stays in React context. No Redux.
**Rejected.** Cytoscape.js (React Flow's custom node components are easier to make accessible and to style with Tailwind). Next.js (no SSR need; static SPA hosting is simpler).

## ADR-008 — TLS and domain: Traefik (bundled with k3s) + cert-manager + Let's Encrypt on a DuckDNS subdomain
**Decision.** Unless you own a domain, use a free DuckDNS subdomain (e.g. `specforge-sohum.duckdns.org`). DuckDNS has a TXT-record API, so DNS-01 works, but HTTP-01 through Traefik is simpler and is the default. cert-manager `ClusterIssuer` uses Let's Encrypt staging first, then prod.
**Rejected.** sslip.io/nip.io (IP-embedded hostnames look unprofessional, and Let's Encrypt rate limits are shared). Cloudflare Tunnel (works, but hides the ingress/TLS work the resume claims).

## ADR-009 — Target B (AWS): on-demand only, small instance, budget alarm
**Context (checked 2026-11-26).** New AWS accounts use a **credits model**: $100 at sign-up plus up to $100 more. A "Free plan" account is closed after 6 months. Free-tier-eligible types include `t3.micro`, `t3.small`, `t4g.micro`, `t4g.small`, `c7i-flex.large`, `m7i-flex.large`. Public IPv4 / Elastic IP costs **$0.005/h whether attached or idle** (~$3.60/month if left up), and that's drawn from credits. CloudWatch always-free covers 10 custom metrics, 10 alarms, 3 dashboards and 5 GB logs.
**Decision.** `t4g.small` (2 vCPU ARM, 2 GB) by default, so the same arm64 images work. Use a "lite" profile: worker concurrency 1, ONNX int8 models, 2 GB swap. `m7i-flex.large` (8 GB) is an optional `-var` for interviews. `make aws-up` / `aws-down`, an AWS Budget at $1 with email alerts, and a CloudWatch agent shipping container logs (kept within 5 GB) plus a dashboard and alarms within the free counts. You run it yourself. Nothing on AWS is left running.
**Rejected.** Running AWS as Target A (credits run out and the account closes). EKS (control plane costs ~$73/month).

## ADR-010 — Monitoring: in-cluster Prometheus + Grafana, UptimeRobot for external checks
**Decision.** Plain Prometheus and Grafana Deployments with a small retention (7 days), not the full kube-prometheus-stack (too heavy for 12 GB). Grafana dashboards are provisioned from JSON in the repo. External uptime uses the UptimeRobot free plan (50 monitors, 5-minute interval, commercial use allowed) with email alerts. Alertmanager handles in-cluster alerts by email.
**Rejected.** Grafana Cloud free (10k series, 14-day retention) is a fine alternative, but self-hosting is what the resume says. It stays documented as an option.

## ADR-011 — Images on GHCR, repo public, CI on GitHub-hosted runners
**Decision.** GHCR is free for public packages, and Actions standard runners are free for public repos. Multi-arch images are built with buildx + QEMU on amd64 runners, switching to native `ubuntu-24.04-arm` runners if they're confirmed free for public repos.
**Needs your OK:** making `sohumcs/specforge` public (ground rule 6).

## ADR-012 — PDF export with WeasyPrint (HTML → PDF)
**Decision.** Render the same Jinja HTML used for Markdown/HTML export, then convert it with WeasyPrint. This adds Pango libs to the API image. If image size or Trivy findings are a problem, switch to ReportLab (pure Python).

## ADR-013 — Local tooling on Windows: run `make`/Ansible from WSL Ubuntu
**Context.** This machine has Docker, Terraform, kubectl, gh, Python 3.13 and Node 22. `make` and Ansible aren't installed on Windows, and Ansible has no native Windows control node.
**Decision.** Document `make dev` for Linux/macOS/WSL (WSL Ubuntu is installed here) and provide a `scripts/dev.ps1` equivalent. Ansible runs from WSL or from CI.

## ADR-014 — Sync SQLAlchemy 2.0 + psycopg 3, shared by API and workers
**Status:** Accepted · 2026-11-26 (Phase 2)
**Decision.** Sync sessions everywhere. FastAPI runs sync endpoints in its threadpool, and Celery tasks are sync, so the API and the workers share the same service functions (`app/services/*`), and those functions are tested once.
**Rejected.** Async SQLAlchemy + asyncpg. It's faster under very high concurrency, but it would need a second code path for Celery, and the demo's traffic doesn't need it.

## ADR-015 — RBAC: non-members get 404, under-privileged members get 403
**Status:** Accepted · 2026-11-26
**Decision.** `app/services/access.py` resolves node → blueprint → project, then checks the caller's role. Non-members get `404` so project IDs can't be probed. Members whose role is too low get `403 FORBIDDEN` with `details.required`. Admins bypass the check. `tests/test_rbac.py` runs a 14-action × 5-role matrix.

## ADR-016 — Change-impact as one recursive CTE over a "directed view" of edges
**Status:** Accepted · 2026-11-26
**Decision.** `app/services/graph.py::_WALK_SQL` first builds `directed(src,dst)`: forward edge types as stored, plus `threatens`/`depends_on` reversed. A recursive walk over that view carries a `path` array to cut cycles, with `max_graph_depth` (12) as a hard cap, and returns each node's *minimum* hop distance. Upstream trace is the same query with the two direction sets swapped. Stale-marking and the `change_events` row are written in the same transaction as the edit.
**Rejected.** Walking the graph in Python (N+1 queries). Postgres `CYCLE` clause (less obvious to readers than an explicit path array).

## ADR-017 — Staged generation (3 LLM calls) instead of one big call
**Status:** Accepted · 2026-11-26 (Phase 3)
**Context.** I measured Groq's free plan from its response headers: `x-ratelimit-limit-tokens: 8000` per minute and 1,000 requests/day. `gpt-oss` reasoning tokens count toward that. A whole blueprint (~55 nodes) needs more than 8K tokens in a single response.
**Decision.** Generate in three stages, each with its own small Pydantic schema: **requirements** (requirements, stories, risks) → **design** (modules, entities, APIs; sees a compact stage-1 summary) → **tests** (sees stories + APIs). Each stage is validated for shape (Pydantic) and meaning (`cross_reference_errors`: every `*_refs` must resolve). Problems go back to the model in a repair prompt, up to 2 times. If a stage exhausts every provider, the *whole* blueprint comes from the stale cache or the DemoProvider, so the stages can never be mixed inconsistently.
**Measured (2026-11-26).** Gemini `gemini-3.5-flash-lite`: 58 nodes in 18.6 s with 0 repairs. Groq `gpt-oss-120b`: full blueprint in 18.9 s, and one real repair round fired (Groq's own 400 `json_validate_failed`).
**Bonus.** Stage-level progress events, and in Phase 4 "regenerate subgraph" can re-run a single stage.

## ADR-018 — Celery worker uses the threads pool
**Decision.** `celery worker -P threads -c 2`. All threads share one in-memory copy of spaCy (and, from Phase 4, the sentence-transformer and NLI models). With prefork, every child process would load its own copy, which doesn't fit on the 12 GB VM. LLM calls are I/O-bound and model inference releases the GIL, so threads lose little throughput. It also works on Windows for local dev, where prefork doesn't.

## ADR-019 — Own Redis fixed-window limiter instead of slowapi
**Decision.** About 50 lines in `app/services/ratelimit.py`: `INCR` + `EXPIRE NX` in one pipeline. Limits apply per user, per IP and globally per day. The shared demo account is limited **per IP** (every recruiter shares one user ID), and the demo login is limited per IP too. Limits are checked only when a *new* job would start, so idempotent retries are free. If Redis is down the endpoint returns **503**, never unmetered access. 429 responses carry `Retry-After` and a friendly message pointing at the sample blueprints.
**Rejected.** slowapi. It's decorator-based per route, which makes the demo-account special case and "count only new jobs" awkward.

## ADR-020 — SSE progress = Redis pub/sub push + periodic DB resync
**Decision.** The worker writes each step to Postgres (the source of truth), then publishes it on `specforge:jobs:<id>`. The SSE endpoint sends the current DB state first, forwards pub/sub messages, re-reads the DB every 5 s in case a message was lost, sends a keep-alive every 15 s, and closes on a terminal status. If Redis is down it falls back to polling the DB every second. The frontend will use fetch-based SSE so it can send the bearer token.

## ADR-021 — Provider error taxonomy and circuit breaker
**Decision.** Adapters raise `ProviderUnavailable` (429/5xx/timeout → move to the next provider and open a Redis circuit for `max(Retry-After, 60 s)`), `ProviderBadOutput` (bad JSON/schema → repair) or `ProviderConfigError` (400/401/403 → skip). Gemini puts its wait time in the error body (`google.rpc.RetryInfo.retryDelay`) and the adapter reads it. A short wait (≤ 20 s) is slept through once before falling over. This was seen live: while I generated the 4 samples, Gemini hit its per-minute quota, the breaker opened, and Groq took over.

## ADR-022 — Contradictions = NLI proposes, polarity cue confirms
**Status:** Accepted · 2026-11-26 (Phase 4)
**Context.** I probed `cross-encoder/nli-deberta-v3-xsmall` before using it. It scored *"Patients can **book** appointments"* vs *"Patients can **cancel** appointments"* at **0.99 contradiction**: to an SNLI-trained model, two different events in one scene contradict. Raw NLI would flag every pair of sibling requirements.
**Decision.** Report a pair only if (1) it's on-topic (embedding cosine ≥ 0.45), (2) NLI P(contradiction) ≥ 0.80 in either direction, and (3) a **polarity cue** differs: a negation in exactly one statement, an antonym-prefix pair (`encrypted`/`unencrypted`), or conflicting numbers for the same unit (`300 ms` vs `2000 ms`). The cue filter also runs *before* NLI, so most pairs never reach the model. The issue is worded as "**may** contradict" and carries the NLI score and cue, so the user can judge it. False positives can be **dismissed**, and dismissals persist across re-verification via an issue fingerprint (`rule_code:sorted(node_ids)`).
**Evidence.** `tests/test_ml.py::test_book_vs_cancel_is_not_reported_although_nli_alone_says_contradiction`. On the 4 curated samples: 1 flag (college ERP, "upload/publish marks" vs "published marks never editable"), which is a legitimate question to raise.
**Rejected.** LLM-as-judge (not deterministic, costs quota). A larger NLI model (memory, and the same SNLI bias).

## ADR-023 — Duplicates via a pgvector self-join; HNSW for "similar nodes"
**Decision.** Embeddings are stored in `nodes.embedding vector(384)`. Duplicate search is one SQL self-join (`1 - (a.embedding <=> b.embedding)`) restricted to the same blueprint and node type: ≥ 0.90 → `DUP-001`, 0.80–0.90 → `DUP-002`. Tests are excluded, because test scenarios are legitimately similar. `GET /nodes/{id}/similar` uses `ORDER BY embedding <=> :vec LIMIT k`, which is served by the HNSW index. Only nodes with a NULL embedding (new or edited) are re-embedded, so repeat verification is cheap.
**Measured.** Paraphrase cosine 0.88 vs unrelated 0.06. On the 4 samples: 0 duplicate false positives at 0.80. ML verification takes ~0.3 s per 60-node blueprint once the models are loaded.

## ADR-024 — Fixes: deterministic where possible, LLM where language is needed
**Decision.** `app/services/fixes.py` maps each rule code to a fixer, and every fix runs in one transaction followed by a full re-verification (`score_before → score_after`).
- **Deterministic** (no quota): merge duplicates (re-point links, drop the duplicate ones), link orphans / APIs / modules to the *most similar* candidate by embedding (or by path-to-entity name match), add missing CRUD endpoints, normalise REST paths and entity names.
- **Generative** (small LLM call through the same fallback chain, with a template fallback): stories + tests for a requirement, tests for a story, Given/When/Then criteria, a missing NFR, risk mitigations.
- **Contradictions** require an LLM or a human. In demo mode the job fails with `FIX_NOT_POSSIBLE` and a clear message rather than inventing a resolution.

Mutating jobs (generate, fix, regenerate) are serialised per blueprint (`409 JOB_IN_PROGRESS`). Verify jobs can run alongside them.

## ADR-025 — Change impact is pruned semantically at module → API edges
**Context.** Live run on a 65-node blueprint: editing one requirement marked **45 nodes** stale, because the walk crossed story → module → *every* API the module exposes.
**Decision.** In the recursive CTE, a `module -exposes-> api` edge is followed only if the API's embedding has cosine ≥ 0.40 with the edited node's embedding. If either embedding is missing, the walk falls back to conservative (follow everything). Impact uses the *pre-edit* embedding, because the API process doesn't load ML models and an edit rarely changes a node's topic. Same edit after the change: **25 nodes**.
**Regenerate subgraph** sends the edited node plus its stale downstream nodes to the LLM and applies the updates by key. IDs, links and kanban status are preserved. In demo mode the nodes are marked reviewed.

## ADR-026 — /ready reports the worker but doesn't gate on it
**Decision.** Workers write a heartbeat (`{models_loaded, ts}`, 30 s TTL) to Redis every 10 s. `/ready` returns 503 only for DB/Redis failures, and *reports* worker and model state. If ML models aren't loaded yet, jobs simply wait in the queue. An API pod shouldn't leave the load balancer because a worker restarted. `/status` shows the same data for humans.

## ADR-027 — Report timestamps use clock_timestamp()
`now()` in Postgres is the *transaction* start time, so two reports written in one transaction tied and "latest report" was ambiguous. A test caught it. `quality_reports.created_at` now defaults to `clock_timestamp()` and is indexed (migration 0003).

## ADR-028 — SPA and API share one origin (proxy in dev, nginx in prod)
**Status:** Accepted · 2026-11-26 (Phase 5)
**Decision.** The browser only ever talks to one origin. In dev, Vite proxies `/api`, `/health`, `/ready` and `/docs` to FastAPI. In production, the frontend's nginx does the same proxying, behind Traefik. The refresh token is an httpOnly, `SameSite=Strict` cookie scoped to `/api/v1/auth`, and the 15-minute access token lives only in JS memory (never localStorage). On a 401 the client refreshes once, with the refresh shared across concurrent requests (`src/lib/api.ts`), then retries.
**Why.** There's no CORS preflight on every call, the cookie works without `SameSite=None`, and XSS can't steal a long-lived credential.

## ADR-029 — Graph layout: own layered layout instead of dagre/ELK
**Decision.** `src/features/graph/layout.ts` (~90 lines) puts node types in columns in trace order: risk | requirement | story | module | api | entity | test. It orders each column by the barycentre of each node's neighbours, using alternating down/up sweeps (the Sugiyama crossing-reduction heuristic). It's deterministic, there's no dependency, and a unit test shows it removes crossings that the naive order has.
**Rejected.** dagre (unmaintained fork, generic ranks ignore our type semantics). ELK (~1 MB of WASM/JS for a problem whose ranks we already know).

## ADR-030 — Progress over fetch-based SSE, with polling fallback
**Decision.** The native `EventSource` can't send an `Authorization` header, so `useJob` uses `@microsoft/fetch-event-source` with the bearer token. If the stream errors, it falls back to polling `GET /jobs/{id}` every 2 s. Together with the server's DB re-sync (ADR-020), progress always arrives.

## ADR-031 — Frontend toolchain pins
- **TypeScript 6.0, not 7.** `typescript-eslint` 8.x supports TS < 6.1, and the CI gate is `eslint` + `tsc`.
- **ESLint 9, not 10.** `eslint-plugin-jsx-a11y` (accessibility rules) supports up to ESLint 9.
- **React Flow v13**: dark mode follows the OS through CSS `light-dark()`, so the canvas is pinned with `forceColorMode="light"` (it rendered dark on a dark-mode machine in the first browser check).
- **Accessibility:** jsx-a11y lint, a skip link, visible focus rings, `prefers-reduced-motion`, ARIA tabs, labelled meters and progress bars, keyboard-sortable kanban (dnd-kit keyboard sensor, plus a status `<select>` on every card), and an **Outline** tab that gives a text alternative to the canvas.

## ADR-032 — The sandbox is seeded with verified samples and heals itself
**Decision.** `python -m app.seed` and the nightly Celery beat task (`specforge.reset_sandbox`, 03:00 UTC) wipe the shared sandbox and restore the 4 curated samples **with their quality reports**. If a visitor empties the sandbox, the next demo login restores the samples immediately and queues their verification. A recruiter clicking "Try it instantly" sees four complete, scored blueprints with no LLM call.
