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


# District names carry an ordinal that's spelled out in some sources
# ("First Middlesex District") and numeral in others (PD43+'s "1st
# Middlesex District", OCPF's filer roster's "1st Essex & Middlesex") —
# found the hard way twice, independently, in two different join problems
# (build.derived_metrics matching PD43+ races to boundary files;
# build.campaign_finance_match matching candidates to OCPF filers, where a
# real long-serving senator's real filer went unmatched across all 12
# years purely because "First Essex & Middlesex" and "1st Essex &
# Middlesex" never collided under a naive normalizer). Both now share this
# one canonicalization instead of drifting into two subtly different
# normalizers with two subtly different gaps. Naive fuzzy matching on the
# un-normalized text is actively unsafe here, not just imprecise — it can
# match "4th Middlesex District" to "Third Middlesex District" (textually
# similar, a real but wrong district), silently corrupting whichever
# dataset gets joined that way. Covers ordinals through 20th; no MA
# chamber has more than ~20 same-county-ordinal districts.
_ORDINAL_WORDS = [
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
    "eighteenth", "nineteenth", "twentieth",
]
_ORDINAL_WORD_TO_NUMERAL = {word: f"{i + 1}" for i, word in enumerate(_ORDINAL_WORDS)}


def normalize_district_name(name: str) -> str:
    name = name.lower()
    name = name.replace("&", " and ")
    name = re.sub(r"[,\-]", " ", name)
    name = re.sub(r"\bdistrict\b", "", name)
    name = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", name)  # "1st" -> "1"
    for word, numeral in _ORDINAL_WORD_TO_NUMERAL.items():
        name = re.sub(rf"\b{word}\b", numeral, name)  # "first" -> "1"
    name = re.sub(r"\s+", " ", name).strip()
    return name
