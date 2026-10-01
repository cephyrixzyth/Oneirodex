#!/usr/bin/env bash
# DESK-05 proof E: the supported move command end to end.
#
# A real standalone install (launcher + bundled PostgreSQL 17) with Windows-style
# game paths, artwork, a generated pack, an uploaded theme and encrypted saves is
# exported with `python -m oneirodex_standalone export`, imported into an empty
# database on a separate PostgreSQL 17 server whose SECRET_KEY differs, checked,
# and then served by the real server. Every refusal is rehearsed and must exit
# exactly 1 and change nothing. Throwaway containers and volumes only; no
# internet (the server network is --internal, the standalone has none).
#
#   bash scripts/spikes/desk03/run_proof_e.sh
set -uo pipefail
export MSYS_NO_PATHCONV=1
REPO=${REPO:-C:/Apps/Oneirodex}
IMG=oneirodex:standalone-proof PGIMG=postgres:17.6
NET=p05e-net DB=p05e-db SA=p05e-standalone SRV=p05e-server
VOLS=(p05e-data p05e-move p05e-library)
PW=proof-only-pw SERVER_SECRET=proof-only-server-secret
TARGET="postgresql://postgres:$PW@$DB:5432/oneirodex_moved"
BUSY="postgresql://postgres:$PW@$DB:5432/oneirodex"
PGHOME=/opt/oneirodex-postgres PGBIN=/opt/oneirodex-postgres/usr/lib/postgresql/17/bin
CODE=(-v "$REPO/oneirodex:/app/oneirodex:ro" -v "$REPO/oneirodex_standalone:/app/oneirodex_standalone:ro"
      -v "$REPO/asgi.py:/app/asgi.py:ro" -v "$REPO/config.py:/app/config.py:ro" -v "$REPO/scripts:/app/scripts:ro")
FAILS=0

cleanup() { docker rm -f -v "$SA" "$DB" "$SRV" >/dev/null 2>&1; docker volume rm "${VOLS[@]}" >/dev/null 2>&1
            docker network rm "$NET" >/dev/null 2>&1; }
trap cleanup EXIT
ok() { if "$@"; then echo "PASS"; else echo "FAIL"; FAILS=$((FAILS + 1)); fi; }
refused() { "$@"; local rc=$?; if [ $rc -eq 1 ]; then echo "PASS (refused)"; else echo "FAIL (expected exit 1, got $rc)"; FAILS=$((FAILS + 1)); fi; }
# The standalone machine: user nobody, no network, read-only install.
standalone() { docker run --rm --network none --user 65534:65534 -e HOME=/data -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app -e SECRET_KEY=unused \
  --read-only --tmpfs /tmp "${CODE[@]}" -v p05e-data:/data -v p05e-move:/move -w /app --entrypoint python "$IMG" "$@"; }
# The server's app container: PostgreSQL 17 client tools, the server library volume, the move folder read-only.
server() { docker run --rm --network "$NET" -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app "${CODE[@]}" \
  -v p05e-move:/move:ro -v p05e-library:/srv/library -w /app "$@"; }
# import_ DOCKER_ENV... -- IMPORT_ARGS...  (pg_restore from the bundle; move finds its libs)
import_() { local env=(); while [ "$1" != -- ]; do env+=("$1"); shift; done; shift
  server "${env[@]}" --entrypoint python "$IMG" -m oneirodex_standalone import /move/bundle --expect "$FP" \
    --library-dir /srv/library --pg-bin $PGBIN "$@"; }
