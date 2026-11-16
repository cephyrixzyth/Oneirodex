#!/usr/bin/env bash
# Drop each vendored library's canonical LICENSE file next to its code.
#
# oneirodex/static/vendor/THIRD-PARTY-NOTICES.md is the inventory and carries the
# copyright lines read out of the shipped files themselves. This fetches the
# upstream licence texts so each directory is self-describing too.
#
# Usage:
#   ./scripts/fetch-vendor-licenses.sh
#
# Safe to re-run: existing files are overwritten with the same upstream text.
# Needs network. WebRetro's MIT text is included (upstream LICENSE, 2021
# BinBashBanana) — the vendored JS still has no banner of its own. The
# WebRetro and EmulatorJS sources are tied to the shipped versions.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/oneirodex/static/vendor"

# dir<TAB>url
TARGETS="
bootstrap/5.3.2	https://raw.githubusercontent.com/twbs/bootstrap/v5.3.2/LICENSE
chart.js/4.4.1	https://raw.githubusercontent.com/chartjs/Chart.js/v4.4.1/LICENSE.md
cropperjs/1.6.1	https://raw.githubusercontent.com/fengyuanchen/cropperjs/v1.6.1/LICENSE
datatables/1.13.7	https://raw.githubusercontent.com/DataTables/DataTables/1.13.7/license.txt
jquery/3.7.1	https://raw.githubusercontent.com/jquery/jquery/3.7.1/LICENSE.txt
notify/0.4.2	https://raw.githubusercontent.com/mouse0270/bootstrap-notify/master/LICENSE
sortablejs/1.15.2	https://raw.githubusercontent.com/SortableJS/Sortable/1.15.2/LICENSE
webretro	https://raw.githubusercontent.com/BinBashBanana/webretro/v6.5/LICENSE
nostalgist	https://raw.githubusercontent.com/arianrhodsandlot/nostalgist/v0.21.1/LICENSE
emulatorjs	https://raw.githubusercontent.com/EmulatorJS/EmulatorJS/v4.2.3/LICENSE
"

failed=0

while IFS=$'\t' read -r dir url; do
  [ -n "${dir:-}" ] || continue
  target="$VENDOR/$dir"
  if [ ! -d "$target" ]; then
    echo "skip  $dir (not vendored here)"
    continue
  fi
  if curl -fsSL -o "$target/LICENSE" "$url"; then
    echo "ok    $dir/LICENSE"
  else
    echo "FAIL  $dir  <- $url" >&2
    rm -f "$target/LICENSE"
    failed=$((failed + 1))
  fi
done <<< "$TARGETS"

if [ "$failed" -gt 0 ]; then
  echo "$failed licence(s) not fetched." >&2
  exit 1
fi

echo
echo "Done. Inventory: oneirodex/static/vendor/THIRD-PARTY-NOTICES.md"
