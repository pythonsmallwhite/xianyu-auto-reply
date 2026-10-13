#!/usr/bin/env bash
# 服务器一键更新：用当前仓库源码构建镜像，替换 deploy.sh 部署的四个业务容器（MySQL/Redis 与数据目录不动）。
#
# 适用：已用根目录 deploy.sh 部署、存在 docker-compose.deploy.yml 与 .env 的服务器。
# 用法（在仓库根目录，先自行 git pull）：
#   bash scripts/update-server.sh            # 构建 → 备份数据库 → 逐个切换 → 健康检查，失败自动回滚
#   bash scripts/update-server.sh rollback   # 切回上一次的镜像
#   bash scripts/update-server.sh status     # 查看当前镜像与健康状态
# 构建方式：
#   默认快速构建：Python 服务以服务器上已有的同服务镜像为底座（docker/app-overlay.Dockerfile），
#   只替换源码、补装新增 Python 依赖，不跑 apt、不下载浏览器；底座固定为 xianyu-local/xianyu-<服务>:deps。
#   FULL_BUILD=1：按各服务 Dockerfile 完整构建（需要大量下载和约 3GB 空闲磁盘），成功后刷新 :deps 底座。
# 可选环境变量：
#   PIP_INDEX_URL=...     构建时的 PyPI 镜像（默认腾讯云，适合腾讯云服务器）
#   SKIP_BACKUP=1         跳过数据库备份（不建议）
#   MIN_BUILD_FREE_MB / MIN_SWITCH_FREE_MB   构建/切换前要求的最小剩余磁盘（MB）
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/docker-compose.deploy.yml}"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
STATE_FILE="${ROOT_DIR}/.update-server.state"
BACKUP_DIR="${ROOT_DIR}/xianyu_auto_reply/backups/update-server"
LOCAL_REGISTRY="xianyu-local"
APP_SERVICES=(backend-web websocket scheduler frontend)
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.cloud.tencent.com/pypi/simple}"
FULL_BUILD="${FULL_BUILD:-0}"
OVERLAY_DOCKERFILE="docker/app-overlay.Dockerfile"
UPSTREAM_REGISTRY="registry.cn-shanghai.aliyuncs.com/zhinian-software"
if [[ "$FULL_BUILD" == 1 ]]; then MIN_BUILD_FREE_MB="${MIN_BUILD_FREE_MB:-3072}"; else MIN_BUILD_FREE_MB="${MIN_BUILD_FREE_MB:-1024}"; fi
MIN_SWITCH_FREE_MB="${MIN_SWITCH_FREE_MB:-1024}"
HEALTH_TIMEOUT_SEC="${HEALTH_TIMEOUT_SEC:-300}"

log(){ printf '[update-server] %s\n' "$*"; }
die(){ printf '[update-server] ERROR: %s\n' "$*" >&2; exit 1; }
compose(){ docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

dockerfile_for(){
  case "$1" in
    backend-web) echo backend-web/Dockerfile ;;
    websocket) echo websocket/Dockerfile ;;
    scheduler) echo scheduler/Dockerfile ;;
    frontend) echo nginx/Dockerfile ;;
    *) die "unknown service $1" ;;
  esac
}

env_get(){ awk -F= -v k="$1" '$1==k {v=substr($0,index($0,"=")+1)} END {print v}' "$ENV_FILE" | tr -d '\r'; }

# 写入/删除 .env 中的键（值为空则删除，让 compose 使用默认值）
env_set(){
  local key="$1" value="$2"
  if [[ -z "$value" ]]; then
    sed -i "/^${key}=/d" "$ENV_FILE"
  elif grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

free_mb(){ df --output=avail -BM / | tail -1 | tr -dc '0-9'; }

# 等待磁盘剩余空间达到要求（服务器上其他容器可能临时占满磁盘），超时失败
wait_disk(){
  local need="$1" waited=0
  while (( $(free_mb) < need )); do
    if (( waited == 0 )); then log "disk free $(free_mb)MB < ${need}MB, waiting..."; fi
    if (( waited >= 600 )); then die "disk free stayed below ${need}MB for 10 minutes; free some space and retry"; fi
    sleep 5; waited=$((waited + 5))
  done
}

container_of(){ compose ps -q "$1" 2>/dev/null | head -1; }

# 单次判断服务是否可用：有健康检查看 healthy，没有则看 running
service_ok(){
  local service="$1" cid="$2" state port
  if [[ "$service" == frontend ]]; then
    # 上游前端镜像的健康检查访问 localhost 会走 IPv6 而误报 unhealthy，这里直接访问对外端口
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)"
    [[ "$state" == running ]] || return 1
    port="$(env_get FRONTEND_PORT)"
    curl -fsS -m 5 -o /dev/null "http://127.0.0.1:${port:-9000}/"
    return
  fi
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
  [[ "$state" == healthy || "$state" == running ]]
}

