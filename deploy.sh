#!/usr/bin/env bash
# ==========================================
# 闲鱼自动回复系统（自用 fork）- 部署 / 更新入口
#
# 只用本仓库源码构建镜像，不再拉取原作者预构建镜像（那些镜像带广告和远程“官方”内容）。
#   bash deploy.sh                 首次：安装依赖并部署；已部署：更新到当前代码
#   bash deploy.sh status|logs|rollback|backup
#   bash deploy.sh stop-legacy     停用旧版（原作者镜像）容器，保留数据
# 首次部署选项：--port N（默认 80） --public-url URL --import 数据包 --no-bundle
#
# Ubuntu：检测到旧版 deploy.sh 部署的容器（xianyu-*）时自动迁移：
#   旧站点运行期间先构建新镜像 → 停旧版并导出数据 → 新版导入数据并启动 → 成功后旧版保持停用；
#   任一步失败自动恢复旧版。旧数据目录 xianyu_auto_reply/ 与旧镜像都不删除。
# 非 Ubuntu（如 CentOS 7）且已有旧版部署：调用 scripts/update-server.sh 原地换成本仓库镜像。
# ==========================================
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_STATE_DIR="${ROOT_DIR}/.ubuntu-deploy"
LEGACY_COMPOSE="${ROOT_DIR}/docker-compose.deploy.yml"
LEGACY_ENV="${ROOT_DIR}/.env"
LEGACY_PROJECT="xianyu-auto-reply"
LEGACY_APPS=(xianyu-frontend xianyu-scheduler xianyu-websocket xianyu-backend-web)
LEGACY_DATA=(xianyu-mysql xianyu-redis)
OS_RELEASE="${OS_RELEASE:-/etc/os-release}"
COMMAND="auto"
PORT="80"
PORT_SET=0
PUBLIC_URL=""
IMPORT=""
NO_BUNDLE=0
LEGACY_STOPPED=0

log(){ printf '[deploy] %s\n' "$*"; }
die(){ printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }
usage(){ sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; }

