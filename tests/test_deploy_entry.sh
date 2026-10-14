#!/usr/bin/env bash
# Tests for the root deploy.sh entry (source builds only, legacy migration with rollback). No real Docker.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failures=0
check(){ local name="$1"; shift; if "$@"; then printf 'ok - %s\n' "$name"; else printf 'not ok - %s\n' "$name"; failures=$((failures+1)); fi; }

for s in deploy.sh update.sh deploy_remote.sh; do check "$s syntax" bash -n "$ROOT/$s"; done
check "no script pulls the original author's prebuilt images" bash -c "! grep -En 'zhinian-software|xy-update\\.zhinianboke|compose[^#]* pull' '$ROOT/deploy.sh' '$ROOT/update.sh' '$ROOT/deploy_remote.sh'"
check "README has no upstream one-click curl install" bash -c "! grep -q 'xy-update.zhinianboke.com' '$ROOT/README.md'"
check "update.sh delegates to deploy.sh" grep -q 'exec bash "$ROOT_DIR/deploy.sh" update' "$ROOT/update.sh"
check "deploy_remote.sh refuses" bash -c "! bash '$ROOT/deploy_remote.sh' 2>/dev/null"

# ---- sandbox: stub docker + stub sub-scripts, run the real deploy.sh dispatcher ----
setup(){
  T="$(mktemp -d)"; mkdir -p "$T/scripts" "$T/bin" "$T/c" "$T/uploads"
  cp "$ROOT/deploy.sh" "$T/"
  for s in install-ubuntu deploy-ubuntu export-for-migration update-server; do
    cat > "$T/scripts/$s.sh" <<EOF
#!/usr/bin/env bash
echo "$s \$*" >> "$T/calls"
if [[ "$s" == export-for-migration ]]; then b="$T/export.tar.gz"; : > "\$b"; printf '%s\n' "\$b" > "\$EXPORT_PATH_FILE"; fi
if [[ "$s" == install-ubuntu && "\$*" == *--import* && -n "\${SIM_INSTALL_FAIL:-}" ]]; then exit 1; fi
exit 0
EOF
  done
  # containers: file per container: "<running|stopped> <restart-policy>"
  cat > "$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
C="$SIM_ROOT/c"
case "$1" in
  info) exit 0 ;;
  inspect)
    if [[ "$2" == -f ]]; then [[ -f "$C/$4" ]] || exit 1; read -r st _ < "$C/$4"; [[ "$st" == running ]] && echo true || echo false; exit 0; fi
    [[ -f "$C/$2" ]]; exit $? ;;
  update) p="${2#--restart=}"; [[ -f "$C/$3" ]] && { read -r st _ < "$C/$3"; echo "$st $p" > "$C/$3"; }; exit 0 ;;
  stop) [[ -f "$C/$2" ]] && { read -r _ p < "$C/$2"; echo "stopped $p" > "$C/$2"; }; exit 0 ;;
  start) [[ -f "$C/$2" ]] && { read -r _ p < "$C/$2"; echo "running $p" > "$C/$2"; }; exit 0 ;;
  port) [[ "$2" == xianyu-frontend && -f "$C/xianyu-frontend" ]] && echo "0.0.0.0:${SIM_LEGACY_PORT:-9000}"; exit 0 ;;
  image) [[ -n "${SIM_NEW_STABLE:-}" ]]; exit $? ;;
  exec) exit 0 ;;
esac
exit 0
EOF
  printf '#!/usr/bin/env bash\necho "State"\nfor p in ${SIM_BUSY_PORTS:-}; do [[ "$*" == *":$p"* ]] && echo "LISTEN"; done\nexit 0\n' > "$T/bin/ss"
  chmod +x "$T/bin/"* "$T/scripts/"*.sh
  printf 'ID=ubuntu\nVERSION_ID="24.04"\n' > "$T/os-ubuntu"; printf 'ID="centos"\n' > "$T/os-centos"
  : > "$T/calls"
}
legacy(){ local c; for c in xianyu-frontend xianyu-scheduler xianyu-websocket xianyu-backend-web xianyu-mysql xianyu-redis; do echo "running unless-stopped" > "$T/c/$c"; done; }
run(){ local os="$1"; shift
  (cd "$T" && SIM_ROOT="$T" PATH="$T/bin:$PATH" OS_RELEASE="$T/os-$os" BUNDLE_GLOBS="$T/uploads/xianyu-export-*.tar.gz" \
    bash -c 'source ./deploy.sh; require_root(){ :; }; main "$@"' _ "$@" > "$T/out" 2>&1); echo $?; }
calls(){ tr '\n' ';' < "$T/calls"; }
state(){ cat "$T/c/$1"; }

setup; rc="$(run ubuntu)"
check "fresh Ubuntu: installs from source on port 80" bash -c "[ $rc = 0 ] && grep -qx 'install-ubuntu --port 80' '$T/calls'"; rm -rf "$T"

