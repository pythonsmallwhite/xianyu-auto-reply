#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/bootstrap-ubuntu.sh"
failures=0
check(){ local name="$1"; shift; if "$@"; then printf 'ok - %s\n' "$name"; else printf 'not ok - %s\n' "$name"; failures=$((failures+1)); fi; }
contains(){ grep -Fq -- "$1" "$2"; }
check "strict shell mode" contains 'set -Eeuo pipefail' "$SCRIPT"
check "dry-run option" contains '--dry-run' "$SCRIPT"
check "skip docker option" contains '--skip-docker' "$SCRIPT"
check "base packages" bash -c "grep -Eq 'ca-certificates.*curl.*gnupg.*git.*openssl' '$SCRIPT'"
check "docker engine packages" bash -c "grep -Eq 'docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin' '$SCRIPT'"
check "docker compose check" contains 'docker compose version' "$SCRIPT"
check "daemon enable" contains 'systemctl enable --now docker' "$SCRIPT"
check "docker group support" contains 'usermod -aG docker' "$SCRIPT"
check "official repository key" contains 'download.docker.com/linux/ubuntu/gpg' "$SCRIPT"
check "no project startup" bash -c "! grep -Eq '^[[:space:]]*(bash|sh|\\./|exec).*deploy-ubuntu' '$SCRIPT'"
check "no application credentials" bash -c "! grep -Eq 'MYSQL_ROOT_PASSWORD|INTERNAL_API_TOKEN|REDIS_PASSWORD' '$SCRIPT'"
check "no destructive volume command" bash -c "! grep -Eq 'down[[:space:]]+(-v|--volumes)' '$SCRIPT'"
check "shell syntax" bash -n "$SCRIPT"
(( failures == 0 ))
