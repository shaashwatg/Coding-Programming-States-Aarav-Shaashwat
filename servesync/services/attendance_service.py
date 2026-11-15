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
from dataclasses import dataclass
from datetime import timedelta

from servesync.config import MAX_SHIFT_HOURS
from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr
from servesync.core.validators import calculate_age, parse_hours, parse_int, validate_field
from servesync.models import Assignment, AssignmentStatus, RosterEntry, Shift, ShiftOverview
from servesync.models.opportunity import MAX_IMPACT_AMOUNT
from servesync.services.base import Service
from servesync.services.rules import (
    HourGoalProgress,
    certification_message,
    hour_goal_progress,
    missing_certifications,
    walk_in_role,
)
from servesync.services.session import Permission, Session

logger = logging.getLogger(__name__)

CHECK_IN_EARLY_MINUTES = 30
PHONE_DIGITS_FOR_CHECK_IN = 4


@dataclass(frozen=True, slots=True)
class KioskPerson:
    """One possible match on the check-in screen (just enough to tell people apart)."""

    assignment_id: int
    short_name: str


@dataclass(frozen=True, slots=True)
class KioskResult:
    given_name: str
    hours: float
    goal: HourGoalProgress | None
    assignment: Assignment


def _first_name_and_initial(full_name: str) -> str:
    first, _, last = full_name.rpartition(" ")
    return f"{first} {last[:1]}." if first else full_name


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
        missing = missing_certifications(volunteer, opportunity.required_certifications, shift.starts_at.date())
        if missing:
            raise BusinessRuleError(certification_message(volunteer, missing))
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
                role_id=walk_in_role(self._store.shifts.roles(shift_id), volunteer.skills).role.role_id,
            )
        )
        logger.info("Walk-in: volunteer #%s on shift #%s", volunteer_id, shift_id)
        return saved

    # ------------------------------------------------------------ check-in kiosk

    def kiosk_shifts(self, session: Session) -> list[ShiftOverview]:
        """Shifts people can check in for right now: from 30 minutes before the start until the end."""
        session.require(Permission.RECORD_ATTENDANCE)
        now = self._clock.now()
        nearby = self._store.shifts.overviews(
            starts_after=now - timedelta(hours=MAX_SHIFT_HOURS),
            starts_before=now + timedelta(minutes=CHECK_IN_EARLY_MINUTES + 1),  # the bound is exclusive
        )
        earliest_start = now + timedelta(minutes=CHECK_IN_EARLY_MINUTES)
        return [o for o in nearby if o.shift.starts_at <= earliest_start and o.shift.ends_at > now]

    def kiosk_lookup(self, session: Session, shift_id: int, last_four: str) -> list[KioskPerson]:
        """
        Find who is checking in from the last 4 digits of their phone. Only people on this
        shift can match, and only a first name and last initial are shown on the shared screen.
        """
        session.require(Permission.RECORD_ATTENDANCE)
        digits = last_four.strip()
        if len(digits) != PHONE_DIGITS_FOR_CHECK_IN or not digits.isdecimal():
            raise BusinessRuleError(tr("Enter the last 4 digits of your phone number."))
        people = [
            KioskPerson(entry.assignment.assignment_id or 0, _first_name_and_initial(entry.volunteer_name))
            for entry in self._store.assignments.roster(shift_id)
            if entry.volunteer_phone.endswith(digits)
        ]
        if not people:
            raise BusinessRuleError(tr("We couldn't find you on this shift. Please see a coordinator."))
        return people

    def kiosk_check_in(self, session: Session, assignment_id: int) -> KioskResult:
        """Record arrival for the full shift (a leader can correct the hours on the roster afterward)."""
        session.require(Permission.RECORD_ATTENDANCE)
        signup = self._store.assignments.get(assignment_id)
        shift = self._store.shifts.get(signup.shift_id)
        if shift.shift_id not in {o.shift.shift_id for o in self.kiosk_shifts(session)}:
            raise BusinessRuleError(tr("Check-in for this shift isn't open right now."))
        if signup.status is AssignmentStatus.ATTENDED:
            raise BusinessRuleError(tr("You're already checked in. Thank you for coming!"))
        volunteer = self._store.volunteers.get(signup.volunteer_id)
        required = self._store.opportunities.get(shift.opportunity_id).required_certifications
        if missing_certifications(volunteer, required, shift.starts_at.date()):
            raise BusinessRuleError(tr("Please see a coordinator before you start today."))
        saved = self._store.assignments.update(
            dataclasses.replace(signup, status=AssignmentStatus.ATTENDED, hours_served=shift.duration_hours)
        )
        logger.info("Kiosk check-in: sign-up #%s", assignment_id)
        return KioskResult(
            volunteer.given_name,
            shift.duration_hours,
            hour_goal_progress(
                volunteer, self._store.assignments.history(signup.volunteer_id), self._clock.now().date()
            ),
            saved,
        )

    # ---------------------------------------------------------------- helpers

    def record_impact(self, session: Session, shift_id: int, amount: object) -> Shift:
        """Record what a shift achieved, in its program's unit (only once the shift has started)."""
        session.require(Permission.RECORD_ATTENDANCE)
        shift = self._started_shift(shift_id)
        opportunity = self._store.opportunities.get(shift.opportunity_id)
        if not opportunity.impact_unit:
            raise BusinessRuleError(
                tr("Choose what '{title}' measures first (edit the program).", title=opportunity.title)
            )
        value = validate_field("impact_amount", parse_int, amount, tr("Result"), minimum=0, maximum=MAX_IMPACT_AMOUNT)
        return self._store.shifts.set_impact(shift_id, int(value))

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
