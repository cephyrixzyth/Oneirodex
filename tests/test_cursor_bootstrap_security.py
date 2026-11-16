"""Security contract for the tracked Cursor Cloud Agent bootstrap."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cursor_bootstrap_generates_a_private_database_credential_only_for_new_env():
    script = (ROOT / ".cursor" / "install.sh").read_text(encoding="utf-8")

    env_creation = script.index('if [ ! -f "${REPO_ROOT}/.env" ]; then')
    role_password = script.index("ALTER ROLE postgres WITH PASSWORD")
    env_write = script.index('cat > "${REPO_ROOT}/.env"')
    env_end = script.index("\nfi", env_write)

    assert role_password > env_creation
    assert env_write > role_password
    assert role_password < env_end
    assert 'DB_PASSWORD="$(python3 -c' in script[env_creation:env_end]
    assert "${DB_PASSWORD}" in script[env_write:env_end]
    assert "postgres:postgres@localhost" not in script
    assert "psql -c \"ALTER USER postgres" not in script
    assert "    umask 077" in script[env_creation:env_end]
