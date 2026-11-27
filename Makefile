.PHONY: setup ingest sync ask test eval api lint sso bootstrap-admin

setup:
	pip install -e ".[dev]"

ingest:
	python -m truthguard.ingest data/raw

sync:
	python -m truthguard.connectors.sync

# make ask Q="..." USER=employee [AS_OF=2025-01-01]
ask:
	python -m truthguard.pipeline.graph --question "$(Q)" --user "$(USER)" $(if $(AS_OF),--as-of "$(AS_OF)",)

test:
	pytest tests/ -v

eval:
	python eval/run.py

api:
	uvicorn truthguard.api.main:app --reload --port 8000

# Keycloak + Mailpit for ENABLE_SSO=true
sso:
	docker compose up -d

# First admin from BOOTSTRAP_ADMIN_EMAIL; run while the API is stopped
bootstrap-admin:
	python -m truthguard.auth.bootstrap

lint:
	ruff check truthguard/ eval/ tests/
	ruff format --check truthguard/ eval/ tests/
