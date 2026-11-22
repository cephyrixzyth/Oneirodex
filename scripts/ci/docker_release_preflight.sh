#!/usr/bin/env bash
set -euo pipefail

# Refuse operator workstations before touching Docker, files or credentials.
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux ||
      "${GITHUB_REPOSITORY:-}" != cephyrixzyth/Oneirodex ||
      "${RELEASE_DOCKER_PREFLIGHT_ALLOWED:-}" != 1 ||
      ! "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ || "$EUID" -eq 0 ||
      "$(uname -s)" != Linux || -e .env ]]; then
    echo 'Container verification requires explicitly selected disposable CI.' >&2
    exit 78
fi
[[ "${GITHUB_SHA:-}" =~ ^[a-f0-9]{40}$ && -d "${RUNNER_TEMP:-}" ]]

name="oneirodex-release-${GITHUB_RUN_ID}-${RANDOM}"
marker="$(openssl rand -hex 16)"
env_file="$(mktemp "$RUNNER_TEMP/oneirodex-release-env.XXXXXX")"
cleanup() {
    if [[ "$(docker inspect -f '{{index .Config.Labels "oneirodex.ci.owner"}}' "$name" 2>/dev/null || true)" == "$marker" ]]; then
        docker rm -fv "$name" >/dev/null
    fi
    rm -f -- "$env_file"
}
trap cleanup EXIT
! docker container inspect "$name" >/dev/null 2>&1
cp .env.docker.example "$env_file"
chmod 600 "$env_file"
export SECRET_KEY="$(openssl rand -hex 32)"
echo 'Image preflight: fresh embedded-database startup.'
docker run -d --name "$name" --label "oneirodex.ci.owner=$marker" \
    --env-file "$env_file" -e SECRET_KEY \
    -e ONEIRODEX_EMBEDDED_DB=true -e POSTGRES_DB=oneirodex_release_preflight_test \
    -e DATABASE_HOST= -e DATABASE_URL= -e DATA_FOLDER_GAMES=/storage \
    -e ONEIRODEX_LIBRARY_DIR=/config/library -e LIBRARY_HOST_PATH=/config/library \
    -e ONEIRODEX_ENABLE_BACKGROUND_WORKERS=false -e ENABLE_EMAIL_DIGEST=false \
    -e ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE=/config/secrets/store-keyring.json \
    -e ONEIRODEX_SAVE_KEYRING_FILE=/config/secrets/save-keyring.json \
    --tmpfs /config:rw,size=1073741824,mode=0755 --tmpfs /storage:ro,size=1048576,mode=0555 \
    -p 127.0.0.1::5006 oneirodex:release-preflight >/dev/null
binding="$(docker port "$name" 5006/tcp)"
[[ "$binding" =~ ^127\.0\.0\.1:[0-9]+$ ]]
base="http://$binding"
echo 'Image preflight: waiting for readiness.'
ready=false
for attempt in $(seq 1 90); do
    if curl --fail --silent --max-time 2 "$base/awake" >/dev/null; then ready=true; break; fi
    sleep 2
done
if [[ "$ready" != true ]]; then
    docker inspect -f 'Container status={{.State.Status}} exit={{.State.ExitCode}}' "$name"
    exit 1
fi
echo 'Image preflight: served icon and packaged SPA inventories.'
curl --fail --silent --max-time 10 "$base/static/icons/oneirodex-512.png" > "$RUNNER_TEMP/oneirodex-preflight-icon.png"
cmp oneirodex/static/icons/oneirodex-512.png "$RUNNER_TEMP/oneirodex-preflight-icon.png"
docker exec -e EXPECTED_SOURCE_SHA="$GITHUB_SHA" -e EXPECTED_RELEASE_VERSION="$(cat VERSION)" "$name" python3 -c '
import hashlib, json, os
from pathlib import Path
root=Path("/app/oneirodex/static/dist")
manifest=json.loads((root/"server-ui-manifest.json").read_text())
assert manifest["source_commit"] == os.environ["EXPECTED_SOURCE_SHA"]
assert Path("/app/VERSION").read_text().strip() == os.environ["EXPECTED_RELEASE_VERSION"]
assert set(manifest["targets"]) == {"member-app","member-auth","admin-app","admin-pilot","ops-glance"}
for target, data in manifest["targets"].items():
    for item in data["files"]:
        assert hashlib.sha256((root/target/item["path"]).read_bytes()).hexdigest() == item["sha256"]
print(json.dumps({"source_commit":manifest["source_commit"],"version":Path("/app/VERSION").read_text().strip(),
    "spa_targets":sorted(manifest["targets"]),"startup_architecture":"linux/amd64","awake_http":200,
    "architectures_built":["linux/amd64","linux/arm64"],"served_icon_matches_source":True}))
' > "$RUNNER_TEMP/oneirodex-image-preflight.json"
cleanup
! docker container inspect "$name" >/dev/null 2>&1
python3 -c 'import json,os; from pathlib import Path; p=Path(os.environ["RUNNER_TEMP"])/"oneirodex-image-preflight.json"; d=json.loads(p.read_text()); d.update(status="passed",container_removed=True); p.write_text(json.dumps(d,indent=2)+"\n"); print(json.dumps(d))'
