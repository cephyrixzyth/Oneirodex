import pytest

from scripts.upgrade_test_schema import resolve_loopback_test_database_url


def test_test_schema_upgrade_accepts_loopback_test_database():
    url = "postgresql://postgres:postgres@127.0.0.1:5432/oneirodex_upgrade_test"
    assert resolve_loopback_test_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:postgres@example.invalid:5432/oneirodex_upgrade_test",
        "postgresql://postgres:postgres@127.0.0.1:5432/oneirodex",
        "postgresql://postgres:postgres@127.0.0.1:5432/oneirodex_upgrade_test?options=-csearch_path%3Dpublic",
    ],
)
def test_test_schema_upgrade_rejects_non_loopback_or_unsafe_database(url):
    with pytest.raises(RuntimeError):
        resolve_loopback_test_database_url(url)
