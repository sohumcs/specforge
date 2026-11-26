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
