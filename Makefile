# One entry point for common tasks. Run `make help` to list targets.
# Recipes are kept to plain commands so they work from cmd, PowerShell or bash.

COMPOSE = docker compose -f infra/docker-compose.yml
ALEMBIC = uv run alembic -c packages/db/alembic.ini

.PHONY: help install lint format typecheck test check up down db-up db-down db-shell migrate migration seed

help:
	@echo "install    Install Python (uv) and web (pnpm) dependencies"
	@echo "lint       Lint and check formatting (ruff)"
	@echo "format     Auto-fix lint issues and format code (ruff)"
	@echo "typecheck  Static type check (mypy, strict)"
	@echo "test       Run unit tests (pytest)"
	@echo "check      lint + typecheck + test (what CI runs)"
	@echo "up / down  Start / stop the full stack (docker compose)"
	@echo "db-up      Start Postgres and wait until it is healthy"
	@echo "db-down    Stop Postgres (data is kept in the pgdata volume)"
	@echo "db-shell   Open a psql prompt inside the database container"
	@echo "migrate    Apply database migrations (alembic upgrade head)"
	@echo "migration  Generate a migration from model changes: make migration m=\"message\""
	@echo "seed       Apply migrations, then add the default watchlist (idempotent)"

install:
	uv sync --all-packages
	pnpm install

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

db-up:
	$(COMPOSE) up -d --wait db

db-down:
	$(COMPOSE) down

db-shell:
	$(COMPOSE) exec db psql -U marketsentry -d marketsentry

migrate:
	$(ALEMBIC) upgrade head

migration:
	$(ALEMBIC) revision --autogenerate -m "$(m)"

seed: migrate
	uv run python -m worker.seed
