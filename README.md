# b24-migration-runtime (enterprise baseline extension)

Production-oriented runtime for deterministic Bitrix24 migration with **CLI + Web UI** over one shared service layer.

## One-command Docker install (default path)

> Default runtime is now fully dockerized: **db + web UI/runtime in Docker Compose**.

```bash
chmod +x install.sh
./install.sh
```

Installer flow:

1. checks `docker` and `docker compose` (or `docker-compose`);
2. generates `.env` (DB credentials, web basic auth, web port) if missing;
3. generates `migration.config.yml` if missing;
4. runs `docker compose up -d --build`;
5. waits until **db** and **web** are `healthy`;
6. prints final URL/login/password summary.

Default credentials on first install:

- `B24_WEB_USERNAME=admin`
- `B24_WEB_PASSWORD=2156`

The installer is idempotent: existing `.env` and config are reused.

### Result after successful install

- MariaDB runtime DB is running in Docker with persistent volume.
- Web UI/runtime (`uvicorn b24_migrator.web.app:app`) is running in Docker.
- Basic Auth is active for all routes when `B24_WEB_USERNAME/B24_WEB_PASSWORD` are set.
- URL is available immediately from installer summary.

### Runtime operations

```bash
# status
docker compose ps

# logs
docker compose logs -f web db

# stop
docker compose down

# restart
docker compose up -d
```

## Configuration and auth

### Auto-generated config

Generated file: `migration.config.yml`

- created automatically when missing;
- uses generated DB credentials from `.env`;
- no mandatory manual `database_url` editing for first run.

`runtime_mode: production` keeps MySQL-only storage policy.

### Basic Auth

When env vars are present, UI/API access always requires HTTP Basic Auth:

```bash
B24_WEB_USERNAME=admin
B24_WEB_PASSWORD=2156
```

In docker-first mode these values are stored in `.env`.

## Healthchecks

Compose includes healthchecks for both services:

- `db`: MariaDB ping healthcheck;
- `web`: `/health` probe (with basic auth headers when auth is enabled).

`install.sh` reports success only after both are healthy.

## Known limitations

- HTTPS is **not enabled** in default docker-first scenario.
- For production domain/TLS/public exposure, use reverse proxy as **optional advanced mode**.

## Advanced/manual mode (optional)

If you need custom infra (systemd/nginx/manual process control), use this path.

### Manual Python runtime install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/b24-runtime deployment:check --config migration.config.yml
.venv/bin/b24-runtime install:local --config migration.config.yml
```

### Manual web start

```bash
uvicorn b24_migrator.web.app:app
```

### Optional systemd + nginx examples

- systemd unit: `deploy/systemd/b24-migrator-web.service`
- nginx reverse proxy example: `deploy/nginx/b24-migrator.conf`

These are not required for default install scenario.

## Summary

This repository keeps the baseline and includes enterprise extensions:

- users/groups/projects/tasks/comments/file references migration services;
- CRM schemas and CRM entities migration;
- source↔target mapping subsystem;
- user conflict policy + manual review queue;
- dependency-aware execution safety;
- expanded verification (`verify:counts`, `verify:relations`, `verify:integrity`, `verify:files`) persisted in DB;
- cleanup/delta/cutover planning;
- enterprise UI screen for matrix/mappings/conflicts/verification/cleanup/delta.

## CLI additions

Core commands:

- `b24-runtime create-job`
- `b24-runtime plan`
- `b24-runtime execute`
- `b24-runtime status`
- `b24-runtime checkpoint`
- `b24-runtime report`
- `b24-runtime verify`
- `b24-runtime deployment:check`
- `b24-runtime install:local`

Enterprise extensions:

- `matrix`
- `domains`
- `mappings`
- `users:discover`
- `users:map`
- `users:review`
- `groups:sync`
- `projects:sync`
- `tasks:migrate`
- `crm:sync`
- `crm:verify`
- `verify:counts`
- `verify:relations`
- `verify:integrity`
- `verify:files`
- `verify:results`
- `cleanup:plan`
- `cleanup:execute`
- `delta:plan`
- `delta:execute`
- `cutover:readiness`

## Testing

```bash
pytest
```
