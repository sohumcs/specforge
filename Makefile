# SPECForge. Run from Linux/macOS/WSL. Windows PowerShell: scripts/dev.ps1 <target>.
#
#   make dev        build + start the whole stack, wait until healthy -> http://localhost:8080
#   make down       stop (keeps the database volume);  make clean  also deletes it
#   make logs       follow logs;  make ps  container status
#   make seed       reset the demo sandbox (samples + quality reports)
#   make e2e        Playwright end-to-end tests against the running stack
#   make test       backend (pytest) + frontend (vitest) unit tests
#   make lint       ruff + mypy + bandit + eslint + tsc

COMPOSE ?= docker compose
WEB_URL ?= http://localhost:8080
PY      ?= backend/.venv/bin/python
export GIT_SHA ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

.PHONY: dev up down clean logs ps seed wait smoke e2e e2e-ci test test-backend test-frontend lint db-up db-down

dev: up wait
	@echo "SPECForge is up: $(WEB_URL)  (API docs: $(WEB_URL)/docs)"

up:
	$(COMPOSE) up -d --build

wait:
	@echo "waiting for $(WEB_URL)/ready ..."
	@for i in $$(seq 1 90); do \
	  curl -fsS $(WEB_URL)/ready >/dev/null 2>&1 && exit 0; sleep 2; \
	done; echo "stack did not become ready"; $(COMPOSE) ps; exit 1

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

seed:
	$(COMPOSE) run --rm seed

smoke:
	cd backend && $(abspath $(PY)) scripts/e2e_smoke.py $(WEB_URL)

e2e:
	cd frontend && E2E_BASE_URL=$(WEB_URL) npx playwright test

# Deterministic run used by CI: offline DemoProvider, generous rate limits.
e2e-ci:
	LLM_PROVIDERS='["demo"]' GENERATE_LIMIT_PER_IP_HOUR=1000 GENERATE_LIMIT_PER_USER_HOUR=1000 \
	  DEMO_LOGIN_LIMIT_PER_IP_HOUR=1000 $(COMPOSE) up -d --build
	$(MAKE) wait
	$(MAKE) e2e

test: test-backend test-frontend

test-backend: db-up
	cd backend && $(abspath $(PY)) -m pytest --cov=app

test-frontend:
	cd frontend && npm test

lint:
	cd backend && $(abspath $(PY)) -m ruff check app tests scripts && $(abspath $(PY)) -m ruff format --check app tests scripts
	cd backend && $(abspath $(PY)) -m mypy app && $(abspath $(PY)) -m bandit -q -r app
	cd frontend && npm run lint && npm run typecheck

# Throwaway Postgres+pgvector and Redis for the backend unit tests (ports 5433/6380).
db-up:
	docker run -d --name specforge-pg -e POSTGRES_USER=specforge -e POSTGRES_PASSWORD=specforge \
	  -e POSTGRES_DB=specforge -p 5433:5432 pgvector/pgvector:pg16 2>/dev/null || docker start specforge-pg >/dev/null
	docker run -d --name specforge-redis -p 6380:6379 redis:7-alpine 2>/dev/null || docker start specforge-redis >/dev/null

db-down:
	docker rm -f specforge-pg specforge-redis
