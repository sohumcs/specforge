# SPECForge — Progress

Resume a session by reading this file + `../Web/new-portfolio/SPECFORGE_BUILD_PROMPT.md` (the brief).

## Status
| Phase | State |
|---|---|
| 1. Plan | ✅ drafted — **waiting for Sohum's OK** |
| 2. Backend core | ⏳ next |
| 3–10 | not started |

## Done (Phase 1)
- Repo initialised (`main`, local only, no remote yet).
- Free-tier research on providers' own pages (2026-11-26) → `docs/COSTS.md`.
- `docs/ARCHITECTURE.md`: context, pipeline, verification engine, scoring, data model, API outline, topology, memory budget.
- `docs/DECISIONS.md`: ADR-001…013.

## Key findings that changed the plan
- Oracle Always Free A1 is now **2 OCPU / 12 GB** (was 4 / 24). Still enough. ARCHITECTURE §5 has the budget.
- AWS new accounts are **credits-based**, and Free-plan accounts close after 6 months. Elastic IP is $0.005/h even when idle.
- Groq Llama 3.x models are on the deprecation list → use `openai/gpt-oss-120b`. Gemini 2.5 is being re-routed from 2026-12-01 → use `gemini-3.5-flash-lite`. Model IDs are config.

## Open decisions (need Sohum)
1. Approve the plan as a whole.
2. Make GitHub repo `sohumcs/specforge` **public**? (Needed for free Actions/GHCR.) Can stay private until Phase 7.
3. Domain: own one, or use DuckDNS `specforge-sohum.duckdns.org`?
4. Accounts Sohum must create (never shared in chat), and when they're needed:
   Gemini API key (Phase 3), Groq API key (Phase 3), Oracle Cloud account + API signing key (Phase 8), DuckDNS token (Phase 8), UptimeRobot (Phase 8), AWS account (Phase 9).

## Next
Phase 2: backend skeleton (FastAPI, SQLAlchemy 2, Alembic, pgvector), auth + RBAC, project/blueprint/node/edge CRUD, graph traversal, pytest with a Postgres test container.
