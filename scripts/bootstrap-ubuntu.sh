#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="/var/lock/xianyu-auto-reply-bootstrap.lock"
DRY_RUN=0
SKIP_DOCKER=0
NO_GROUP=0
INVOKING_USER="${SUDO_USER:-${USER:-}}"

log(){ printf '[ubuntu-bootstrap] %s\n' "$*"; }
die(){ printf '[ubuntu-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }
usage(){
  cat <<'EOF'
Usage: sudo ./scripts/bootstrap-ubuntu.sh [options]

Install Ubuntu host prerequisites for this repository. This script does not
start project containers, create application credentials, migrate databases,
or deploy the application.

Options:
  --dry-run       Print intended actions without changing the host.
  --skip-docker   Install base tools but leave Docker unchanged.
  --no-group      Do not add the invoking user to the docker group.
  -h, --help      Show this help.
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
    sudo "$@"
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
install_docker(){
  (( SKIP_DOCKER )) && { log "skipping Docker by request"; return; }
  if docker_ready; then
    log "Docker Engine and Compose plugin already available"
  else
    log "installing Docker Engine and Compose plugin"
    local arch codename
    arch="$(dpkg --print-architecture)"
    # shellcheck disable=SC1091
    source /etc/os-release
    codename="${VERSION_CODENAME:-}"
    [[ -n "$codename" ]] || die "cannot determine Ubuntu codename"
    run_root install -m 0755 -d /etc/apt/keyrings
    if (( DRY_RUN )); then
      printf '+ download Docker signing key and configure the official apt repository\n'
    else
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor | run_root tee /etc/apt/keyrings/docker.gpg >/dev/null
      run_root chmod a+r /etc/apt/keyrings/docker.gpg
      printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' "$arch" "$codename" | \
        run_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    fi
    run_root apt-get update
    run_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  if (( ! DRY_RUN )); then
    run_root systemctl enable --now docker
    docker info >/dev/null 2>&1 || die "Docker daemon is not reachable after installation"
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
main "$@"
