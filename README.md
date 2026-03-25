# b24-migration-runtime (MVP)

Production-oriented Python runtime scaffold for deterministic Bitrix24 structured data migration.

## Runtime state model

- `Job` — top-level migration entity (`job -> 0..N plans`).
- `Plan` — deterministic migration plan owned by a job (`plan -> 0..N runs`).
- `Run` — execution attempt/state for a plan.
- `Checkpoint` — persisted runtime checkpoint/state bound to a run.
- `Log` — run-level execution log entries (used by `report`).

## MVP features

- Deterministic job creation (`create-job`).
- Explicit plan creation (`plan`) for a selected job.
- `execute` with `--dry-run`.
- `resume` from persisted checkpoint by `--plan-id` or `--run-id`.
- Runtime state persistence in SQL database (SQLAlchemy + Alembic).
- Deterministic JSON responses for all CLI commands.
- Runtime status/report commands (`status`, `report`).
- Deployment readiness check (`deployment:check`) with sanitized DB output.

## Storage policy

- **Production mode is MySQL-only** for runtime state.
- SQLite is allowed only with explicit non-production mode (`runtime_mode: dev` or `runtime_mode: test`).

This rule is validated during config loading, so runtime behavior is explicit and deterministic.

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
pip install --upgrade pip
pip install -e .
```

Install developer/test extras when needed:

```bash
pip install -e .[dev]
```

## Configuration

1. Copy template:

```bash
cp migration.config.yml.example migration.config.yml
```

2. Fill values (`migration.config.yml` example):

```yaml
runtime_mode: production
database_url: mysql+pymysql://b24_user:b24_password@127.0.0.1:3306/b24_runtime
source:
  base_url: https://source.bitrix24.example
  webhook: source_webhook_token
target:
  base_url: https://target.bitrix24.example
  webhook: target_webhook_token
default_scope:
  - crm
  - tasks
```

3. Optional env overrides:

- `MIGRATION_RUNTIME_MODE`
- `MIGRATION_DATABASE_URL`
- `MIGRATION_SOURCE_BASE_URL`
- `MIGRATION_SOURCE_WEBHOOK`
- `MIGRATION_TARGET_BASE_URL`
- `MIGRATION_TARGET_WEBHOOK`

If config is missing/invalid, CLI returns structured JSON error with deterministic exit code.

## CLI examples

```bash
# 1) Create a job
b24-runtime create-job --config migration.config.yml

# 2) Create plan for job
b24-runtime plan --config migration.config.yml --job-id <job_id>

# Backward-compatible shortcut: if --job-id is omitted, command creates a job automatically
b24-runtime plan --config migration.config.yml

# 3) Execute / inspect / resume
b24-runtime execute --config migration.config.yml --plan-id <plan_id>
b24-runtime status --config migration.config.yml --job-id <job_id>
b24-runtime status --config migration.config.yml --plan-id <plan_id>
b24-runtime status --config migration.config.yml --run-id <run_id>
b24-runtime report --config migration.config.yml --run-id <run_id>
b24-runtime resume --config migration.config.yml --plan-id <plan_id>

# Infra validation and compatibility alias
b24-runtime deployment:check --config migration.config.yml
b24-runtime verify --config migration.config.yml --run-id <run_id>
```

All commands print structured JSON for automation.
