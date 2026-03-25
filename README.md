# b24-migration-runtime (MVP)

Production-oriented Python runtime scaffold for deterministic Bitrix24 structured data migration.

## Features in MVP

- Deterministic plan generation (`plan`)
- `execute` with `--dry-run`
- `resume` from persisted run checkpoint
- Runtime state persistence in MySQL (SQLAlchemy + Alembic)
- Deterministic JSON responses for all CLI commands
- Verification checks (`verify`)

## Tech stack

- Python 3.12
- Typer
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- httpx
- pytest

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

## CLI examples

```bash
b24-runtime plan --config migration.config.yml
b24-runtime execute --config migration.config.yml --plan-id <plan_id> --dry-run
b24-runtime resume --config migration.config.yml --plan-id <plan_id>
b24-runtime verify --config migration.config.yml --run-id <run_id>
b24-runtime checkpoint --config migration.config.yml --run-id <run_id>
```

All commands print JSON for automation.
