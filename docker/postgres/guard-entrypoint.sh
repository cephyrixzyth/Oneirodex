#!/bin/sh
set -eu

. /usr/local/bin/oneirodex-postgres-guard.sh
oneirodex_guard_postgres_publication

case "${POSTGRES_HOST_BIND:-127.0.0.1}" in
    127.*|localhost|::1|'[::1]') ;;
    *) oneirodex_verify_persisted_postgres_password ;;
esac

exec /usr/local/bin/docker-entrypoint.sh "$@"
