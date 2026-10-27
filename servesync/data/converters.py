"""
Conversions between Python types and the text SQLite stores.

Python 3.12 deprecated sqlite3's built-in date/datetime adapters, so ServeSync
converts explicitly. Dates and times are stored as ISO-8601 text
(``2026-11-14`` and ``2026-11-14T09:30``), which sorts and compares correctly
as plain strings — that is what lets SQL like ``starts_at < ?`` work.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime
from typing import TypeVar

T = TypeVar("T")

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
_LIKE_ESCAPE = "\\"

#: SQLite limits how many "?" placeholders one statement may use.
MAX_PARAMS_PER_QUERY = 500


def date_to_db(value: date) -> str:
    return value.isoformat()


def date_from_db(value: str) -> date:
    return date.fromisoformat(value)


def optional_date_from_db(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def datetime_to_db(value: datetime) -> str:
    """Minute precision, no time zone: ``2026-11-14T09:30``."""
    return value.strftime(_DATETIME_FORMAT)


def datetime_from_db(value: str) -> datetime:
    return datetime.fromisoformat(value)


def optional_datetime_to_db(value: datetime | None) -> str | None:
    return None if value is None else datetime_to_db(value)


def optional_datetime_from_db(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def escape_like(text: str) -> str:
    """
    Escape ``%`` and ``_`` so user search text is matched literally.

    Without this, searching for "50%" would match everything starting with 50.
    Use together with ``LIKE ? ESCAPE '\\'`` in SQL.
    """
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", _LIKE_ESCAPE + "%").replace("_", _LIKE_ESCAPE + "_")
    )


def contains_pattern(text: str) -> str:
    """LIKE pattern for "contains ``text``" (already escaped)."""
    return f"%{escape_like(text)}%"


def chunked(items: Sequence[T], size: int = MAX_PARAMS_PER_QUERY) -> Iterator[Sequence[T]]:
    """Split a sequence into slices of at most ``size`` items."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def placeholders(items: Iterable[object]) -> str:
    """``"?, ?, ?"`` for an ``IN (...)`` clause with one placeholder per item."""
    return ", ".join("?" for _ in items)
