# b24-migration-runtime (MVP)

Production-oriented Python runtime scaffold for deterministic Bitrix24 structured data migration.

## Features in MVP

- Deterministic job generation (`create-job`)
- `execute` with `--dry-run`
- `resume` from persisted run checkpoint
- Runtime state persistence in SQL database (SQLAlchemy + Alembic)
- Deterministic JSON responses for all CLI commands
- Runtime status/report commands (`status`, `report`)
- Deployment readiness check (`deployment:check`)

## Tech stack

- Python 3.12
- Typer
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- httpx
- pytest

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you run tests or CLI in a minimal environment, ensure YAML parser is installed:

```bash
pip install PyYAML
```

## Config

1. Copy template:

```bash
cp migration.config.yml.example migration.config.yml
```

2. Fill values. You can override core settings using env:

- `MIGRATION_DATABASE_URL`
- `MIGRATION_SOURCE_BASE_URL`
- `MIGRATION_SOURCE_WEBHOOK`
- `MIGRATION_TARGET_BASE_URL`
- `MIGRATION_TARGET_WEBHOOK`

If config file is missing, invalid, or PyYAML is unavailable, CLI returns structured JSON error with deterministic exit code.

## CLI examples

```bash
b24-runtime create-job --config migration.config.yml
b24-runtime status --config migration.config.yml --plan-id <plan_id>
b24-runtime report --config migration.config.yml --run-id <run_id>
b24-runtime deployment:check --config migration.config.yml

# Backward-compatible aliases:
b24-runtime plan --config migration.config.yml
b24-runtime verify --config migration.config.yml --run-id <run_id>
```

All commands print JSON for automation.
