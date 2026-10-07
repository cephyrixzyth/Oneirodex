#!/bin/bash

# Docker-specific startup script for Oneirodex
# This script is designed to run inside the Docker container
set -e


# Parse arguments
FORCE_SETUP=false
if [[ "$1" == "--force-setup" || "$1" == "-fs" ]]; then
    FORCE_SETUP=true
fi

# We're already in /app directory in Docker, no need to cd

PORT="${PORT:-5006}"
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    printf '\033[0;32m'
fi
printf '%s\n' \
    '╭──────────────────────────────────────────────────────────────╮' \
    '│  Oneirodex  //  EXPEDITION DECK                 FIELD BOOT  │' \
    '╰──────────────────────────────────────────────────────────────╯' \
    '                         .-""""-.' \
    '                        /  .--.  \' \
    '                       |  (o  o)  |     ONEI' \
    '                       |    ∇     |     map scout · field guide' \
    '                        \  ____  /      d20 packed · radio tuned' \
    '                       .-|      |-.' \
    '                      /  |  []  |  \' \
    '                     /___|______|___\' \
    '                          /    \' \
    '                         /______\' \
    '  QUEST LOG // waking the deck and checking the trail markers...' \
    ''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    printf '\033[0m'
fi

if [[ "$FORCE_SETUP" == "true" ]]; then
    echo "🔄 Force setup mode - resetting database..."

    # Load environment for standalone execution
    python3 -c "
from dotenv import load_dotenv
load_dotenv()

from oneirodex import create_app, db
from oneirodex.utils.setup import reset_setup_state

# Create app and reset database
app = create_app()
with app.app_context():
    print('Dropping all tables...')
    db.drop_all()
    print('Recreating all tables...')
    db.create_all()
    print('Database reset complete.')

    reset_setup_state()
    print('Setup state reset - setup wizard will run on next startup')

print('Database reset complete. Restart the container to start the server.')
"
    exit 0
fi

echo "ONEI > The launch gate is coming online on port $PORT."

# The public preview keeps its redistributable sample ROMs on the configured
# persistent library volume. DATA_FOLDER_GAMES is also the app's safe download
# allowlist for the /api/downloadrom route.
if [[ "${ONEIRODEX_PUBLIC_DEMO:-false}" == "true" ]]; then
    DEMO_LIBRARY_DIR="${ONEIRODEX_LIBRARY_DIR:-/config/library}"
    export DATA_FOLDER_GAMES="${DATA_FOLDER_GAMES:-${DEMO_LIBRARY_DIR}/demo-games}"
fi

# Run complete startup initialization once before starting workers
python3 -c "
from oneirodex.init_manager import run_complete_startup_initialization
import sys

print('QUEST LOG // checking the camp ledger and preparing the worlds...')
if not run_complete_startup_initialization():
    print('FIELD ALERT // startup did not complete; see the log above.')
    sys.exit(1)
print('QUEST COMPLETE // initialization ready; opening the launch gate...')
"

# Render's free Docker service supplies PORT at runtime. The public demo uses
# the same image and keeps the normal Compose/Unraid port unchanged otherwise.
if [[ "${ONEIRODEX_PUBLIC_DEMO:-false}" == "true" ]]; then
    echo "QUEST LOG // preparing the public demo field kit..."
    if ! PYTHONPATH=/app python3 /app/scripts/fetch-free-roms.py \
        --out "${DATA_FOLDER_GAMES}" \
        --id nestest --id dmg-acid2 --id cascade7 --id genmddj --id atari2600-4paddle-tester; then
        echo "FIELD NOTE // some demo samples were unavailable; available samples will still be seeded."
    fi
    # Executing a file under /app/scripts puts that directory, not /app, at
    # sys.path[0]. Add the application root so the seed can import oneirodex.
    PYTHONPATH=/app python3 /app/scripts/seed_public_demo.py
fi

# Ensure environment variables are set for worker processes
export ONEIRODEX_MIGRATIONS_COMPLETE=true
export ONEIRODEX_INITIALIZATION_COMPLETE=true

# Start uvicorn for Docker (bind to all interfaces).
# Default 1 worker — SSE/schedulers, cache, login rate limit, and EventBus stay
# single-process. Override UVICORN_WORKERS=2+ only when you accept per-worker state
# (or after a shared cache lands).
WORKERS="${UVICORN_WORKERS:-1}"
exec uvicorn asgi:asgi_app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT:-5}"
