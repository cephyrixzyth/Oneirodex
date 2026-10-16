# Shared policy for the Compose PostgreSQL entrypoint. Keep this POSIX-shell
# compatible so the official postgres image can run it before initialization.
oneirodex_guard_postgres_publication() {
    bind_address=${POSTGRES_HOST_BIND:-127.0.0.1}
    password=${POSTGRES_PASSWORD:-}

    case "$bind_address" in
        127.*|localhost|::1|'[::1]') return 0 ;;
    esac

    case "$password" in
        ''|postgres|CHANGE_ME*)
            echo "PostgreSQL refuses non-loopback publication with an unset, default, or template password." >&2
            echo "Rotate the database password or restore POSTGRES_HOST_BIND=127.0.0.1." >&2
            return 1
            ;;
    esac

    return 0
}

# Existing data volumes ignore POSTGRES_PASSWORD during initialization. Before
# publishing one beyond loopback, prove that the configured credential works
# against the stored database. The probe listener is container-loopback only
# and uses a port that Compose does not publish.
oneirodex_verify_persisted_postgres_password() {
    pgdata=${PGDATA:-/var/lib/postgresql/data}
    if [ ! -s "$pgdata/PG_VERSION" ]; then
        # A fresh volume will be initialized from POSTGRES_PASSWORD by the
        # official entrypoint, so the configured credential is authoritative.
        return 0
    fi

    probe_port=55432
    probe_options="-c listen_addresses=127.0.0.1 -c port=$probe_port -c hba_file=/etc/oneirodex/pg_hba.conf -c unix_socket_directories=/var/run/postgresql"
    if ! gosu postgres pg_ctl -D "$pgdata" -o "$probe_options" -w start >/dev/null 2>&1; then
        echo "PostgreSQL refuses non-loopback publication: the existing database could not be checked safely." >&2
        return 1
    fi
    probe_started=true
    oneirodex_stop_probe() {
        if [ "$probe_started" = true ]; then
            gosu postgres pg_ctl -D "$pgdata" -m fast -w stop >/dev/null 2>&1 || true
            probe_started=false
        fi
    }
    trap oneirodex_stop_probe EXIT
    trap 'exit 1' HUP INT TERM

    superuser_state=$(psql \
        --no-password --no-psqlrc --set=ON_ERROR_STOP=1 \
        --host=/var/run/postgresql --port="$probe_port" \
        --username="${POSTGRES_USER:-postgres}" \
        --dbname="${POSTGRES_DB:-${POSTGRES_USER:-postgres}}" \
        --tuples-only --no-align \
        --command='SELECT count(*) = 1 AND COALESCE(bool_or(rolname = current_user), false) FROM pg_roles WHERE rolsuper AND rolcanlogin' \
        2>/dev/null || true)

    role_ok=false
    if [ "$superuser_state" = t ]; then
        role_ok=true
    fi

    probe_ok=false
    if [ "$role_ok" = true ] && PGPASSWORD="$POSTGRES_PASSWORD" psql \
        --no-password --no-psqlrc --set=ON_ERROR_STOP=1 \
        --host=127.0.0.1 --port="$probe_port" \
        --username="${POSTGRES_USER:-postgres}" \
        --dbname="${POSTGRES_DB:-${POSTGRES_USER:-postgres}}" \
        --tuples-only --no-align --command='SELECT 1' >/dev/null 2>&1; then
        probe_ok=true
    fi

    if ! gosu postgres pg_ctl -D "$pgdata" -m fast -w stop >/dev/null 2>&1; then
        echo "PostgreSQL refuses non-loopback publication: the private credential-check server did not stop cleanly." >&2
        return 1
    fi
    probe_started=false
    trap - EXIT HUP INT TERM

    if [ "$role_ok" != true ]; then
        echo "PostgreSQL refuses non-loopback publication: the configured account is not the sole login-capable superuser." >&2
        echo "Keep POSTGRES_HOST_BIND on loopback or leave one configured login-capable superuser." >&2
        return 1
    fi

    if [ "$probe_ok" != true ]; then
        echo "PostgreSQL refuses non-loopback publication: POSTGRES_PASSWORD does not authenticate to the existing database." >&2
        echo "Keep POSTGRES_HOST_BIND on loopback, rotate the password in the database, then retry." >&2
        return 1
    fi
}
