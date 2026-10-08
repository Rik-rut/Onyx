from __future__ import annotations

from arr.core.models import SeedingPolicyMode


class SeedingConfigError(Exception):
    pass


def validate_seeding(mode: SeedingPolicyMode | str, import_mode: str) -> None:
    m = mode.value if isinstance(mode, SeedingPolicyMode) else str(mode)
    if m == SeedingPolicyMode.REMOVE_ON_IMPORT.value and import_mode == "hardlink":
        raise SeedingConfigError(
            "seeding_policy=remove_on_import is incompatible with import_mode=hardlink: "
            "removing the torrent data after a hardlink import would delete the library's "
            "only copy. Use import_mode=copy/move, or choose ratio/time/manual."
        )


def should_remove(
    mode: SeedingPolicyMode | str,
    *,
    ratio: float | None = None,
    seed_ratio: float = 1.0,
    hours_seeded: float | None = None,
    seed_time_hours: float = 24.0,
    imported: bool = False,
    import_mode: str = "hardlink",
) -> bool:
    m = mode.value if isinstance(mode, SeedingPolicyMode) else str(mode)
    if m == SeedingPolicyMode.RATIO.value:
        return ratio is not None and ratio >= seed_ratio
    if m == SeedingPolicyMode.TIME.value:
        return hours_seeded is not None and hours_seeded >= seed_time_hours
    if m == SeedingPolicyMode.REMOVE_ON_IMPORT.value:
        return imported and import_mode != "hardlink"
    # manual: never auto-remove
    return False


HARDLINK_NOTICE = (
    "Note: imported via hardlink — the torrent data in the incomplete dir remains the library's "
    "only backing copy, so seeding can continue. Removing the torrent will not affect the library, "
    "but the data will be lost when the incomplete dir is cleaned."
)


def evaluate_torrent(
    torrent: dict,
    mode: SeedingPolicyMode | str,
    *,
    seed_ratio: float = 1.0,
    seed_time_hours: float = 24.0,
    imported: bool = False,
    import_mode: str = "hardlink",
) -> bool:
    """Decide from a Transmission torrent dict whether its data should be removed.

    Extracts ratio/secondsSeeding so callers don't duplicate the field logic.
    Deterministic and side-effect free.
    """
    ratio = torrent.get("uploadRatio")
    seconds = torrent.get("secondsSeeding")
    return should_remove(
        mode,
        ratio=float(ratio) if ratio is not None else None,
        seed_ratio=seed_ratio,
        hours_seeded=float(seconds) / 3600.0 if seconds is not None else None,
        seed_time_hours=seed_time_hours,
        imported=imported,
        import_mode=import_mode,
    )
