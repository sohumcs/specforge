# SPECForge — Progress

Resume a session by reading this file + `../Web/new-portfolio/SPECFORGE_BUILD_PROMPT.md` (the brief).

## Status
| Phase | State |
|---|---|
| 1. Plan | ✅ approved 2026-11-26 |
| 2. Backend core | ✅ done 2026-11-26: 122 tests green, 94 % coverage, ruff/mypy-strict/bandit clean |
| 3. AI pipeline | ✅ done 2026-11-26: 190 tests green, 95 % coverage, live E2E proven |
| 4. Verification engine | ✅ done 2026-11-26: 269 tests green, 94 % coverage, live E2E smoke passes |
| 5. Frontend | ✅ done 2026-11-26: verified in a real browser; 28 Vitest + 280 pytest tests |
| 6. Local full stack | ✅ done 2026-11-26: compose stack healthy, Playwright 17/17 passing (3 consecutive runs) |
| 7. CI | ✅ done 2026-11-27: 6/6 checks green on PR #1, branch protection on main |
| 8. Target A deploy | ⏳ next (needs accounts, see below) |
| 9–10 | not started |

## Decisions made by Sohum
- Repo `sohumcs/specforge` is **public**.
- No domain owned → use a free **DuckDNS** subdomain (Sohum creates the DuckDNS account in Phase 8).
- Has an **AWS student account via college** (learner ID). Before Phase 9, confirm which kind it is. AWS Academy Learner Lab accounts typically have temporary credentials, fixed regions, a pre-made `LabRole`, and no IAM-user/role creation. If that's the case, Target B Terraform takes `instance_profile = "LabInstanceProfile"` instead of creating IAM, and the $1 budget alarm may need to be swapped for the lab's own spend cap. *Unverified; check in Phase 9.*

## Phase 2 — what exists
- `backend/app/core`: settings (refuses weak JWT secret in prod), `{code,message,details}` error envelope, JSON logs with request id, Argon2id + JWT + hashed refresh tokens.
- `backend/app/models`: all tables from ARCHITECTURE §3 (users, refresh_tokens, projects, project_members, blueprints, nodes w/ `vector(384)` + HNSW, edges, jobs, quality_reports, issues, generation_cache, change_events).
- `backend/alembic/versions/20261126_0001_initial_schema.py`: upgrade/downgrade round-trip and `alembic check` clean. Tests build the schema through Alembic.
- Auth: register, login, demo (editor on Sandbox), refresh (rotation + reuse detection → family revoke), logout, `/me`, admin `/admin/users`.
- RBAC (`services/access.py`): viewer < editor < owner, admin bypass, 404 for non-members.
- CRUD: projects, members (last-owner guard), blueprints, nodes (auto keys `REQ-001`…), edges (type matrix validation), kanban status for stories/tests.
- Graph (`services/graph.py`): `replace_graph` (atomic bulk write for generation), `downstream_impact` / `upstream_trace` (recursive CTE, cycle-safe), edit → stale marking + change event in one transaction.
- Probes: `/health`, `/ready` (DB + Redis, 503 on failure), `/api/v1/status`, `/metrics`, `/docs`.

## How to run the tests (Windows, Git Bash)
```
docker run -d --name specforge-pg -e POSTGRES_USER=specforge -e POSTGRES_PASSWORD=specforge -e POSTGRES_DB=specforge -p 5433:5432 pgvector/pgvector:pg16
docker run -d --name specforge-redis -p 6380:6379 redis:7-alpine
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]" && .venv/Scripts/python -m pytest --cov=app
```

## Phase 3 — what exists
- `app/llm/schemas.py`: 3 stage schemas (requirements / design / tests) + `cross_reference_errors` + `to_graph`.
- `app/llm/templates/*.v1.md`: versioned prompts. `PROMPT_VERSION` is part of the cache key.
- `app/llm/providers/`: `gemini.py`, `groq.py` (httpx REST, strict JSON schema), `demo.py` (4 curated samples in `app/llm/demo_data/`, else spaCy-driven templates).
- `app/llm/chain.py`: per-stage fallback, repair retries (max 2), Retry-After waits, Redis circuit breaker (`breaker.py`). Order: exact cache, then gemini, then groq, then stale cache, then demo.
- `app/nlp/brief.py`: spaCy `en_core_web_sm` 3.8.0 → actors, entities, (verb, object, actor) actions, terms.
- `app/services/generation.py`: the pipeline + Postgres generation cache. `jobs.py`: idempotent submission, progress → DB + Redis pub/sub, DLQ. `ratelimit.py`: per user/IP/global.
- `app/worker/`: Celery app (acks_late, reject_on_worker_lost, threads pool) + `generate_blueprint` task (retry with backoff → dead-letter).
- API: `POST /blueprints/{id}/generate` (Idempotency-Key, 202/200/429/503), `GET /jobs/{id}`, `GET /blueprints/{id}/jobs`, `GET /jobs/{id}/events` (SSE). `/status` shows the LLM chain and breaker state.
- Migration `0002`: `generation_cache.brief_hash`, `jobs(blueprint_id,status)` index.
- Proven live: uvicorn + Celery worker + Gemini, demo login → generate → SSE showed every step → 55 nodes / 97 edges stored. Opt-in live tests: `SPECFORGE_LIVE_TESTS=1 pytest -m live` (both providers pass).

