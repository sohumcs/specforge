# SPECForge — Progress

Resume a session by reading this file + `../Web/new-portfolio/SPECFORGE_BUILD_PROMPT.md` (the brief).

## Status
| Phase | State |
|---|---|
| 1. Plan | ✅ approved 2026-11-26 |
| 2. Backend core | ✅ done 2026-11-26: 122 tests green, 94 % coverage, ruff/mypy-strict/bandit clean |
| 3. AI pipeline | ⏳ next |
| 4–10 | not started |

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

## Accounts Sohum will need to create (never paste keys in chat)
| When | What |
|---|---|
| Phase 3 (next) | Google AI Studio → Gemini API key; GroqCloud → API key. Put both in `backend/.env` only. |
| Phase 7 | Nothing (GitHub already authenticated) |
| Phase 8 | Oracle Cloud Free Tier account + API signing key; DuckDNS (sign in with GitHub) + token; UptimeRobot free account |
| Phase 9 | Confirm the AWS student account type; sign in and generate credentials when we get there |

## Next: Phase 3
LLM provider layer (Gemini, Groq, Cached, Demo, fallback chain, circuit breaker), versioned prompt templates, Pydantic structured output + repair retries, spaCy brief parsing, Celery app + `generate_blueprint` task with progress (Redis pub/sub → SSE), idempotent job submission, per-user/IP rate limiting.
