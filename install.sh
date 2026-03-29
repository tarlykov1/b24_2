#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CONFIG_PATH="${B24_CONFIG_PATH:-migration.config.yml}"
STATE_DIR="${B24_INSTALL_STATE_DIR:-.local/install}"
DB_ENV_PATH="$STATE_DIR/db.env"
VENV_PATH="${B24_VENV_PATH:-.venv}"
DB_PORT="${B24_DB_PORT:-13306}"
DB_NAME="${B24_DB_NAME:-b24_runtime}"
DB_USER="${B24_DB_USER:-b24_user}"

log() {
  printf '[install] %s\n' "$*"
}

fail() {
  printf '[install] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

choose_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    fail "Docker Compose is required (docker compose or docker-compose)"
  fi
}

gen_password() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
}

write_db_env_if_needed() {
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"

  if [[ -f "$DB_ENV_PATH" ]]; then
    log "Reusing existing DB credentials at $DB_ENV_PATH"
    return
  fi

  local password root_password
  password="$(gen_password)"
  root_password="$(gen_password)"

  umask 077
  cat > "$DB_ENV_PATH" <<ENV
MYSQL_DATABASE=$DB_NAME
MYSQL_USER=$DB_USER
MYSQL_PASSWORD=$password
MYSQL_ROOT_PASSWORD=$root_password
ENV
  chmod 600 "$DB_ENV_PATH"
  log "Generated DB credentials at $DB_ENV_PATH"
}

load_db_env() {
  set -a
  # shellcheck disable=SC1090
  source "$DB_ENV_PATH"
  set +a
}

bring_up_db() {
  log "Starting MySQL container via docker-compose.db.yml"
  "${COMPOSE_CMD[@]}" -f docker-compose.db.yml up -d
}

wait_for_db_healthy() {
  log "Waiting for DB healthcheck"
  local cid status attempt
  cid="$("${COMPOSE_CMD[@]}" -f docker-compose.db.yml ps -q db)"
  [[ -n "$cid" ]] || fail "DB container id was not found"

  for attempt in $(seq 1 90); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
      log "DB is healthy"
      return
    fi
    if [[ "$status" == "exited" || "$status" == "dead" ]]; then
      "${COMPOSE_CMD[@]}" -f docker-compose.db.yml logs db || true
      fail "DB container failed with status=$status"
    fi
    sleep 2
  done

  "${COMPOSE_CMD[@]}" -f docker-compose.db.yml logs db || true
  fail "Timed out while waiting for DB health status"
}

write_config_if_needed() {
  if [[ -f "$CONFIG_PATH" ]]; then
    log "Reusing existing config: $CONFIG_PATH"
    return
  fi

  umask 077
  cat > "$CONFIG_PATH" <<CFG
runtime_mode: production
database_url: mysql+pymysql://$MYSQL_USER:$MYSQL_PASSWORD@127.0.0.1:$DB_PORT/$MYSQL_DATABASE
source:
  base_url: https://source.example
  webhook: replace-with-source-webhook
target:
  base_url: https://target.example
  webhook: replace-with-target-webhook
default_scope:
  - crm
  - tasks
CFG
  chmod 600 "$CONFIG_PATH"
  log "Generated config: $CONFIG_PATH"
}

ensure_venv_and_deps() {
  if [[ ! -d "$VENV_PATH" ]]; then
    log "Creating Python virtualenv at $VENV_PATH"
    python3 -m venv "$VENV_PATH"
  fi

  log "Installing Python dependencies"
  "$VENV_PATH/bin/pip" install --upgrade pip
  "$VENV_PATH/bin/pip" install -e .
}

run_install_flow() {
  log "Running application-level local install flow"
  "$VENV_PATH/bin/b24-runtime" install:local --config "$CONFIG_PATH"
}

print_summary() {
  log "готово"
  cat <<SUMMARY

Install summary:
- config: $CONFIG_PATH
- db compose file: docker-compose.db.yml
- db host: 127.0.0.1
- db port: $DB_PORT
- db name: $MYSQL_DATABASE
- db user: $MYSQL_USER
- db secrets file: $DB_ENV_PATH

Useful commands:
- DB status: ${COMPOSE_CMD[*]} -f docker-compose.db.yml ps
- DB logs:   ${COMPOSE_CMD[*]} -f docker-compose.db.yml logs db
- DB stop:   ${COMPOSE_CMD[*]} -f docker-compose.db.yml down
SUMMARY
}

main() {
  require_cmd docker
  require_cmd python3
  choose_compose
  write_db_env_if_needed
  load_db_env
  bring_up_db
  wait_for_db_healthy
  write_config_if_needed
  ensure_venv_and_deps
  run_install_flow
  print_summary
}

main "$@"