## Phase 4 — what exists
- `app/verify/rules.py`: 12 rules (TR-001..005, CP-001..004, CV-001..003) on a `GraphView` snapshot (`graphview.py`).
- `app/verify/ml.py`: MiniLM embeddings + DeBERTa NLI (lazy, once per worker), polarity-cue hybrid contradictions. `scoring.py`: weighted 0-100.
- `app/services/verification.py`: embed missing nodes → pgvector duplicate self-join → contradictions → `QualityReport` + `Issue` rows; dismissals by fingerprint; degrades to rules-only if ML fails.
- `app/services/fixes.py`: 14 fixers (deterministic + LLM with template fallback) and `regenerate_subgraph`.
- Tasks refactored around one `_run_job` lifecycle: generate (now generate → verify), verify, fix_issue, regenerate_subgraph.
- API: `POST /blueprints/{id}/verify`, `GET /blueprints/{id}/quality[/history]`, `POST /issues/{id}/fix|dismiss|restore`, `POST /blueprints/{id}/regenerate-subgraph`, `GET /nodes/{id}/similar` (HNSW), `GET /rules`.
- Change impact pruned semantically (module→api by embedding similarity): 45 → 25 nodes on a live edit.
- Worker heartbeat in Redis → `/ready` and `/status` show `models_loaded`.
- Migration `0003`: report timestamps use `clock_timestamp()`.
- `scripts/e2e_smoke.py`: live smoke (demo → generate → quality → fix → edit → impact → regenerate → similar). Passed against a real API + worker + Gemini/Groq.

