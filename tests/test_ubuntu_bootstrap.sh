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
check "official repository is a candidate" contains 'https://download.docker.com/linux/ubuntu' "$SCRIPT"
check "domestic docker-ce mirror tried first" bash -c "grep -Eq 'DOCKER_APT_MIRRORS=.*mirrors\\.cloud\\.tencent\\.com/docker-ce.*download\\.docker\\.com' '$SCRIPT'"
check "repository key fetched from chosen mirror" contains 'curl -fsSL "${base}/gpg"' "$SCRIPT"
check "falls back to Ubuntu docker.io packages" contains 'docker.io docker-compose-v2 docker-buildx' "$SCRIPT"
check "registry mirrors configured" contains '"registry-mirrors"' "$SCRIPT"
check "container log rotation" contains '"max-size": "50m"' "$SCRIPT"
check "existing daemon.json preserved" contains '/etc/docker/daemon.json already exists; left unchanged' "$SCRIPT"
check "non-interactive apt" contains 'DEBIAN_FRONTEND=noninteractive' "$SCRIPT"
daemon_json="$(REGISTRY_MIRRORS='https://a.example https://b.example' bash -c "source '$SCRIPT'; DRY_RUN=1; configure_docker_daemon" 2>&1)"
check "dry-run daemon.json lists mirrors in order" bash -c "printf '%s' '$daemon_json' | grep -q '\"registry-mirrors\": \[\"https://a.example\",\"https://b.example\"\]'"
check "dry-run daemon.json is valid JSON" bash -c "printf '%s' '$daemon_json' | sed '1d' | node -e 'JSON.parse(require(\"fs\").readFileSync(0,\"utf8\"))' 2>/dev/null || printf '%s' '$daemon_json' | sed '1d' | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null || printf '%s' '$daemon_json' | sed '1d' | py -3 -c 'import json,sys; json.load(sys.stdin)'"
picked="$(bash -c "source '$SCRIPT'; curl(){ [[ \"\$*\" == *b.example* ]]; }; DOCKER_APT_MIRRORS='https://a.example https://b.example https://c.example'; pick_docker_repo noble")"
check "first reachable docker-ce mirror is chosen" test "$picked" = "https://b.example"
check "no reachable docker-ce mirror returns failure" bash -c "source '$SCRIPT'; curl(){ return 7; }; DOCKER_APT_MIRRORS='https://a.example'; ! pick_docker_repo noble"
check "no project startup" bash -c "! grep -Eq '^[[:space:]]*(bash|sh|\\./|exec).*deploy-ubuntu' '$SCRIPT'"
check "no application credentials" bash -c "! grep -Eq 'MYSQL_ROOT_PASSWORD|INTERNAL_API_TOKEN|REDIS_PASSWORD' '$SCRIPT'"
check "no destructive volume command" bash -c "! grep -Eq 'down[[:space:]]+(-v|--volumes)' '$SCRIPT'"
check "shell syntax" bash -n "$SCRIPT"
(( failures == 0 ))
