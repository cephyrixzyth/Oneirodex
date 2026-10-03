#!/usr/bin/env python3
"""Run Unraid compose rebuild with livekit/clamav/challenge profiles. No artwork GPU profile."""
from __future__ import annotations

import subprocess

SSH = ["ssh", "-o", "BatchMode=yes", "root@192.168.50.116"]
SCRIPT = r"""
set -eu
cd /mnt/user/infernal-data-streams/_projects/Oneirodex
echo '=== compose config services ==='
docker compose config --services
echo '=== build + up ==='
docker compose --profile livekit --profile clamav --profile challenge up -d --build
echo '=== ps ==='
docker compose --profile livekit --profile clamav --profile challenge ps
"""


def main() -> int:
    run = subprocess.run(SSH + ["bash", "-s"], input=SCRIPT.encode())
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
