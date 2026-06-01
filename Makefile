.PHONY: dev prod down migrate migrate-create shell psql logs backup build

# ─── Development ──────────────────────────────────────────────────────────────

dev:
	docker-compose up

dev-build:
	docker-compose up --build

down:
	docker-compose down

# ─── Production ───────────────────────────────────────────────────────────────
# Requires CF_TUNNEL_TOKEN and a proper DATABASE_URL in .env

prod:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-build:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

prod-down:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

# ─── Database Migrations ──────────────────────────────────────────────────────

migrate:
	docker-compose exec api flask db upgrade

migrate-create:
	@if [ -z "$(msg)" ]; then echo "Usage: make migrate-create msg=\"your message\""; exit 1; fi
	docker-compose exec api flask db migrate -m "$(msg)"

migrate-history:
	docker-compose exec api flask db history

# ─── Shells ───────────────────────────────────────────────────────────────────

shell:
	docker-compose exec api flask shell

psql:
	docker-compose exec postgres psql -U safe2gether -d safe2gether

bash:
	docker-compose exec api bash

# ─── Logs & Monitoring ────────────────────────────────────────────────────────

logs:
	docker-compose logs -f api

logs-all:
	docker-compose logs -f

health:
	curl -s http://localhost:5000/api/v1/health | python3 -m json.tool

# ─── Backup ───────────────────────────────────────────────────────────────────

backup:
	./scripts/backup.sh