## Phase 5 — what exists
- Backend additions: `GET /blueprints/{id}/progress` (roll-ups), `GET /blueprints/{id}/export?format=md|json|pdf` (ReportLab PDF), `GET /samples`, `POST /projects/{id}/samples/{slug}`, regenerate without a root (uses the latest edit), `python -m app.seed` + nightly `specforge.reset_sandbox` beat task, demo login self-heals an empty sandbox.
- `frontend/`: landing (animated walkthrough, architecture SVG, samples, demo CTA), login/register, status page, projects, project page with generate + live progress, blueprint workspace (graph, node panel, impact wave, regenerate, quality panel, kanban + roll-ups, outline, exports). Responsive (checked at 375 px) and accessible (jsx-a11y lint, keyboard paths).
- Checked in a real browser against the real API + worker: demo login → sample graph → select/trace → edit REQ-006 → 4 nodes stale + amber wave → regenerate (LLM) → contradiction resolved, score 92 → 98 → Fix with AI (CRUD) → kanban drag → status page → new brief generated end-to-end (Groq answered after Gemini's per-minute quota).
- Tests: backend 280 (pytest, 94 % coverage), frontend 28 (Vitest + Testing Library); eslint, tsc, ruff, mypy, bandit clean.

## Phase 7 — what exists
- `.github/workflows/ci.yml`: backend / frontend / secrets / images (Trivy, x2) / e2e. All third-party actions SHA-pinned, read-only token. Details: ADR-036.
- `backend/scripts/coverage_gate.py`: each core module (rules, scoring, graph, RBAC, auth) must be at least 80 %. Current: 90.6 % to 100 %.
- `.github/dependabot.yml`: pip, npm, GitHub Actions (SHA bumps), both Dockerfiles, compose. Weekly, grouped. torch and the TS/ESLint majors are held back on purpose.
- PR [#1](https://github.com/sohumcs/specforge/pull/1): run 1 failed on real findings (57 fixable OS CVEs in a stale nginx base, 1 in Debian, 1 lint error), and run 2 was **6/6 green**. Squash-merged.
- Branch protection on `main` (ADR-037): PR + 1 review + 6 required checks; owner may bypass (solo repo).
- From now on, changes go through PRs: `git checkout -b <type>/<topic>` → push → PR → green → merge.

## Phase 6 — what exists
- `backend/Dockerfile`: one image (api/worker/beat/migrate/seed), CPU torch, models baked in (`HF_HUB_OFFLINE`), non-root, ~0.9 GB. `backend/requirements.lock` + `requirements-dev.lock` from `scripts/lock.sh` (uv, universal amd64/arm64, CUDA excluded).
- `frontend/Dockerfile`: nginx-unprivileged serving the SPA and proxying the API (SSE unbuffered, security headers + CSP, `/metrics` hidden).
- `docker-compose.yml`: postgres+pgvector, redis, migrate → seed (one-shots), api, worker, beat, web on :8080; read-only root FS, `cap_drop: ALL`, healthchecks. Keys come from `backend/.env` if present.
- `make dev | down | clean | logs | seed | e2e | e2e-ci | test | lint`; `scripts/dev.ps1` does the same on Windows.
- Playwright (`frontend/e2e/`): full flow (register → project → generate → quality → fix → edit → impact → regenerate → kanban → export MD+PDF), recruiter demo path (< 10 s), axe WCAG A/AA checks on landing + workspace tabs, probes through the proxy; desktop + mobile (Pixel 7) projects.
- Result against the compose stack in CI mode (`LLM_PROVIDERS=["demo"]`): **17/17 passing (3 consecutive runs)**.
- **Fresh-clone check:** `git clone` from GitHub into an empty folder (no `backend/.env`, no `node_modules`) → `scripts\dev.ps1 e2e-ci` built the stack, installed frontend deps + Chromium, and passed 17/17 in 176 s. Make targets dry-run cleanly in WSL (`make -n dev e2e e2e-ci`).
- Real bugs the e2e/axe run caught: a scrollable diagram that keyboard users couldn't scroll, a redundant nested ARIA label on the header gauge, plus the two nginx container gotchas (ADR-034).

## One-command local run
```
make dev                  # Linux/macOS/WSL
.\scripts\dev.ps1         # Windows PowerShell
# -> http://localhost:8080   (API docs: /docs)
make e2e-ci               # deterministic Playwright run (offline LLM)
```

## Run the UI locally
```
cd backend && .venv/Scripts/uvicorn app.main:app --port 8000
cd backend && .venv/Scripts/celery -A app.worker.celery_app worker -P threads -c 2
cd frontend && npm install && npm run dev        # http://localhost:5173
cd backend && .venv/Scripts/python -m app.seed   # (re)create the demo sandbox
```

## Run locally (Windows, Git Bash)
```
cd backend
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:app --port 8000
.venv/Scripts/celery -A app.worker.celery_app worker -P threads -c 2 -l INFO
.venv/Scripts/python scripts/e2e_smoke.py   # with both running
```
Torch comes from the CPU index: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

## Open items / notes
- ⚠️ The Gemini key in `backend/.env` is the one that was pasted in chat. **Rotate it before Phase 8 (deploy).**
- `backend/.env` has `JWT_SECRET=change-me`. Fine for dev, but production gets a generated secret via k8s Secret.

## Accounts Sohum will need to create (never paste keys in chat)
| When | What |
|---|---|
| Phase 3 | ✅ Gemini + Groq keys added to `backend/.env` |
| Phase 7 | Nothing (GitHub already authenticated) |
| Phase 8 | Oracle Cloud Free Tier account + API signing key; DuckDNS (sign in with GitHub) + token; UptimeRobot free account |
| Phase 9 | Confirm the AWS student account type; sign in and generate credentials when we get there |

## Next: Phase 8 (Target A: always-on free deploy)
**Sohum first:** rotate the Gemini key; create an Oracle Cloud Free Tier account + API signing key; DuckDNS account + subdomain + token; UptimeRobot account. Then: Terraform (OCI provider: VCN, subnet, security list, A1.Flex 2 OCPU/12 GB VM, reserved IP), Ansible (harden: non-root user, SSH keys only, ufw, fail2ban, unattended-upgrades; install k3s), k8s manifests (kustomize), cert-manager + Let's Encrypt, CD workflow (multi-arch GHCR images, deploy, smoke test, automatic rollback), Prometheus + Grafana, nightly pg_dump to OCI Object Storage with a tested restore.
