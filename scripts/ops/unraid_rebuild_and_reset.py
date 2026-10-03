#!/usr/bin/env python3
"""Unraid compose rebuild from the live NAS tree (no git pull). Reset themes, verify hang-fix assets."""
from __future__ import annotations

import subprocess
import sys

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", "root@192.168.50.116"]
REPO = "/mnt/user/infernal-data-streams/_projects/Oneirodex"
SCRIPT = rf"""
set -eu
cd {REPO}
echo '=== HEAD (uncommitted tree is the build context) ==='
git -c safe.directory={REPO} log -1 --oneline || true
git -c safe.directory={REPO} status -sb || true
echo '=== compose config services ==='
docker compose config --services
echo '=== build + up (livekit clamav challenge; no artwork) ==='
docker compose --profile livekit --profile clamav --profile challenge up -d --build
echo '=== ps ==='
docker compose --profile livekit --profile clamav --profile challenge ps
echo '=== wait awake ==='
ok=0
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:5006/awake >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:5006/awake
    echo
    ok=1
    break
  fi
  sleep 2
done
test "$ok" = 1
echo '=== reset default themes ==='
docker exec -i oneirodex-app python - < {REPO}/scripts/ops/unraid_reset_themes.py
echo '=== verify hang-fix assets ==='
curl -sS -o /dev/null -w 'scanJobsDom=%{{http_code}}\n' http://127.0.0.1:5006/static/library/themes/default/js/scanJobsDom.js
curl -sS http://127.0.0.1:5006/static/library/themes/default/js/admin_manage_scanjobs.js | grep -c 'patchScanJobProgressRows' | awk '{{print "patchScanJobProgressRows_hits="$1}}'
curl -sS http://127.0.0.1:5006/static/library/themes/default/js/scanJobsDom.js | grep -c 'scanJobsPollMs' | awk '{{print "scanJobsPollMs_hits="$1}}'
curl -sS http://127.0.0.1:5006/static/library/themes/default/css/od-shell.css | grep -c 'od-topnav__dropdown-panel' | awk '{{print "dropdown_panel_hits="$1}}'
echo '--- spa hashes ---'
curl -fsS http://127.0.0.1:5006/ | grep -oE 'member-app[^" ]+\.(css|js)' | head -n 8 || true
curl -fsS http://127.0.0.1:5006/admin/ | grep -oE 'admin-app[^" ]+\.(css|js)' | head -n 8 || true
docker exec oneirodex-app python -c "from oneirodex.utils.preset_themes import GENERATOR_VERSION; print('GENERATOR_VERSION='+str(GENERATOR_VERSION))"
echo '=== containers (names must stay oneirodex-*) ==='
docker ps --format '{{.Names}} {{.Status}}' | grep -E 'oneirodex-|oneirodex-|authentik' || true
echo '=== DONE ==='
"""


def main() -> int:
    run = subprocess.run(SSH + ["bash", "-s"], input=SCRIPT.encode())
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
