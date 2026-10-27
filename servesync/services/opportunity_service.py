"""
Service opportunities and their shifts: planning, publishing, and scheduling time slots.

Key rules (each one an answer ready for the judges' Q&A):

* New shifts must start in the future, and a closed program takes no new shifts.
* A shift that has started is part of the record and can no longer be edited.
* Capacity can't drop below the number of people already signed up.
* Moving a shift's time re-checks every signed-up volunteer for clashes and age.
* Raising a program's minimum age is refused if it would strand someone already scheduled.
* Closing a program cancels its upcoming sign-ups (spots reopen; history stays).
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta

from servesync.core.errors import BusinessRuleError, RecordNotFoundError, ValidationError
from servesync.core.validators import calculate_age, parse_int, validate_field
from servesync.models import (
    AssignmentStatus,
    Opportunity,
    OpportunityCategory,
    OpportunityStatus,
    Shift,
    ShiftOverview,
)
from servesync.services.base import Service
from servesync.services.rules import check_opportunity_transition, describe_names
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)

MAX_WEEKLY_OCCURRENCES = 52


class OpportunityService(Service):
    # ---------------------------------------------------------- opportunities

    def create(self, session: Session, opportunity: Opportunity) -> Opportunity:
        session.require(Permission.MANAGE_OPPORTUNITIES)
        if opportunity.opportunity_id is not None:
            raise BusinessRuleError("This opportunity already exists.")
        saved = self._store.opportunities.add(opportunity)
        logger.info("Opportunity #%s created by account #%s", saved.opportunity_id, session.account_id)
        return saved

    def update(self, session: Session, opportunity: Opportunity) -> Opportunity:
        """Save edits. Status changes go through :meth:`change_status` so lifecycle rules apply."""
        session.require(Permission.MANAGE_OPPORTUNITIES)
        if opportunity.opportunity_id is None:
            raise BusinessRuleError("Create the opportunity before editing it.")
        with self._store.transaction():
            existing = self._store.opportunities.get(opportunity.opportunity_id)
            if opportunity.min_age > existing.min_age:
                self._check_age_increase(opportunity.opportunity_id, opportunity.min_age)
            return self._store.opportunities.update(dataclasses.replace(opportunity, status=existing.status))

    def change_status(self, session: Session, opportunity_id: int, new_status: OpportunityStatus) -> int:
        """Publish, close, or reopen a program. Returns how many upcoming sign-ups were cancelled."""
        session.require(Permission.MANAGE_OPPORTUNITIES)
        with self._store.transaction():
            existing = self._store.opportunities.get(opportunity_id)
            check_opportunity_transition(existing.status, new_status)
            self._store.opportunities.set_status(opportunity_id, new_status)
            cancelled = 0
            if new_status is OpportunityStatus.CLOSED:
                upcoming = self._store.assignments.upcoming_scheduled(
                    after=self._clock.now(), opportunity_id=opportunity_id
                )
                cancelled = self._cancel_signups(upcoming)
        logger.info("Opportunity #%s -> %s (%s sign-ups cancelled)", opportunity_id, new_status.value, cancelled)
        return cancelled

    def delete(self, session: Session, opportunity_id: int) -> None:
        session.require(Permission.DELETE_RECORDS)
        self._store.opportunities.delete(opportunity_id)

    def get(self, session: Session, opportunity_id: int) -> Opportunity:
        opportunity = self._store.opportunities.get(opportunity_id)
        if not session.can(Permission.MANAGE_OPPORTUNITIES) and opportunity.status is not OpportunityStatus.OPEN:
            # Volunteers only ever see published programs; drafts look like they don't exist.
            raise RecordNotFoundError("Opportunity", opportunity_id)
        return opportunity

    def find_all(
        self,
        session: Session,
        *,
        status: OpportunityStatus | None = None,
        category: OpportunityCategory | None = None,
        search: str = "",
    ) -> list[Opportunity]:
        """Leaders see every program; volunteers see only Open ones."""
        if not session.can(Permission.MANAGE_OPPORTUNITIES):
            status = OpportunityStatus.OPEN
        return self._store.opportunities.find_all(status=status, category=category, search=search)

    # ----------------------------------------------------------------- photos

    def photo(self, session: Session, opportunity_id: int) -> bytes | None:
        """The program's photo (JPEG bytes), or None if it has none."""
        self.get(session, opportunity_id)  # applies the same visibility rules
        return self._store.photos.load(opportunity_id)

    def set_photo(self, session: Session, opportunity_id: int, jpeg: bytes) -> None:
        """Attach the organization's own photo (JPEG, at most 300 kB) to a program."""
        session.require(Permission.MANAGE_OPPORTUNITIES)
        self._store.opportunities.get(opportunity_id)  # must exist
        self._store.photos.save(opportunity_id, jpeg)
        logger.info("Photo set for opportunity #%s (%s bytes)", opportunity_id, len(jpeg))

    def remove_photo(self, session: Session, opportunity_id: int) -> None:
        session.require(Permission.MANAGE_OPPORTUNITIES)
        self._store.photos.delete(opportunity_id)

    # ----------------------------------------------------------------- shifts

    def add_shift(self, session: Session, shift: Shift) -> Shift:
        session.require(Permission.MANAGE_OPPORTUNITIES)
        if shift.shift_id is not None:
            raise BusinessRuleError("This shift already exists.")
        self._check_new_shift(shift)
        saved = self._store.shifts.add(shift)
        logger.info("Shift #%s added to opportunity #%s", saved.shift_id, shift.opportunity_id)
        return saved

    def add_weekly_shifts(self, session: Session, first: Shift, occurrences: object) -> list[Shift]:
        """
        Create ``occurrences`` copies of ``first``, one week apart, all-or-nothing.

        Saves coordinators from entering "every Saturday 9-12" by hand.
        """
        session.require(Permission.MANAGE_OPPORTUNITIES)
        count = validate_field(
            "occurrences", parse_int, occurrences, "Number of weeks", minimum=1, maximum=MAX_WEEKLY_OCCURRENCES
        )
        self._check_new_shift(first)
        created: list[Shift] = []
        with self._store.transaction():
            for week in range(count):
                offset = timedelta(weeks=week)
                created.append(
                    self._store.shifts.add(
                        Shift(
                            opportunity_id=first.opportunity_id,
                            starts_at=first.starts_at + offset,
                            ends_at=first.ends_at + offset,
                            capacity=first.capacity,
                            notes=first.notes,
                        )
                    )
                )
        logger.info("%s weekly shifts added to opportunity #%s", count, first.opportunity_id)
        return created

    def update_shift(self, session: Session, shift: Shift) -> Shift:
        session.require(Permission.MANAGE_OPPORTUNITIES)
        if shift.shift_id is None:
            raise BusinessRuleError("Add the shift before editing it.")
        now = self._clock.now()
        with self._store.transaction():
            existing = self._store.shifts.get(shift.shift_id)
            if existing.has_started(now):
                raise BusinessRuleError("This shift has already started, so its details are now part of the record.")
            if shift.opportunity_id != existing.opportunity_id:
                raise BusinessRuleError(
                    "A shift can't be moved to a different opportunity. Create a new shift instead."
                )
            if shift.starts_at <= now:
                raise ValidationError.single("starts_at", "The new start time must be in the future.")
            filled = self._store.shifts.count_filled(shift.shift_id)
            if shift.capacity < filled:
                raise ValidationError.single(
                    "capacity", f"{filled} volunteers are already signed up, so capacity can't be lower than {filled}."
                )
            if (shift.starts_at, shift.ends_at) != (existing.starts_at, existing.ends_at):
                self._check_reschedule(shift.shift_id, shift)
            return self._store.shifts.update(shift)

    def delete_shift(self, session: Session, shift_id: int) -> None:
        """Remove a shift nobody has signed up for (otherwise the database refuses)."""
        session.require(Permission.MANAGE_OPPORTUNITIES)
        self._store.shifts.delete(shift_id)

    def schedule(
        self,
        session: Session,
        *,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        opportunity_id: int | None = None,
        only_with_openings: bool = False,
        limit: int | None = None,
    ) -> list[ShiftOverview]:
        """Shifts with fill counts. Volunteers see only Open programs."""
        status = None if session.can(Permission.MANAGE_OPPORTUNITIES) else OpportunityStatus.OPEN
        return self._store.shifts.overviews(
            starts_after=starts_after,
            starts_before=starts_before,
            opportunity_id=opportunity_id,
            opportunity_status=status,
            only_with_openings=only_with_openings,
            limit=limit,
        )

    def shift_overview(self, session: Session, shift_id: int) -> ShiftOverview:
        """One shift with its program details and fill count (volunteers: Open programs only)."""
        overview = self._store.shifts.get_overview(shift_id)
        if (
            not session.can(Permission.MANAGE_OPPORTUNITIES)
            and overview.opportunity_status is not OpportunityStatus.OPEN
        ):
            raise RecordNotFoundError("Shift", shift_id)
        return overview

    def upcoming_schedule(
        self, session: Session, *, days: int = 14, only_with_openings: bool = False
    ) -> list[ShiftOverview]:
        days = validate_field("days", parse_int, days, "Days", minimum=1, maximum=366)
        now = self._clock.now()
        return self.schedule(
            session, starts_after=now, starts_before=now + timedelta(days=days), only_with_openings=only_with_openings
        )

    # ---------------------------------------------------------------- helpers

    def _check_new_shift(self, shift: Shift) -> None:
        opportunity = self._store.opportunities.get(shift.opportunity_id)
        if opportunity.status is OpportunityStatus.CLOSED:
            raise BusinessRuleError(f"'{opportunity.title}' is closed. Reopen it before adding shifts.")
        if shift.starts_at <= self._clock.now():
            raise ValidationError.single("starts_at", "New shifts must start in the future.")

    def _check_reschedule(self, shift_id: int, shift: Shift) -> None:
        """Moving a shift must not double-book or under-age anyone already on it."""
        opportunity = self._store.opportunities.get(shift.opportunity_id)
        clashes: list[str] = []
        too_young: list[str] = []
        for entry in self._store.assignments.roster(shift_id):
            if entry.assignment.status is not AssignmentStatus.SCHEDULED:
                continue
            volunteer_id = entry.assignment.volunteer_id
            if self._store.assignments.conflicting_shifts(
                volunteer_id, shift.starts_at, shift.ends_at, exclude_shift_id=shift_id
            ):
                clashes.append(entry.volunteer_name)
            volunteer = self._store.volunteers.get(volunteer_id)
            if calculate_age(volunteer.birth_date, shift.starts_at.date()) < opportunity.min_age:
                too_young.append(entry.volunteer_name)
        if clashes:
            raise BusinessRuleError(
                f"Moving this shift would double-book {describe_names(clashes)}. "
                "Cancel their sign-ups first or choose another time."
            )
        if too_young:
            raise BusinessRuleError(
                f"On the new date {describe_names(too_young)} would be under the minimum age of {opportunity.min_age}."
            )

    def _check_age_increase(self, opportunity_id: int, new_min_age: int) -> None:
        upcoming = self._store.assignments.upcoming_scheduled(after=self._clock.now(), opportunity_id=opportunity_id)
        if not upcoming:
            return
        starts = {s.shift_id: s.starts_at for s in self._store.shifts.for_opportunity(opportunity_id)}
        too_young = sorted(
            {
                volunteer.full_name
                for signup in upcoming
                if (volunteer := self._store.volunteers.get(signup.volunteer_id))
                and calculate_age(volunteer.birth_date, starts[signup.shift_id].date()) < new_min_age
            }
        )
        if too_young:
            raise ValidationError.single(
                "min_age",
                f"{describe_names(too_young)} {'is' if len(too_young) == 1 else 'are'} already scheduled and "
                f"would be under {new_min_age}. Cancel those sign-ups first.",
            )
