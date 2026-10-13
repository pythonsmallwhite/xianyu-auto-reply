#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="/var/lock/xianyu-auto-reply-bootstrap.lock"
DRY_RUN=0
SKIP_DOCKER=0
NO_GROUP=0
NO_REGISTRY_MIRROR=0
INVOKING_USER="${SUDO_USER:-${USER:-}}"
# docker-ce apt 源候选（依次探测，第一个可访问的生效），可用环境变量覆盖
DOCKER_APT_MIRRORS="${DOCKER_APT_MIRRORS:-https://mirrors.cloud.tencent.com/docker-ce/linux/ubuntu https://mirrors.aliyun.com/docker-ce/linux/ubuntu https://download.docker.com/linux/ubuntu}"
# Docker Hub 镜像加速（写入 /etc/docker/daemon.json），可用环境变量覆盖
REGISTRY_MIRRORS="${REGISTRY_MIRRORS:-https://mirror.ccs.tencentyun.com https://docker.m.daocloud.io https://docker.1panel.live https://hub.rat.dev}"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a

log(){ printf '[ubuntu-bootstrap] %s\n' "$*"; }
die(){ printf '[ubuntu-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }
usage(){
  cat <<'EOF'
Usage: sudo ./scripts/bootstrap-ubuntu.sh [options]

Install Ubuntu host prerequisites for this repository. This script does not
start project containers, create application credentials, migrate databases,
or deploy the application.

Options:
  --dry-run              Print intended actions without changing the host.
  --skip-docker          Install base tools but leave Docker unchanged.
  --no-group             Do not add the invoking user to the docker group.
  --no-registry-mirror   Do not write /etc/docker/daemon.json registry mirrors.
  -h, --help             Show this help.

Environment overrides: DOCKER_APT_MIRRORS, REGISTRY_MIRRORS (space separated).
EOF
}
run_root(){
  if (( DRY_RUN )); then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  elif (( EUID == 0 )); then
    "$@"
  else
    sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a "$@"
  fi
}
root_shell(){
  if (( DRY_RUN )); then
    printf '+ %s\n' "$*"
  elif (( EUID == 0 )); then
    bash -c "$*"
  else
    sudo bash -c "$*"
  fi
}
require_command(){ command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
check_platform(){
  [[ "$(uname -s)" == "Linux" ]] || die "Ubuntu/Linux is required"
  [[ -r /etc/os-release ]] || die "cannot identify operating system"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" || "${ID_LIKE:-}" == *ubuntu* ]] || die "Ubuntu is required"
  case "$(uname -m)" in
    x86_64|aarch64|arm64) ;;
    *) die "unsupported architecture: $(uname -m)" ;;
  esac
}
check_privileges(){
  if (( EUID != 0 )); then
    require_command sudo
    sudo -v
  fi
}
install_base_tools(){
  log "installing Ubuntu base tools"
  run_root apt-get update
  run_root apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release git openssl util-linux iproute2 gzip tar jq
}
docker_ready(){
  command -v docker >/dev/null 2>&1 &&
    docker compose version >/dev/null 2>&1 &&
    return 0
  return 1
}
# 按顺序探测可用的 docker-ce apt 源；国内服务器访问官方源经常很慢或超时
pick_docker_repo(){
  local codename="$1" base
  for base in ${DOCKER_APT_MIRRORS}; do
    if curl -fsS -m 10 -o /dev/null "${base}/dists/${codename}/Release"; then
      printf '%s\n' "$base"; return 0
    fi
  done
  return 1
}
install_docker_ce(){
  local arch codename base
  arch="$(dpkg --print-architecture)"
  # shellcheck disable=SC1091
  source /etc/os-release
  codename="${VERSION_CODENAME:-}"
  [[ -n "$codename" ]] || die "cannot determine Ubuntu codename"
  if (( DRY_RUN )); then
    printf '+ pick a reachable docker-ce repository from: %s\n' "$DOCKER_APT_MIRRORS"
    printf '+ download Docker signing key, configure apt repository, install docker-ce\n'
    return 0
  fi
  base="$(pick_docker_repo "$codename")" || return 1
  log "using docker-ce repository $base"
  run_root install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "${base}/gpg" | gpg --dearmor | run_root tee /etc/apt/keyrings/docker.gpg >/dev/null
  run_root chmod a+r /etc/apt/keyrings/docker.gpg
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] %s %s stable\n' "$arch" "$base" "$codename" | \
    run_root tee /etc/apt/sources.list.d/docker.list >/dev/null
  run_root apt-get update
  run_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}
# 镜像加速与容器日志轮转；已有 daemon.json 时不覆盖
configure_docker_daemon(){
  (( NO_REGISTRY_MIRROR )) && { log "skipping registry mirror configuration by request"; return 0; }
  if [[ -f /etc/docker/daemon.json ]]; then
    log "/etc/docker/daemon.json already exists; left unchanged"
    return 0
  fi
  local mirrors json
  mirrors="$(printf '"%s",' ${REGISTRY_MIRRORS})"; mirrors="[${mirrors%,}]"
  json="$(printf '{\n  "registry-mirrors": %s,\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "50m", "max-file": "3"}\n}\n' "$mirrors")"
  if (( DRY_RUN )); then printf '+ write /etc/docker/daemon.json:\n%s\n' "$json"; return 0; fi
  run_root install -m 0755 -d /etc/docker
  printf '%s' "$json" | run_root tee /etc/docker/daemon.json >/dev/null
  run_root systemctl restart docker
  log "configured Docker registry mirrors and log rotation"
}
install_docker(){
  (( SKIP_DOCKER )) && { log "skipping Docker by request"; return; }
  if docker_ready; then
    log "Docker Engine and Compose plugin already available"
  else
    log "installing Docker Engine and Compose plugin"
    if ! install_docker_ce; then
      log "no docker-ce repository reachable; falling back to Ubuntu docker.io packages"
      run_root apt-get install -y docker.io docker-compose-v2 docker-buildx
    fi
  fi
  if (( ! DRY_RUN )); then
    run_root systemctl enable --now docker
    configure_docker_daemon
    docker info >/dev/null 2>&1 || die "Docker daemon is not reachable after installation"
    docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is not available after installation"
  else
    configure_docker_daemon
  fi
  if (( ! NO_GROUP && EUID != 0 && -n "$INVOKING_USER" && "$INVOKING_USER" != "root" )); then
    run_root groupadd --force docker
    run_root usermod -aG docker "$INVOKING_USER"
    log "added $INVOKING_USER to docker group; open a new login shell before using docker without sudo"
  fi
}
main(){
  while (($#)); do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --skip-docker) SKIP_DOCKER=1 ;;
      --no-group) NO_GROUP=1 ;;
      --no-registry-mirror) NO_REGISTRY_MIRROR=1 ;;
      -h|--help) usage; return 0 ;;
      *) usage >&2; die "unknown option: $1" ;;
    esac
    shift
  done
  check_platform
  check_privileges
  if (( EUID == 0 && ! DRY_RUN )); then
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "another bootstrap process is running"
  fi
  install_base_tools
  install_docker
  log "bootstrap complete; no project containers were started"
  log "next step: ./scripts/deploy-ubuntu.sh deploy"
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
