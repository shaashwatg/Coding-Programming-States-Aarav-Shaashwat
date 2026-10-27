"""
Assignment: one volunteer signed up for one shift, plus its attendance outcome.

This is the heart of "maintain records and monitor participation": every hour
a volunteer serves is an ``Assignment`` marked ``ATTENDED`` with
``hours_served`` filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from servesync.config import MAX_SHIFT_HOURS
from servesync.core.validators import ErrorCollector, parse_datetime, parse_enum, parse_hours
from servesync.models._common import validate_optional_id, validate_reference_id
from servesync.models.enums import AssignmentStatus


def _now_to_minute() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _parse_optional_hours(value: object) -> float | None:
    return None if value is None else parse_hours(value, "Hours served", maximum=MAX_SHIFT_HOURS)


@dataclass(slots=True)
class Assignment:
    """A volunteer's sign-up for a shift."""

    shift_id: int
    volunteer_id: int
    status: AssignmentStatus = AssignmentStatus.SCHEDULED
    hours_served: float | None = None
    signed_up_at: datetime = field(default_factory=_now_to_minute)
    assignment_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        self.shift_id = errors.check("shift_id", validate_reference_id, self.shift_id, "Shift")
        self.volunteer_id = errors.check("volunteer_id", validate_reference_id, self.volunteer_id, "Volunteer")
        self.status = errors.check("status", parse_enum, self.status, AssignmentStatus, "Attendance status")
        self.hours_served = errors.check("hours_served", _parse_optional_hours, self.hours_served)
        self.signed_up_at = errors.check("signed_up_at", parse_datetime, self.signed_up_at, "Sign-up time")
        self.assignment_id = errors.check("assignment_id", validate_optional_id, self.assignment_id, "Assignment ID")

        # Semantic invariant (also enforced by a CHECK constraint in SQLite):
        # hours exist if, and only if, the volunteer actually attended.
        if self.status is AssignmentStatus.ATTENDED and self.hours_served is None:
            errors.add("hours_served", "Enter the hours served when marking a volunteer as attended.")
        if self.status is not AssignmentStatus.ATTENDED and self.hours_served is not None:
            errors.add("hours_served", "Hours can only be recorded for volunteers who attended.")
        errors.raise_if_any()

    @property
    def counted_hours(self) -> float:
        """Hours that count toward totals (0 unless attended)."""
        return self.hours_served or 0.0
