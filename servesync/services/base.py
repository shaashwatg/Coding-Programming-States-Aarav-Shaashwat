"""Shared base class for services (dependency injection of storage and time)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable

from servesync.data import DataStore
from servesync.models import Assignment, AssignmentStatus
from servesync.services.clock import Clock

#: Who to name in the history for something done without signing in (the public application form).
PUBLIC_FORM = "application-form"
#: ... and for a sign-up made automatically from a waitlist.
WAITLIST = "waitlist"


class Service:
    """Every service receives its collaborators instead of creating them."""

    def __init__(self, store: DataStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock
        #: Called with the shifts that just gained free spots, so their waitlists can move up.
        #: The composition root (``Services.create``) connects it to the scheduling service;
        #: services don't import each other, which keeps the layers simple.
        self.on_spots_freed: Callable[[Iterable[int]], object] = lambda _shift_ids: None

    def _log(
        self,
        who: str,
        action: str,
        entity: str,
        entity_id: int | None,
        label: str,
        details: str = "",
    ) -> None:
        """
        Add a line to the change history (who, what, when). Only codes and names are stored,
        so the history can be worded in either language; field values (like a new phone
        number) are deliberately left out, so the history doesn't become a second copy of
        personal data.
        """
        self._store.changes.add(
            changed_at=self._clock.now(),
            changed_by=who,
            action=action,
            entity=entity,
            entity_id=entity_id,
            label=label,
            details=details,
        )

    def _signup_label(self, signup: Assignment) -> str:
        """'Priya Patel: Food Pantry, 2026-11-07 09:00' for the change history."""
        volunteer = self._store.volunteers.get(signup.volunteer_id).full_name
        overview = self._store.shifts.get_overview(signup.shift_id)
        return f"{volunteer}: {overview.opportunity_title}, {overview.shift.starts_at:%Y-%m-%d %H:%M}"

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


def changed_fields(old: object, new: object, fields: Iterable[str]) -> str:
    """The names of the fields that differ between two versions of a record, e.g. 'email, phone'."""
    return ", ".join(name for name in fields if getattr(old, name, None) != getattr(new, name, None))
