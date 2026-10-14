#!/usr/bin/env bash
# 重装系统前在旧服务器导出数据（适用于 deploy.sh / update-server.sh 部署的 docker-compose.deploy.yml）。
# 导出：业务数据库（单库，不含 mysql 系统库）、static 上传文件、browser_data 浏览器数据，打包为一个 .tar.gz。
# 用法（仓库根目录）：bash scripts/export-for-migration.sh            # 在线导出（InnoDB 一致性快照）
#                     bash scripts/export-for-migration.sh --stop     # 先停业务容器再导出，导出后恢复
# 产物含账号 Cookie 等敏感数据：只保存在自己的电脑/服务器，重装前务必下载到本地。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/docker-compose.deploy.yml}"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
DATA_DIR="${DATA_DIR:-${ROOT_DIR}/xianyu_auto_reply}"
OUT_ROOT="${OUT_ROOT:-${ROOT_DIR}/migration-export}"
APP_SERVICES=(backend-web websocket scheduler frontend)
STOP=0
STOPPED=0
# 旧版 deploy.sh 固定使用此 compose 项目名（与目录名无关）
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-xianyu-auto-reply}"

log(){ printf '[export] %s\n' "$*"; }
die(){ printf '[export] ERROR: %s\n' "$*" >&2; exit 1; }
compose(){ docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }
restart_apps(){ if (( STOPPED )); then log "starting application containers again"; compose start "${APP_SERVICES[@]}" >/dev/null 2>&1 || true; fi; }
trap restart_apps EXIT

case "${1:-}" in
  "") ;;
  --stop) STOP=1 ;;
  -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
  *) die "unknown option: $1" ;;
esac

cd "$ROOT_DIR"
mysql_cid=""
if [[ -f "$COMPOSE_FILE" ]]; then mysql_cid="$(compose ps -q mysql 2>/dev/null | head -1 || true)"; fi
[[ -n "$mysql_cid" ]] || mysql_cid="$(docker ps -q --filter name='^xianyu-mysql$' | head -1)"
[[ -n "$mysql_cid" ]] || die "running MySQL container not found (expected xianyu-mysql)"
db="$(docker exec "$mysql_cid" sh -c 'printf %s "$MYSQL_DATABASE"')"
[[ -n "$db" ]] || die "MYSQL_DATABASE is not set in the MySQL container"

stamp="$(date +%Y%m%d%H%M%S)"
name="xianyu-export-${stamp}"
out="${OUT_ROOT}/${name}"
umask 077
mkdir -p "$out"

if (( STOP )); then
  log "stopping application containers for a fully quiet export"
  compose stop "${APP_SERVICES[@]}" >/dev/null 2>&1 || true
  STOPPED=1
fi

log "dumping database '$db'"
err="$(mktemp)"
if ! docker exec "$mysql_cid" sh -c 'exec mysqldump --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' 2>"$err" | gzip -c > "$out/database.sql.gz"; then
  grep -v "Using a password" "$err" >&2 || true; rm -f "$err"; die "mysqldump failed"
fi
rm -f "$err"
zcat "$out/database.sql.gz" | tail -1 | grep -q "Dump completed" || die "database dump is incomplete"
tables="$(zcat "$out/database.sql.gz" | grep -c '^CREATE TABLE' || true)"
log "database dump ok: ${tables} tables"

if [[ -d "$DATA_DIR/static" ]]; then
  tar -C "$DATA_DIR/static" -czf "$out/static.tar.gz" .
  log "static files: $(du -sh "$DATA_DIR/static" | cut -f1)"
fi
if [[ -d "$DATA_DIR/browser_data" ]] && [[ -n "$(ls -A "$DATA_DIR/browser_data" 2>/dev/null)" ]]; then
  tar -C "$DATA_DIR/browser_data" -czf "$out/browser_data.tar.gz" .
  log "browser data: $(du -sh "$DATA_DIR/browser_data" | cut -f1)"
fi

commit="$(cd "$ROOT_DIR" && git rev-parse --short HEAD 2>/dev/null || printf unknown)"
printf 'source=%s\ncreated_at=%s\ndatabase=%s\ntables=%s\nrepo_commit=%s\n' \
  "$(hostname)" "$(date '+%F %T %z')" "$db" "$tables" "$commit" > "$out/manifest"

restart_apps; STOPPED=0
tar -C "$OUT_ROOT" -czf "${OUT_ROOT}/${name}.tar.gz" "$name"
rm -rf "$out"
bundle="${OUT_ROOT}/${name}.tar.gz"
log "export bundle: $bundle ($(du -h "$bundle" | cut -f1))"
# 供根目录 deploy.sh 自动迁移时读取导出路径
if [[ -n "${EXPORT_PATH_FILE:-}" ]]; then printf '%s\n' "$bundle" > "$EXPORT_PATH_FILE"; fi
if [[ -n "${EXPORT_QUIET:-}" ]]; then exit 0; fi
cat <<EOF

下一步：重装前把文件下载到本地（在你自己的电脑上执行）：
  scp root@<旧服务器IP>:${bundle} .
重装 Ubuntu 24.04 后上传到新服务器并导入：
  scp ${name}.tar.gz root@<新服务器IP>:/root/
  sudo bash scripts/install-ubuntu.sh --port 80 --import /root/${name}.tar.gz
EOF
