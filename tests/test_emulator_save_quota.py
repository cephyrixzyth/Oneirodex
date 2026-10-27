"""Small DB-free regressions for aggregate emulator-save quota accounting."""

from oneirodex.utils.emulator_saves import save_quota_would_be_exceeded


def test_save_quota_counts_replacement_delta_not_the_old_slot_twice():
    assert not save_quota_would_be_exceeded(100, 70, 80, 110)
    assert save_quota_would_be_exceeded(100, 70, 81, 110)


def test_save_quota_rejects_new_bytes_at_the_limit():
    assert save_quota_would_be_exceeded(100, 0, 1, 100)
    assert not save_quota_would_be_exceeded(99, 0, 1, 100)
