"""Login rate-limit unit tests (no DB)."""

import os

from oneirodex.utils import login_rate_limit as lrl


_ENV = {
    'ENABLE_LOGIN_RATE_LIMIT': 'true',
    'LOGIN_RATE_LIMIT_ATTEMPTS': '3',
    'LOGIN_RATE_LIMIT_WINDOW_SECONDS': '60',
}

_saved: dict[str, str | None] = {}


def setup_function():
    # Saved and restored rather than just set. These are process-wide, and the
    # teardown reset only the limiter's own state — so every file that ran after
    # this one did so with login rate limiting switched on and a 3-attempt
    # window, which is not what any of them meant to test.
    lrl.reset_for_tests()
    for key, value in _ENV.items():
        _saved[key] = os.environ.get(key)
        os.environ[key] = value


def teardown_function():
    lrl.reset_for_tests()
    for key, previous in _saved.items():
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
    _saved.clear()


def test_not_limited_until_threshold():
    key = lrl.login_rate_key('1.2.3.4', 'alice')
    assert lrl.is_rate_limited(key) is False
    lrl.record_failure(key)
    lrl.record_failure(key)
    assert lrl.is_rate_limited(key) is False
    lrl.record_failure(key)
    assert lrl.is_rate_limited(key) is True


def test_clear_failures_unlocks():
    key = lrl.login_rate_key('1.2.3.4', 'bob')
    for _ in range(5):
        lrl.record_failure(key)
    assert lrl.is_rate_limited(key) is True
    lrl.clear_failures(key)
    assert lrl.is_rate_limited(key) is False


def test_window_expiry(monkeypatch):
    key = lrl.login_rate_key('9.9.9.9', 'carol')
    now = 1000.0
    lrl.record_failure(key, now=now)
    lrl.record_failure(key, now=now + 1)
    lrl.record_failure(key, now=now + 2)
    assert lrl.is_rate_limited(key, now=now + 3) is True
    # After window (60s) all hits expire
    assert lrl.is_rate_limited(key, now=now + 70) is False


def test_disabled_never_limits(monkeypatch):
    monkeypatch.setenv('ENABLE_LOGIN_RATE_LIMIT', 'false')
    key = lrl.login_rate_key('5.5.5.5', 'dave')
    for _ in range(20):
        lrl.record_failure(key)
    assert lrl.is_rate_limited(key) is False


def test_distinct_limit_checks_do_not_allocate_buckets():
    for index in range(100_000):
        assert lrl.is_rate_limited(f'probe:{index}') is False
    assert lrl._hits == {}


def test_distinct_failures_are_bounded_and_evict_oldest_key():
    for index in range(60_000):
        lrl.record_failure(f'failure:{index}', now=1000.0)
    assert len(lrl._hits) <= lrl._MAX_KEYS
    assert 'failure:0' not in lrl._hits
    assert 'failure:59999' in lrl._hits
