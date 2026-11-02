"""
Business rules as pure functions.

These functions take plain facts and return decisions; they never touch the
database or the clock. That makes the organization's policies easy to read
in one place, easy to explain to judges, and testable in microseconds.
Services gather the facts, call these rules, and act on the answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr
from servesync.core.validators import calculate_age
from servesync.models import (
    AccessNeed,
    OpportunityStatus,
    ServiceRecord,
    ShiftOverview,
    Volunteer,
    VolunteerStatus,
    access_gaps,
)

#: Allowed recruitment-pipeline moves. Applicants are approved (Active) or
#: declined (Inactive); Active volunteers can be archived and later return.
VOLUNTEER_TRANSITIONS: Mapping[VolunteerStatus, frozenset[VolunteerStatus]] = MappingProxyType(
    {
        VolunteerStatus.APPLICANT: frozenset({VolunteerStatus.ACTIVE, VolunteerStatus.INACTIVE}),
        VolunteerStatus.ACTIVE: frozenset({VolunteerStatus.INACTIVE}),
        VolunteerStatus.INACTIVE: frozenset({VolunteerStatus.ACTIVE}),
    }
)

#: Allowed opportunity lifecycle moves. Once published, a program never goes
#: back to Draft, because volunteers may already have seen or joined it.
OPPORTUNITY_TRANSITIONS: Mapping[OpportunityStatus, frozenset[OpportunityStatus]] = MappingProxyType(
    {
        OpportunityStatus.DRAFT: frozenset({OpportunityStatus.OPEN, OpportunityStatus.CLOSED}),
        OpportunityStatus.OPEN: frozenset({OpportunityStatus.CLOSED}),
        OpportunityStatus.CLOSED: frozenset({OpportunityStatus.OPEN}),
    }
)


def check_volunteer_transition(current: VolunteerStatus, new: VolunteerStatus) -> None:
    if current is new:
        raise BusinessRuleError(tr("This volunteer is already {label}.", label=new.label))
    if new not in VOLUNTEER_TRANSITIONS[current]:
        raise BusinessRuleError(
            tr("A volunteer can't move from {label} to {label2}.", label=current.label, label2=new.label)
        )


def check_opportunity_transition(current: OpportunityStatus, new: OpportunityStatus) -> None:
    if current is new:
        raise BusinessRuleError(tr("This opportunity is already {label}.", label=new.label))
    if new not in OPPORTUNITY_TRANSITIONS[current]:
        raise BusinessRuleError(
            tr("An opportunity can't move from {label} back to {label2}.", label=current.label, label2=new.label)
        )


def missing_certifications(volunteer: Volunteer, required: Iterable[str], on: date) -> list[str]:
    """The required certifications this volunteer won't hold, or that will have run out, on the given day."""
    missing = []
    for name in sorted(required, key=str.casefold):
        held = volunteer.certification(name)
        if held is None or not held.is_valid_on(on):
            missing.append(name)
    return missing


def certification_message(volunteer: Volunteer, missing: Sequence[str]) -> str:
    return tr(
        "{full_name} needs a current certification for this program: {names}.",
        full_name=volunteer.full_name,
        names=", ".join(missing),
    )


