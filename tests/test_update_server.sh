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
OVERLAY="$ROOT/docker/app-overlay.Dockerfile"
check "fast build is the default" contains 'FULL_BUILD="${FULL_BUILD:-0}"' "$SCRIPT"
check "fast build uses overlay Dockerfile" contains 'OVERLAY_DOCKERFILE="docker/app-overlay.Dockerfile"' "$SCRIPT"
check "overlay never runs apt" bash -c "! grep -q 'apt-get' '$OVERLAY'"
check "overlay removes old source before copying" order 'rm -rf /app/common' 'COPY common /app/common' "$OVERLAY"
check "overlay installs new python deps" contains 'pip install --no-cache-dir -r /tmp/requirements.txt' "$OVERLAY"
check "full build refreshes deps base" contains 'docker tag "${target}:${sha}" "${target}:deps"' "$SCRIPT"

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

# deps_base_for with a stub docker: images listed in $tmp/images exist; `docker tag a b` adds b.
mkdir -p "$tmp/bin"
cat > "$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  image) grep -qxF "$3" "$STUB_IMAGES" ;;
  tag) echo "$3" >> "$STUB_IMAGES"; echo "tag $2 -> $3" >> "$STUB_IMAGES.log" ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$tmp/bin/docker"
base_case(){  # $1 = images present (space separated); prints chosen base and tag log
  printf '%s\n' $1 > "$tmp/images"; : > "$tmp/images.log"
  printf 'IMAGE_REGISTRY=registry.example.com/up\nIMAGE_TAG=latest\n' > "$tmp/.env"
  PATH="$tmp/bin:$PATH" STUB_IMAGES="$tmp/images" ENV_FILE="$tmp/.env" bash -c 'source "'"$SCRIPT"'"; deps_base_for backend-web' 2>/dev/null
  echo "rc=$?"; cat "$tmp/images.log"
}
out="$(base_case "xianyu-local/xianyu-backend-web:latest registry.example.com/up/xianyu-backend-web:latest")"
check "base prefers previous local build and pins it as :deps" bash -c "printf '%s' '$out' | grep -q '^xianyu-local/xianyu-backend-web:deps$' && printf '%s' '$out' | grep -q 'tag xianyu-local/xianyu-backend-web:latest -> xianyu-local/xianyu-backend-web:deps'"
out="$(base_case "registry.example.com/up/xianyu-backend-web:latest")"
check "base falls back to configured upstream image" bash -c "printf '%s' '$out' | grep -q 'tag registry.example.com/up/xianyu-backend-web:latest -> xianyu-local/xianyu-backend-web:deps'"
out="$(base_case "xianyu-local/xianyu-backend-web:deps xianyu-local/xianyu-backend-web:latest")"
check "existing :deps is reused without re-tagging" bash -c "printf '%s' '$out' | grep -q 'rc=0' && ! printf '%s' '$out' | grep -q '^tag '"
out="$(base_case "")"
check "no base image means full build" bash -c "printf '%s' '$out' | grep -q 'rc=1'"

if (( failures )); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
echo "all update-server checks passed"
