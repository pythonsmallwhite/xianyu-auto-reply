#!/usr/bin/env bash
# Ubuntu 源码部署：构建本仓库镜像并以 docker/ubuntu-compose.yml 运行（首装 / 更新 / 备份 / 恢复 / 回滚）。
# 一键首装请用 scripts/install-ubuntu.sh（会先安装 Docker 等依赖再调用本脚本）。
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${XIAN_YU_DEPLOY_DIR:-${ROOT_DIR}/.ubuntu-deploy}"
ENV_FILE="${XIAN_YU_ENV_FILE:-${STATE_DIR}/.env}"
COMPOSE_FILE="${ROOT_DIR}/docker/ubuntu-compose.yml"
PROJECT="${COMPOSE_PROJECT_NAME:-xianyu-ubuntu}"
LOCK_FILE="${STATE_DIR}/deploy.lock"
APP_SERVICES=(backend-web websocket scheduler frontend)
# 仅首次生成 .env 时使用（install-ubuntu.sh 传入）；之后以 .env 为准
IMPORT_DIR="${IMPORT_DIR:-}"
log(){ printf '[ubuntu-deploy] %s\n' "$*"; }
die(){ printf '[ubuntu-deploy] ERROR: %s\n' "$*" >&2; exit 1; }
# 以 .env 为唯一配置来源：清除同名 shell 变量，避免覆盖 .env
compose(){ env -u MYSQL_ROOT_PASSWORD -u MYSQL_PASSWORD -u REDIS_PASSWORD -u INTERNAL_API_TOKEN -u PUBLIC_HTTP_PORT -u PIP_INDEX_URL -u RELEASE_VERSION docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
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
  # 端口被本项目正在运行的前端占用属于正常（更新时）；被其他程序占用才报错
  if compose port frontend 80 2>/dev/null | grep -q ":${port}$"; then
    return 0
  fi
  if ss -ltn "sport = :$port" | tail -n +2 | grep -q .; then die "PUBLIC_HTTP_PORT $port is in use by another program"; fi
}
write_env(){
  mkdir -p "$STATE_DIR"
  if [[ -f "$ENV_FILE" ]]; then chmod 600 "$ENV_FILE"; return; fi
  local release; release="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf local)"
  umask 077
  {
    printf 'COMPOSE_PROJECT_NAME=%s\nRELEASE_VERSION=%s\nMYSQL_DATABASE=xianyu_data\nMYSQL_USER=xianyu\n' "$PROJECT" "$release"
    printf 'MYSQL_ROOT_PASSWORD=%s\nMYSQL_PASSWORD=%s\nREDIS_PASSWORD=%s\nINTERNAL_API_TOKEN=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$(openssl rand -hex 32)"
    printf 'PUBLIC_HTTP_PORT=%s\nLOG_LEVEL=INFO\nSQL_ECHO=false\nAUTO_START_CRAWL_JOBS=true\nAUTO_START_WEBSOCKET=true\n' "${XY_PUBLIC_HTTP_PORT:-8080}"
    printf 'FRONTEND_PUBLIC_URL=%s\nBACKEND_WEB_PUBLIC_URL=%s\n' "${XY_PUBLIC_URL:-}" "${XY_PUBLIC_URL:-http://127.0.0.1:8089}"
    printf 'PIP_INDEX_URL=%s\n' "${XY_PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"; log "created private configuration (credentials are not displayed)"
}
try_healthy(){
  local service="$1" timeout="${2:-240}" started now; started="$(date +%s)"
  while :; do
    compose ps --format '{{.Service}} {{.Health}}' "$service" 2>/dev/null | grep -q "^$service healthy$" && return 0
    now="$(date +%s)"; (( now-started < timeout )) || { log "$service did not become healthy"; compose logs --tail=40 "$service" >&2 || true; return 1; }
    sleep 3
  done
}
wait_healthy(){ try_healthy "$@" || die "$1 did not become healthy"; }
apps_healthy(){ try_healthy backend-web 240 && try_healthy websocket 240 && try_healthy scheduler 240 && try_healthy frontend 120; }
backup(){
  local dir="${1:-$STATE_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)}" root
  root="$(realpath -m "$STATE_DIR/backups")"; dir="$(realpath -m "$dir")"
  [[ "$dir" == "$root"/* ]] || die "backup path must remain below $root"
  mkdir -p "$dir"; chmod 700 "$dir"; wait_healthy mysql 240
  compose exec -T mysql sh -c 'exec mysqldump --single-transaction --routines --triggers -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' | gzip -c > "$dir/database.sql.gz"
  compose run --rm --no-deps -T backend-web sh -c 'tar -C /app/static -czf - .' > "$dir/static.tar.gz"
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
  compose run --rm --no-deps -T backend-web sh -c 'rm -rf /app/static/* && tar -xzf - -C /app/static' < "$dir/static.tar.gz"
  compose up -d backend-web websocket scheduler frontend
  wait_healthy backend-web 240; wait_healthy websocket 240; wait_healthy scheduler 240; wait_healthy frontend 120
}
verify_health(){
  local port body; port="$(env_value PUBLIC_HTTP_PORT)"; port="${port:-8080}"
  body="$(curl --fail --silent --show-error "http://127.0.0.1:$port/health")" || { log "public health endpoint failed"; return 1; }
  grep -q '"database"[[:space:]]*:[[:space:]]*"connected"' <<<"$body" || { log "public health reports database not connected"; return 1; }
}
# 首次部署导入旧服务器数据（scripts/export-for-migration.sh 导出）；只允许导入到空数据库。
# 导入成功后记录数据包校验值：首装中途失败后用同一个数据包重跑会跳过导入，不会重复导入或误拒绝。
IMPORT_MARKER_FILE="${STATE_DIR}/imported-database.sha256"
# 至少成功部署过一次的标记（之后库里可能有新业务数据，任何导入都必须拒绝）
DEPLOYED_MARKER_FILE="${STATE_DIR}/deployed.ok"
import_database(){
  [[ -n "$IMPORT_DIR" ]] || return 0
  [[ -f "$IMPORT_DIR/database.sql.gz" ]] || die "IMPORT_DIR must contain database.sql.gz"
  local tables digest
  digest="$(sha256sum "$IMPORT_DIR/database.sql.gz" | awk '{print $1}')"
  if [[ -f "$IMPORT_MARKER_FILE" && "$(cat "$IMPORT_MARKER_FILE")" == "$digest" ]]; then
    log "this data bundle was already imported; skipping database import"
    return 0
  fi
  # shellcheck disable=SC2016
  tables="$(compose exec -T mysql sh -c 'mysql -N -uroot -p"$MYSQL_ROOT_PASSWORD" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '"'"'$MYSQL_DATABASE'"'"'"' 2>/dev/null | tr -dc '0-9')" || true
  [[ "$tables" =~ ^[0-9]+$ ]] || die "cannot inspect target database before import"
  if (( tables > 0 )); then
    # 上一次首装导入过、但从未部署成功：库里只有那次导入的数据，没有被使用过，可以重建后导入新数据包
    if [[ -f "$IMPORT_MARKER_FILE" && ! -f "$DEPLOYED_MARKER_FILE" ]]; then
      log "previous first-install import never completed a deployment; recreating database before importing"
      # shellcheck disable=SC2016
      compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"' 2>/dev/null \
        || die "cannot recreate database before import"
    else
      die "target database already has $tables tables; import is only for a fresh install (use 'restore' for backups made by this script)"
    fi
  fi
  log "importing database from $IMPORT_DIR/database.sql.gz"
  gzip -dc "$IMPORT_DIR/database.sql.gz" | compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
  printf '%s\n' "$digest" > "$IMPORT_MARKER_FILE"; chmod 600 "$IMPORT_MARKER_FILE"
  log "database import finished"
}
import_files(){
  [[ -n "$IMPORT_DIR" ]] || return 0
  if [[ -f "$IMPORT_DIR/static.tar.gz" ]]; then
    log "importing static files"
    compose run --rm --no-deps -T backend-web sh -c 'tar -xzf - -C /app/static' < "$IMPORT_DIR/static.tar.gz"
  fi
  if [[ -f "$IMPORT_DIR/browser_data.tar.gz" ]]; then
    log "importing browser data"
    compose run --rm --no-deps -T websocket sh -c 'tar -xzf - -C /app/browser_data' < "$IMPORT_DIR/browser_data.tar.gz"
  fi
}
app_image(){ printf 'xianyu-ubuntu/%s:%s' "$1" "$(env_value RELEASE_VERSION)"; }
# 部署完全成功（迁移 + 健康检查通过）后才把当前镜像标记为 :stable；失败时回滚到 :stable。
# 这样构建中途失败后重跑，也不会把半新的镜像当成“上一个可用版本”。
mark_stable(){
  local service
  for service in "${APP_SERVICES[@]}"; do docker image tag "$(app_image "$service")" "xianyu-ubuntu/${service}:stable"; done
}
has_stable(){
  local service
  for service in "${APP_SERVICES[@]}"; do docker image inspect "xianyu-ubuntu/${service}:stable" >/dev/null 2>&1 || return 1; done
}
build_images(){
  local service
  # 逐个构建：小内存服务器上并行构建三个 Python 镜像容易内存不足
  for service in "${APP_SERVICES[@]}"; do
    log "building $service"
    compose build "$service"
  done
}
do_rollback(){
  has_stable || die "no stable images to roll back to (first deployment has not succeeded yet)"
  local service
  for service in "${APP_SERVICES[@]}"; do docker image tag "xianyu-ubuntu/${service}:stable" "$(app_image "$service")"; done
  if compose up -d --force-recreate "${APP_SERVICES[@]}" && apps_healthy && verify_health; then
    log "rolled back to last stable images"; return 0
  fi
  die "rollback did not become healthy; check: bash scripts/deploy-ubuntu.sh logs"
}
rollback(){
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"
  check_platform; check_env; do_rollback
}
# 新版本迁移或启动失败：有上一版镜像就自动回滚，否则保留现场退出
fail_or_rollback(){
  local reason="$1"
  if has_stable; then
    log "$reason; rolling back to last stable images"
    do_rollback
    die "$reason; rolled back to the previous version (backup: $SNAPSHOT)"
  fi
  die "$reason; backup and logs were preserved"
}
deploy(){
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"
  check_platform; check_prereqs; check_env; compose config --quiet
  compose up -d mysql redis; wait_healthy mysql 240; wait_healthy redis 120
  import_database
  build_images
  import_files
  local snapshot="$STATE_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)"; backup "$snapshot"; SNAPSHOT="$snapshot"
  compose stop frontend scheduler websocket backend-web >/dev/null 2>&1 || true
  log "running current-source database initializer once"
  if ! compose run --rm --no-deps backend-web python -m common.db.init_database; then
    fail_or_rollback "database migration failed"
  fi
  if ! { compose up -d && apps_healthy && verify_health; }; then
    fail_or_rollback "new version did not become healthy"
  fi
  mark_stable
  date -u +%Y-%m-%dT%H:%M:%SZ > "$DEPLOYED_MARKER_FILE"
  compose ps
  log "deployment finished: release $(env_value RELEASE_VERSION), http://<server-ip>:$(env_value PUBLIC_HTTP_PORT)/"
}
SNAPSHOT=""
# 只构建镜像、不启动/不停止任何服务（迁移时先在旧站点运行期间完成耗时的构建）
build_only(){
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"
  check_platform; check_env; compose config --quiet
  build_images
  log "images built; no service was started or stopped"
}
status(){ check_platform; check_prereqs; check_env; compose ps; }
logs(){ compose logs --tail="${LOG_LINES:-200}" -f; }
main(){
  local command="${1:-deploy}"; mkdir -p "$STATE_DIR"; write_env
  case "$command" in
    deploy|update) deploy;;
    build) build_only;;
    status) status;;
    logs) logs;;
    stop) compose stop;;
    restart) compose restart;;
    backup) exec 9>"$LOCK_FILE"; flock -n 9 || die "another deployment, backup or restore is running"; check_platform; check_prereqs; check_env; backup "${2:-}";;
    restore) check_platform; check_prereqs; check_env; restore "${2:-}";;
    rollback) rollback;;
    *) printf 'usage: %s [deploy|update|build|status|logs|stop|restart|backup [dir]|restore <dir>|rollback]\n' "$0" >&2; return 2;;
  esac
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