def signup_blockers(
    *,
    volunteer: Volunteer,
    overview: ShiftOverview,
    min_age: int,
    now: datetime,
    already_signed_up: bool,
    has_conflict: bool,
    required_certifications: Iterable[str],
) -> list[str]:
    """
    Every reason ``volunteer`` cannot sign up for the shift (empty list = allowed).

    Returning *all* reasons, not just the first, lets the interface explain
    the full picture ("full, and you'd also be double-booked").
    """
    reasons: list[str] = []
    shift = overview.shift
    if not volunteer.status.can_be_scheduled:
        reasons.append(
            tr(
                "{full_name} is {label} and can't be scheduled until approved.",
                full_name=volunteer.full_name,
                label=volunteer.status.label,
            )
        )
    if not overview.opportunity_status.accepts_signups:
        reasons.append(
            tr(
                "'{opportunity_title}' is {label} and not taking sign-ups.",
                opportunity_title=overview.opportunity_title,
                label=overview.opportunity_status.label,
            )
        )
    if shift.starts_at <= now:
        reasons.append(tr("This shift has already started."))
    if already_signed_up:
        reasons.append(tr("{full_name} is already signed up for this shift.", full_name=volunteer.full_name))
    elif overview.is_full:
        reasons.append(tr("This shift is full."))
    age = calculate_age(volunteer.birth_date, shift.starts_at.date())
    if age < min_age:
        reasons.append(
            tr(
                ("'{opportunity_title}' requires volunteers aged {min_age}+; {given_name} will be {age}."),
                opportunity_title=overview.opportunity_title,
                min_age=min_age,
                given_name=volunteer.given_name,
                age=age,
            )
        )
    missing = missing_certifications(volunteer, required_certifications, shift.starts_at.date())
    if missing:
        reasons.append(certification_message(volunteer, missing))
    if has_conflict:
        reasons.append(
            tr("{full_name} is already scheduled for another shift at that time.", full_name=volunteer.full_name)
        )
    return reasons


@dataclass(frozen=True, slots=True)
class HourGoalProgress:
    """How a volunteer is doing against their personal goal, counted from Aug 1 (the school year)."""

    goal: int
    due: date
    served: float
    expected_by_now: float
    days_left: int

    @property
    def remaining(self) -> float:
        return max(self.goal - self.served, 0.0)

    @property
    def share(self) -> float:
        return min(self.served / self.goal, 1.0)

    @property
    def reached(self) -> bool:
        return self.served >= self.goal

    @property
    def on_pace(self) -> bool:
        return self.served >= self.expected_by_now

    @property
    def hours_per_week(self) -> float:
        """What it takes from here; the whole remainder when there are no full weeks left."""
        return round(self.remaining / max(self.days_left / 7, 1.0), 1)


def school_year_start(today: date) -> date:
    return date(today.year if today.month >= 8 else today.year - 1, 8, 1)


def hour_goal_progress(volunteer: Volunteer, records: Iterable[ServiceRecord], today: date) -> HourGoalProgress | None:
    """Progress toward a volunteer's goal (pure: facts in, answer out), or None if no goal is set."""
    if volunteer.hour_goal is None or volunteer.hour_goal_due is None:
        return None
    start = school_year_start(today)
    served = sum(r.assignment.counted_hours for r in records if start <= r.starts_at.date() <= volunteer.hour_goal_due)
    span = max((volunteer.hour_goal_due - start).days, 1)
    elapsed = min(max((today - start).days, 0), span)
    return HourGoalProgress(
        goal=volunteer.hour_goal,
        due=volunteer.hour_goal_due,
        served=round(served, 2),
        expected_by_now=round(volunteer.hour_goal * elapsed / span, 2),
        days_left=max((volunteer.hour_goal_due - today).days, 0),
    )


def describe_access_gaps(needs: frozenset[AccessNeed], offered: frozenset[AccessNeed], program_title: str) -> list[str]:
    """
    Plain-English notes for each access need a program doesn't list as met.

    These are *information*, never a reason to refuse a sign-up: the person
    knows their own needs best, and a coordinator can often arrange support.
    """
    return [
        tr("Needs {need}: '{program}' {gap}", need=need.label.lower(), program=program_title, gap=need.gap_text)
        for need in access_gaps(needs, offered)
    ]


def describe_names(names: Sequence[str], limit: int = 3) -> str:
    """Readable list for messages: 'Ana, Ben and Cara' or 'Ana, Ben, Cara and 2 more'."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return tr("{first} and {last}", first=", ".join(names[:-1]), last=names[-1])
    return tr("{join} and {value} more", join=", ".join(names[:limit]), value=len(names) - limit)
