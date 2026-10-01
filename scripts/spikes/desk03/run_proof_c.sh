#!/usr/bin/env bash
# DESK-03 proof C: move a standalone (PostgreSQL) install to a household server,
# verify it row for row, and rehearse every rollback path.
#
# Everything runs in throwaway containers on an --internal Docker network (no
# internet). Nothing touches the repo, the live .env (masked by an empty file)
# or any running staging stack. Output and evidence land in $WORK.
#
#   bash scripts/spikes/desk03/run_proof_c.sh
set -uo pipefail
export MSYS_NO_PATHCONV=1

REPO=${REPO:-C:/Apps/Oneirodex}
WORK=${WORK:-$REPO/.artifacts/p05/proof-c}
NET=p05c-net SRC=p05c-src DST=p05c-dst PW=spike-only-pw
APPIMG=${APPIMG:-oneirodex:p04-tests} PGIMG=${PGIMG:-postgres:17.6}
SRCURL="postgresql://postgres:$PW@$SRC:5432/oneirodex_standalone"
DSTURL="postgresql://postgres:$PW@$DST:5432/oneirodex_household"
SRC_ROOTS=(--root games=/mnt/standalone/games --root saves=/work/standalone/saves)
DST_ROOTS=(--root games=/mnt/user/games --root saves=/srv/oneirodex/saves)
FAILS=0