# 等待服务可用，超时打印最近日志
wait_healthy(){
  local service="$1" deadline=$((SECONDS + HEALTH_TIMEOUT_SEC)) cid state
  while (( SECONDS < deadline )); do
    cid="$(container_of "$service")"
    if [[ -n "$cid" ]] && service_ok "$service" "$cid"; then return 0; fi
    sleep 5
  done
  if [[ -n "${cid:-}" ]]; then
    state="$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid" 2>/dev/null || true)"
  fi
  log "$service not healthy after ${HEALTH_TIMEOUT_SEC}s (state=${state:-missing}); last logs:"
  if [[ -n "${cid:-}" ]]; then docker logs --tail 30 "$cid" 2>&1 | sed 's/^/    /' || true; fi
  return 1
}

# 重建单个服务；磁盘瞬时占满导致 "no space left" 时重试
up_service(){
  local service="$1" attempt out
  for attempt in 1 2 3 4 5; do
    wait_disk "$MIN_SWITCH_FREE_MB"
    if out="$(compose up -d --no-deps "$service" 2>&1)"; then return 0; fi
    printf '%s\n' "$out" | tail -3 | sed 's/^/    /'
    grep -q "no space left" <<<"$out" || return 1
    log "no space left while starting $service, retry $attempt/5"; sleep 10
  done
  return 1
}

preflight(){
  cd "$ROOT_DIR"
  [[ -f "$COMPOSE_FILE" ]] || die "missing $COMPOSE_FILE (this script updates a deploy.sh installation)"
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 (docker compose) is required"
  git rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT_DIR is not a git checkout"
  exec 9>"${ROOT_DIR}/.update-server.lock"
  flock -n 9 || die "another update-server run is in progress"
}

image_exists(){ docker image inspect "$1" >/dev/null 2>&1; }

# 快速构建的底座：固定为 xianyu-local/xianyu-<服务>:deps，避免每次在上一次产物上继续叠层。
# 首次没有 :deps 时，依次取上次本仓库构建的 :latest、.env 当前配置的镜像、上游默认镜像，并打上 :deps 标签。
# 输出底座镜像名；找不到可用底座返回 1（调用方改为完整构建）。
deps_base_for(){
  local service="$1" deps cfg_registry cfg_tag candidate
  deps="${LOCAL_REGISTRY}/xianyu-${service}:deps"
  if image_exists "$deps"; then echo "$deps"; return 0; fi
  cfg_registry="$(env_get IMAGE_REGISTRY)"; cfg_tag="$(env_get IMAGE_TAG)"
  for candidate in \
    "${LOCAL_REGISTRY}/xianyu-${service}:latest" \
    "${cfg_registry:-$UPSTREAM_REGISTRY}/xianyu-${service}:${cfg_tag:-latest}" \
    "${UPSTREAM_REGISTRY}/xianyu-${service}:latest"; do
    if image_exists "$candidate"; then
      docker tag "$candidate" "$deps" || return 1
      printf '[update-server] fast-build base for %s: %s (tagged %s)\n' "$service" "$candidate" "$deps" >&2
      echo "$deps"; return 0
    fi
  done
  return 1
}