check() { server -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET --entrypoint python "$IMG" scripts/spikes/desk03/proof_e/check_server.py "$@"; }
awake() { docker exec "$1" python -c "
import time, urllib.request
for _ in range($2):
    try:
        if urllib.request.urlopen('http://127.0.0.1:5006/awake', timeout=3).status == 200: raise SystemExit(0)
    except Exception: pass
    time.sleep(1)
raise SystemExit(1)"; }

cleanup
echo "== images and throwaway volumes"
ok docker build -q -t "$IMG" "$REPO/scripts/spikes/desk03/proof_d" >/dev/null
for v in "${VOLS[@]}"; do docker volume create "$v" >/dev/null; done
docker run --rm -v p05e-data:/data -v p05e-move:/move --entrypoint sh "$IMG" -c 'chown 65534:65534 /data /move'

echo "== standalone: first start, then export is refused while it runs"
docker run -d --name "$SA" --network none --user 65534:65534 -e HOME=/data -e PYTHONDONTWRITEBYTECODE=1 --read-only --tmpfs /tmp \
  "${CODE[@]}" -v p05e-data:/data -v p05e-move:/move -w /app --entrypoint python "$IMG" \
  -m oneirodex_standalone --pg-home $PGHOME --data-dir /data --port 5006 >/dev/null
ok awake "$SA" 240
refused docker exec "$SA" python -m oneirodex_standalone export --pg-home $PGHOME --data-dir /data --to /move/while-running
docker stop -t 60 "$SA" >/dev/null && docker rm "$SA" >/dev/null

echo "== standalone: seed data worth moving (Windows-style game folder, encrypted saves)"
ok standalone scripts/spikes/desk03/proof_e/seed.py

echo "== export"
# The trailing separator is deliberate: it must not change which paths match.
out=$(standalone -m oneirodex_standalone export --pg-home $PGHOME --data-dir /data --to /move/bundle --root 'games=C:\Games\')
ok test $? -eq 0
echo "$out"
FP=$(sed -n 's/^fingerprint: //p' <<<"$out")
ok test ${#FP} -eq 64
refused standalone -m oneirodex_standalone export --pg-home $PGHOME --data-dir /data --to /move/bundle --root 'games=C:\Games'

echo "== server: PostgreSQL 17 on an internal network; the target is a new empty database"
docker network create --internal "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=oneirodex "$PGIMG" >/dev/null
for _ in $(seq 1 60); do docker exec "$DB" pg_isready -h 127.0.0.1 -U postgres -q && break; sleep 1; done
docker exec "$DB" psql -U postgres -h 127.0.0.1 -qc 'CREATE DATABASE oneirodex_moved'
docker exec "$DB" psql -U postgres -h 127.0.0.1 -d oneirodex -qc 'CREATE TABLE busy (id int)'

echo "== refusals: each exits 1 and leaves the target untouched"
refused import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET --                           # games folder not named
refused import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET -- --root games=/elsewhere/x --root extra=/y
refused import_ -e DATABASE_URL="$TARGET" -- --root games=/mnt/user/games                               # encrypted saves, no key
refused import_ -e DATABASE_URL="$BUSY" -e SECRET_KEY=$SERVER_SECRET -- --root games=/mnt/user/games    # target not empty
first=$(docker run --rm -v p05e-move:/move --entrypoint python "$IMG" -c "import json;print(json.load(open('/move/bundle/manifest.json'))['files'][0]['path'])")
docker run --rm -v p05e-library:/srv/library --entrypoint sh "$IMG" -c "mkdir -p \"\$(dirname '/srv/library/$first')\" && echo other > '/srv/library/$first'"
refused import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET -- --root games=/mnt/user/games  # file conflict
docker run --rm -v p05e-library:/srv/library --entrypoint sh "$IMG" -c 'rm -rf /srv/library/* && chown 0:0 /srv/library'
docker run --rm -v p05e-move:/move --entrypoint sh "$IMG" -c 'rm -rf /move/tampered && cp -a /move/bundle /move/tampered &&
  f=$(ls /move/tampered/files/saves/*/*/slot1.sav | head -1) && printf x >> "$f"'
refused server -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET --entrypoint python "$IMG" \
  -m oneirodex_standalone import /move/tampered --expect "$FP" --library-dir /srv/library --root games=/mnt/user/games --pg-bin $PGBIN
# Changed and re-sealed so every checksum in the folder agrees: only the fingerprint from export catches it.
docker run --rm -v p05e-move:/move --entrypoint python "$IMG" -c "
import hashlib, json, shutil
shutil.rmtree('/move/resealed', ignore_errors=True)
shutil.copytree('/move/bundle', '/move/resealed')
m = json.load(open('/move/resealed/manifest.json'))
e = next(x for x in m['files'] if x['path'].startswith('images/'))
open('/move/resealed/files/' + e['path'], 'wb').write(b'planted')
e['sha256'] = hashlib.sha256(b'planted').hexdigest()
raw = json.dumps(m, indent=2, sort_keys=True)
open('/move/resealed/manifest.json', 'w').write(raw)
open('/move/resealed/manifest.sha256', 'w').write(hashlib.sha256(raw.encode()).hexdigest() + '\n')"
refused server -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET --entrypoint python "$IMG" \
  -m oneirodex_standalone import /move/resealed --expect "$FP" --library-dir /srv/library --root games=/mnt/user/games --pg-bin $PGBIN
ok check untouched

echo "== import"
ok import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET -- --root games=/mnt/user/games
ok check moved
refused import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET -- --root games=/mnt/user/games  # already imported

echo "== roll back (drop the database), then the same import again: the files it left behind are accepted"
docker exec "$DB" psql -U postgres -h 127.0.0.1 -qc 'DROP DATABASE oneirodex_moved WITH (FORCE)' -c 'CREATE DATABASE oneirodex_moved'
ok import_ -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET -- --root games=/mnt/user/games
ok check moved

echo "== the standalone install is unchanged by the move"
ok standalone -m oneirodex_standalone export --pg-home $PGHOME --data-dir /data --to /move/after --root 'games=C:\Games'
ok docker run --rm -v p05e-move:/move --entrypoint python "$IMG" -c "
import json
a, b = (json.load(open(f'/move/{n}/manifest.json')) for n in ('bundle', 'after'))
assert a['db'] == b['db'] and a['files'] == b['files'], 'standalone changed'"

echo "== the real server starts on the moved data and serves a moved file"
docker run -d --name "$SRV" --network "$NET" -e PYTHONDONTWRITEBYTECODE=1 -e DATABASE_URL="$TARGET" -e SECRET_KEY=$SERVER_SECRET \
  -e ONEIRODEX_LIBRARY_DIR=/srv/library -e SESSION_COOKIE_SECURE=false "${CODE[@]}" -v p05e-library:/srv/library -w /app \
  --entrypoint sh "$IMG" -c 'python -c "import sys; from oneirodex.init_manager import run_complete_startup_initialization as r; sys.exit(0 if r() else 1)" &&
  ONEIRODEX_INITIALIZATION_COMPLETE=true exec python -m uvicorn asgi:asgi_app --host 127.0.0.1 --port 5006' >/dev/null
ok awake "$SRV" 240
ok docker exec "$SRV" python -c "
import urllib.request
p = 'themes/proof-upload/css/base.css'
assert urllib.request.urlopen('http://127.0.0.1:5006/static/library/' + p, timeout=5).read() == open('/srv/library/' + p, 'rb').read()"
docker logs "$SRV" 2>&1 | grep -iE 'traceback|\[ERR\]' | head -5

echo "== rollback is dropping the target"
ok docker exec "$DB" psql -U postgres -h 127.0.0.1 -qc 'DROP DATABASE oneirodex_moved WITH (FORCE)'

printf '\nproof E: %s\n' "$([ $FAILS -eq 0 ] && echo 'ALL CHECKS PASSED' || echo "$FAILS CHECK(S) FAILED")"
exit $FAILS
