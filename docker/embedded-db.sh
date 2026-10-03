#!/bin/bash
# Embedded PostgreSQL for the single-container (all-in-one) image.
#
# Sourced by entrypoint.sh. Nothing here runs on import except function
# definitions, so the Compose stack (external `db` service) is untouched.
#
# Mode (ONEIRODEX_EMBEDDED_DB):
#   auto  (default) embedded only when no DATABASE_URL / DATABASE_HOST is given
#   true            always embedded (ignores DATABASE_URL)
#   false           never embedded (a missing DATABASE_URL then fails as before)
#
# Everything stateful lives under ONEIRODEX_CONFIG_DIR (default /config), the one
# appdata mount an Unraid / `docker run` install needs:
#   /config/pgdata            the cluster
#   /config/secrets/          generated db password + SECRET_KEY (0600)
#   /config/logs/postgres.log
#   /config/library/          themes, covers, saves (when the library path is not
#                             bind-mounted separately), via ONEIRODEX_LIBRARY_DIR
#
# The server listens on 127.0.0.1 inside the container only, over TCP, scram auth.
# It runs as PUID:PGID (default 99:100 = Unraid nobody:users) because PostgreSQL
# refuses to run as root; the app itself keeps running as it always has.

EMBEDDED_PG_PORT="${ONEIRODEX_EMBEDDED_DB_PORT:-55432}"
EMBEDDED_PG_USER="oneirodex"
EMBEDDED_PG_DB="${POSTGRES_DB:-oneirodex}"
CONFIG_DIR="${ONEIRODEX_CONFIG_DIR:-/config}"
EMBEDDED_PGDATA="${CONFIG_DIR}/pgdata"
EMBEDDED_PG_LOG="${CONFIG_DIR}/logs/postgres.log"
EMBEDDED_RUN_AS=()

embedded_db_wanted() {
    case "${ONEIRODEX_EMBEDDED_DB:-auto}" in
        true|1|yes|on) return 0 ;;
        false|0|no|off) return 1 ;;
    esac
    [[ -z "${DATABASE_URL:-}" && -z "${DATABASE_HOST:-}" ]]
}

