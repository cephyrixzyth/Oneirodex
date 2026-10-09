#!/usr/bin/env bash
# Fetch an EmulatorJS release into the data directory Oneirodex serves as
# browser play engine B (BP-2).
#
# Usage:
#   ./scripts/fetch-emulatorjs.sh                 # latest release, into the repo's static path
#   ./scripts/fetch-emulatorjs.sh --version 4.2.3 # a pinned release
#   EMULATORJS_DATA_DIR=/mnt/cache/appdata/oneirodex/emulatorjs ./scripts/fetch-emulatorjs.sh
#
# For local development, EMULATORJS_DATA_DIR may point to a temporary data
# directory. Production images fetch a pinned release during the Docker build.
# The app offers EmulatorJS only when <data dir>/loader.js exists; cores under
# data/cores/ are fetched lazily by the loader itself from this directory.
#
# EmulatorJS is GPL-3 (https://github.com/EmulatorJS/EmulatorJS). You are
# responsible for the licences of the libretro cores it bundles.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${EMULATORJS_DATA_DIR:-$ROOT/oneirodex/static/vendor/emulatorjs/data}"
VERSION="latest"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$VERSION" == "latest" ]]; then
  URL="https://github.com/EmulatorJS/EmulatorJS/releases/latest/download/EmulatorJS.zip"
else
  URL="https://github.com/EmulatorJS/EmulatorJS/releases/download/v${VERSION}/EmulatorJS.zip"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "==> Downloading $URL"
curl -fsSL "$URL" -o "$TMP/EmulatorJS.zip"
echo "==> Unpacking"
unzip -q "$TMP/EmulatorJS.zip" -d "$TMP/unpacked"
# The release zip carries data/ at its root (loader.js, emulator.min.js,
# cores/, ...). Some releases nest it one directory down.
SRC="$(find "$TMP/unpacked" -type f -name loader.js -path '*/data/*' -print -quit | xargs -r dirname)"
if [[ -z "${SRC:-}" ]]; then
  echo "!! No data/loader.js in the archive; layout changed upstream" >&2
  exit 1
fi
mkdir -p "$DATA_DIR"
echo "==> Installing into $DATA_DIR"
rm -rf "$DATA_DIR"/*
cp -R "$SRC"/. "$DATA_DIR"/
echo "==> $(ls "$DATA_DIR" | wc -l) entries; loader.js present: $([[ -f "$DATA_DIR/loader.js" ]] && echo yes || echo NO)"
echo "    Admin -> Emulators now offers EmulatorJS as the browser engine."
