"""
Translation: every word ServeSync shows can appear in English or Spanish.

How it works
------------
* Code is written in English and wraps each user-facing message in
  :func:`tr`. The English text *is* the message ID, so the code stays
  readable and English needs no catalog at all::

      tr("Saved {name}.", name=volunteer.full_name)

* Spanish lives in ``servesync/locale/es.json`` — one entry per English
  message. ``tests/test_i18n.py`` scans the code and fails if any message is
  missing a translation or a translation drops a ``{placeholder}``, so the
  two languages can never drift apart.
* Plurals use :func:`tr_n` (Spanish, like English, has "one" and "other").
* When one English phrase needs two Spanish wordings, :func:`tr_for` adds a
  context ("leader|Sign up").
* Dates and times use :func:`format_day`, :func:`format_clock` and friends,
  because month and weekday names differ by language.
* Text that is defined once at import time (column headers, enum labels) is
  marked with :func:`mark` and translated when shown, so switching language
  changes it instantly.

Defensive by design: a missing or broken translation falls back to English
(and is logged) instead of crashing in front of a judge.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from enum import Enum
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)


class Language(str, Enum):
    """Interface languages. Each shows its own name, so anyone can find theirs."""

    ENGLISH = "en"
    SPANISH = "es"

    @property
    def label(self) -> str:
        return {"en": "English", "es": "Español"}[self.value]


_state: dict[str, Language] = {"language": Language.ENGLISH}


def set_language(language: Language) -> None:
    _state["language"] = Language(language)


def current_language() -> Language:
    return _state["language"]


def locale_dir() -> Path:
    from servesync.config import is_frozen, resource_root  # local: config imports nothing from here

    root = resource_root()
    return root / "servesync" / "locale" if is_frozen() else root / "locale"


@cache
def catalog(language: Language) -> dict[str, str]:
    """English message -> translation for one language (English needs none)."""
    if language is Language.ENGLISH:
        return {}
    path = locale_dir() / f"{language.value}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Could not read translations from %s; showing English", path)
        return {}
    return {str(key): str(value) for key, value in data.items() if not str(key).startswith("//")}


def tr(message: str, /, **fields: object) -> str:
    """Translate ``message`` into the current language, then fill in ``{fields}``."""
    language = current_language()
    text = catalog(language).get(message, message) if language is not Language.ENGLISH else message
    if not fields:
        return text
    try:
        return text.format(**fields)
    except (KeyError, IndexError, ValueError):
        logger.warning("Translation of %r has bad placeholders; showing English", message)
        return message.format(**fields)


def tr_n(singular: str, plural: str, count: int, /, **fields: object) -> str:
    """Pick the singular or plural message for ``count`` (available as ``{count}``)."""
    return tr(singular if count == 1 else plural, count=count, **fields)


def tr_for(context: str, message: str, /, **fields: object) -> str:
    """
    Translate a message whose wording depends on who it's for. English uses
    the same "Sign up" for a volunteer's own button and a leader's button,
    but Spanish needs "Inscribirme" and "Inscribir"; the catalog key for the
    second is ``"leader|Sign up"``. Falls back to plain :func:`tr`.
    """
    if current_language() is not Language.ENGLISH:
        special = catalog(current_language()).get(f"{context}|{message}")
        if special is not None:
            return special.format(**fields) if fields else special
    return tr(message, **fields)


def mark(message: str) -> str:
    """Mark text for translation without translating it yet (translated when shown)."""
    return message


# ------------------------------------------------------------------ dates

_MONTHS = {
    Language.ENGLISH: [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
    Language.SPANISH: [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ],
}
_WEEKDAYS = {
    Language.ENGLISH: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    Language.SPANISH: ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}


def month_name(month: int, *, short: bool = False) -> str:
    name = _MONTHS[current_language()][month - 1]
    return name[:3] if short else name


def weekday_name(weekday: int, *, short: bool = False) -> str:
    name = _WEEKDAYS[current_language()][weekday]
    return name[:3] if short else name


def weekday_plural(weekday: int) -> str:
    """'Saturdays' / 'sábados' ('lunes' to 'viernes' don't change in Spanish)."""
    name = _WEEKDAYS[current_language()][weekday]
    if current_language() is Language.SPANISH:
        return name + "s" if name.endswith("o") else name
    return name + "s"


def format_clock(moment: datetime | time) -> str:
    """'9:00 AM' in English, '9:00 a. m.' in Spanish (12-hour, as used in the U.S.)."""
    hour = moment.hour % 12 or 12
    if current_language() is Language.SPANISH:
        return f"{hour}:{moment.minute:02d} {'a. m.' if moment.hour < 12 else 'p. m.'}"
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def format_day(day: date) -> str:
    """'Nov 7, 2026' / '7 nov 2026'."""
    if current_language() is Language.SPANISH:
        return f"{day.day} {month_name(day.month, short=True)} {day.year}"
    return f"{month_name(day.month, short=True)} {day.day}, {day.year}"


def format_day_short(day: date) -> str:
    """'Nov 7' / '7 nov' (no year)."""
    if current_language() is Language.SPANISH:
        return f"{day.day} {month_name(day.month, short=True)}"
    return f"{month_name(day.month, short=True)} {day.day}"


def format_weekday_day(day: date) -> str:
    """'Sat, Nov 7' / 'sáb 7 nov'."""
    if current_language() is Language.SPANISH:
        return f"{weekday_name(day.weekday(), short=True)} {day.day} {month_name(day.month, short=True)}"
    return f"{weekday_name(day.weekday(), short=True)}, {month_name(day.month, short=True)} {day.day}"


def format_long_day(day: date) -> str:
    """'Saturday, Nov 7, 2026' / 'sábado, 7 nov 2026'."""
    return f"{weekday_name(day.weekday())}, {format_day(day)}"


def format_month_year(day: date) -> str:
    """'Nov 2026' / 'nov 2026'."""
    return f"{month_name(day.month, short=True)} {day.year}"
