#!/usr/bin/env bash
# Contract + sandboxed tests for install-ubuntu.sh, export-for-migration.sh and deploy-ubuntu.sh helpers (no Docker).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL="$ROOT/scripts/install-ubuntu.sh"
EXPORT="$ROOT/scripts/export-for-migration.sh"
DEPLOY="$ROOT/scripts/deploy-ubuntu.sh"
COMPOSE="$ROOT/docker/ubuntu-compose.yml"
failures=0
check(){ local name="$1"; shift; if "$@"; then printf 'ok - %s\n' "$name"; else printf 'not ok - %s\n' "$name"; failures=$((failures+1)); fi; }
contains(){ grep -Fq -- "$1" "$2"; }
order(){ awk -v a="$1" -v b="$2" 'index($0,a)&&!x{x=NR} index($0,b)&&!y{y=NR} END{exit !(x&&y&&x<y)}' "$3"; }

# install-ubuntu.sh
check "install: syntax" bash -n "$INSTALL"
check "install: strict mode" contains 'set -Eeuo pipefail' "$INSTALL"
check "install: requires Ubuntu" contains 'Ubuntu is required' "$INSTALL"
check "install: bootstrap before deploy" order 'scripts/bootstrap-ubuntu.sh' 'scripts/deploy-ubuntu.sh" deploy' "$INSTALL"
check "install: settings passed via XY_ vars, not compose names" bash -c "grep -q 'XY_PUBLIC_HTTP_PORT=\"\$PORT\"' '$INSTALL' && ! grep -Eq '^[[:space:]]*export[[:space:]]+PUBLIC_HTTP_PORT' '$INSTALL'"
check "install: import guard delegated to deploy (rerun-safe)" bash -c "! grep -q 'is only for the first install' '$INSTALL'"
check "install: verifies dump archive" contains 'gzip -t "$IMPORT_DIR/database.sql.gz"' "$INSTALL"
check "install: swap only for small memory" contains 'mem_kb >= 4000000' "$INSTALL"
check "install: reminds default password" contains 'admin / admin123' "$INSTALL"
check "install: rejects bad port" bash -c "bash '$INSTALL' --port 99999 2>&1 | grep -q 'invalid --port'"
check "install: rejects bad public url" bash -c "bash '$INSTALL' --public-url ftp://x 2>&1 | grep -q 'must start with http'"

# export-for-migration.sh
check "export: syntax" bash -n "$EXPORT"
check "export: single business database (no mysql system db)" bash -c "grep -q 'mysqldump --single-transaction' '$EXPORT' && ! grep -q -- '--all-databases' '$EXPORT'"
check "export: dump completeness verified" contains 'grep -q "Dump completed"' "$EXPORT"
check "export: private file mode" contains 'umask 077' "$EXPORT"
check "export: restarts apps it stopped" contains 'trap restart_apps EXIT' "$EXPORT"
check "export: never removes containers or volumes" bash -c "! grep -Eq 'compose (down|rm)|volume rm|rm -rf .*DATA_DIR' '$EXPORT'"
check "export: bundle layout matches importer" bash -c "grep -q 'database.sql.gz' '$EXPORT' && grep -q 'static.tar.gz' '$EXPORT' && grep -q 'browser_data.tar.gz' '$EXPORT' && grep -q 'browser_data.tar.gz' '$DEPLOY'"

# deploy-ubuntu.sh (static)
check "deploy: syntax" bash -n "$DEPLOY"
check "deploy: import before build, stable tag only after health check" bash -c "awk '/^deploy\\(\\)/{d=1} d&&/import_database\$/{a=NR} d&&/build_images\$/{b=NR} d&&/apps_healthy && verify_health/{c=NR} d&&/mark_stable\$/{m=NR} END{exit !(a&&b&&c&&m&&a<b&&c<m)}' '$DEPLOY'"
check "deploy: rollback target is :stable" bash -c "grep -q 'xianyu-ubuntu/\${service}:stable\" \"\$(app_image' '$DEPLOY' && ! grep -q ':previous' '$DEPLOY'"
check "deploy: import refuses non-empty database" contains 'import is only for a fresh install' "$DEPLOY"
check "deploy: failed migration rolls back" bash -c "grep -A2 'common.db.init_database; then' '$DEPLOY' | grep -q fail_or_rollback"
check "deploy: unhealthy release rolls back" bash -c "grep -A1 'compose up -d && apps_healthy && verify_health' '$DEPLOY' | grep -q fail_or_rollback"
check "deploy: rollback command" contains 'rollback) rollback;;' "$DEPLOY"
check "deploy: sequential builds" contains 'compose build "$service"' "$DEPLOY"
check "compose: pip mirror build arg" bash -c "test \"\$(grep -c 'PIP_INDEX_URL:' '$COMPOSE')\" -eq 3"
check "compose: public URL env" contains 'FRONTEND_PUBLIC_URL: ${FRONTEND_PUBLIC_URL:-}' "$COMPOSE"
check "compose: no flow-style env list (invalid YAML with \${...})" bash -c "! grep -Eq 'environment: \\[' '$COMPOSE'"
for f in backend-web websocket scheduler; do
  check "$f Dockerfile: deps installed before source copy" order "COPY $f/pyproject.toml" "COPY common /app/common" "$ROOT/$f/Dockerfile"
  check "$f Dockerfile: browsers installed before source copy" order 'playwright install --with-deps' 'COPY common /app/common' "$ROOT/$f/Dockerfile"
done

