# -*- coding: utf-8 -*-

"""Small date helpers shared by the UI and the scoring layer."""

from __future__ import annotations

from typing import Any, List

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def month_matches(best_months: List[Any], month_number: int) -> bool:
    """Whether a destination's best months include the chosen month.

    Seed data stores month names ("May"); the UI works in numbers.
    Comparing the two directly excluded every destination, so both
    forms are accepted, and data we cannot read is treated as "no
    opinion" rather than as a mismatch - hiding a place because its
    metadata is odd is worse than showing it.
    """
    if not best_months:
        return True
    target = MONTH_NAMES[month_number - 1].lower()
    prefixes = {name[:3].lower() for name in MONTH_NAMES}
    recognised = False
    for entry in best_months:
        if isinstance(entry, bool):
            continue
        if isinstance(entry, int):
            if 1 <= entry <= 12:
                recognised = True
                if entry == month_number:
                    return True
            continue
        if not isinstance(entry, str):
            continue
        text = entry.strip().lower()
        if not text:
            continue
        if text.isdigit():
            value = int(text)
            if 1 <= value <= 12:
                recognised = True
                if value == month_number:
                    return True
            continue
        # Only a real month name counts as readable data; anything
        # else ("whenever", "shoulder season") is not a month, and
        # must not be treated as an exclusion.
        if text[:3] in prefixes:
            recognised = True
            if target.startswith(text[:3]):
                return True
    return not recognised
