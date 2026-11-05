#!/usr/bin/env bash
# Fetch an EmulatorJS release into the data directory Oneirodex serves as
# browser play engine B (BP-2).
#
# Usage:
#   ./scripts/fetch-emulatorjs.sh --version 4.2.3 --sha256 <64-hex-digest>
#
# A SHA-256 is required before extraction. The install destination is fixed to
# the app's bundled data directory; production images pin both the release and
# digest during the Docker build.
# The app offers EmulatorJS only when <data dir>/loader.js exists; cores under
# data/cores/ are fetched lazily by the loader itself from this directory.
#
# EmulatorJS is GPL-3 (https://github.com/EmulatorJS/EmulatorJS). You are
# responsible for the licences of the libretro cores it bundles.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
DEFAULT_DATA_DIR="$ROOT/oneirodex/static/vendor/emulatorjs/data"
DATA_DIR="$DEFAULT_DATA_DIR"
VERSION="latest"
EXPECTED_SHA256=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --sha256) EXPECTED_SHA256="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -n "${EMULATORJS_DATA_DIR:-}" ]]; then
  REQUESTED_DATA_DIR="$(realpath -m -- "$EMULATORJS_DATA_DIR")"
  if [[ "$REQUESTED_DATA_DIR" != "$(realpath -m -- "$DEFAULT_DATA_DIR")" ]]; then
    echo "!! EMULATORJS_DATA_DIR overrides are disabled; use the bundled app data directory" >&2
    exit 2
  fi
fi
DATA_DIR="$(realpath -m -- "$DEFAULT_DATA_DIR")"
ROOT="$(realpath -e -- "$ROOT")"
case "$DATA_DIR" in
  "$ROOT"/*) ;;
  *)
    echo "!! The default EmulatorJS data directory resolves outside the app tree" >&2
    exit 2
    ;;
esac

if [[ "$VERSION" == "latest" ]]; then
  VERSION="$(curl -fsSL https://api.github.com/repos/EmulatorJS/EmulatorJS/releases/latest | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"].removeprefix("v"))')"
fi
URL="https://github.com/EmulatorJS/EmulatorJS/releases/download/v${VERSION}/${VERSION}.7z"

if [[ -n "$EXPECTED_SHA256" && ! "$EXPECTED_SHA256" =~ ^[[:xdigit:]]{64}$ ]]; then
  echo "!! --sha256 must be a 64-character hexadecimal digest" >&2
  exit 2
fi
if [[ -z "$EXPECTED_SHA256" ]]; then
  echo "!! No trusted SHA-256 supplied; refusing to download an unverified release." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "==> Downloading $URL"
curl -fsSL "$URL" -o "$TMP/EmulatorJS.7z"
printf '%s  %s\n' "$EXPECTED_SHA256" "$TMP/EmulatorJS.7z" | sha256sum --check --status || {
  echo "!! EmulatorJS archive SHA-256 mismatch" >&2
  exit 1
}
echo "==> Unpacking"
7z x "$TMP/EmulatorJS.7z" "-o$TMP/unpacked" -y >/dev/null
# The release archive carries data/ at its root (loader.js, emulator.min.js,
# cores/, ...). Some releases nest it one directory down.
SRC="$(find "$TMP/unpacked" -type f -name loader.js -path '*/data/*' -print -quit | xargs -r dirname)"
if [[ -z "${SRC:-}" ]]; then
  echo "!! No data/loader.js in the archive; layout changed upstream" >&2
  exit 1
fi
mkdir -p "$DATA_DIR"
echo "==> Installing into $DATA_DIR"
rm -rf -- "$DATA_DIR"/*
cp -R "$SRC"/. "$DATA_DIR"/
echo "==> $(ls "$DATA_DIR" | wc -l) entries; loader.js present: $([[ -f "$DATA_DIR/loader.js" ]] && echo yes || echo NO)"
echo "    Admin -> Emulators now offers EmulatorJS as the browser engine."
