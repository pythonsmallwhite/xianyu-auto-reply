#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/build-android-apk.sh"
failures=0
check(){ local name="$1"; shift; if "$@"; then printf 'ok - %s\n' "$name"; else printf 'not ok - %s\n' "$name"; failures=$((failures+1)); fi; }
contains(){ grep -Fq -- "$1" "$2"; }
check "syntax" bash -n "$SCRIPT"
check "strict mode" contains 'set -Eeuo pipefail' "$SCRIPT"
check "requires Ubuntu" contains 'Ubuntu is required' "$SCRIPT"
check "requires JDK 17 jlink" bash -c "grep -q 'openjdk-17-jdk-headless' '$SCRIPT' && grep -q 'bin/jlink' '$SCRIPT'"
check "installs Node with version check" bash -c "grep -q 'NODE_VERSION' '$SCRIPT' && grep -q 'node_major' '$SCRIPT'"
check "installs Android SDK packages" bash -c "grep -q 'platforms.*android-36' '$SCRIPT' && grep -q 'ndk.*27.1.12297006' '$SCRIPT' && grep -q 'cmake.*3.22.1' '$SCRIPT'"
check "supports SDK proxy" contains 'ANDROID_SDK_PROXY' "$SCRIPT"
check "supports Gradle proxy" contains 'https.proxyHost' "$SCRIPT"
check "uses legacy peer deps" contains 'npm ci --legacy-peer-deps' "$SCRIPT"
check "runs TypeScript check" contains 'tsc --noEmit' "$SCRIPT"
check "builds Release" contains 'assembleRelease' "$SCRIPT"
check "verifies APK SHA256" contains 'sha256sum "$target"' "$SCRIPT"
check "verifies APK signature" contains 'verify --verbose' "$SCRIPT"
check "does not disable lockfile reproducibility" bash -c "! grep -Eq 'npm (install|ci).*--package-lock=false' '$SCRIPT'"
if ((failures)); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
echo "all android build checks passed"