parse_args(){
  while (($#)); do
    case "$1" in
      install|update|status|logs|rollback|backup|stop-legacy) COMMAND="$1" ;;
      --port) PORT="${2:-}"; PORT_SET=1; shift ;;
      --public-url) PUBLIC_URL="${2:-}"; shift ;;
      --import) IMPORT="${2:-}"; shift ;;
      --no-bundle) NO_BUNDLE=1 ;;
      -h|--help|help) usage; exit 0 ;;
      *) usage >&2; die "unknown argument: $1" ;;
    esac
    shift
  done
  if [[ -n "$IMPORT" ]]; then
    [[ -e "$IMPORT" ]] || die "--import path not found: $IMPORT"
    IMPORT="$(cd "$(dirname "$IMPORT")" && pwd)/$(basename "$IMPORT")"
  fi
  [[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || die "invalid --port: $PORT"
}
is_ubuntu(){ [[ -r "$OS_RELEASE" ]] && [[ "$(awk -F= '$1=="ID"{gsub(/"/,"",$2); print $2}' "$OS_RELEASE")" == ubuntu ]]; }
have_docker(){ command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
container_exists(){ docker inspect "$1" >/dev/null 2>&1; }
container_running(){ [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == true ]]; }
legacy_present(){ have_docker && { container_exists xianyu-backend-web || container_exists xianyu-mysql; }; }
legacy_running(){ local c; for c in "${LEGACY_APPS[@]}"; do container_running "$c" && return 0; done; return 1; }
new_installed(){
  [[ -f "$NEW_STATE_DIR/deployed.ok" ]] && return 0
  have_docker && docker image inspect xianyu-ubuntu/backend-web:stable >/dev/null 2>&1
}
require_root(){
  if (( EUID != 0 )); then
    command -v sudo >/dev/null 2>&1 || die "run as root or install sudo"
    exec sudo -E bash "$ROOT_DIR/deploy.sh" "$@"
  fi
}
# 用户上传的旧服务器数据包（scripts/export-for-migration.sh 导出）
find_uploaded_bundle(){
  local f
  # shellcheck disable=SC2086
  for f in ${BUNDLE_GLOBS:-/root/xianyu-export-*.tar.gz /home/*/xianyu-export-*.tar.gz}; do
    [[ -f "$f" ]] && { printf '%s\n' "$f"; return 0; }
  done
  return 1
}
# 发现已上传的数据包但用户没有明确选择时停下来，避免导错数据
check_bundle_choice(){
  local context="$1" found
  [[ -n "$IMPORT" || "$NO_BUNDLE" == 1 ]] && return 0
  found="$(find_uploaded_bundle)" || return 0
  if [[ "$context" == legacy ]]; then
    die "found uploaded data bundle $found. Choose one: 'bash deploy.sh --import $found' to import it, or 'bash deploy.sh --no-bundle' to migrate the data of the containers running on this server"
  fi
  die "found uploaded data bundle $found. Choose one: 'bash deploy.sh --import $found' to import it, or 'bash deploy.sh --no-bundle' to start with an empty database"
}
port_in_use(){ ss -ltn "sport = :$1" 2>/dev/null | tail -n +2 | grep -q .; }
legacy_port(){ docker port xianyu-frontend 80 2>/dev/null | head -1 | sed 's/.*://'; }
# 停用旧版容器：先禁止自动重启再停止（防止重启服务器后新旧两套同时运行、重复自动回复），不删除容器和数据
stop_legacy(){
  local c
  for c in "$@"; do
    if container_exists "$c"; then
      docker update --restart=no "$c" >/dev/null 2>&1 || true
      docker stop "$c" >/dev/null 2>&1 || true
    fi
  done
}
restore_legacy(){
  local c
  for c in "${LEGACY_DATA[@]}" "${LEGACY_APPS[@]}"; do
    if container_exists "$c"; then
      docker update --restart=unless-stopped "$c" >/dev/null 2>&1 || true
      docker start "$c" >/dev/null 2>&1 || true
    fi
  done
}
# 迁移中途失败（或被中断）：停掉新版应用，恢复旧版，保证任何时刻只有一套应用在跑
on_migration_exit(){
  local rc=$?
  if (( rc != 0 && LEGACY_STOPPED )); then
    log "migration failed; stopping the new stack and restarting the previous containers"
    bash "$ROOT_DIR/scripts/deploy-ubuntu.sh" stop >/dev/null 2>&1 || true
    restore_legacy
    log "previous site restored. Fix the reported error and run 'bash deploy.sh' again."
  fi
}
ensure_legacy_mysql(){
  container_exists xianyu-mysql || die "legacy MySQL container xianyu-mysql not found; cannot export its data"
  container_running xianyu-mysql || docker start xianyu-mysql >/dev/null
  local i
  for i in $(seq 1 60); do
    # shellcheck disable=SC2016
    docker exec xianyu-mysql sh -c 'mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD" --silent' >/dev/null 2>&1 && return 0
    sleep 2
  done
  die "legacy MySQL did not become ready"
}
install_args(){
  INSTALL_ARGS=(--port "$PORT")
  if [[ -n "$PUBLIC_URL" ]]; then INSTALL_ARGS+=(--public-url "$PUBLIC_URL"); fi
}
# 新版对外端口：已有配置以配置为准；否则默认 80，80 被其他程序占用且用户没指定时沿用旧版端口
choose_port(){
  local configured old
  configured="$(awk -F= '$1=="PUBLIC_HTTP_PORT"{print $2}' "$NEW_STATE_DIR/.env" 2>/dev/null || true)"
  if [[ -n "$configured" ]]; then PORT="$configured"; return 0; fi
  old="$(legacy_port || true)"
  if (( ! PORT_SET )) && port_in_use "$PORT" && [[ "$PORT" != "$old" ]] && [[ -n "$old" ]]; then
    log "port $PORT is used by another program; keeping the previous port $old"
    PORT="$old"
  fi
  return 0
}
migrate_legacy(){
  local old export_path_file bundle
  check_bundle_choice legacy
  choose_port
  old="$(legacy_port || true)"
  if port_in_use "$PORT" && [[ "$PORT" != "$old" ]]; then
    die "port $PORT is used by another program; free it or run: bash deploy.sh --port <other-port>"
  fi
  install_args
  log "step 1/4: building images from this repository while the current site keeps running"
  bash "$ROOT_DIR/scripts/install-ubuntu.sh" "${INSTALL_ARGS[@]}" --build-only

  trap on_migration_exit EXIT
  log "step 2/4: stopping the previous application containers (data is kept)"
  stop_legacy "${LEGACY_APPS[@]}"; LEGACY_STOPPED=1
  if [[ -n "$IMPORT" ]]; then
    bundle="$IMPORT"
    log "step 3/4: using uploaded data bundle $bundle"
  else
    log "step 3/4: exporting data of the previous containers"
    ensure_legacy_mysql
    export_path_file="$(mktemp)"
    EXPORT_PATH_FILE="$export_path_file" EXPORT_QUIET=1 bash "$ROOT_DIR/scripts/export-for-migration.sh"
    bundle="$(cat "$export_path_file")"; rm -f "$export_path_file"
    [[ -f "$bundle" ]] || die "export did not produce a data bundle"
  fi
  stop_legacy "${LEGACY_DATA[@]}"
  log "step 4/4: starting the new version and importing data"
  bash "$ROOT_DIR/scripts/install-ubuntu.sh" "${INSTALL_ARGS[@]}" --import "$bundle"
  trap - EXIT
  log "migration finished. Previous containers are stopped and will not auto-start; data backup: $bundle"
  log "after confirming the new site works you may remove them: docker rm ${LEGACY_APPS[*]} ${LEGACY_DATA[*]}"
}
fresh_install(){
  check_bundle_choice fresh
  install_args
  if [[ -n "$IMPORT" ]]; then INSTALL_ARGS+=(--import "$IMPORT"); fi
  exec bash "$ROOT_DIR/scripts/install-ubuntu.sh" "${INSTALL_ARGS[@]}"
}
main(){
  parse_args "$@"
  require_root "$@"
  if ! is_ubuntu; then
    legacy_present || die "fresh installs need Ubuntu 24.04: reinstall the server, then run bash deploy.sh"
    log "non-Ubuntu server with a previous deployment: switching it to images built from this repository"
    case "$COMMAND" in
      auto|install|update) exec bash "$ROOT_DIR/scripts/update-server.sh" update ;;
      rollback|status) exec bash "$ROOT_DIR/scripts/update-server.sh" "$COMMAND" ;;
      logs) exec docker compose -p "$LEGACY_PROJECT" -f "$LEGACY_COMPOSE" --env-file "$LEGACY_ENV" logs --tail=200 -f ;;
      stop-legacy) stop_legacy "${LEGACY_APPS[@]}"; log "previous application containers stopped"; exit 0 ;;
      *) die "'$COMMAND' is not supported on this server; reinstall it as Ubuntu 24.04" ;;
    esac
  fi
  case "$COMMAND" in
    status|logs|rollback|backup) exec bash "$ROOT_DIR/scripts/deploy-ubuntu.sh" "$COMMAND" ;;
    stop-legacy) stop_legacy "${LEGACY_APPS[@]}" "${LEGACY_DATA[@]}"; log "previous containers stopped (data kept)"; exit 0 ;;
  esac
  if new_installed; then
    bash "$ROOT_DIR/scripts/deploy-ubuntu.sh" update
    if legacy_present && legacy_running; then
      log "previous containers (original author's images) were still running; stopping them to avoid duplicate auto-replies"
      stop_legacy "${LEGACY_APPS[@]}" "${LEGACY_DATA[@]}"
    fi
    exit 0
  fi
  if legacy_present; then migrate_legacy; exit 0; fi
  fresh_install
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
