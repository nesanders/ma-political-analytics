"""Shared name-normalization helpers, used wherever two independently
sourced datasets need joining or displaying by a name that isn't spelled
identically in both."""

from __future__ import annotations

import re

# Two independently-sourced town name spellings need reconciling before any
# town-keyed join or display: TIGER COUSUB's NAME field suffixes some
# municipalities with "Town"/"City" (inconsistently — only some of MA's
# 351), while PD43+ abbreviates directional prefixes ("N. Adams",
# "W. Springfield"). Verified live (build.derived_metrics) this closes the
# gap completely except for TIGER's one legitimate non-municipality
# placeholder row ("County subdivisions not defined", water/unassigned
# area, correctly has no PD43+ counterpart).
_DIRECTION_ABBREV = {"N.": "North", "S.": "South", "E.": "East", "W.": "West"}


def normalize_town_name(name: str) -> str:
    name = re.sub(r"\s+(Town|City)$", "", name)
    parts = name.split()
    if parts and parts[0] in _DIRECTION_ABBREV:
        parts[0] = _DIRECTION_ABBREV[parts[0]]
    return " ".join(parts)
