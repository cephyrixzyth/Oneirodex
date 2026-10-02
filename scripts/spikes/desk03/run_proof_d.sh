#!/usr/bin/env bash
# DESK-04 proof D: the standalone launcher end to end on Linux, offline, as an
# unprivileged user, with the install read-only — first run, health, runtime
# files in the data folder and served from it, database crash restart, clean
# stop on SIGTERM, second start reusing the data, portable collation, no
# secrets logged.
#
#   bash scripts/spikes/desk03/run_proof_d.sh
set -uo pipefail
export MSYS_NO_PATHCONV=1
REPO=${REPO:-C:/Apps/Oneirodex}
IMG=oneirodex:standalone-proof C=p05d-standalone VOL=p05d-data
FAILS=0
cleanup() { docker rm -f -v "$C" >/dev/null 2>&1; docker volume rm "$VOL" >/dev/null 2>&1; }
trap cleanup EXIT
ok() { if "$@"; then echo "PASS"; else echo "FAIL"; FAILS=$((FAILS + 1)); fi; }
inside() { docker exec "$C" python -c "$1"; }
awake() {  # wait up to $1 s for /awake 200
  inside "
import time, urllib.request
for _ in range($1):
    try:
        if urllib.request.urlopen('http://127.0.0.1:5006/awake', timeout=3).status == 200: raise SystemExit(0)
    except Exception: pass
    time.sleep(1)
raise SystemExit(1)"
}
sql() {  # one value from the standalone database, using the launcher's own state file
  inside "
import json, psycopg2
s = json.load(open('/data/standalone.json'))
c = psycopg2.connect(host='127.0.0.1', port=s['db_port'], user='oneirodex', password=s['db_password'], dbname='oneirodex')
cur = c.cursor(); cur.execute(\"\"\"$1\"\"\"); print(cur.fetchone()[0])"
}

cleanup
echo "== build throwaway image (app image + relocated PostgreSQL 17 bundle)"
ok docker build -q -t "$IMG" "$REPO/scripts/spikes/desk03/proof_d" >/dev/null
docker run --rm --entrypoint sh "$IMG" -c 'du -sk /opt/oneirodex-postgres' | awk '{print "bundle in image: " $1 " kB"}'

echo "== first run: unprivileged user (nobody), no network, read-only install, working-tree code"
docker volume create "$VOL" >/dev/null
docker run --rm -v "$VOL:/data" --entrypoint sh "$IMG" -c 'chown 65534:65534 /data'
t0=$(date +%s)
docker run -d --name "$C" --network none --user 65534:65534 -e HOME=/data -e PYTHONDONTWRITEBYTECODE=1 \
  --read-only --tmpfs /tmp \
  -v "$REPO/oneirodex:/app/oneirodex:ro" -v "$REPO/oneirodex_standalone:/app/oneirodex_standalone:ro" \
  -v "$REPO/asgi.py:/app/asgi.py:ro" -v "$REPO/config.py:/app/config.py:ro" -v "$VOL:/data" -w /app --entrypoint python "$IMG" \
  -m oneirodex_standalone --pg-home /opt/oneirodex-postgres --data-dir /data --port 5006 >/dev/null
ok awake 240
echo "healthy $(( $(date +%s) - t0 )) s after start (includes initdb and migrations)"
ok test "$(sql 'SELECT version_num FROM alembic_version')" = a7c1d9e2f3b4
echo "collation: $(sql "SELECT datlocprovider::text || ' ' || coalesce(datlocale, '-') || ' ' || datcollate FROM pg_database WHERE datname = 'oneirodex'")"
ok test "$(sql "SELECT datlocprovider::text || datlocale FROM pg_database WHERE datname = 'oneirodex'")" = "bC.UTF-8"
ok test "$(docker exec "$C" stat -c %a /data/standalone.json)" = 600

echo "== runtime files land in the data folder and are served from it"
ok docker exec "$C" test -s /data/library/themes/default/css/od-tokens.css
ok docker exec "$C" sh -c 'ls /data/library/icon-themes/*/manifest.json >/dev/null'
ok docker exec "$C" test -d /data/library/fonts
ok inside "
import urllib.request
body = urllib.request.urlopen('http://127.0.0.1:5006/static/library/themes/default/css/od-tokens.css', timeout=5).read()
assert body == open('/data/library/themes/default/css/od-tokens.css', 'rb').read()"
mark=$(docker exec "$C" sh -c 'cd /data/library && ls system-marks/*/*.webp | head -1')
echo "shipped art copied into the data folder: $mark"
ok inside "
import urllib.request
assert urllib.request.urlopen('http://127.0.0.1:5006/static/library/$mark', timeout=5).status == 200"
docker logs "$C" 2>&1 | grep -iE 'read-only file system|\[ERR\]' | head -5
ok bash -c "! docker logs $C 2>&1 | grep -qiE 'read-only file system|\[ERR\]'"

echo "== the supervisor restarts a database that dies"
pid=$(docker exec "$C" head -1 /data/pgdata/postmaster.pid)
docker exec "$C" sh -c "kill -9 $pid"
ok awake 60
docker logs "$C" 2>&1 | grep -q 'restarting it' && echo "restart logged" || { echo "FAIL: no restart logged"; FAILS=$((FAILS + 1)); }

echo "== SIGTERM stops the server and the database cleanly"
docker stop -t 60 "$C" >/dev/null
docker logs "$C" 2>&1 | tail -3
ok bash -c "docker logs $C 2>&1 | grep -q '\[standalone\] stopped'"
ok bash -c "docker run --rm -v $VOL:/data --entrypoint sh $IMG -c 'tail -5 /data/logs/postgres.log' | grep -q 'database system is shut down'"

echo "== second start reuses the data folder"
docker start "$C" >/dev/null
ok awake 120
ok bash -c "! docker logs $C 2>&1 | grep -c '(created)' | grep -q '^2$'"
ok test "$(sql 'SELECT version_num FROM alembic_version')" = a7c1d9e2f3b4

echo "== nothing secret in the logs"
secret=$(docker exec "$C" python -c "import json;print(json.load(open('/data/standalone.json'))['db_password'])")
key=$(docker exec "$C" python -c "import json;print(json.load(open('/data/standalone.json'))['secret_key'])")
logs=$( { docker logs "$C" 2>&1; docker exec "$C" cat /data/logs/postgres.log; } )
ok bash -c "! grep -qF -- '$secret' <<<\"\$0\" && ! grep -qF -- '$key' <<<\"\$0\"" "$logs"
docker stop -t 60 "$C" >/dev/null

printf '\nproof D: %s\n' "$([ $FAILS -eq 0 ] && echo 'ALL CHECKS PASSED' || echo "$FAILS CHECK(S) FAILED")"
exit $FAILS
