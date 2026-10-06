#!/usr/bin/env python3
"""Merge Unraid product flags + Authentik OIDC into live .env. Does not print secrets."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ENV_PATH = Path(r"C:\Apps\Oneirodex\.env")
SSH = ["ssh", "-o", "BatchMode=yes", "root@192.168.50.116"]
SECRET_REMOTE = "/mnt/user/appdata/authentik/media/.oneirodex_oidc_secret"

UPSERT = {
    "APP_IMAGE": "oneirodex:1.1.1",
    "APP_CONTAINER_NAME": "oneirodex-app",
    "COMPOSE_FILE": "docker-compose.single.yml",
    "APPDATA_PATH": "/mnt/cache/appdata/oneirodex/config",
    "ENABLE_ARR_MODULE": "true",
    "ENABLE_ARR_HARDLINK_PIPELINE": "true",
    "ENABLE_AI_ASSIST": "true",
    "ENABLE_AI_AUTO_APPLY": "false",
    "ENABLE_HARDLINK_HELPERS": "true",
    "ALLOW_HARDLINK_APPLY": "false",
    "ENABLE_VR_BROWSE": "true",
    "ENABLE_AI_ARTWORK": "true",
    # No LIVEKIT_* here on purpose. This used to upsert ENABLE_LIVEKIT=true with
    # LIVEKIT_API_KEY=devkey / LIVEKIT_API_SECRET=secret and a LAN ws:// URL.
    # Those are the keys the compose `livekit` service's `--dev` mode has built
    # in, so they are not a secret that leaked -- but writing them here pushed a
    # dev posture onto a live host, overriding .env.unraid.example, which ships
    # LIVEKIT_API_KEY deliberately blank. With the server on `--bind 0.0.0.0`
    # and the port published on every interface, anyone on the LAN who reaches
    # :7880 can mint room tokens. Enabling LiveKit for real means dropping
    # `--dev` and setting real keys in the host .env, which is an operator
    # decision, not something a flags-merge script should make.
    "ENABLE_MALWARE_SCAN": "true",
    "ENABLE_GAME_ASSISTS": "true",
    "ENABLE_DEBRID": "true",
    "ENABLE_PCDOS_BROWSER": "true",
    "ENABLE_RUFFLE": "true",
    "ENABLE_ROM_PATCH_APPLY": "true",
    "ENABLE_PATCH_CATALOG": "true",
    "ENABLE_ROM_AI_TRANSLATE": "true",
    "ENABLE_MOD_TRACKING": "true",
    "ENABLE_ACTIVITY_FEED": "true",
    "ENABLE_FREE_GAMES": "true",
    "ENABLE_DISCOVER_ML": "true",
    "ENABLE_EMAIL_DIGEST": "true",
    "ENABLE_LOGIN_RATE_LIMIT": "true",
    "ENABLE_REMOTE_PLAY": "true",
    "ENABLE_AMBIENT_LIGHTING": "true",
    "ENABLE_CHALLENGE_SOLVER": "true",
    "CHALLENGE_SOLVER_URL": "http://trawl:8191",
    "OIDC_ENABLED": "true",
    "OIDC_ISSUER_URL": "http://192.168.50.116:9000/application/o/oneirodex/",
    "OIDC_CLIENT_ID": "oneirodex",
    "OIDC_REDIRECT_URI": "http://192.168.50.116:5006/login/oidc/callback",
    "OIDC_SCOPES": "openid email profile groups",
    "OIDC_ROLE_CLAIM": "groups",
    "OIDC_DISPLAY_NAME": "Sign in with SSO",
    "SESSION_COOKIE_SECURE": "false",
    "REMEMBER_COOKIE_SECURE": "false",
    "TRUSTED_PROXIES": "0",
}


def upsert(text: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    found = False
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix) or line.startswith(f"#{prefix}"):
            if not found:
                out.append(f"{key}={value}\n")
                found = True
            continue
        out.append(line)
    if not found:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"{key}={value}\n")
    return "".join(out)


def write_atomic(path: Path, text: str) -> Path:
    """Replace ``path`` in one step, keeping the previous contents in ``.bak``.

    The live ``.env`` holds SECRET_KEY, OIDC_CLIENT_SECRET and the database
    credentials. The old read-then-``write_text`` was not atomic: an interrupt
    between truncate and flush left a half-written file and no way back, which
    is exactly what CLAUDE.md means by never overwriting the root ``.env``.

    Write a sibling temp file, fsync it, then ``os.replace`` -- atomic on the
    same filesystem, on Windows as well as POSIX. The backup is taken first so
    it exists even if the replace is what fails.
    """
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        backup.write_bytes(path.read_bytes())

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup


def main() -> int:
    got = subprocess.run(
        SSH + [f"cat {SECRET_REMOTE}"],
        capture_output=True,
        check=True,
    )
    secret = got.stdout.decode().strip()
    if len(secret) < 16:
        raise SystemExit("OIDC secret file missing or too short")
    text = ENV_PATH.read_text(encoding="utf-8")
    for key, value in UPSERT.items():
        text = upsert(text, key, value)
    text = upsert(text, "OIDC_CLIENT_SECRET", secret)
    backup = write_atomic(ENV_PATH, text)
    keys = [ln.split("=", 1)[0] for ln in text.splitlines() if ln.startswith("ENABLE_") or ln.startswith("OIDC_")]
    print("patched", ENV_PATH.name, "flags", ",".join(keys))
    print("previous contents kept at", backup.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
