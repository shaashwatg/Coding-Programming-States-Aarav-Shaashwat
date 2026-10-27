"""
Business rules as pure functions.

These functions take plain facts and return decisions; they never touch the
database or the clock. That makes the organization's policies easy to read
in one place, easy to explain to judges, and testable in microseconds.
Services gather the facts, call these rules, and act on the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType

from servesync.core.errors import BusinessRuleError
from servesync.core.validators import calculate_age
from servesync.models import AccessNeed, OpportunityStatus, ShiftOverview, Volunteer, VolunteerStatus, access_gaps

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
        raise BusinessRuleError(f"This volunteer is already {new.label}.")
    if new not in VOLUNTEER_TRANSITIONS[current]:
        raise BusinessRuleError(f"A volunteer can't move from {current.label} to {new.label}.")


def check_opportunity_transition(current: OpportunityStatus, new: OpportunityStatus) -> None:
    if current is new:
        raise BusinessRuleError(f"This opportunity is already {new.label}.")
    if new not in OPPORTUNITY_TRANSITIONS[current]:
        raise BusinessRuleError(f"An opportunity can't move from {current.label} back to {new.label}.")


def signup_blockers(
    *,
    volunteer: Volunteer,
    overview: ShiftOverview,
    min_age: int,
    now: datetime,
    already_signed_up: bool,
    has_conflict: bool,
) -> list[str]:
    """
    Every reason ``volunteer`` cannot sign up for the shift (empty list = allowed).

    Returning *all* reasons, not just the first, lets the interface explain
    the full picture ("full, and you'd also be double-booked").
    """
    reasons: list[str] = []
    shift = overview.shift
    if not volunteer.status.can_be_scheduled:
        reasons.append(f"{volunteer.full_name} is {volunteer.status.label} and can't be scheduled until approved.")
    if not overview.opportunity_status.accepts_signups:
        reasons.append(
            f"'{overview.opportunity_title}' is {overview.opportunity_status.label} and not taking sign-ups."
        )
    if shift.starts_at <= now:
        reasons.append("This shift has already started.")
    if already_signed_up:
        reasons.append(f"{volunteer.full_name} is already signed up for this shift.")
    elif overview.is_full:
        reasons.append("This shift is full.")
    age = calculate_age(volunteer.birth_date, shift.starts_at.date())
    if age < min_age:
        reasons.append(
            f"'{overview.opportunity_title}' requires volunteers aged {min_age}+; {volunteer.given_name} will be {age}."
        )
    if has_conflict:
        reasons.append(f"{volunteer.full_name} is already scheduled for another shift at that time.")
    return reasons


def describe_access_gaps(needs: frozenset[AccessNeed], offered: frozenset[AccessNeed], program_title: str) -> list[str]:
    """
    Plain-English notes for each access need a program doesn't list as met.

    These are *information*, never a reason to refuse a sign-up: the person
    knows their own needs best, and a coordinator can often arrange support.
    """
    return [f"Needs {need.label.lower()}: '{program_title}' {need.gap_text}" for need in access_gaps(needs, offered)]


def describe_names(names: Sequence[str], limit: int = 3) -> str:
    """Readable list for messages: 'Ana, Ben and Cara' or 'Ana, Ben, Cara and 2 more'."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{', '.join(names[:limit])} and {len(names) - limit} more"
