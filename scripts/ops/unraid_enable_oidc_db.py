#!/usr/bin/env python3
"""Turn on GlobalSettings.oidc_enabled after Unraid app is up. Does not print secrets."""
from __future__ import annotations

import subprocess
import sys

SSH = ["ssh", "-o", "BatchMode=yes", "root@192.168.50.116"]
SCRIPT = r"""
set -eu
sql="UPDATE global_settings
SET oidc_enabled = true,
    oidc_issuer_url = 'http://192.168.50.116:9000/application/o/oneirodex/',
    oidc_client_id = 'oneirodex',
    oidc_redirect_uri = 'http://192.168.50.116:5006/login/oidc/callback',
    oidc_scopes = 'openid email profile groups',
    oidc_role_claim = 'groups',
    oidc_display_name = 'Sign in with SSO'
WHERE id = (SELECT MIN(id) FROM global_settings);"
if docker inspect oneirodex-db >/dev/null 2>&1 && docker exec oneirodex-db pg_isready -U postgres >/dev/null 2>&1; then
  docker exec oneirodex-db psql -U postgres -d oneirodex -v ON_ERROR_STOP=1 -c "$sql"
  docker exec oneirodex-db psql -U postgres -d oneirodex -tAc \
    "SELECT id, oidc_enabled, oidc_client_id, oidc_issuer_url IS NOT NULL AS has_issuer FROM global_settings ORDER BY id LIMIT 1;"
else
  docker exec oneirodex-app bash -c 'export PGPASSWORD="$(cat /config/secrets/db_password)"; psql -h 127.0.0.1 -p 55432 -U oneirodex -d oneirodex -v ON_ERROR_STOP=1 -c "$1"' _ "$sql"
  docker exec oneirodex-app bash -c 'export PGPASSWORD="$(cat /config/secrets/db_password)"; psql -h 127.0.0.1 -p 55432 -U oneirodex -d oneirodex -tAc "SELECT id, oidc_enabled, oidc_client_id, oidc_issuer_url IS NOT NULL AS has_issuer FROM global_settings ORDER BY id LIMIT 1;"'
fi
"""


def main() -> int:
    run = subprocess.run(SSH + ["bash", "-s"], input=SCRIPT.encode())
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
