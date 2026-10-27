"""
Injectable clock.

Many business rules depend on "now": a shift that already started can't
take sign-ups, a lockout expires after 15 minutes, attendance can't be
recorded for the future. If services called ``datetime.now()`` directly,
those rules could only be tested by waiting. Instead every service asks a
``Clock``; the real app passes :class:`SystemClock`, and tests pass a
:class:`FixedClock` they can move forward on demand.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current local time, to the minute."""
        ...


class SystemClock:
    """The real wall clock."""

    def now(self) -> datetime:
        return datetime.now().replace(second=0, microsecond=0)


class FixedClock:
    """A clock that only moves when told to (tests and scripted demos)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment.replace(second=0, microsecond=0)

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = moment.replace(second=0, microsecond=0)

    def advance(self, delta: timedelta) -> None:
        self._moment += delta
