#!/bin/bash
set -e

echo "🚀 Oneirodex container starting up..."

if [[ ! -f /app/oneirodex/static/dist/member-app/member-app.js ]]; then
    echo "⚠️  Warning: member-app.js not found — React member app may not load. Rebuild the Docker image to include the member-app build stage."
fi
if [[ ! -f /app/oneirodex/static/dist/member-app/member-app.css ]]; then
    echo "⚠️  Warning: member-app.css not found — member SPA chrome will render unstyled. Rebuild the Docker image."
fi
if [[ ! -f /app/oneirodex/static/dist/admin-app/admin-app.js ]]; then
    echo "⚠️  Warning: admin-app.js not found — React admin SPA may not load. Rebuild the Docker image."
fi
if [[ ! -f /app/oneirodex/static/dist/admin-app/admin-app.css ]]; then
    echo "⚠️  Warning: admin-app.css not found — admin SPA chrome will render unstyled. Rebuild the Docker image."
fi
if [[ ! -f /app/oneirodex/static/library/themes/default/css/od-tokens.css ]]; then
    echo "⚠️  Warning: themes/default/css/od-tokens.css missing — run init or Admin → Reset Default Themes after boot."
fi

# Single-container mode: no DATABASE_URL given, so run PostgreSQL inside this
# container (docker/embedded-db.sh). The Compose stack sets DATABASE_URL and is
# unaffected.
EMBEDDED=false
# shellcheck source=docker/embedded-db.sh
source /app/docker/embedded-db.sh
if embedded_db_wanted; then
    EMBEDDED=true
    echo "📦 Single-container mode: using the embedded PostgreSQL (data in ${CONFIG_DIR})."
    embedded_db_defaults
    start_embedded_db || exit 1
fi

# Inside Docker Compose, Postgres is the sibling service named "db".
# Never wait on localhost/127.0.0.1 (common leftover from non-Docker .env files).
if [[ "${EMBEDDED}" == "false" && -f /.dockerenv ]]; then
    export DATABASE_HOST="${DATABASE_HOST:-db}"
    export DATABASE_PORT="${DATABASE_PORT:-5432}"
    export POSTGRES_USER="${POSTGRES_USER:-postgres}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
    export POSTGRES_DB="${POSTGRES_DB:-oneirodex}"

    # The env templates ship a placeholder, not a password. It is public (it is
    # in this repo), so starting a database with it is refused outright. The
    # old default `postgres` is only warned about: existing stacks rely on it.
    if [[ "${POSTGRES_PASSWORD}" == CHANGE_ME* || "${DATABASE_URL}" == *":CHANGE_ME"* ]]; then
        echo "❌ POSTGRES_PASSWORD is still the template placeholder. Set a strong password in .env"
        echo "   (e.g. openssl rand -hex 24) before the first start; see docs/runbooks/docker-compose-deploy.md."
        exit 1
    fi
    if [[ "${POSTGRES_PASSWORD}" == "postgres" ]]; then
        echo "⚠️  POSTGRES_PASSWORD is the old default 'postgres'. Rotate it (docs/runbooks/docker-compose-deploy.md)."
    fi

    if [[ -z "${DATABASE_URL}" \
        || "${DATABASE_URL}" == *"@localhost"* \
        || "${DATABASE_URL}" == *"@127.0.0.1"* \
        || "${DATABASE_URL}" == *"@::1"* ]]; then
        export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
        echo "ℹ️  DATABASE_URL forced to Compose service db (was empty/localhost)."
    fi
fi

DB_HOST=${DATABASE_HOST:-db}
DB_USER=${POSTGRES_USER:-postgres}
DB_PORT=${DATABASE_PORT:-5432}

# Prefer parsing host from DATABASE_URL when it is not localhost
if [[ -n "$DATABASE_URL" ]]; then
    PARSED_HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:/]*\)[:/].*/\1/p')
    PARSED_PORT=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9][0-9]*\)\/.*/\1/p')
    PARSED_USER=$(echo "$DATABASE_URL" | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
    if [[ -n "$PARSED_HOST" && "$PARSED_HOST" != "localhost" && "$PARSED_HOST" != "127.0.0.1" ]]; then
        DB_HOST="$PARSED_HOST"
    fi
    if [[ -n "$PARSED_PORT" ]]; then
        DB_PORT="$PARSED_PORT"
    fi
    if [[ -n "$PARSED_USER" ]]; then
        DB_USER="$PARSED_USER"
    fi
fi

wait_for_postgres() {
    echo "🔄 Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
    echo "   DATABASE_URL host hint: $(echo "${DATABASE_URL}" | sed -E 's#://[^:]+:[^@]+@#://***:***@#')"

    until python3 -c "
import os
import sys
import psycopg2
from urllib.parse import urlparse

host = os.environ.get('DATABASE_HOST', '${DB_HOST}')
port = int(os.environ.get('DATABASE_PORT', '${DB_PORT}') or 5432)
user = os.environ.get('POSTGRES_USER', '${DB_USER}')
password = os.environ.get('POSTGRES_PASSWORD', 'postgres')
database = os.environ.get('POSTGRES_DB', 'oneirodex')

url = os.environ.get('DATABASE_URL') or ''
if url:
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        host = parsed.hostname
        port = parsed.port or port
        user = parsed.username or user
        password = parsed.password or password
        database = (parsed.path or '/oneirodex').lstrip('/') or database
    else:
        # Force Compose service when URL still points at loopback
        host = 'db'

try:
    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=5,
    )
    conn.close()
    print(f'✅ PostgreSQL connection successful ({host}:{port}/{database})')
except Exception as e:
    print(f'❌ Connection failed ({host}:{port}): {e}')
    sys.exit(1)
"; do
        echo "⏳ PostgreSQL not ready yet, waiting 5 seconds..."
        sleep 5
    done
    echo "✅ PostgreSQL is now available!"
}

if [[ "${EMBEDDED}" == "false" ]]; then
    wait_for_postgres

    echo "🎮 Starting Oneirodex Docker container..."
    exec /app/startweb-docker.sh "$@"
fi

# Embedded database: stay as the parent so SIGTERM (docker stop) stops the app
# first and PostgreSQL second, cleanly, and so a dead database takes the
# container down for the restart policy to bring back.
echo "🎮 Starting Oneirodex Docker container..."
/app/startweb-docker.sh "$@" &
APP_PID=$!

shutdown() {
    kill -TERM "${APP_PID}" 2>/dev/null || true
    wait "${APP_PID}" 2>/dev/null || true
    stop_embedded_db
    exit 0
}
trap shutdown TERM INT

while kill -0 "${APP_PID}" 2>/dev/null; do
    if ! embedded_db_alive; then
        echo "❌ Embedded PostgreSQL stopped unexpectedly; exiting so the container restarts."
        kill -TERM "${APP_PID}" 2>/dev/null || true
        wait "${APP_PID}" 2>/dev/null || true
        exit 1
    fi
    sleep 5 &
    wait $! || true
done

wait "${APP_PID}"
APP_STATUS=$?
stop_embedded_db
exit "${APP_STATUS}"
