#!/usr/bin/env bash
# Fetch / validate WebRetro libretro WASM cores into oneirodex/static/vendor/webretro/cores/
#
# Usage:
#   ./scripts/fetch-webretro-cores.sh --defaults
#   ./scripts/fetch-webretro-cores.sh --from-dir /path/to/built/cores
#   ./scripts/fetch-webretro-cores.sh --defaults --from-dir /path/to/built/cores
#
# --defaults pulls the 24 shipped core IDs from BinBashBanana/webretro@6.5 (jsDelivr)
# and verifies every file against scripts/webretro-cores.sha256 before replacing it.
# Deferred PCE / VICE / DOS cores are NOT on that CDN — place them with --from-dir.
# You are responsible for core license compliance.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORES_DIR="${WEBRETR_CORES_DIR:-$ROOT/oneirodex/static/vendor/webretro/cores}"
CDN="https://cdn.jsdelivr.net/gh/BinBashBanana/webretro@6.5/cores"
HASHES_FILE="$ROOT/scripts/webretro-cores.sha256"

DEFAULT_CORES=(
  a5200 freechaf freeintv gearcoleco genesis_plus_gx handy
  mednafen_ngp mednafen_psx_hw mednafen_vb mednafen_wswan melonds
  mgba mupen64plus_next neocd nestopia o2em opera parallel_n64
  prosystem snes9x stella2014 vecx virtualjaguar yabause
)

DEFERRED_HINT=(mednafen_pce_fast mednafen_supergrafx vice_x64 dosbox_pure dosbox)

DO_DEFAULTS=0
FROM_DIR=""

usage() {
  sed -n '2,12p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --defaults) DO_DEFAULTS=1; shift ;;
    --from-dir) FROM_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

if [[ "$DO_DEFAULTS" -eq 0 && -z "$FROM_DIR" ]]; then
  echo "Specify --defaults and/or --from-dir <path>" >&2
  usage 1
fi

mkdir -p "$CORES_DIR"

download_pair() {
  local id="$1"
  local base="$CDN/${id}_libretro"
  local js_name="${id}_libretro.js"
  local wasm_name="${id}_libretro.wasm"
  local js_tmp wasm_tmp js_expected wasm_expected js_actual wasm_actual
  echo "Fetching $id ..."
  js_expected="$(awk -v name="$js_name" '$2 == name {print $1}' "$HASHES_FILE")"
  wasm_expected="$(awk -v name="$wasm_name" '$2 == name {print $1}' "$HASHES_FILE")"
  if [[ ! "$js_expected" =~ ^[0-9a-f]{64}$ || ! "$wasm_expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "No valid SHA-256 lock found for $id" >&2
    return 1
  fi

  js_tmp="$(mktemp "$CORES_DIR/.${js_name}.XXXXXX.part")"
  wasm_tmp="$(mktemp "$CORES_DIR/.${wasm_name}.XXXXXX.part")"
  if ! curl -fsSL -o "$js_tmp" "${base}.js" || ! curl -fsSL -o "$wasm_tmp" "${base}.wasm"; then
    rm -f -- "$js_tmp" "$wasm_tmp"
    return 1
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    js_actual="$(sha256sum "$js_tmp" | awk '{print $1}')"
    wasm_actual="$(sha256sum "$wasm_tmp" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    js_actual="$(shasum -a 256 "$js_tmp" | awk '{print $1}')"
    wasm_actual="$(shasum -a 256 "$wasm_tmp" | awk '{print $1}')"
  else
    echo "sha256sum or shasum is required to verify downloaded cores" >&2
    rm -f -- "$js_tmp" "$wasm_tmp"
    return 1
  fi

  if [[ "$js_actual" != "$js_expected" || "$wasm_actual" != "$wasm_expected" ]]; then
    echo "SHA-256 integrity check failed for $id; existing files were preserved" >&2
    rm -f -- "$js_tmp" "$wasm_tmp"
    return 1
  fi

  mv -f -- "$js_tmp" "$CORES_DIR/$js_name"
  mv -f -- "$wasm_tmp" "$CORES_DIR/$wasm_name"
}

if [[ "$DO_DEFAULTS" -eq 1 ]]; then
  for id in "${DEFAULT_CORES[@]}"; do
    download_pair "$id"
  done
fi

if [[ -n "$FROM_DIR" ]]; then
  if [[ ! -d "$FROM_DIR" ]]; then
    echo "--from-dir is not a directory: $FROM_DIR" >&2
    exit 1
  fi
  copied=0
  for wasm in "$FROM_DIR"/*_libretro.wasm; do
    [[ -f "$wasm" ]] || continue
    base="$(basename "$wasm" _libretro.wasm)"
    js="$FROM_DIR/${base}_libretro.js"
    if [[ ! -f "$js" ]]; then
      echo "Skip $base — missing matching .js" >&2
      continue
    fi
    cp -f "$js" "$wasm" "$CORES_DIR/"
    echo "Copied $base"
    copied=$((copied + 1))
  done
  if [[ "$copied" -eq 0 ]]; then
    echo "No *_libretro.{js,wasm} pairs found in $FROM_DIR" >&2
    exit 1
  fi
fi

echo ""
echo "Cores directory: $CORES_DIR"
echo "Present WASM:"
found_deferred=0
for wasm in "$CORES_DIR"/*_libretro.wasm; do
  [[ -f "$wasm" ]] || continue
  id="$(basename "$wasm" _libretro.wasm)"
  js_ok="no-js"
  [[ -f "$CORES_DIR/${id}_libretro.js" ]] && js_ok="ok"
  echo "  - $id ($js_ok)"
  for d in "${DEFERRED_HINT[@]}"; do
    [[ "$id" == "$d" ]] && found_deferred=1
  done
done

echo ""
echo "After restart (or with a live bind-mount), check:"
echo "  curl -sS \"\$BASE/api/emulator/health\" | jq '.installed_cores, .deferred_cores'"
echo "  curl -sS \"\$BASE/api/emulator/installed-cores.js\""
if [[ "$found_deferred" -eq 0 ]]; then
  echo ""
  echo "Note: deferred cores (PCE/VICE/DOS) still missing. Build via RetroArch emscripten"
  echo "or copy a compatible pack with --from-dir. See docs/runbooks/webretro-cores.md"
fi
