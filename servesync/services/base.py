"""Shared base class for services (dependency injection of storage and time)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable

from servesync.data import DataStore
from servesync.models import Assignment, AssignmentStatus
from servesync.services.clock import Clock


class Service:
    """Every service receives its collaborators instead of creating them."""

    def __init__(self, store: DataStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        #: Called with the shifts that just gained free spots, so their waitlists can move up.
        #: The composition root (``Services.create``) connects it to the scheduling service;
        #: services don't import each other, which keeps the layers simple.
        self.on_spots_freed: Callable[[Iterable[int]], object] = lambda _shift_ids: None

    def _cancel_signups(self, signups: Iterable[Assignment]) -> int:
        """Mark sign-ups CANCELLED (frees their spots, keeps the record). Returns how many."""
        freed: set[int] = set()
        count = 0
        for signup in signups:
            self._store.assignments.update(
                dataclasses.replace(signup, status=AssignmentStatus.CANCELLED, hours_served=None)
            )
            freed.add(signup.shift_id)
            count += 1
        self.on_spots_freed(freed)
        return count
