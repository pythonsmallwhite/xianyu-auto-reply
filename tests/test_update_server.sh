#!/usr/bin/env bash
# Static contract + sandboxed function tests for scripts/update-server.sh (no Docker required).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/update-server.sh"
failures=0
check(){ local name="$1"; shift; if "$@"; then printf 'ok - %s\n' "$name"; else printf 'not ok - %s\n' "$name"; failures=$((failures+1)); fi; }
contains(){ grep -Fq -- "$1" "$2"; }
order(){ awk -v a="$1" -v b="$2" 'index($0,a)&&!x{x=NR} index($0,b)&&!y{y=NR} END{exit !(x&&y&&x<y)}' "$3"; }

check "shell syntax" bash -n "$SCRIPT"
check "strict shell mode" contains 'set -Eeuo pipefail' "$SCRIPT"
check "single-run lock" contains 'flock -n 9' "$SCRIPT"
check "builds from repo Dockerfiles" bash -c "grep -Fq 'echo backend-web/Dockerfile' '$SCRIPT' && grep -Fq 'echo nginx/Dockerfile' '$SCRIPT'"
check "local image namespace" contains 'LOCAL_REGISTRY="xianyu-local"' "$SCRIPT"
check "skips already built images" contains 'already built, skip' "$SCRIPT"
check "build happens before backup" order 'build_images "$sha"' '  backup_db' "$SCRIPT"
check "backup happens before switch" order '  backup_db' 'switch_to "$LOCAL_REGISTRY" "$sha"' "$SCRIPT"
check "backup completeness verified" contains 'grep -q "Dump completed"' "$SCRIPT"
check "env backed up before switch" order 'cp -p "$ENV_FILE"' 'switch_to "$LOCAL_REGISTRY" "$sha"' "$SCRIPT"
check "failed switch rolls back" bash -c "grep -A3 'if ! switch_to \"\$LOCAL_REGISTRY\"' '$SCRIPT' | grep -q rollback"
check "mysql and redis untouched" bash -c "grep -Eq '^APP_SERVICES=\(backend-web websocket scheduler frontend\)$' '$SCRIPT'"
check "no volume removal" bash -c "! grep -Eq 'down -v|volume rm|rm -rf .*mysql' '$SCRIPT'"
check "waits for disk space" contains 'wait_disk "$MIN_BUILD_FREE_MB"' "$SCRIPT"

# Sandboxed function tests: source the script (main is guarded) against a temp .env.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
printf 'FRONTEND_PORT=9000\r\nIMAGE_REGISTRY=registry.example.com/up\nIMAGE_TAG=latest\nOTHER=1\n' > "$tmp/.env"
result="$(ENV_FILE="$tmp/.env" bash -c '
  source "'"$SCRIPT"'"
  env_set IMAGE_REGISTRY xianyu-local
  env_set IMAGE_TAG abc1234
  env_set NEW_KEY v
  printf "%s|%s|%s|%s\n" "$(env_get IMAGE_REGISTRY)" "$(env_get IMAGE_TAG)" "$(env_get NEW_KEY)" "$(env_get FRONTEND_PORT)"
  env_set IMAGE_TAG ""
  grep -c "^IMAGE_TAG=" "$ENV_FILE" || true
')"
check "env_set/env_get update, append and CRLF-safe read" test "$(printf '%s' "$result" | head -1)" = "xianyu-local|abc1234|v|9000"
check "env_set with empty value deletes key" test "$(printf '%s' "$result" | tail -1)" = "0"
check "other keys preserved" grep -q '^OTHER=1$' "$tmp/.env"
check "dockerfile_for maps frontend" test "$(bash -c 'source "'"$SCRIPT"'"; dockerfile_for frontend')" = "nginx/Dockerfile"

if (( failures )); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
echo "all update-server checks passed"
