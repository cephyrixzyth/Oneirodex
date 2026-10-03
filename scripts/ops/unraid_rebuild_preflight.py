#!/usr/bin/env python3
"""Unraid preflight before compose rebuild. No secrets."""
from __future__ import annotations

import subprocess
import sys

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "root@192.168.50.116"]
SCRIPT = r"""
set -eu
echo '=== df ==='
df -h /var/lib/docker /mnt/user /mnt/cache 2>/dev/null || df -h | head -15
echo '=== containers ==='
docker ps --format '{{.Names}} {{.Status}}' | grep -E 'oneirodex-|oneirodex-|authentik' || true
echo '=== active scans ==='
if docker inspect oneirodex-db >/dev/null 2>&1 && docker exec oneirodex-db pg_isready -U postgres >/dev/null 2>&1; then
  docker exec oneirodex-db psql -U postgres -d oneirodex -c "SELECT id, status, LEFT(scan_folder, 70) AS folder, total_folders, folders_success, folders_failed FROM scan_jobs WHERE status IN ('Running','Queued','Stopping') ORDER BY id;"
else
  docker exec oneirodex-app bash -c 'export PGPASSWORD="$(cat /config/secrets/db_password)"; psql -h 127.0.0.1 -p 55432 -U oneirodex -d oneirodex -c "SELECT id, status, LEFT(scan_folder, 70) AS folder, total_folders, folders_success, folders_failed FROM scan_jobs WHERE status IN ('\''Running'\'','\''Queued'\'','\''Stopping'\'') ORDER BY id;"'
fi
echo '=== tree files ==='
ls -l /mnt/user/infernal-data-streams/_projects/Oneirodex/oneirodex/setup/default_theme/js/scanJobsDom.js
grep -n 'scanJobsDom.js' /mnt/user/infernal-data-streams/_projects/Oneirodex/Dockerfile || echo 'Dockerfile missing scanJobsDom COPY'
echo '=== live scanjobs asset (before) ==='
curl -sS -o /dev/null -w 'scanJobsDom=%{http_code}\n' http://127.0.0.1:5006/static/library/themes/default/js/scanJobsDom.js || true
curl -sS -o /dev/null -w 'pulse=%{http_code}\n' http://127.0.0.1:5006/pulse || true
"""


def main() -> int:
    run = subprocess.run(SSH + ["bash", "-s"], input=SCRIPT.encode())
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
