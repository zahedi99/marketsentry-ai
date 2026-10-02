# One entry point for common tasks. Run `make help` to list targets.
# Recipes are kept to plain commands so they work from cmd, PowerShell or bash.

COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

.PHONY: help install lint format typecheck test check up down

help:
	@echo "install    Install Python (uv) and web (pnpm) dependencies"
	@echo "lint       Lint and check formatting (ruff)"
	@echo "format     Auto-fix lint issues and format code (ruff)"
	@echo "typecheck  Static type check (mypy, strict)"
	@echo "test       Run unit tests (pytest)"
	@echo "check      lint + typecheck + test (what CI runs)"
	@echo "up / down  Start / stop the full stack (docker compose)"

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
