"""
Attendance — turning sign-ups into verified service hours.

Rules:
* Attendance is recorded only once a shift has started (no logging the future).
* Hours default to the shift's length and can never exceed it.
* Walk-ins (people who show up without signing up) can be recorded, even past
  capacity, but they must be Active, old enough, and not booked elsewhere.
"""

from __future__ import annotations

import dataclasses
import logging

from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr
from servesync.core.validators import calculate_age, parse_hours, validate_field
from servesync.models import Assignment, AssignmentStatus, RosterEntry, Shift
from servesync.services.base import Service
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)


class AttendanceService(Service):
    def roster(self, session: Session, shift_id: int, *, include_cancelled: bool = False) -> list[RosterEntry]:
        session.require(Permission.RECORD_ATTENDANCE)
        return self._store.assignments.roster(shift_id, include_cancelled=include_cancelled)

    def record_attendance(self, session: Session, assignment_id: int, hours: object = None) -> Assignment:
        """Mark a volunteer as attended. ``hours`` defaults to the full shift length."""
        session.require(Permission.RECORD_ATTENDANCE)
        signup = self._store.assignments.get(assignment_id)
        shift = self._started_shift(signup.shift_id)
        attended = dataclasses.replace(
            signup, status=AssignmentStatus.ATTENDED, hours_served=self._hours_for(shift, hours)
        )
        saved = self._store.assignments.update(attended)
        logger.info("Sign-up #%s marked attended (%s h)", assignment_id, saved.hours_served)
        return saved

    def mark_no_show(self, session: Session, assignment_id: int) -> Assignment:
        session.require(Permission.RECORD_ATTENDANCE)
        signup = self._store.assignments.get(assignment_id)
        if signup.status is AssignmentStatus.CANCELLED:
            raise BusinessRuleError(tr("This sign-up was cancelled in advance, so it isn't a no-show."))
        self._started_shift(signup.shift_id)
        return self._store.assignments.update(
            dataclasses.replace(signup, status=AssignmentStatus.NO_SHOW, hours_served=None)
        )

    def check_in_everyone(self, session: Session, shift_id: int) -> int:
        """Mark every still-scheduled volunteer on a shift as attended for the full shift."""
        session.require(Permission.RECORD_ATTENDANCE)
        shift = self._started_shift(shift_id)
        count = 0
        with self._store.transaction():
            for entry in self._store.assignments.roster(shift_id):
                if entry.assignment.status is AssignmentStatus.SCHEDULED:
                    self._store.assignments.update(
                        dataclasses.replace(
                            entry.assignment, status=AssignmentStatus.ATTENDED, hours_served=shift.duration_hours
                        )
                    )
                    count += 1
        logger.info("Checked in %s volunteers on shift #%s", count, shift_id)
        return count

    def record_walk_in(self, session: Session, shift_id: int, volunteer_id: int, hours: object = None) -> Assignment:
        """Record someone who served without signing up first."""
        session.require(Permission.RECORD_ATTENDANCE)
        shift = self._started_shift(shift_id)
        existing = self._store.assignments.find(shift_id, volunteer_id)
        if existing is not None:
            return self.record_attendance(session, existing.assignment_id or 0, hours)

        volunteer = self._store.volunteers.get(volunteer_id)
        opportunity = self._store.opportunities.get(shift.opportunity_id)
        if not volunteer.status.can_be_scheduled:
            raise BusinessRuleError(
                tr(
                    "{full_name} is {label}; approve them first.",
                    full_name=volunteer.full_name,
                    label=volunteer.status.label,
                )
            )
        if calculate_age(volunteer.birth_date, shift.starts_at.date()) < opportunity.min_age:
            raise BusinessRuleError(
                tr(
                    "'{title}' requires volunteers aged {min_age}+.",
                    title=opportunity.title,
                    min_age=opportunity.min_age,
                )
            )
        if self._store.assignments.conflicting_shifts(
            volunteer_id, shift.starts_at, shift.ends_at, exclude_shift_id=shift_id
        ):
            raise BusinessRuleError(
                tr("{full_name} is recorded on another shift at that time.", full_name=volunteer.full_name)
            )
        saved = self._store.assignments.add(
            Assignment(
                shift_id=shift_id,
                volunteer_id=volunteer_id,
                status=AssignmentStatus.ATTENDED,
                hours_served=self._hours_for(shift, hours),
                signed_up_at=self._clock.now(),
            )
        )
        logger.info("Walk-in: volunteer #%s on shift #%s", volunteer_id, shift_id)
        return saved

    # ---------------------------------------------------------------- helpers

    def _started_shift(self, shift_id: int) -> Shift:
        shift = self._store.shifts.get(shift_id)
        if not shift.has_started(self._clock.now()):
            raise BusinessRuleError(tr("Attendance can be recorded once the shift has started."))
        return shift

    @staticmethod
    def _hours_for(shift: Shift, hours: object) -> float:
        """Default to the full shift; never more than the shift actually lasted (semantic check)."""
        if hours is None or (isinstance(hours, str) and not hours.strip()):
            return shift.duration_hours
        return float(
            validate_field("hours_served", parse_hours, hours, tr("Hours served"), maximum=shift.duration_hours)
        )
