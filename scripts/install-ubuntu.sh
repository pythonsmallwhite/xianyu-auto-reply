#!/usr/bin/env bash
# Ubuntu 24.04 一键安装：安装 Docker 等依赖 → 生成配置 → 从本仓库源码构建镜像 → 启动并健康检查。
#
# 用法（root 或 sudo，在仓库根目录）：
#   sudo bash scripts/install-ubuntu.sh --port 80
#   sudo bash scripts/install-ubuntu.sh --port 80 --import /root/xianyu-export-XXXX.tar.gz   # 导入旧服务器数据
# 之后更新代码：git pull && sudo bash scripts/deploy-ubuntu.sh update
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${XIAN_YU_DEPLOY_DIR:-${ROOT_DIR}/.ubuntu-deploy}"
ENV_FILE="${XIAN_YU_ENV_FILE:-${STATE_DIR}/.env}"
PORT="80"
PUBLIC_URL=""
IMPORT=""
PIP_INDEX="https://mirrors.cloud.tencent.com/pypi/simple"
SWAP=1
REGISTRY_MIRROR=1
TMP_DIR=""

log(){ printf '[install-ubuntu] %s\n' "$*"; }
die(){ printf '[install-ubuntu] ERROR: %s\n' "$*" >&2; exit 1; }
cleanup(){ [[ -n "$TMP_DIR" ]] && rm -rf "$TMP_DIR"; return 0; }
trap cleanup EXIT
usage(){
  cat <<'EOF'
Usage: sudo bash scripts/install-ubuntu.sh [options]

  --port N           Public HTTP port for the web UI (default 80)
  --public-url URL   Public base URL, e.g. http://1.2.3.4 (used in generated links; optional)
  --import PATH      Import data exported by scripts/export-for-migration.sh
                     (a .tar.gz bundle or its extracted directory); only into an empty
                     database. Re-running the same command after a failure is safe.
  --pip-index URL    PyPI mirror for image builds (default: Tencent Cloud mirror)
  --no-swap          Do not create a swap file on small-memory servers
  --no-registry-mirror  Do not configure Docker Hub mirrors
  -h, --help         Show this help

Options --port/--public-url/--pip-index only apply on the first install; afterwards
edit .ubuntu-deploy/.env and run: sudo bash scripts/deploy-ubuntu.sh update
EOF
}
parse_args(){
  while (($#)); do
    case "$1" in
      --port) PORT="${2:-}"; shift ;;
      --public-url) PUBLIC_URL="${2:-}"; shift ;;
      --import) IMPORT="${2:-}"; shift ;;
      --pip-index) PIP_INDEX="${2:-}"; shift ;;
      --no-swap) SWAP=0 ;;
      --no-registry-mirror) REGISTRY_MIRROR=0 ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "unknown option: $1" ;;
    esac
    shift
  done
  [[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]] || die "invalid --port: $PORT"
  if [[ -n "$PUBLIC_URL" && ! "$PUBLIC_URL" =~ ^https?:// ]]; then die "--public-url must start with http:// or https://"; fi
  PUBLIC_URL="${PUBLIC_URL%/}"
}
check_os(){
  [[ -r /etc/os-release ]] || die "cannot identify operating system"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == ubuntu ]] || die "Ubuntu is required (found ${ID:-unknown})"
  if [[ "${VERSION_ID:-}" != 24.04 ]]; then log "WARNING: tested for Ubuntu 24.04, found ${VERSION_ID:-unknown}; continuing"; fi
  local free_kb; free_kb="$(df -Pk "$ROOT_DIR" | awk 'NR==2{print $4}')"
  [[ "$free_kb" =~ ^[0-9]+$ && "$free_kb" -ge 15728640 ]] || die "at least 15 GiB free disk is required (images + build cache + data)"
}
# 小内存服务器构建三个 Python 镜像时容易内存不足：内存 < 4GB 且无 swap 时创建 2GB swap
ensure_swap(){
  (( SWAP )) || return 0
  local mem_kb; mem_kb="$(awk '/^MemTotal:/{print $2}' /proc/meminfo)"
  if (( mem_kb >= 4000000 )) || [[ -n "$(swapon --noheadings 2>/dev/null)" ]]; then return 0; fi
  if [[ -e /swapfile ]]; then log "/swapfile exists but is not active; leaving it unchanged"; return 0; fi
  log "memory $((mem_kb / 1024))MB and no swap: creating 2GB /swapfile"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
}
# 解析导入数据：支持 export-for-migration.sh 生成的 .tar.gz 或其解压目录
prepare_import(){
  [[ -n "$IMPORT" ]] || return 0
  [[ -e "$IMPORT" ]] || die "--import path not found: $IMPORT"
  # 是否允许导入由 deploy-ubuntu.sh 判断：空库才导入；同一数据包已导入过则跳过（首装中途失败可原样重跑）
  local dir found
  if [[ -d "$IMPORT" ]]; then
    dir="$(cd "$IMPORT" && pwd)"
  else
    TMP_DIR="$(mktemp -d)"; chmod 700 "$TMP_DIR"
    tar -xzf "$IMPORT" -C "$TMP_DIR" || die "cannot extract $IMPORT"
    dir="$TMP_DIR"
  fi
  found="$(find "$dir" -maxdepth 2 -name database.sql.gz -print -quit)"
  [[ -n "$found" ]] || die "database.sql.gz not found in $IMPORT"
  IMPORT_DIR="$(dirname "$found")"
  gzip -t "$IMPORT_DIR/database.sql.gz" || die "database.sql.gz is corrupted"
  log "will import data from $IMPORT_DIR"
}
summary(){
  local port url
  port="$(awk -F= '$1=="PUBLIC_HTTP_PORT"{print $2}' "$ENV_FILE")"
  url="$(awk -F= '$1=="FRONTEND_PUBLIC_URL"{print substr($0,index($0,"=")+1)}' "$ENV_FILE")"
  [[ -n "$url" ]] || url="http://<服务器公网IP>$([[ "$port" == 80 ]] || printf ':%s' "$port")"
  cat <<EOF

========================================================================
部署完成：$url
  - 云服务器安全组需放行 TCP ${port}（MySQL/Redis 未对外开放）
  - 未导入旧数据时默认管理员为 admin / admin123，请登录后立即修改密码
  - 配置与密码保存在 ${ENV_FILE}（仅 root 可读，请勿外传）
常用命令（在 ${ROOT_DIR} 下执行）：
  更新：git pull && sudo bash scripts/deploy-ubuntu.sh update
  状态：sudo bash scripts/deploy-ubuntu.sh status
  日志：sudo bash scripts/deploy-ubuntu.sh logs
  回滚：sudo bash scripts/deploy-ubuntu.sh rollback
  备份：sudo bash scripts/deploy-ubuntu.sh backup
========================================================================
EOF
}
main(){
  parse_args "$@"
  if (( EUID != 0 )); then
    command -v sudo >/dev/null 2>&1 || die "run as root or install sudo"
    exec sudo -E bash "$0" "$@"
  fi
  check_os
  ensure_swap
  local bootstrap_args=(--no-group)
  (( REGISTRY_MIRROR )) || bootstrap_args+=(--no-registry-mirror)
  bash "$ROOT_DIR/scripts/bootstrap-ubuntu.sh" "${bootstrap_args[@]}"
  IMPORT_DIR=""
  prepare_import
  if [[ -f "$ENV_FILE" ]]; then
    log "existing configuration $ENV_FILE is kept; --port/--public-url/--pip-index are ignored"
  fi
  log "building images and starting services (first build takes 20-40 minutes)"
  XY_PUBLIC_HTTP_PORT="$PORT" XY_PUBLIC_URL="$PUBLIC_URL" XY_PIP_INDEX_URL="$PIP_INDEX" IMPORT_DIR="$IMPORT_DIR" \
    bash "$ROOT_DIR/scripts/deploy-ubuntu.sh" deploy
  summary
}
main "$@"
