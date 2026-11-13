#!/usr/bin/env bash
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux ]]; then
    echo "This bounded filesystem fixture requires an isolated Linux GitHub runner." >&2
    exit 1
fi
: "${RUNNER_TEMP:?Runner temporary directory required}"
: "${GITHUB_RUN_ID:?Run identity required}"

archive_test_volume=$(mktemp -d "${RUNNER_TEMP}/oneirodex-enospc.XXXXXX")
readonly archive_test_volume
readonly archive_test_owner="${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT:-0}:$$"
case "$archive_test_volume" in
    "$RUNNER_TEMP"/oneirodex-enospc.*) ;;
    *) echo "Unexpected fixture path; refusing to mount." >&2; exit 1 ;;
esac

cleanup() {
    local result=$?
    trap - EXIT
    if mountpoint -q "$archive_test_volume"; then
        if [[ ! -f "$archive_test_volume/.oneirodex-enospc-owner" ||
              -L "$archive_test_volume/.oneirodex-enospc-owner" ||
              "$(cat "$archive_test_volume/.oneirodex-enospc-owner")" != "$archive_test_owner" ||
              "$(stat -f -c %T "$archive_test_volume")" != tmpfs ]]; then
            echo "Fixture ownership changed; refusing to unmount." >&2
            exit 1
        fi
        sudo -n umount "$archive_test_volume" || result=1
    fi
    if mountpoint -q "$archive_test_volume"; then
        echo "Fixture mount remains active." >&2
        result=1
    else
        if rmdir "$archive_test_volume"; then
            echo "REAL_ENOSPC_CLEANUP unmounted=true removed=true"
        else
            result=1
        fi
    fi
    exit "$result"
}
trap cleanup EXIT

sudo -n mount -t tmpfs \
    -o "size=16m,uid=$(id -u),gid=$(id -g),mode=0700,nosuid,nodev,noexec" \
    tmpfs "$archive_test_volume"
printf '%s' "$archive_test_owner" > "$archive_test_volume/.oneirodex-enospc-owner"
readonly archive_test_log="${RUNNER_TEMP}/oneirodex-enospc-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-0}.log"

ONEIRODEX_TEST_REAL_ENOSPC_ROOT="$archive_test_volume" \
ONEIRODEX_TEST_REAL_ENOSPC_OWNER="$archive_test_owner" \
CARGO_TERM_COLOR=never \
cargo test --offline --locked --lib \
    tests::real_disk_full_after_preflight_preserves_install_and_recovers \
    -- --ignored --exact --nocapture --test-threads=1 2>&1 | tee "$archive_test_log"
grep -Eq 'test result: ok\. 1 passed; 0 failed; 0 ignored;' "$archive_test_log"
