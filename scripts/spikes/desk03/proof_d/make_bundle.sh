#!/bin/bash
# Assemble a relocatable PostgreSQL 17 bundle from the Debian packages in the
# postgres image (recipe from the DESK-03 proof B). Layout:
#   <root>/usr/lib/postgresql/17/bin   server + client tools
#   <root>/usr/lib/postgresql/17/lib   plpgsql, snowball, encoding conversions
#   <root>/usr/share/postgresql/17     share (found relative to bin)
#   <root>/libs                        shared libraries (LD_LIBRARY_PATH)
set -euo pipefail
R=${1:?bundle root}
SRC_BIN=/usr/lib/postgresql/17/bin SRC_MOD=/usr/lib/postgresql/17/lib SRC_SHARE=/usr/share/postgresql/17
mkdir -p "$R/usr/lib/postgresql/17/bin" "$R/usr/lib/postgresql/17/lib" "$R/usr/share/postgresql/17" "$R/libs"
TOOLS="postgres initdb pg_ctl pg_dump pg_restore psql"
for b in $TOOLS; do cp "$SRC_BIN/$b" "$R/usr/lib/postgresql/17/bin/"; done
for b in $TOOLS; do ldd "$SRC_BIN/$b" | awk '/=>/{print $3}'; done | sort -u \
  | grep -vE '/lib(c|m|resolv)\.so|/ld-linux' | while read -r l; do cp -L "$l" "$R/libs/"; done
cp "$SRC_MOD"/plpgsql.so "$SRC_MOD"/dict_snowball.so "$SRC_MOD"/*_and_*.so "$R/usr/lib/postgresql/17/lib/" 2>/dev/null || true
cp -rL "$SRC_SHARE/." "$R/usr/share/postgresql/17/"
rm -rf "$R/usr/share/postgresql/17/man"
find "$R/usr/share/postgresql/17/extension" -type f ! -name 'plpgsql*' -delete
chmod -R a+rX "$R"
du -sk "$R" | awk '{print "bundle " $1 " kB"}'
