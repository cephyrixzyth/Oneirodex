"""Database selection safety shared by pytest bootstrap and app construction."""
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def validate_test_database_url(value):
    valid = False
    try:
        url = make_url(value)
        valid = (
            url.get_backend_name() == 'postgresql'
            and bool(url.host)
            and bool(url.database)
            # SQLAlchemy releases differ in decoding the database/host path.
            # Test harness names must be plain identifiers: reject encoded
            # components rather than validating a different name from the
            # one eventually passed to the driver.
            and '%' not in url.database
            and '%' not in url.host
            and 'test' in url.database.lower()
            and not any(ord(char) < 32 or ord(char) == 127
                        for part in (url.database, url.host, url.username, url.password)
                        for char in (part or ''))
            and not url.query
        )
    except (TypeError, ValueError, ArgumentError):
        pass
    if not valid:
        raise RuntimeError(
            "CRITICAL: TEST_DATABASE_URL must be an explicit PostgreSQL URL "
            "with a host, a database name containing 'test', no control characters "
            "no percent-encoded database/host names and no query options. "
            "Connection details are withheld."
        ) from None
    return value