build_images(){
  local sha="$1" service file base
  if [[ -n "$(git status --porcelain --untracked-files=no -- backend-web websocket scheduler common launcher frontend nginx docker)" ]]; then
    log "WARNING: tracked source files have local changes; they will be built into the images"
  fi
  for service in "${APP_SERVICES[@]}"; do
    local target="${LOCAL_REGISTRY}/xianyu-${service}"
    if image_exists "${target}:${sha}"; then
      log "image xianyu-${service}:${sha} already built, skip"; continue
    fi
    wait_disk "$MIN_BUILD_FREE_MB"
    local args=()
    if [[ "$service" != frontend ]]; then
      args=(--build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" --build-arg PIP_DEFAULT_TIMEOUT=180)
    fi
    if [[ "$service" != frontend && "$FULL_BUILD" != 1 ]] && base="$(deps_base_for "$service")"; then
      log "fast build $service @ $sha on $base (source only, no apt / browser download)"
      DOCKER_BUILDKIT=1 docker build "${args[@]}" --build-arg "BASE_IMAGE=${base}" --build-arg "SERVICE=${service}" \
        -f "$OVERLAY_DOCKERFILE" -t "${target}:${sha}" -t "${target}:latest" . \
        || die "build failed for $service; running services were not touched (re-run to resume, or FULL_BUILD=1)"
      continue
    fi
    file="$(dockerfile_for "$service")"
    log "full build $service from $file @ $sha"
    DOCKER_BUILDKIT=1 docker build ${args[@]+"${args[@]}"} -f "$file" -t "${target}:${sha}" -t "${target}:latest" . \
      || die "build failed for $service; running services were not touched (re-run to resume)"
    # 完整构建产物包含最新的系统依赖与浏览器，作为后续快速构建的底座
    if [[ "$service" != frontend ]]; then docker tag "${target}:${sha}" "${target}:deps"; fi
  done
}

backup_db(){
  if [[ "${SKIP_BACKUP:-0}" == 1 ]]; then log "SKIP_BACKUP=1, database backup skipped"; return 0; fi
  local cid file err
  cid="$(container_of mysql)"
  [[ -n "$cid" ]] || die "mysql container not found; refusing to switch without a backup"
  mkdir -p "$BACKUP_DIR"
  file="${BACKUP_DIR}/mysql-$(date +%Y%m%d%H%M%S).sql.gz"
  err="$(mktemp)"
  wait_disk "$MIN_SWITCH_FREE_MB"
  if ! docker exec "$cid" sh -c 'exec mysqldump --single-transaction --routines --triggers --all-databases -uroot -p"$MYSQL_ROOT_PASSWORD"' 2>"$err" | gzip -c > "$file"; then
    grep -v "Using a password" "$err" | tail -5 >&2 || true
    rm -f "$file" "$err"; die "database backup failed; nothing was switched"
  fi
  rm -f "$err"
  zcat "$file" | tail -1 | grep -q "Dump completed" || { rm -f "$file"; die "database backup is incomplete; nothing was switched"; }
  log "database backup: $file ($(du -h "$file" | cut -f1))"
}

# 把四个业务服务切到指定镜像（registry/tag 为空表示使用 compose 默认的上游镜像）
switch_to(){
  local registry="$1" tag="$2" service
  env_set IMAGE_REGISTRY "$registry"
  env_set IMAGE_TAG "$tag"
  for service in "${APP_SERVICES[@]}"; do
    log "starting $service with ${registry:-<default>}/xianyu-${service}:${tag:-<default>}"
    up_service "$service" || return 1
    wait_healthy "$service" || return 1
  done
}

rollback(){
  [[ -f "$STATE_FILE" ]] || die "no previous image recorded in $STATE_FILE"
  local prev_registry prev_tag
  prev_registry="$(awk -F= '$1=="PREV_IMAGE_REGISTRY"{print substr($0,index($0,"=")+1)}' "$STATE_FILE")"
  prev_tag="$(awk -F= '$1=="PREV_IMAGE_TAG"{print substr($0,index($0,"=")+1)}' "$STATE_FILE")"
  log "rolling back to ${prev_registry:-<default>}/*:${prev_tag:-<default>}"
  SWITCHING=0
  switch_to "$prev_registry" "$prev_tag" || die "rollback did not become healthy; check: docker compose -f $COMPOSE_FILE ps"
  log "rollback finished"
}

status(){
  cd "$ROOT_DIR"
  log "repo HEAD $(git rev-parse --short HEAD); IMAGE_REGISTRY=$(env_get IMAGE_REGISTRY) IMAGE_TAG=$(env_get IMAGE_TAG)"
  compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
  log "disk free $(free_mb)MB"
}

update(){
  local sha cur_registry cur_tag
  sha="$(git rev-parse --short HEAD)"
  build_images "$sha"
  cur_registry="$(env_get IMAGE_REGISTRY)"
  cur_tag="$(env_get IMAGE_TAG)"
  backup_db
  cp -p "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
  # 记录切换前镜像供回滚；重复更新到当前已运行的同一版本时不覆盖记录，避免回滚目标变成自己
  if [[ "$cur_registry" != "$LOCAL_REGISTRY" || ! -f "$STATE_FILE" || "$cur_tag" != "$sha" ]]; then
    printf 'PREV_IMAGE_REGISTRY=%s\nPREV_IMAGE_TAG=%s\nUPDATED_TO=%s\n' "$cur_registry" "$cur_tag" "$sha" > "$STATE_FILE"
  fi
  SWITCHING=1
  if ! switch_to "$LOCAL_REGISTRY" "$sha"; then
    log "switch failed, rolling back automatically"
    rollback
    die "update to $sha failed and was rolled back; see logs above"
  fi
  SWITCHING=0
  log "update finished: all services on ${LOCAL_REGISTRY}/*:${sha}"
  docker builder prune -f >/dev/null 2>&1 && log "build cache pruned" || true
  status
  log "previous images are kept for rollback; keep the xianyu-local/*:deps images (fast-build bases) when cleaning up"
}

SWITCHING=0
on_exit(){
  local rc=$?
  if (( rc != 0 && SWITCHING == 1 )); then
    printf '[update-server] interrupted during switch; restore previous images with: bash scripts/update-server.sh rollback\n' >&2
  fi
}

main(){
  trap on_exit EXIT
  preflight
  case "${1:-update}" in
    update) update ;;
    rollback) rollback ;;
    status) status ;;
    *) die "usage: bash scripts/update-server.sh [update|rollback|status]" ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
