PYTHON := $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null)
VENV   := .venv

.PHONY: dev prod down migrate migrate-create shell psql logs backup build \
        lint lint-fix lint-openapi test check install-dev install-hooks

# ─── Development ──────────────────────────────────────────────────────────────

dev:
	docker compose up

dev-build:
	docker compose up --build

down:
	docker compose down

# ─── Production ───────────────────────────────────────────────────────────────
# Requires CF_TUNNEL_TOKEN and a proper DATABASE_URL in .env

prod:
	docker compose -f docker compose.yml -f docker compose.prod.yml up -d

prod-build:
	docker compose -f docker compose.yml -f docker compose.prod.yml up -d --build

prod-down:
	docker compose -f docker compose.yml -f docker compose.prod.yml down

# ─── Database Migrations ──────────────────────────────────────────────────────

migrate:
	docker compose exec api flask db upgrade

migrate-create:
	@if [ -z "$(msg)" ]; then echo "Usage: make migrate-create msg=\"your message\""; exit 1; fi
	docker compose exec api flask db migrate -m "$(msg)"

migrate-history:
	docker compose exec api flask db history

# ─── Shells ───────────────────────────────────────────────────────────────────

shell:
	docker compose exec api flask shell

psql:
	docker compose exec postgres psql -U safe2gether -d safe2gether

bash:
	docker compose exec api bash

# ─── Logs & Monitoring ────────────────────────────────────────────────────────

logs:
	docker compose logs -f api

logs-all:
	docker compose logs -f

health:
	curl -s http://localhost:5000/api/v1/health | python3 -m json.tool

# ─── Backup ───────────────────────────────────────────────────────────────────

backup:
	./scripts/backup.sh

# ─── Local Checks (identisch mit CI) ─────────────────────────────────────────

$(VENV)/.installed: requirements.txt requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements.txt -r requirements-dev.txt
	@touch $@

install-dev: $(VENV)/.installed

lint:
	ruff check app/ wsgi.py

lint-fix:
	ruff check --fix app/ wsgi.py

lint-openapi:
	@if command -v npx >/dev/null 2>&1; then \
	  npx --yes @redocly/cli lint docs/api/openapi.yaml; \
	else \
	  echo "⚠  npx nicht gefunden — OpenAPI-Lint übersprungen (wird in CI geprüft)"; \
	  echo "   Node.js installieren: brew install node"; \
	fi

test: $(VENV)/.installed
	$(VENV)/bin/pytest tests/ -v

check: lint lint-openapi test

install-hooks:
	cp scripts/pre-push-hook .git/hooks/pre-push
	chmod +x .git/hooks/pre-push
	@echo "pre-push hook installed — 'make check' runs before every push"