# deploy-ubuntu.sh (sandboxed functions)
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $* | PUBLIC_HTTP_PORT=${PUBLIC_HTTP_PORT:-<unset>}" >> "$STUB_LOG"
if [[ "$*" == *" port frontend 80"* ]]; then [[ -n "${STUB_OWN_PORT:-}" ]] && echo "0.0.0.0:${STUB_OWN_PORT}"; exit 0; fi
if [[ "$*" == *"information_schema.tables"* ]]; then echo "${STUB_TABLES:-0}"; exit 0; fi
exit 0
EOF
printf '#!/usr/bin/env bash\necho "State Recv-Q"; [[ -n "${STUB_PORT_BUSY:-}" ]] && echo "LISTEN 0"; exit 0\n' > "$tmp/bin/ss"
# flock/openssl may be missing on dev machines (e.g. Git Bash); stub only when absent
for c in flock openssl; do command -v "$c" >/dev/null 2>&1 || printf '#!/usr/bin/env bash\necho 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n' > "$tmp/bin/$c"; done
chmod +x "$tmp/bin/"*
run_deploy_fn(){ STUB_LOG="$tmp/log" PATH="$tmp/bin:$PATH" XIAN_YU_DEPLOY_DIR="$tmp/state" bash -c "source '$DEPLOY'; $1" 2>&1; }

out="$(XY_PUBLIC_HTTP_PORT=80 XY_PUBLIC_URL=http://1.2.3.4 XY_PIP_INDEX_URL=https://pip.example/simple run_deploy_fn 'write_env >/dev/null; echo "$(env_value PUBLIC_HTTP_PORT) $(env_value FRONTEND_PUBLIC_URL) $(env_value BACKEND_WEB_PUBLIC_URL) $(env_value PIP_INDEX_URL)"')"
check "write_env: first install takes XY_ settings" test "$(printf '%s' "$out" | tail -1)" = "80 http://1.2.3.4 http://1.2.3.4 https://pip.example/simple"
check "write_env: chmod 600 applied" contains 'chmod 600 "$ENV_FILE"; log "created private configuration' "$DEPLOY"
check "write_env: generated secrets are strong" bash -c "for k in MYSQL_ROOT_PASSWORD MYSQL_PASSWORD REDIS_PASSWORD INTERNAL_API_TOKEN; do v=\$(awk -F= -v k=\$k '\$1==k{print \$2}' '$tmp/state/.env'); [ \${#v} -eq 64 ] || exit 1; done"
out="$(XY_PUBLIC_HTTP_PORT=9999 run_deploy_fn 'write_env; env_value PUBLIC_HTTP_PORT')"
check "write_env: existing .env is never overwritten" test "$(printf '%s' "$out" | tail -1)" = "80"
: > "$tmp/log"
PUBLIC_HTTP_PORT=1234 run_deploy_fn 'compose version' >/dev/null
check "compose wrapper ignores shell PUBLIC_HTTP_PORT (.env wins)" grep -q 'PUBLIC_HTTP_PORT=<unset>' "$tmp/log"
out="$(STUB_OWN_PORT=80 STUB_PORT_BUSY=1 run_deploy_fn 'df(){ printf "Filesystem 1K Used Avail\n/dev/x 1 1 99999999\n"; }; check_prereqs && echo PREREQ_OK')"
check "port check accepts our own running frontend" bash -c "printf '%s' '$out' | grep -q PREREQ_OK"
out="$(STUB_PORT_BUSY=1 run_deploy_fn 'df(){ printf "Filesystem 1K Used Avail\n/dev/x 1 1 99999999\n"; }; check_prereqs && echo PREREQ_OK')"
check "port check rejects a foreign listener" bash -c "printf '%s' '$out' | grep -q 'in use by another program'"
mkdir -p "$tmp/import"; printf 'x' | gzip -c > "$tmp/import/database.sql.gz"
out="$(STUB_TABLES=105 IMPORT_DIR="$tmp/import" run_deploy_fn 'import_database && echo IMPORTED')"
check "import refuses a database that already has tables" bash -c "printf '%s' '$out' | grep -q 'already has 105 tables' && ! printf '%s' '$out' | grep -q IMPORTED"
out="$(STUB_TABLES=0 IMPORT_DIR="$tmp/import" run_deploy_fn 'import_database && echo IMPORTED')"
check "import proceeds into an empty database" bash -c "printf '%s' '$out' | grep -q IMPORTED"
out="$(run_deploy_fn 'import_database && echo NOOP')"
check "no IMPORT_DIR means no import" bash -c "printf '%s' '$out' | grep -q NOOP"
check "successful import writes bundle marker" test -s "$tmp/state/imported-database.sha256"
: > "$tmp/log"
out="$(STUB_TABLES=105 IMPORT_DIR="$tmp/import" run_deploy_fn 'import_database && echo SKIPPED_OK')"
check "rerun with the same bundle skips import even though tables exist" bash -c "printf '%s' '$out' | grep -q 'already imported' && printf '%s' '$out' | grep -q SKIPPED_OK && ! grep -q 'exec mysql -uroot' '$tmp/log'"
mkdir -p "$tmp/import2"; printf 'different' | gzip -c > "$tmp/import2/database.sql.gz"
out="$(STUB_TABLES=105 IMPORT_DIR="$tmp/import2" run_deploy_fn 'import_database && echo IMPORTED')"
check "a different bundle into a non-empty database is still refused" bash -c "printf '%s' '$out' | grep -q 'already has 105 tables' && ! printf '%s' '$out' | grep -q IMPORTED"

if (( failures )); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
echo "all ubuntu install checks passed"
