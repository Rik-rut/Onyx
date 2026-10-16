"""Pick the metadata record that matches a library folder's title and year."""

from __future__ import annotations

from typing import Any

from arr.db import normalize_title


def pick_match(
    items: list[dict[str, Any]], title: str, year: int | None, *, require_year: bool = False
) -> dict[str, Any] | None:
    """The best candidate with the same title, preferring one released in `year`.

    Folder years are not always the premiere year (a later season can carry it), so a
    show may match on title alone. Movies pass `require_year` so a remake is not picked.
    """
    wanted = normalize_title(title)
    same_title = [item for item in items if normalize_title(item.get("title")) == wanted]
    if not same_title:
        return None
    if year is not None:
        for item in same_title:
            item_year = item.get("year")
            if item_year is not None and abs(int(item_year) - int(year)) <= 1:
                return item
        if require_year:
            return None
    return same_title[0]
