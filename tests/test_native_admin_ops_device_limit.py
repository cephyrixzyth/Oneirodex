"""Legacy-compatible limit semantics for the admin Ops device list."""

import pytest

from oneirodex.runtime_native.admin_ops_reads import _bounded_device_limit


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (None, 200),
        ('invalid', 200),
        ('0', 200),
        ('-3', 1),
        ('7', 7),
        ('1001', 1000),
    ],
)
def test_device_limit_preserves_legacy_default_and_bounds(value, expected):
    assert _bounded_device_limit(value) == expected
