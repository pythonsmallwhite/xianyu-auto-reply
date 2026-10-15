#!/usr/bin/env bash
# Build the xianyu-mobile Release APK on Ubuntu.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOBILE_DIR="$ROOT_DIR/xianyu-mobile"
ANDROID_DIR="$MOBILE_DIR/android"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/xianyu-android"
SDK_DIR="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Android/Sdk}}"
OUTPUT_DIR="$ROOT_DIR/release/android"
NODE_VERSION="${NODE_VERSION:-24.14.1}"
GRADLE_VERSION="9.3.1"
GRADLE_SHA256="b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06"
GRADLE_DIST_URL="${GRADLE_DIST_URL:-https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip}"
ANDROID_CMDLINE_TOOLS_URL="${ANDROID_CMDLINE_TOOLS_URL:-https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip}"
ANDROID_CMDLINE_TOOLS_SHA256="${ANDROID_CMDLINE_TOOLS_SHA256:-}"
ANDROID_SDK_PROXY="${ANDROID_SDK_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}"
CLEAN=0
SKIP_INSTALL=0

log() { printf '[android-apk] %s\n' "$*"; }
warn() { printf '[android-apk] WARNING: %s\n' "$*" >&2; }
die() { printf '[android-apk] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage: bash scripts/build-android-apk.sh [options]
  --output DIR       Directory for the final APK and SHA256 file
  --clean            Run Gradle clean before assembleRelease
  --skip-install     Do not install/check system or JavaScript dependencies
  -h, --help         Show this help

Network variables: HTTPS_PROXY, ANDROID_SDK_PROXY, GRADLE_DIST_URL
EOF
}
while (($#)); do
  case "$1" in
    --output) OUTPUT_DIR="${2:-}"; shift ;;
    --clean) CLEAN=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }
