"""Shared base class for services (dependency injection of storage and time)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from servesync.data import DataStore
from servesync.models import Assignment, AssignmentStatus
from servesync.services.clock import Clock


class Service:
    """Every service receives its collaborators instead of creating them."""

    def __init__(self, store: DataStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def _cancel_signups(self, signups: Iterable[Assignment]) -> int:
        """Mark sign-ups CANCELLED (frees their spots, keeps the record). Returns how many."""
        count = 0
        for signup in signups:
            self._store.assignments.update(
                dataclasses.replace(signup, status=AssignmentStatus.CANCELLED, hours_served=None)
            )
            count += 1
        return count
