"""
Read models: immutable, query-shaped views that join several tables.

Screens and reports rarely want one raw table — a shift list needs the
opportunity's title and how many spots are filled; a roster needs volunteer
names. Rather than making the UI stitch tables together (slow and error-prone),
repositories return these purpose-built, read-only objects. This is the
"query side" of the Command-Query Separation principle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from servesync.core.i18n import tr
from servesync.core.validators import format_phone
from servesync.models.assignment import Assignment
from servesync.models.enums import (
    ActivityKind,
    AssignmentStatus,
    NoticeKind,
    OpportunityCategory,
    OpportunityStatus,
    RecruitmentSource,
    VolunteerStatus,
)
from servesync.models.opportunity import Shift


@dataclass(frozen=True, slots=True)
class ShiftOverview:
    """A shift plus the opportunity details and fill count a schedule view needs."""

    shift: Shift
    opportunity_title: str
    category: OpportunityCategory
    location: str
    opportunity_status: OpportunityStatus
    filled: int

    @property
    def open_spots(self) -> int:
        return max(self.shift.capacity - self.filled, 0)

    @property
    def is_full(self) -> bool:
        return self.filled >= self.shift.capacity

    @property
    def fill_ratio(self) -> float:
        return min(self.filled / self.shift.capacity, 1.0)


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One line on a shift's sign-in sheet."""

    assignment: Assignment
    volunteer_name: str
    volunteer_email: str
    volunteer_phone: str
    role_name: str = ""  # "" is the shift's general role

    @property
    def display_phone(self) -> str:
        return format_phone(self.volunteer_phone)

    @property
    def role_display(self) -> str:
        return self.role_name or tr("General")


@dataclass(frozen=True, slots=True)
class ServiceRecord:
    """One line of a volunteer's service history."""

    assignment: Assignment
    opportunity_title: str
    category: OpportunityCategory
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class VolunteerParticipation:
    """Participation totals for one volunteer (backed by a SQL view)."""

    volunteer_id: int
    full_name: str
    status: VolunteerStatus
    total_hours: float
    shifts_attended: int
    no_shows: int
    cancellations: int
    upcoming_shifts: int
    last_served_on: date | None

    @property
    def reliability(self) -> float | None:
        """
        Share of completed commitments the volunteer kept (attended / (attended + no-shows)).

        ``None`` when there is no history yet, so newcomers are not penalized.
        """
        completed = self.shifts_attended + self.no_shows
        return None if completed == 0 else round(self.shifts_attended / completed, 3)


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """One line of the activity feed: someone applied, signed up, or served."""

    kind: ActivityKind
    occurred_at: datetime
    volunteer_name: str
    opportunity_title: str = ""
    hours: float | None = None
    shift_starts_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ServiceFact:
    """
    One sign-up, flattened with everything a report could group or filter by.

    Reports load a list of these in a single query, then aggregate in Python
    with plain dictionaries and lists. That keeps every report's math in one
    readable, testable place (``services/analytics.py``) instead of scattered
    across many specialised SQL statements.
    """

    assignment_id: int
    status: AssignmentStatus
    hours_served: float | None
    shift_id: int
    starts_at: datetime
    ends_at: datetime
    capacity: int
    opportunity_id: int
    opportunity_title: str
    category: OpportunityCategory
    volunteer_id: int
    volunteer_name: str
    volunteer_status: VolunteerStatus
    recruitment_source: RecruitmentSource

    @property
    def hours(self) -> float:
        """Hours that count toward totals (only attended service counts)."""
        if self.status is not AssignmentStatus.ATTENDED:
            return 0.0
        return self.hours_served or 0.0


@dataclass(frozen=True, slots=True)
class WaitlistEntry:
    """One person waiting for a spot on a full shift (oldest first)."""

    entry_id: int
    shift_id: int
    volunteer_id: int
    volunteer_name: str
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class Notice:
    """A message waiting on a volunteer's Home page, with the shift it is about."""

    notice_id: int
    volunteer_id: int
    kind: NoticeKind
    created_at: datetime
    shift_id: int
    opportunity_title: str
    starts_at: datetime
    ends_at: datetime
    role_name: str = ""


@dataclass(frozen=True, slots=True)
class Announcement:
    """A leader's note to everyone signed up for a program or for one shift."""

    announcement_id: int
    body: str
    posted_by: str
    posted_at: datetime
    opportunity_title: str
    opportunity_id: int | None = None  # set when it is for the whole program
    shift_id: int | None = None  # set when it is for one shift
    shift_starts_at: datetime | None = None