as_root() { if (( EUID == 0 )); then "$@"; else require_cmd sudo; sudo "$@"; fi; }
proxy_parts() {
  local value="${1:-}"; value="${value#http://}"; value="${value#https://}"; value="${value#*@}"
  PROXY_HOST="${value%%:*}"; PROXY_PORT="${value##*:}"
  [[ "$PROXY_HOST" != "$PROXY_PORT" && "$PROXY_PORT" =~ ^[0-9]+$ ]]
}
configure_gradle_proxy() {
  local value="${HTTPS_PROXY:-${https_proxy:-}}"
  [[ -n "$value" ]] || return 0
  if proxy_parts "$value"; then
    export GRADLE_OPTS="${GRADLE_OPTS:-} -Dhttps.proxyHost=${PROXY_HOST} -Dhttps.proxyPort=${PROXY_PORT} -Dhttp.proxyHost=${PROXY_HOST} -Dhttp.proxyPort=${PROXY_PORT}"
    log "Gradle proxy configured: ${PROXY_HOST}:${PROXY_PORT}"
  else warn "cannot parse HTTPS_PROXY for Gradle: host:port expected"; fi
}
check_ubuntu() {
  [[ -r /etc/os-release ]] || die "cannot identify operating system"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == ubuntu ]] || die "Ubuntu is required (found ${ID:-unknown})"
}
ensure_base_tools() {
  local missing=(); for command_name in curl unzip tar xz sha256sum; do command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name"); done
  if ((${#missing[@]})); then
    log "installing base tools: ${missing[*]}"
    as_root apt-get update
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl unzip tar xz-utils coreutils
  fi
}
java_major() { java -version 2>&1 | awk -F'[".]' '/version/{print $2; exit}'; }
ensure_java() {
  local candidate="${JAVA_HOME:-}"
  if [[ -z "$candidate" || ! -x "$candidate/bin/java" || ! -x "$candidate/bin/jlink" ]]; then
    candidate=""
    for path in /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/java-17-openjdk /usr/lib/jvm/jdk-17; do
      if [[ -x "$path/bin/java" && -x "$path/bin/jlink" ]]; then candidate="$path"; break; fi
    done
  fi
  if [[ -z "$candidate" ]]; then
    log "installing complete OpenJDK 17 (javac and jlink are required)"
    as_root apt-get update
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-17-jdk-headless
    for path in /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/java-17-openjdk; do
      if [[ -x "$path/bin/java" && -x "$path/bin/jlink" ]]; then candidate="$path"; break; fi
    done
  fi
  [[ -n "$candidate" ]] || die "complete JDK 17 with jlink was not found"
  export JAVA_HOME="$candidate"; export PATH="$JAVA_HOME/bin:$PATH"
  [[ "$(java_major)" == 17 ]] || die "JAVA_HOME must point to Java 17"
  [[ -x "$JAVA_HOME/bin/javac" && -x "$JAVA_HOME/bin/jlink" ]] || die "JAVA_HOME is missing javac or jlink"
}
node_major() { node --version | sed -E 's/^v([0-9]+).*/\1/'; }
ensure_node() {
  if command -v node >/dev/null 2>&1 && (( $(node_major) >= 20 )); then return 0; fi
  local prefix="$CACHE_DIR/node-v${NODE_VERSION}-linux-x64" archive="$CACHE_DIR/node-v${NODE_VERSION}-linux-x64.tar.xz"
  mkdir -p "$CACHE_DIR"
  if [[ ! -x "$prefix/bin/node" ]]; then
    log "downloading Node.js ${NODE_VERSION}"
    curl -fsSL --retry 3 -o "$archive" "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
    mkdir -p "$CACHE_DIR/unpack-node"; tar -xJf "$archive" -C "$CACHE_DIR/unpack-node"
    mv "$CACHE_DIR/unpack-node/node-v${NODE_VERSION}-linux-x64" "$prefix"; rm -rf "$CACHE_DIR/unpack-node"
  fi
  export PATH="$prefix/bin:$PATH"; (( $(node_major) >= 20 )) || die "Node.js 20 or newer is required"
}
sdkmanager_path() { printf '%s/cmdline-tools/latest/bin/sdkmanager\n' "$SDK_DIR"; }
ensure_sdkmanager() {
  local manager; manager="$(sdkmanager_path)"; [[ -x "$manager" ]] && return 0
  local archive="$CACHE_DIR/commandlinetools.zip" temp="$CACHE_DIR/cmdline-tools"
  mkdir -p "$CACHE_DIR" "$SDK_DIR/cmdline-tools/latest"; log "downloading Android command-line tools"
  curl -fsSL --retry 3 -o "$archive" "$ANDROID_CMDLINE_TOOLS_URL"
  if [[ -n "$ANDROID_CMDLINE_TOOLS_SHA256" ]]; then
    [[ "$(sha256sum "$archive" | awk '{print $1}')" == "$ANDROID_CMDLINE_TOOLS_SHA256" ]] || die "Android command-line tools SHA256 mismatch"
  fi
  rm -rf "$temp"; mkdir -p "$temp"; unzip -q "$archive" -d "$temp"; cp -a "$temp/cmdline-tools/." "$SDK_DIR/cmdline-tools/latest/"
}
sdk_proxy_args=()
configure_sdk_proxy() { if [[ -n "$ANDROID_SDK_PROXY" ]] && proxy_parts "$ANDROID_SDK_PROXY"; then sdk_proxy_args=(--proxy=http --proxy_host="$PROXY_HOST" --proxy_port="$PROXY_PORT"); log "Android SDK proxy configured: ${PROXY_HOST}:${PROXY_PORT}"; fi; }
ensure_android_sdk() {
  ensure_sdkmanager; configure_sdk_proxy; local manager; manager="$(sdkmanager_path)"
  yes | "$manager" --sdk_root="$SDK_DIR" "${sdk_proxy_args[@]}" --licenses >/dev/null || true
  "$manager" --sdk_root="$SDK_DIR" "${sdk_proxy_args[@]}" platform-tools platforms\;android-36 build-tools\;36.0.0 ndk\;27.1.12297006 cmake\;3.22.1
  export ANDROID_HOME="$SDK_DIR" ANDROID_SDK_ROOT="$SDK_DIR"; export PATH="$SDK_DIR/platform-tools:$SDK_DIR/cmdline-tools/latest/bin:$PATH"
}
gradle_path() { printf '%s/gradle-%s/bin/gradle\n' "$CACHE_DIR" "$GRADLE_VERSION"; }
ensure_gradle() {
  local gradle; gradle="$(gradle_path)"; if [[ -x "$gradle" ]]; then GRADLE_BIN="$gradle"; return 0; fi
  local archive="$CACHE_DIR/gradle-${GRADLE_VERSION}-bin.zip"; mkdir -p "$CACHE_DIR"; log "downloading Gradle ${GRADLE_VERSION}"
  curl -fsSL --retry 3 -o "$archive" "$GRADLE_DIST_URL"; [[ "$(sha256sum "$archive" | awk '{print $1}')" == "$GRADLE_SHA256" ]] || die "Gradle SHA256 mismatch"
  unzip -q "$archive" -d "$CACHE_DIR"; [[ -x "$gradle" ]] || die "Gradle extraction failed"; GRADLE_BIN="$gradle"
}
prepare_dependencies() { cd "$MOBILE_DIR"; if [[ "$SKIP_INSTALL" == 0 ]]; then log "installing JavaScript dependencies"; npm ci --legacy-peer-deps --no-audit --no-fund; fi; node node_modules/typescript/bin/tsc --noEmit; }
build_apk() { ensure_gradle; cd "$ANDROID_DIR"; ((CLEAN)) && "$GRADLE_BIN" clean --console=plain; log "building assembleRelease"; "$GRADLE_BIN" assembleRelease --console=plain --max-workers="${GRADLE_MAX_WORKERS:-2}"; }
verify_and_copy() {
  local source="$ANDROID_DIR/app/build/outputs/apk/release/app-release.apk"; [[ -f "$source" ]] || die "APK was not produced: $source"; mkdir -p "$OUTPUT_DIR"
  local version; version="$(awk -F'"' '/versionName/{print $2; exit}' "$ANDROID_DIR/app/build.gradle")"; local target="$OUTPUT_DIR/xianyu-mobile-${version}-$(date -u +%Y%m%dT%H%M%SZ).apk"
  cp "$source" "$target"; sha256sum "$target" | tee "$target.sha256"; local apksigner="$ANDROID_HOME/build-tools/36.0.0/apksigner"; [[ -x "$apksigner" ]] && "$apksigner" verify --verbose "$target"; log "APK: $target"; log "SHA256: $target.sha256"
}
main() { [[ -d "$MOBILE_DIR" && -d "$ANDROID_DIR" ]] || die "xianyu-mobile Android project not found"; check_ubuntu; ensure_base_tools; configure_gradle_proxy; ensure_java; ensure_node; ensure_android_sdk; prepare_dependencies; build_apk; verify_and_copy; }
main "$@"
