# b24-migration-runtime (MVP)

Production-oriented runtime for deterministic Bitrix24 structured data migration with **CLI + Web UI** over one shared service layer.

## Runtime state model

- `Job` — top-level migration entity (`job -> 0..N plans`).
- `Plan` — deterministic migration plan owned by a job (`plan -> 0..N runs`).
- `Run` — execution attempt/state for a plan.
- `Checkpoint` — persisted runtime checkpoint/state bound to a run.
- `Log` — run-level execution log entries.
- `Audit` — actor/action/outcome trace for UI and CLI-triggered actions.

## MVP features

- Deterministic job creation (`create-job`).
- Explicit plan creation (`plan`) for a selected job.
- `execute` with `--dry-run`.
- `resume` from persisted checkpoint by `--plan-id` or `--run-id`.
- Runtime state persistence in SQL database (SQLAlchemy + Alembic-compatible schema).
- Deterministic JSON responses for CLI and HTTP API.
- Web UI dashboard with quick actions, run progress, logs and configuration.
- Deployment readiness check (`deployment:check`) with sanitized DB output.

## Storage policy

- **Production mode is MySQL-only** for runtime state.
- SQLite is allowed only with explicit non-production mode (`runtime_mode: dev` or `runtime_mode: test`).

This rule is validated during config loading.

## Tech stack

- Python 3.12
- Typer
- FastAPI + Jinja2 + HTMX
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
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

## CLI

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
b24-runtime checkpoint --config migration.config.yml --run-id <run_id>
b24-runtime report --config migration.config.yml --run-id <run_id>
b24-runtime resume --config migration.config.yml --plan-id <plan_id>

# Infra validation and compatibility alias
b24-runtime deployment:check --config migration.config.yml
b24-runtime verify --config migration.config.yml --run-id <run_id>
```

## Web UI

Run locally:

```bash
uvicorn b24_migrator.web.app:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000/`

Main endpoints:

- `GET /health`
- `GET /` (dashboard)
- `GET /config`
- `POST /config/test`
- `POST /config/save`
- `GET /jobs`, `POST /jobs`, `GET /jobs/{job_id}`
- `POST /plans`, `GET /plans/{plan_id}`
- `GET /runs`, `POST /runs/execute`, `POST /runs/resume`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/logs`
- `GET /runs/{run_id}/report`
- `GET /runs/{run_id}/checkpoint`
- `GET /audit`

Optional basic auth for web/API:

- `B24_WEB_USERNAME`
- `B24_WEB_PASSWORD`

## Docker deployment

1. Prepare env and config:

```bash
cp .env.example .env
mkdir -p docker/config
cp docker/config/migration.config.yml.example docker/config/migration.config.yml
```

2. Start stack:

```bash
docker compose up --build
```

3. Open:

- Web UI: `http://127.0.0.1:18080/`
- Adminer (optional): `http://127.0.0.1:18081/`
- MariaDB: `127.0.0.1:13306`

`docker-compose.yml` intentionally avoids port `15173` and uses `18080` by default.

## Health, logs, report, audit

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/runs/<run_id>/logs
curl http://127.0.0.1:8000/runs/<run_id>/report
curl http://127.0.0.1:8000/audit
```

All commands/endpoints print structured JSON for automation.
