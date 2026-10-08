import pytest

from arr.core.models import SeedingPolicyMode
from arr.seeding import SeedingConfigError, should_remove, validate_seeding


def test_ratio_mode():
    assert should_remove(SeedingPolicyMode.RATIO, ratio=1.5, seed_ratio=1.0)
    assert not should_remove(SeedingPolicyMode.RATIO, ratio=0.5, seed_ratio=1.0)


def test_time_mode():
    assert should_remove(SeedingPolicyMode.TIME, hours_seeded=30, seed_time_hours=24)
    assert not should_remove(SeedingPolicyMode.TIME, hours_seeded=1, seed_time_hours=24)


def test_manual_never_removes():
    assert not should_remove(SeedingPolicyMode.MANUAL, ratio=99, hours_seeded=9999)


def test_remove_on_import_requires_non_hardlink():
    assert should_remove(SeedingPolicyMode.REMOVE_ON_IMPORT, imported=True, import_mode="copy")
    assert not should_remove(
        SeedingPolicyMode.REMOVE_ON_IMPORT, imported=True, import_mode="hardlink"
    )


def test_remove_on_import_hardlink_refused():
    with pytest.raises(SeedingConfigError):
        validate_seeding(SeedingPolicyMode.REMOVE_ON_IMPORT, "hardlink")
    validate_seeding(SeedingPolicyMode.REMOVE_ON_IMPORT, "copy")
    validate_seeding(SeedingPolicyMode.RATIO, "hardlink")
