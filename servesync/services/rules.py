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

from servesync.core.errors import BusinessRuleError, ValidationError
from servesync.core.i18n import tr, tr_n
from servesync.core.validators import calculate_age
from servesync.models import (
    AccessNeed,
    OpportunityStatus,
    RoleOverview,
    ServiceRecord,
    ShiftOverview,
    ShiftRole,
    Volunteer,
    VolunteerStatus,
    access_gaps,
)
from servesync.models.role import MAX_ROLES_PER_SHIFT

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


def best_role(roles: Sequence[RoleOverview], skills: frozenset[str]) -> RoleOverview | None:
    """
    The role to give someone who didn't choose one, or None if no open role fits them.

    Roles that need a skill the person has come first, so skilled people fill the
    skilled jobs and general spots stay free for everyone else. Then the role with
    the most room, then the order the leader listed the roles in.
    """
    fitting = [role for role in roles if not role.is_full and role.role.fits(skills)]
    if not fitting:
        return None
    return min(
        fitting,
        key=lambda role: (not role.role.required_skill, -role.open_spots, role.role.position, role.role.role_id or 0),
    )


def walk_in_role(roles: Sequence[RoleOverview], skills: frozenset[str]) -> RoleOverview:
    """
    The role to record a walk-in under. Walk-ins may go over capacity (the person is
    already there helping), so this prefers an open role that fits, then any role
    that fits, then the first role.
    """
    fitting = [role for role in roles if role.role.fits(skills)]
    return best_role(roles, skills) or (fitting[0] if fitting else roles[0])


def role_problems(role: RoleOverview, volunteer: Volunteer) -> list[str]:
    """Why this particular role can't be given to the volunteer (empty list = it can)."""
    reasons = []
    if role.is_full:
        reasons.append(tr("The {role} role is full.", role=role.role.display_name))
    if not role.role.fits(volunteer.skills):
        reasons.append(
            tr(
                "The {role} role needs {skill}, which isn't on {full_name}'s profile.",
                role=role.role.display_name,
                skill=role.role.required_skill,
                full_name=volunteer.full_name,
            )
        )
    return reasons


def no_fitting_role_message(volunteer: Volunteer, roles: Sequence[RoleOverview]) -> str:
    """Explains a shift with open spots that are all in roles needing a skill the person lacks."""
    needs = sorted(
        {role.role.required_skill for role in roles if not role.is_full and role.role.required_skill}, key=str.casefold
    )
    return tr(
        "The open spots on this shift need {skills}, which isn't on {full_name}'s profile.",
        skills=describe_names(needs) or tr("a skill"),
        full_name=volunteer.full_name,
    )


def check_roles(roles: Sequence[ShiftRole], current: Sequence[RoleOverview]) -> None:
    """
    Check a leader's edit of a shift's roles before it is saved.

    Every problem is reported at once, keyed by row ("role_2_capacity"), so the
    form can show each message beside its field. Rules: one to twelve roles;
    names unique (ignoring case); a role can't shrink below the people already
    in it; and a role with people in it can't be removed.
    """
    errors: dict[str, str] = {}
    if not roles:
        errors["roles"] = tr("A shift needs at least one role.")
    elif len(roles) > MAX_ROLES_PER_SHIFT:
        errors["roles"] = tr("A shift can have at most {count} roles.", count=MAX_ROLES_PER_SHIFT)
    seen: set[str] = set()
    filled = {overview.role.role_id: overview.filled for overview in current}
    for index, role in enumerate(roles):
        key = role.name.casefold()
        if key in seen:
            errors[f"role_{index}_name"] = tr("Two roles can't have the same name.")
        seen.add(key)
        taken = filled.get(role.role_id, 0) if role.role_id is not None else 0
        if role.capacity < taken:
            errors[f"role_{index}_capacity"] = tr_n(
                "{count} person is already in this role, so it needs at least {count} spot.",
                "{count} people are already in this role, so it needs at least {count} spots.",
                taken,
            )
    kept = {role.role_id for role in roles if role.role_id is not None}
    for overview in current:
        if overview.role.role_id not in kept and overview.filled:
            errors.setdefault(
                "roles",
                tr_n(
                    "{count} person is signed up as {role}. Cancel or move them before removing the role.",
                    "{count} people are signed up as {role}. Cancel or move them before removing the role.",
                    overview.filled,
                    role=overview.role.display_name,
                ),
            )
    if errors:
        raise ValidationError(errors)


def signup_blockers(
    *,
    volunteer: Volunteer,
    overview: ShiftOverview,
    min_age: int,
    now: datetime,
    already_signed_up: bool,
    has_conflict: bool,
    required_certifications: Iterable[str],
    role_reasons: Sequence[str] = (),
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
    if not already_signed_up and not overview.is_full:
        reasons.extend(role_reasons)  # a full shift already says so; role details would only repeat it
    return reasons


def waitlist_blockers(sign_up_reasons: Sequence[str], *, shift_is_open_to_them: bool) -> list[str]:
    """
    Whether someone may join a shift's waitlist, given why they can't sign up now.

    The waitlist is only for people kept out by a lack of space: if the shift (or a
    role that fits them) has room, they should sign up instead, and if something
    else stops them (age, a missing certification), waiting wouldn't help.
    """
    if shift_is_open_to_them:
        return [tr("There's still a spot for you on this shift. Sign up instead.")]
    return list(sign_up_reasons)


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