setup; : > "$T/uploads/xianyu-export-1.tar.gz"; rc="$(run ubuntu)"
check "fresh Ubuntu with an uploaded bundle but no choice: stops and asks" bash -c "[ $rc != 0 ] && grep -q 'found uploaded data bundle' '$T/out' && [ ! -s '$T/calls' ]"; rm -rf "$T"

setup; : > "$T/uploads/xianyu-export-1.tar.gz"; rc="$(run ubuntu --import "$T/uploads/xianyu-export-1.tar.gz")"
check "fresh Ubuntu with --import: passes the bundle to the installer" bash -c "[ $rc = 0 ] && grep -q 'install-ubuntu --port 80 --import .*xianyu-export-1.tar.gz' '$T/calls'"; rm -rf "$T"

setup; legacy; rc="$(run ubuntu)"
check "legacy on Ubuntu: build first, then stop, export, import" bash -c "[ $rc = 0 ] && [ \"\$(cut -d' ' -f1-2 '$T/calls' | tr '\n' ';')\" = 'install-ubuntu --port;export-for-migration ;install-ubuntu --port;' ] && grep -q 'build-only' '$T/calls' && grep -q -- '--import $T/export.tar.gz' '$T/calls'"
check "legacy on Ubuntu: previous containers stay stopped and will not auto-start" bash -c "[ \"\$(state xianyu-backend-web 2>/dev/null || cat '$T/c/xianyu-backend-web')\" = 'stopped no' ] && [ \"\$(cat '$T/c/xianyu-mysql')\" = 'stopped no' ]"; rm -rf "$T"

setup; legacy; rc="$(SIM_INSTALL_FAIL=1 run ubuntu)"
check "legacy migration failure: new stack stopped, previous containers restored" bash -c "[ $rc != 0 ] && grep -qx 'deploy-ubuntu stop' '$T/calls' && [ \"\$(cat '$T/c/xianyu-backend-web')\" = 'running unless-stopped' ] && [ \"\$(cat '$T/c/xianyu-mysql')\" = 'running unless-stopped' ] && grep -q 'previous site restored' '$T/out'"; rm -rf "$T"

setup; legacy; rc="$(SIM_BUSY_PORTS=80 run ubuntu)"
check "port 80 busy and no --port: keeps the previous port" bash -c "[ $rc = 0 ] && grep -q 'install-ubuntu --port 9000 --build-only' '$T/calls'"; rm -rf "$T"

setup; legacy; rc="$(SIM_BUSY_PORTS=80 run ubuntu --port 80)"
check "explicit busy port: refuses before touching the running site" bash -c "[ $rc != 0 ] && [ ! -s '$T/calls' ] && [ \"\$(cat '$T/c/xianyu-backend-web')\" = 'running unless-stopped' ]"; rm -rf "$T"

setup; legacy; : > "$T/uploads/xianyu-export-1.tar.gz"; rc="$(run ubuntu)"
check "legacy plus uploaded bundle without a choice: asks, site untouched" bash -c "[ $rc != 0 ] && grep -q -- '--no-bundle' '$T/out' && [ ! -s '$T/calls' ] && [ \"\$(cat '$T/c/xianyu-backend-web')\" = 'running unless-stopped' ]"; rm -rf "$T"

setup; legacy; : > "$T/uploads/xianyu-export-1.tar.gz"; rc="$(run ubuntu --import "$T/uploads/xianyu-export-1.tar.gz")"
check "legacy plus --import: imports the uploaded bundle instead of exporting" bash -c "[ $rc = 0 ] && ! grep -q export-for-migration '$T/calls' && grep -q 'xianyu-export-1.tar.gz' '$T/calls'"; rm -rf "$T"

setup; legacy; mkdir -p "$T/.ubuntu-deploy"; date > "$T/.ubuntu-deploy/deployed.ok"; rc="$(run ubuntu)"
check "already installed + legacy still running: update, then stop legacy" bash -c "[ $rc = 0 ] && grep -qx 'deploy-ubuntu update' '$T/calls' && [ \"\$(cat '$T/c/xianyu-frontend')\" = 'stopped no' ]"; rm -rf "$T"

setup; mkdir -p "$T/.ubuntu-deploy"; date > "$T/.ubuntu-deploy/deployed.ok"; rc="$(run ubuntu status)"
check "status passes through to deploy-ubuntu" bash -c "[ $rc = 0 ] && grep -qx 'deploy-ubuntu status' '$T/calls'"; rm -rf "$T"

setup; legacy; rc="$(run centos)"
check "CentOS with previous deployment: in-place source update" bash -c "[ $rc = 0 ] && grep -qx 'update-server update' '$T/calls'"; rm -rf "$T"

setup; rc="$(run centos)"
check "CentOS without deployment: asks to reinstall as Ubuntu" bash -c "[ $rc != 0 ] && grep -q 'need Ubuntu 24.04' '$T/out'"; rm -rf "$T"

setup; rc="$(run ubuntu --port 99999)"
check "invalid port rejected" bash -c "[ $rc != 0 ] && grep -q 'invalid --port' '$T/out'"; rm -rf "$T"

if (( failures )); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
echo "all deploy entry checks passed"