cleanup() { docker rm -f -v "$SRC" "$DST" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
trap cleanup EXIT
now() { date +%s%3N; }
step() { printf '\n== %s\n' "$*"; }
expect_ok() { if "$@"; then echo "PASS"; else echo "FAIL (expected success)"; FAILS=$((FAILS + 1)); fi; }
# A refusal is exit status 1 exactly; 2 (usage) or a crash is a broken rehearsal.
expect_fail() { "$@"; local rc=$?; if [ $rc -eq 1 ]; then echo "PASS (refused as expected)"; else echo "FAIL (expected exit 1, got $rc)"; FAILS=$((FAILS + 1)); fi; }
py() {  # py ENV_URL args...  — the spike tools in the app test image
  local url=$1; shift
  docker run --rm --network "$NET" -v "$REPO:/app:ro" -v "$WORK/empty.env:/app/.env:ro" -v "$WORK:/work" \
    -e PYTHONDONTWRITEBYTECODE=1 -e SECRET_KEY=spike-only -e DATABASE_URL="$url" -e SAVES_ROOT=/work/standalone/saves \
    -w /app --entrypoint python "$APPIMG" "$@"
}
tool() { py "$1" scripts/spikes/desk03/household_move.py "${@:2}"; }
wait_pg() { for _ in $(seq 1 60); do docker exec "$1" pg_isready -h 127.0.0.1 -U postgres -q && return 0; sleep 1; done; return 1; }

cleanup
rm -rf "$WORK/standalone" "$WORK/household" "$WORK/bundle" "$WORK/bundle-tampered" "$WORK/logs"
mkdir -p "$WORK/standalone/saves" "$WORK/household/saves" "$WORK/bundle" "$WORK/logs"
: > "$WORK/empty.env"

step "start throwaway source (standalone) and target (household) PostgreSQL 17 on an internal network"
docker network create --internal "$NET" >/dev/null
docker run -d --name "$SRC" --network "$NET" -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=oneirodex_standalone \
  -v "$WORK/bundle:/bundle" "$PGIMG" >/dev/null
docker run -d --name "$DST" --network "$NET" -e POSTGRES_PASSWORD=$PW -e POSTGRES_DB=oneirodex_household \
  -v "$WORK/bundle:/bundle:ro" "$PGIMG" >/dev/null
expect_ok wait_pg "$SRC"; expect_ok wait_pg "$DST"

step "standalone: schema at head, representative data"
expect_ok py "$SRCURL" -m alembic upgrade head
expect_ok py "$SRCURL" scripts/spikes/desk03/seed_standalone.py

step "export: identity snapshot, pg_dump -Fc, bundle with file checksums"
t0=$(now)
expect_ok tool "$SRCURL" snapshot "${SRC_ROOTS[@]}" --files saves=/work/standalone/saves --out /work/logs/source-before.json
expect_ok docker exec "$SRC" pg_dump -U postgres -Fc -f /bundle/db.dump oneirodex_standalone
expect_ok tool "$SRCURL" pack --snapshot /work/logs/source-before.json --bundle /work/bundle --files saves=/work/standalone/saves
t1=$(now); echo "export took $((t1 - t0)) ms"

step "the export did not change the source"
expect_ok tool "$SRCURL" snapshot "${SRC_ROOTS[@]}" --files saves=/work/standalone/saves --out /work/logs/source-after-export.json
expect_ok cmp -s "$WORK/logs/source-before.json" "$WORK/logs/source-after-export.json"

step "import: bundle integrity first, then one-transaction restore, files, path remap, verification"
t0=$(now)
expect_ok tool "$DSTURL" check-bundle --bundle /work/bundle
expect_ok docker exec "$DST" pg_restore -U postgres -d oneirodex_household --single-transaction --exit-on-error --no-owner /bundle/db.dump
expect_ok tool "$DSTURL" unpack-files --bundle /work/bundle --files saves=/work/household/saves
expect_ok tool "$DSTURL" remap --bundle /work/bundle "${DST_ROOTS[@]}"
expect_ok tool "$DSTURL" verify --bundle /work/bundle "${DST_ROOTS[@]}" --files saves=/work/household/saves
t1=$(now); echo "import + verify took $((t1 - t0)) ms"
expect_ok py "$DSTURL" -m alembic current

step "rehearsal 1: a tampered bundle is refused before anything is restored"
cp -r "$WORK/bundle" "$WORK/bundle-tampered"
victim=$(find "$WORK/bundle-tampered/files" -type f | head -1)
printf 'X' | dd of="$victim" bs=1 seek=0 conv=notrunc status=none
expect_fail tool "$DSTURL" check-bundle --bundle /work/bundle-tampered

step "rehearsal 2: a restore that fails part-way leaves the target exactly as it was"
docker exec "$DST" createdb -U postgres oneirodex_household_conflict
docker exec "$DST" psql -U postgres -d oneirodex_household_conflict -qc 'CREATE TABLE games (x int)'
expect_fail docker exec "$DST" pg_restore -U postgres -d oneirodex_household_conflict --single-transaction --exit-on-error --no-owner /bundle/db.dump
tables=$(docker exec "$DST" psql -U postgres -d oneirodex_household_conflict -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "tables in the conflicting target after the failed restore: $tables (1 = only the pre-existing one)"
expect_ok test "$tables" = 1

step "rehearsal 3: a remap with the wrong root names changes nothing"
expect_fail tool "$DSTURL" remap --bundle /work/bundle --root library=/elsewhere
expect_ok tool "$DSTURL" verify --bundle /work/bundle "${DST_ROOTS[@]}" --files saves=/work/household/saves

step "rehearsal 4: verification catches drift after the move"
docker exec "$DST" psql -U postgres -d oneirodex_household -qc "UPDATE games SET name = name || ' (edited)' WHERE slug = 'spike-game-00'"
expect_fail tool "$DSTURL" verify --bundle /work/bundle "${DST_ROOTS[@]}"

step "rehearsal 5: rolling back the move is dropping the target; the source is untouched"
docker exec "$DST" dropdb -U postgres oneirodex_household
expect_ok tool "$SRCURL" snapshot "${SRC_ROOTS[@]}" --files saves=/work/standalone/saves --out /work/logs/source-final.json
expect_ok cmp -s "$WORK/logs/source-before.json" "$WORK/logs/source-final.json"

step "sizes"
du -sh "$WORK/bundle" "$WORK/bundle/db.dump" 2>/dev/null
printf '\nproof C: %s\n' "$([ $FAILS -eq 0 ] && echo 'ALL CHECKS PASSED' || echo "$FAILS CHECK(S) FAILED")"
exit $FAILS
