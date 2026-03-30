#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

STATE_DIR="${B24_INSTALL_STATE_DIR:-.local/install}"
ENV_PATH="${B24_ENV_PATH:-.env}"
CONFIG_PATH="${B24_CONFIG_PATH:-migration.config.yml}"
WEB_PORT="${B24_WEB_PORT:-8080}"
DEFAULT_WEB_USERNAME="${B24_WEB_USERNAME:-admin}"
DEFAULT_WEB_PASSWORD="${B24_WEB_PASSWORD:-2156}"
DB_NAME="${B24_DB_NAME:-b24_runtime}"
DB_USER="${B24_DB_USER:-b24_user}"
DB_HOST="${B24_DB_HOST:-db}"
DB_PORT="${B24_DB_PORT:-3306}"

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
import string

alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(32)), end='')
PY
}

ensure_state_dir() {
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR"
}

write_env_if_needed() {
  if [[ -f "$ENV_PATH" ]]; then
    log "Reusing existing env file: $ENV_PATH"
    return
  fi

  ensure_state_dir

  local mysql_password mysql_root_password
  mysql_password="$(gen_password)"
  mysql_root_password="$(gen_password)"

  umask 077
  cat > "$ENV_PATH" <<ENV
MYSQL_DATABASE=$DB_NAME
MYSQL_USER=$DB_USER
MYSQL_PASSWORD=$mysql_password
MYSQL_ROOT_PASSWORD=$mysql_root_password
B24_WEB_USERNAME=$DEFAULT_WEB_USERNAME
B24_WEB_PASSWORD=$DEFAULT_WEB_PASSWORD
B24_WEB_PORT=$WEB_PORT
ENV
  chmod 600 "$ENV_PATH"
  log "Generated env file: $ENV_PATH"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$ENV_PATH"
  set +a
}

write_config_if_needed() {
  if [[ -f "$CONFIG_PATH" ]]; then
    log "Reusing existing config: $CONFIG_PATH"
    return
  fi

  umask 077
  cat > "$CONFIG_PATH" <<CFG
runtime_mode: production
database_url: mysql+pymysql://$MYSQL_USER:$MYSQL_PASSWORD@$DB_HOST:$DB_PORT/$MYSQL_DATABASE
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

compose_up() {
  log "Starting docker compose stack"
  "${COMPOSE_CMD[@]}" up -d --build
}

wait_for_service_health() {
  local service="$1"
  local cid status
  cid="$("${COMPOSE_CMD[@]}" ps -q "$service")"
  [[ -n "$cid" ]] || fail "Container id not found for service: $service"

  for _ in $(seq 1 120); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
      log "$service is healthy"
      return
    fi
    if [[ "$status" == "exited" || "$status" == "dead" ]]; then
      "${COMPOSE_CMD[@]}" logs "$service" || true
      fail "$service failed with status=$status"
    fi
    sleep 2
  done

  "${COMPOSE_CMD[@]}" logs "$service" || true
  fail "Timed out waiting for healthy status: $service"
}

detect_server_ip() {
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "$ip" ]]; then
    ip="127.0.0.1"
  fi
  printf '%s' "$ip"
}

print_summary() {
  local server_ip
  server_ip="$(detect_server_ip)"

  cat <<SUMMARY

Install complete
Web UI: http://$server_ip:${B24_WEB_PORT}
Login: ${B24_WEB_USERNAME}
Password: ${B24_WEB_PASSWORD}
Config: ./$CONFIG_PATH

Useful commands:
- Status: ${COMPOSE_CMD[*]} ps
- Logs:   ${COMPOSE_CMD[*]} logs -f web db
- Stop:   ${COMPOSE_CMD[*]} down
SUMMARY
}

main() {
  require_cmd docker
  require_cmd python3
  choose_compose
  write_env_if_needed
  load_env
  write_config_if_needed
  compose_up
  wait_for_service_health db
  wait_for_service_health web
  print_summary
}

main "$@"
