#!/usr/bin/env bash
# Build Oneirodex desktop installers locally — no GitHub Actions required.
#
# Tauri bundles for the host it runs on. That is a hard platform constraint, not
# a configuration gap:
#
#   Windows  -> .exe (NSIS)                 buildable on Windows only
#   macOS    -> .dmg + .app                 buildable on macOS only (codesign,
#                                           hdiutil and the .icns toolchain are
#                                           Apple-only)
#   Linux    -> .deb + .AppImage            buildable on Linux, or from any host
#                                           via the Docker path below
#
# So a Windows box can produce Windows installers directly and Linux ones
# through Docker, but a .dmg genuinely requires a Mac. There is no cross-compile
# for it, with or without CI.
#
# .msi and .rpm are deliberately absent: both reject the pre-release version
# ("1.0.0-beta") the project currently carries. Add them back to `bundle.targets`
# in src-tauri/tauri.conf.json when the version becomes a plain X.Y.Z.
#
#   ./scripts/build-installers.sh                  # bundle for this host
#   ./scripts/build-installers.sh --linux          # Linux bundles via Docker
#   ./scripts/build-installers.sh --thin           # thin client config
#   ./scripts/build-installers.sh --linux --thin   # thin client, Linux bundles
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$REPO/clients/desktop"
OUT="$REPO/dist-installers"

THIN=0
LINUX_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --thin)  THIN=1 ;;
    --linux) LINUX_DOCKER=1 ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

host_os() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    Darwin) echo macos ;;
    Linux)  echo linux ;;
    *) echo unknown ;;
  esac
}

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    echo "  $2" >&2
    exit 1
  }
}

# Copy every bundle matching the given -name predicates into $OUT, and fail if
# there were none. `find ... -exec cp` exits 0 when nothing matches, so the old
# version of this script printed "installers in dist-installers" over an empty
# directory whenever bundling was off — the failure mode it most needed to catch.
collect() {
  local label="$1"; shift
  local before after
  before="$(find "$OUT" -type f 2>/dev/null | wc -l)"
  find "$REPO/clients/desktop/src-tauri/target" -type f \( "$@" \) \
    -path '*bundle*' -exec cp -v {} "$OUT/" \;
  after="$(find "$OUT" -type f 2>/dev/null | wc -l)"
  if [ "$before" -eq "$after" ]; then
    echo "==> no $label bundles were produced" >&2
    echo "    Check that bundle.active is true in src-tauri/tauri.conf.json" >&2
    echo "    (and tauri.thin.conf.json for --thin), then re-run." >&2
    exit 1
  fi
  echo "==> $label installers in $OUT"
}

mkdir -p "$OUT"

if [ "$LINUX_DOCKER" = "1" ]; then
  require docker "install Docker Desktop, or run this script on a Linux host"
  if [ "$THIN" = "1" ]; then
    BUILD_CMD="npm run tauri:build:thin"
    echo "==> Linux bundles via Docker — thin client (deb / AppImage)"
  else
    BUILD_CMD="npm run tauri:build"
    echo "==> Linux bundles via Docker — full companion (deb / AppImage)"
  fi
  # The image needs the GTK/webkit headers Tauri links against; those are the
  # actual reason a Linux bundle cannot be produced natively on Windows.
  # Node comes from NodeSource: Debian bookworm still ships Node 18, and this
  # project is Node 26.
  docker run --rm \
    -v "$REPO":/src \
    -w /src/clients/desktop \
    -e CI=true \
    -e BUILD_CMD="$BUILD_CMD" \
    rust:1-bookworm \
    bash -lc '
      set -e
      apt-get update -qq
      apt-get install -y -qq --no-install-recommends \
        libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
        librsvg2-dev patchelf file curl ca-certificates gnupg >/dev/null
      curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
      apt-get install -y -qq nodejs >/dev/null
      node --version
      npm ci --no-audit --no-fund
      eval "$BUILD_CMD"
    '
  collect "Linux" -name '*.deb' -o -name '*.AppImage'
  exit 0
fi

OS="$(host_os)"
echo "==> host: $OS"

require cargo "install Rust: https://rustup.rs"
require npm   "install Node 26"

cd "$DESKTOP"
npm ci --no-audit --no-fund

if [ "$THIN" = "1" ]; then
  npm run tauri:build:thin
else
  npm run tauri:build
fi

case "$OS" in
  windows)
    collect "Windows" -name '*.exe'
    ;;
  macos)
    collect "macOS" -name '*.dmg'
    echo "    Unsigned by default — Gatekeeper will warn until it is signed and"
    echo "    notarised with an Apple Developer ID."
    ;;
  linux)
    collect "Linux" -name '*.deb' -o -name '*.AppImage'
    ;;
  *)
    echo "unrecognised host; bundles left under src-tauri/target/*/bundle" >&2
    ;;
esac
