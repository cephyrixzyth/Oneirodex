#!/bin/bash


# Parse arguments
FORCE_SETUP=false
if [[ "$1" == "--force-setup" || "$1" == "-fs" ]]; then
    FORCE_SETUP=true
fi

cd "$(dirname "$0")"

python3 -m scripts.startup_art splash

source venv/bin/activate

# Load .env file and export variables to shell environment
if [ -f .env ]; then
    echo "📌 Loading environment variables from .env..."
    set -a  # automatically export all variables
    source .env
    set +a  # turn off automatic export

    # Debug: Verify DATABASE_URL is loaded
    if [ -n "$DATABASE_URL" ]; then
        echo "✅ DATABASE_URL loaded from .env"
    else
        echo "❌ WARNING: DATABASE_URL not found in environment!"
    fi
else
    echo "⚠️  Warning: .env file not found in $(pwd)"
fi

if [[ "$FORCE_SETUP" == "true" ]]; then
    echo "🔄 Force setup mode - resetting database..."

    # Environment variables are already loaded from .env file above
    python3 -c "
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

print('Database reset complete. Run ./startweb.sh to start the server.')
"
    exit 0
fi

STARTUP_STORY_CLOSED=false
close_startup_story() {
    local status="$1"
    if [[ "$STARTUP_STORY_CLOSED" != "true" ]]; then
        STARTUP_STORY_CLOSED=true
        python3 -c "from oneirodex.init_manager import print_startup_epilogue; print_startup_epilogue($status == 0)"
    fi
}
trap 'close_startup_story $?' EXIT

if [ -t 1 ]; then
    printf '\033[0;36m'
fi
echo "ONEI > The launch gate is coming online."
echo "        Oneirodex will be at http://localhost:${PORT:-5006} when ready."
if [ -t 1 ]; then
    printf '\033[0m'
fi

# Run complete startup initialization once before starting workers
python3 -c "
from oneirodex.init_manager import run_complete_startup_initialization
import sys

if not run_complete_startup_initialization():
    sys.exit(1)
"
INIT_STATUS=$?
if [ "$INIT_STATUS" -ne 0 ]; then
    exit "$INIT_STATUS"
fi

# Ensure environment variables are set for worker processes
export ONEIRODEX_MIGRATIONS_COMPLETE=true
export ONEIRODEX_INITIALIZATION_COMPLETE=true

# Set port for uvicorn (default 5006, can be overridden by PORT env var)
export PORT=${PORT:-5006}

# Default 2 workers — high worker counts + WsgiToAsgi can trigger
# "CurrentThreadExecutor already quit" under concurrent asset load.
# Static files are now served natively in asgi.py; keep workers modest.
WORKERS="${UVICORN_WORKERS:-1}"
close_startup_story 0
trap - EXIT
uvicorn asgi:asgi_app --host 0.0.0.0 --port $PORT --workers "$WORKERS" --timeout-graceful-shutdown "${UVICORN_GRACEFUL_TIMEOUT:-5}"
