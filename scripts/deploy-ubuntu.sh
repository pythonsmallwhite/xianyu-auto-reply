#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${XIAN_YU_DEPLOY_DIR:-${ROOT_DIR}/.ubuntu-deploy}"
ENV_FILE="${XIAN_YU_ENV_FILE:-${STATE_DIR}/.env}"
COMPOSE_FILE="${ROOT_DIR}/docker/ubuntu-compose.yml"
PROJECT="${COMPOSE_PROJECT_NAME:-xianyu-ubuntu}"
LOCK_FILE="${STATE_DIR}/deploy.lock"
log(){ printf '[ubuntu-deploy] %s\n' "$*"; }
die(){ printf '[ubuntu-deploy] ERROR: %s\n' "$*" >&2; exit 1; }
compose(){ env -u MYSQL_ROOT_PASSWORD -u MYSQL_PASSWORD -u REDIS_PASSWORD -u INTERNAL_API_TOKEN docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
trap 'rc=$?; printf "[ubuntu-deploy] failed (exit %s); containers, volumes and logs were preserved\n" "$rc" >&2; exit "$rc"' ERR
require_cmd(){ command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
env_value(){ awk -F= -v key="$1" '$1==key {v=substr($0,index($0,"=")+1)} END{print v}' "$ENV_FILE" 2>/dev/null || true; }
check_platform(){
  [[ "$(uname -s)" == Linux ]] || die "Ubuntu/Linux is required"
  [[ -r /etc/os-release ]] || die "cannot identify operating system"
  source /etc/os-release
  [[ "${ID:-}" == ubuntu || "${ID_LIKE:-}" == *ubuntu* ]] || die "Ubuntu is required"
  case "$(uname -m)" in x86_64|aarch64|arm64) ;; *) die "unsupported architecture" ;; esac
}
check_env(){
  local key value
  for key in MYSQL_ROOT_PASSWORD MYSQL_PASSWORD REDIS_PASSWORD INTERNAL_API_TOKEN; do
    value="$(env_value "$key")"; [[ "${#value}" -ge 24 ]] || die "$key must contain at least 24 characters"
    case "$value" in xianyu@2026|change-me|password|admin123) die "$key uses a weak value" ;; esac
  done
}
check_prereqs(){
  require_cmd docker; require_cmd openssl; require_cmd flock; require_cmd curl; require_cmd awk; require_cmd df; require_cmd ss
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
  [[ -f "$COMPOSE_FILE" ]] || die "missing Compose file"
  local free_kb; free_kb="$(df -Pk "$STATE_DIR" | awk 'NR==2{print $4}')"
  [[ "$free_kb" =~ ^[0-9]+$ && "$free_kb" -ge 10485760 ]] || die "at least 10 GiB free disk is required"
  local port; port="$(env_value PUBLIC_HTTP_PORT)"; port="${port:-8080}"
  [[ "$port" =~ ^[0-9]+$ && "$port" -ge 1 && "$port" -le 65535 ]] || die "invalid PUBLIC_HTTP_PORT"
  if ss -ltn "sport = :$port" | tail -n +2 | grep -q .; then die "PUBLIC_HTTP_PORT is in use"; fi
}
write_env(){
  mkdir -p "$STATE_DIR"
  if [[ -f "$ENV_FILE" ]]; then chmod 600 "$ENV_FILE"; return; fi
  local release; release="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf local)"
  umask 077
  {
    printf 'COMPOSE_PROJECT_NAME=%s\nRELEASE_VERSION=%s\nMYSQL_DATABASE=xianyu_data\nMYSQL_USER=xianyu\n' "$PROJECT" "$release"
    printf 'MYSQL_ROOT_PASSWORD=%s\nMYSQL_PASSWORD=%s\nREDIS_PASSWORD=%s\nINTERNAL_API_TOKEN=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)"
    printf 'PUBLIC_HTTP_PORT=8080\nLOG_LEVEL=INFO\nSQL_ECHO=false\nAUTO_START_CRAWL_JOBS=true\nAUTO_START_WEBSOCKET=true\n'
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"; log "created private configuration (credentials are not displayed)"
}
wait_healthy(){
  local service="$1" timeout="${2:-240}" started now; started="$(date +%s)"
  while :; do
    compose ps --format '{{.Service}} {{.Health}}' "$service" 2>/dev/null | grep -q "^$service healthy$" && return 0
    now="$(date +%s)"; (( now-started < timeout )) || die "$service did not become healthy"; sleep 3
  done
}
backup(){
  local dir="${1:-$STATE_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)}" root
  root="$(realpath -m "$STATE_DIR/backups")"; dir="$(realpath -m "$dir")"
  [[ "$dir" == "$root"/* ]] || die "backup path must remain below $root"
  mkdir -p "$dir"; chmod 700 "$dir"; wait_healthy mysql 240
  compose exec -T mysql sh -c 'exec mysqldump --single-transaction --routines --triggers -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' | gzip -c > "$dir/database.sql.gz"
  compose run --rm --no-deps backend-web sh -c 'tar -C /app/static -czf - .' > "$dir/static.tar.gz"
  chmod 600 "$dir/database.sql.gz" "$dir/static.tar.gz"
  printf 'release=%s\ncreated_utc=%s\n' "$(env_value RELEASE_VERSION)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$dir/manifest"; chmod 600 "$dir/manifest"
  log "backup created under $dir"
}
restore(){
  local dir="${1:-}" root; [[ -n "$dir" ]] || die "restore requires a backup directory"
  root="$(realpath -m "$STATE_DIR/backups")"; dir="$(realpath -m "$dir")"
  [[ "$dir" == "$root"/* && -f "$dir/database.sql.gz" && -f "$dir/static.tar.gz" ]] || die "restore directory must contain database.sql.gz and static.tar.gz below $root"
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"
  wait_healthy mysql 240; compose stop frontend scheduler websocket backend-web >/dev/null 2>&1 || true
  gzip -dc "$dir/database.sql.gz" | compose exec -T mysql sh -c 'exec mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
  compose run --rm --no-deps backend-web sh -c 'rm -rf /app/static/* && tar -xzf - -C /app/static' < "$dir/static.tar.gz"
  compose up -d backend-web websocket scheduler frontend
  wait_healthy backend-web 240; wait_healthy websocket 240; wait_healthy scheduler 240; wait_healthy frontend 120
}
verify_health(){
  local port body; port="$(env_value PUBLIC_HTTP_PORT)"; port="${port:-8080}"
  body="$(curl --fail --silent --show-error "http://127.0.0.1:$port/health")" || die "public health endpoint failed"
  grep -q '"database"[[:space:]]*:[[:space:]]*"connected"' <<<"$body" || die "public health reports database not connected"
}
deploy(){
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"
  check_platform; check_prereqs; check_env; compose config --quiet
  compose up -d mysql redis; wait_healthy mysql 240; wait_healthy redis 120
  compose build --pull=false
  local snapshot="$STATE_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)"; backup "$snapshot"
  compose stop frontend scheduler websocket backend-web >/dev/null 2>&1 || true
  log "running current-source database initializer once"
  if ! compose run --rm --no-deps backend-web python -m common.db.init_database; then
    die "database migration failed; backup and logs were preserved"
  fi
  compose up -d; wait_healthy backend-web 240; wait_healthy websocket 240; wait_healthy scheduler 240; wait_healthy frontend 120; verify_health; compose ps
}
status(){ check_platform; check_prereqs; check_env; compose ps; }
logs(){ compose logs --tail="${LOG_LINES:-200}" -f; }
main(){
  local command="${1:-deploy}"; mkdir -p "$STATE_DIR"; write_env
  case "$command" in
    deploy|update) deploy;;
    status) status;;
    logs) logs;;
    stop) compose stop;;
    restart) compose restart;;
    backup) exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"; check_platform; check_prereqs; check_env; backup "${2:-}";;
    restore) check_platform; check_prereqs; check_env; restore "${2:-}";;
    *) printf 'usage: %s [deploy|update|status|logs|stop|restart|backup [dir]|restore <dir>]\n' "$0" >&2; return 2;;
  esac
}
main "$@"
