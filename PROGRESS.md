# SPECForge — Progress

Resume a session by reading this file + `../Web/new-portfolio/SPECFORGE_BUILD_PROMPT.md` (the brief).

## Status
| Phase | State |
|---|---|
| 1. Plan | ✅ approved 2026-11-26 |
| 2. Backend core | ✅ done 2026-11-26: 122 tests green, 94 % coverage, ruff/mypy-strict/bandit clean |
| 3. AI pipeline | ✅ done 2026-11-26: 190 tests green, 95 % coverage, live E2E proven |
| 4. Verification engine | ✅ done 2026-11-26: 269 tests green, 94 % coverage, live E2E smoke passes |
| 5. Frontend | ⏳ next |
| 6–10 | not started |

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

## Next: Phase 5 (frontend)
React + TS (Vite), Tailwind, React Flow graph (filter/colour/trace/zoom), TanStack Query, fetch-based SSE job progress, Quality panel (gauge, category bars, issues with fix/dismiss), change-impact animation + "regenerate affected", kanban + roll-ups (needs a small `/progress` endpoint), exports MD/JSON/PDF (backend endpoint still to build), landing page, `/status` page, demo login.
