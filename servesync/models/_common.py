"""Validation helpers shared by several domain models."""

from __future__ import annotations

from collections.abc import Iterable

from servesync.core.validators import InvalidInputError, clean_text

SKILL_MAX_LENGTH = 40
MAX_SKILLS_PER_RECORD = 20


def validate_optional_id(value: object, label: str) -> int | None:
    """A primary key is either ``None`` (not saved yet) or a positive integer."""
    if value is None:
        return None
    return validate_reference_id(value, label)


def validate_reference_id(value: object, label: str) -> int:
    """A foreign key must be a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidInputError(f"{label} must refer to a saved record.")
    return value


def clean_skill_set(values: object, label: str = "Skills") -> frozenset[str]:
    """
    Normalize a collection of skill names.

    Trims each name, drops blanks, removes case-insensitive duplicates
    ("cpr" and "CPR" count once, first spelling wins) and caps the count.
    """
    if values is None:
        return frozenset()
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise InvalidInputError(f"{label} must be a list of names.")

    seen: dict[str, str] = {}
    for raw in values:
        name = clean_text(raw, "Skill name", max_length=SKILL_MAX_LENGTH, required=False)
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    if len(seen) > MAX_SKILLS_PER_RECORD:
        raise InvalidInputError(f"{label}: choose {MAX_SKILLS_PER_RECORD} or fewer.")
    return frozenset(seen.values())
