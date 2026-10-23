UV ?= uv

.PHONY: install db run migrate seed test cov lint format typecheck audit up down

install:        ## install all deps (incl. dev) from the lockfile
	$(UV) sync --frozen

db:             ## start only Postgres (host port 5433)
	docker compose up -d db

run:            ## run the API with autoreload against local Postgres
	$(UV) run uvicorn app.main:app --reload

migrate:        ## apply migrations
	$(UV) run alembic upgrade head

seed:           ## idempotent seed: 5 doctors, working hours, demo patient
	$(UV) run python -m scripts.seed

test:           ## run tests (needs Postgres; see TEST_DATABASE_URL)
	$(UV) run pytest

cov:            ## tests with coverage
	$(UV) run pytest --cov --cov-report=term-missing

lint:           ## ruff lint + format check + mypy + bandit
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy
	$(UV) run bandit -q -c pyproject.toml -r app scripts

format:
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

audit:          ## known-vulnerability scan of locked runtime deps
	$(UV) export --frozen --no-dev --no-hashes --no-emit-project -o requirements-audit.txt
	$(UV) run pip-audit --strict -r requirements-audit.txt
	rm -f requirements-audit.txt

up:             ## full stack: api + postgres, migrations + seed on boot
	docker compose up --build

down:
	docker compose down
