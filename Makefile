# Run from Linux/macOS/WSL. On Windows PowerShell use scripts/dev.ps1 (added in Phase 6).
PY ?= backend/.venv/bin/python
PG_PORT ?= 5433
REDIS_PORT ?= 6380

.PHONY: db-up db-down test lint typecheck migrate

db-up:  ## start throwaway Postgres+pgvector and Redis for tests
	docker run -d --name specforge-pg -e POSTGRES_USER=specforge -e POSTGRES_PASSWORD=specforge \
	  -e POSTGRES_DB=specforge -p $(PG_PORT):5432 pgvector/pgvector:pg16 || docker start specforge-pg
	docker run -d --name specforge-redis -p $(REDIS_PORT):6379 redis:7-alpine || docker start specforge-redis

db-down:
	docker rm -f specforge-pg specforge-redis

migrate:
	cd backend && $(abspath $(PY)) -m alembic upgrade head

test:
	cd backend && $(abspath $(PY)) -m pytest --cov=app --cov-report=term-missing:skip-covered

lint:
	cd backend && $(abspath $(PY)) -m ruff check app tests alembic && $(abspath $(PY)) -m ruff format --check app tests alembic

typecheck:
	cd backend && $(abspath $(PY)) -m mypy app