_pg_bin_dir() {
    local dir
    for dir in /usr/lib/postgresql/*/bin; do
        [[ -x "${dir}/postgres" ]] && echo "${dir}" && return 0
    done
    return 1
}

_prepare_pg_user() {
    local uid="${PUID:-99}" gid="${PGID:-100}"
    if [[ "${uid}" == "0" ]]; then
        # PostgreSQL will not start as root; fall back to the image's own user.
        uid="$(id -u postgres)"
        gid="$(id -g postgres)"
        echo "ℹ️  PUID=0 is not usable for the embedded database; using postgres (${uid}:${gid})."
    fi
    getent group "${gid}" >/dev/null || groupadd -o -g "${gid}" oneirodex-db
    getent passwd "${uid}" >/dev/null || useradd -o -u "${uid}" -g "${gid}" -d "${CONFIG_DIR}" -s /bin/bash -M oneirodex-db
    EMBEDDED_RUN_AS=(setpriv --reuid "${uid}" --regid "${gid}" --clear-groups)
    EMBEDDED_UID="${uid}"
    EMBEDDED_GID="${gid}"
}

_load_or_create_secret() {
    # $1 file, $2 generator command; prints the value. 0600, owned by the db user.
    local file="$1"; shift
    if [[ ! -s "${file}" ]]; then
        (umask 077 && "$@" > "${file}")
    fi
    chown "${EMBEDDED_UID}:${EMBEDDED_GID}" "${file}"
    chmod 600 "${file}"
    cat "${file}"
}

_pg_run() {
    "${EMBEDDED_RUN_AS[@]}" env -u PGHOST -u PGPORT -u PGDATA -u PGUSER -u PGPASSWORD -u PGDATABASE \
        LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}" "$@"
}

start_embedded_db() {
    local bin
    bin="$(_pg_bin_dir)" || {
        echo "❌ Embedded database requested but no PostgreSQL server is installed in this image."
        echo "   Use the Compose stack, or set DATABASE_URL to an external PostgreSQL."
        return 1
    }
    _prepare_pg_user

    mkdir -p "${CONFIG_DIR}/secrets" "${CONFIG_DIR}/logs" "${EMBEDDED_PGDATA}"
    chmod 700 "${CONFIG_DIR}/secrets"
    chown "${EMBEDDED_UID}:${EMBEDDED_GID}" "${CONFIG_DIR}/secrets" "${CONFIG_DIR}/logs" "${EMBEDDED_PGDATA}"
    chmod 700 "${EMBEDDED_PGDATA}"

    local db_password
    db_password="$(_load_or_create_secret "${CONFIG_DIR}/secrets/db_password" python3 -c 'import secrets; print(secrets.token_hex(24))')"

    if [[ ! -f "${EMBEDDED_PGDATA}/PG_VERSION" ]]; then
        echo "🗄️  Creating embedded PostgreSQL cluster in ${EMBEDDED_PGDATA} (first start only)..."
        # OS-independent collation so a later dump/restore onto another server
        # keeps its indexes valid (ADR 0011).
        _pg_run "${bin}/initdb" -D "${EMBEDDED_PGDATA}" -U "${EMBEDDED_PG_USER}" \
            --pwfile="${CONFIG_DIR}/secrets/db_password" --auth=scram-sha-256 -E UTF8 \
            --locale-provider=builtin --builtin-locale=C.UTF-8 --locale=C >/dev/null || {
            echo "❌ initdb failed. Is ${CONFIG_DIR} writable by ${EMBEDDED_UID}:${EMBEDDED_GID}? (set PUID/PGID)"
            return 1
        }
    else
        # A stale postmaster.pid from an unclean container stop is handled by
        # PostgreSQL itself (WAL redo); nothing to clean up here.
        :
    fi

    echo "🗄️  Starting embedded PostgreSQL on 127.0.0.1:${EMBEDDED_PG_PORT}..."
    _pg_run "${bin}/pg_ctl" start -w -t 120 -D "${EMBEDDED_PGDATA}" -l "${EMBEDDED_PG_LOG}" \
        -o "-c listen_addresses=127.0.0.1 -c port=${EMBEDDED_PG_PORT} -c unix_socket_directories= -c max_connections=${EMBEDDED_PG_MAX_CONNECTIONS:-60} -c shared_buffers=${EMBEDDED_PG_SHARED_BUFFERS:-64MB} -c jit=off" \
        >/dev/null || {
        echo "❌ Embedded PostgreSQL failed to start; see ${EMBEDDED_PG_LOG}"
        return 1
    }

    if ! PGPASSWORD="${db_password}" "${bin}/psql" -h 127.0.0.1 -p "${EMBEDDED_PG_PORT}" -U "${EMBEDDED_PG_USER}" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${EMBEDDED_PG_DB}'" | grep -q 1; then
        PGPASSWORD="${db_password}" "${bin}/psql" -h 127.0.0.1 -p "${EMBEDDED_PG_PORT}" -U "${EMBEDDED_PG_USER}" -d postgres \
            -c "CREATE DATABASE \"${EMBEDDED_PG_DB}\"" >/dev/null
    fi

    export DATABASE_URL="postgresql://${EMBEDDED_PG_USER}:${db_password}@127.0.0.1:${EMBEDDED_PG_PORT}/${EMBEDDED_PG_DB}"
    export DATABASE_HOST=127.0.0.1
    export DATABASE_PORT="${EMBEDDED_PG_PORT}"
    export POSTGRES_USER="${EMBEDDED_PG_USER}"
    export POSTGRES_PASSWORD="${db_password}"
    export POSTGRES_DB="${EMBEDDED_PG_DB}"
    EMBEDDED_PG_BIN="${bin}"
    echo "✅ Embedded PostgreSQL ready."
}

embedded_db_defaults() {
    # App-side defaults that the Compose file otherwise supplies.
    if [[ -z "${SECRET_KEY:-}" ]]; then
        SECRET_KEY="$(_load_or_create_secret "${CONFIG_DIR}/secrets/secret_key" python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
        export SECRET_KEY
    fi
    export DATA_FOLDER_GAMES="${DATA_FOLDER_GAMES:-/storage}"
    # Plain HTTP on a LAN is the norm for this install; secure-only cookies would
    # never be sent back. Put it behind HTTPS and set these to true.
    export SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-false}"
    export REMEMBER_COOKIE_SECURE="${REMEMBER_COOKIE_SECURE:-false}"
    # One appdata mount is enough: unless the library folder is its own mount
    # (Compose-style layout), keep it under /config.
    if [[ -z "${ONEIRODEX_LIBRARY_DIR:-}" ]] && ! mountpoint -q /app/oneirodex/static/library 2>/dev/null; then
        export ONEIRODEX_LIBRARY_DIR="${CONFIG_DIR}/library"
        mkdir -p "${ONEIRODEX_LIBRARY_DIR}"
    fi
}

stop_embedded_db() {
    [[ -n "${EMBEDDED_PG_BIN:-}" ]] || return 0
    echo "🗄️  Stopping embedded PostgreSQL..."
    _pg_run "${EMBEDDED_PG_BIN}/pg_ctl" stop -m fast -w -t 60 -D "${EMBEDDED_PGDATA}" >/dev/null 2>&1 || true
}

embedded_db_alive() {
    _pg_run "${EMBEDDED_PG_BIN}/pg_isready" -h 127.0.0.1 -p "${EMBEDDED_PG_PORT}" -q
}
