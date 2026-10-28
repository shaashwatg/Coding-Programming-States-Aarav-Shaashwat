"""
Smart Match — ServeSync's intelligent feature.

Given a shift, Smart Match ranks every *eligible* volunteer from 0 to 100;
given a volunteer, it ranks the open shifts that suit them best. Each score
is the sum of five weighted factors, and every factor carries a plain-English
explanation, so a coordinator sees *why* someone is recommended — not a
black box.

    Factor                 Max   What earns points
    --------------------   ---   --------------------------------------------
    Availability fit        30   Volunteer listed this weekday + time of day
    Skill fit               30   Share of the opportunity's needed skills held
    Reliability             20   Attended / (attended + no-shows) history
    Program experience      10   Has served this program before
    Fair share              10   Light recent load (prevents burnout and gives
                                 newer volunteers a turn)

"Recommended for you" also diversifies: at most two shifts from any one
program, so a volunteer sees a range of ways to help.

Hard rules (age, active status, double-booking, capacity) are never traded
off against points: anyone who breaks one is filtered out *before* scoring,
using the same ``signup_blockers`` rule the sign-up screen uses.

Access needs are handled differently, on purpose. A volunteer who needs, say,
step-free access is never hidden or refused; if a program doesn't list that
support, the match carries a clear note and is listed after matches with no
gaps. Volunteers browsing for themselves see shifts that fit their needs first,
and can choose to see everything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from servesync.core.errors import BusinessRuleError
from servesync.core.i18n import tr, weekday_plural
from servesync.models import (
    AssignmentStatus,
    AvailabilitySlot,
    Opportunity,
    OpportunityStatus,
    Shift,
    ShiftOverview,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
)
from servesync.models.enums import describe_slot
from servesync.services.base import Service
from servesync.services.rules import describe_access_gaps, signup_blockers
from servesync.services.session import Permission, Session

AVAILABILITY_POINTS = 30.0
SKILL_POINTS = 30.0
RELIABILITY_POINTS = 20.0
EXPERIENCE_POINTS = 10.0
FAIR_SHARE_POINTS = 10.0

#: Reliability assumed for newcomers, so a first-timer isn't ranked last.
NEWCOMER_RELIABILITY = 0.7
#: Skill credit when an opportunity needs no special skills.
NO_SKILLS_NEEDED_SHARE = 2 / 3
#: Recent-hours window and the load at which fair-share points reach zero.
RECENT_WINDOW_DAYS = 30
HEAVY_LOAD_HOURS = 30.0  # fair-share points reach zero here
BUSY_HOURS = 20.0  # above this, the load is flagged as a concern
LIGHT_HOURS = 10.0
EXPERIENCED_VISITS = 3
#: "Recommended for you" shows at most this many shifts from one program, for variety.
MAX_PICKS_PER_PROGRAM = 2


@dataclass(frozen=True, slots=True)
class ScoreFactor:
    """One explained component of a match score."""

    name: str
    points: float
    max_points: float
    explanation: str
    is_concern: bool = False  # True when the factor counts against the match


@dataclass(frozen=True, slots=True)
class _MatchBase:
    score: int
    factors: tuple[ScoreFactor, ...]

    @property
    def strengths(self) -> list[str]:
        return [f.explanation for f in self.factors if not f.is_concern and f.points > 0]

    @property
    def concerns(self) -> list[str]:
        return [f.explanation for f in self.factors if f.is_concern] + list(self._gaps())

    @property
    def fits_access_needs(self) -> bool:
        return not self._gaps()

    def _gaps(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class VolunteerMatch(_MatchBase):
    """A volunteer recommended for a shift."""

    volunteer: Volunteer
    recent_hours: float
    access_gaps: tuple[str, ...] = ()

    def _gaps(self) -> tuple[str, ...]:
        return self.access_gaps


@dataclass(frozen=True, slots=True)
class ShiftMatch(_MatchBase):
    """A shift recommended for a volunteer."""

    overview: ShiftOverview
    access_gaps: tuple[str, ...] = ()

    def _gaps(self) -> tuple[str, ...]:
        return self.access_gaps


def score_match(
    *,
    volunteer: Volunteer,
    shift: Shift,
    opportunity: Opportunity,
    participation: VolunteerParticipation | None,
    program_visits: int,
    recent_hours: float | None,
) -> tuple[ScoreFactor, ...]:
    """
    Pure scoring function: facts in, explained factors out (no database, no clock).

    Pass ``recent_hours=None`` to leave out the fair-share factor — used when
    ranking shifts for one volunteer, where it would be identical for every
    shift and only add noise.
    """
    factors = [
        _availability_factor(volunteer, shift),
        _skill_factor(volunteer, opportunity),
        _reliability_factor(participation),
        _experience_factor(program_visits, opportunity.title),
    ]
    if recent_hours is not None:
        factors.append(_fair_share_factor(recent_hours))
    return tuple(factors)


def total_score(factors: tuple[ScoreFactor, ...]) -> int:
    """Points earned as a percentage of points available (0-100)."""
    available = sum(f.max_points for f in factors)
    return 0 if available == 0 else round(100 * sum(f.points for f in factors) / available)


# ------------------------------------------------------------------ factors


def _availability_factor(volunteer: Volunteer, shift: Shift) -> ScoreFactor:
    slot = AvailabilitySlot.for_datetime(shift.starts_at)
    when = describe_slot(slot.weekday, slot.day_part)
    if slot in volunteer.availability:
        return ScoreFactor(
            tr("Availability"), AVAILABILITY_POINTS, AVAILABILITY_POINTS, tr("Usually free on {when}", when=when)
        )
    if any(other.weekday is slot.weekday for other in volunteer.availability):
        return ScoreFactor(
            tr("Availability"),
            AVAILABILITY_POINTS / 3,
            AVAILABILITY_POINTS,
            tr(
                "Free on {days}, but not usually in the {part}",
                days=weekday_plural(int(slot.weekday)),
                part=slot.day_part.label.lower(),
            ),
            is_concern=True,
        )
    return ScoreFactor(
        tr("Availability"),
        0.0,
        AVAILABILITY_POINTS,
        tr("Hasn't listed {when} as available", when=when),
        is_concern=True,
    )


def _skill_factor(volunteer: Volunteer, opportunity: Opportunity) -> ScoreFactor:
    needed = {skill.casefold(): skill for skill in opportunity.required_skills}
    if not needed:
        return ScoreFactor(
            tr("Skills"),
            SKILL_POINTS * NO_SKILLS_NEEDED_SHARE,
            SKILL_POINTS,
            tr("No special skills needed for this program"),
        )
    held = {skill.casefold() for skill in volunteer.skills}
    matched = sorted(needed[key] for key in needed if key in held)
    missing = sorted(needed[key] for key in needed if key not in held)
    points = SKILL_POINTS * len(matched) / len(needed)
    if not missing:
        return ScoreFactor(
            tr("Skills"), points, SKILL_POINTS, tr("Has every needed skill: {join}", join=", ".join(matched))
        )
    if matched:
        return ScoreFactor(
            tr("Skills"),
            points,
            SKILL_POINTS,
            tr("Has {matched}; missing {missing}", matched=", ".join(matched), missing=", ".join(missing)),
            is_concern=True,
        )
    return ScoreFactor(
        tr("Skills"), 0.0, SKILL_POINTS, tr("Missing needed skills: {join}", join=", ".join(missing)), is_concern=True
    )


def _reliability_factor(participation: VolunteerParticipation | None) -> ScoreFactor:
    reliability = participation.reliability if participation else None
    if reliability is None:
        return ScoreFactor(
            tr("Reliability"),
            RELIABILITY_POINTS * NEWCOMER_RELIABILITY,
            RELIABILITY_POINTS,
            tr("New volunteer with no attendance history yet"),
        )
    percent = round(reliability * 100)
    return ScoreFactor(
        tr("Reliability"),
        RELIABILITY_POINTS * reliability,
        RELIABILITY_POINTS,
        tr("Showed up for {percent}% of past shifts", percent=percent),
        is_concern=reliability < 0.8,
    )


def _experience_factor(visits: int, title: str) -> ScoreFactor:
    if visits >= EXPERIENCED_VISITS:
        return ScoreFactor(
            tr("Experience"),
            EXPERIENCE_POINTS,
            EXPERIENCE_POINTS,
            tr("Has served '{title}' {visits} times", title=title, visits=visits),
        )
    if visits > 0:
        return ScoreFactor(
            tr("Experience"),
            EXPERIENCE_POINTS * 0.6,
            EXPERIENCE_POINTS,
            tr("Has served '{title}' once", title=title)
            if visits == 1
            else tr("Has served '{title}' twice", title=title),
        )
    return ScoreFactor(tr("Experience"), 0.0, EXPERIENCE_POINTS, tr("Would be new to '{title}'", title=title))


def _fair_share_factor(recent_hours: float) -> ScoreFactor:
    points = FAIR_SHARE_POINTS * max(0.0, 1 - recent_hours / HEAVY_LOAD_HOURS)
    hours_text = tr(
        "{recent_hours:g} h in the last {RECENT_WINDOW_DAYS} days",
        recent_hours=recent_hours,
        RECENT_WINDOW_DAYS=RECENT_WINDOW_DAYS,
    )
    if recent_hours <= LIGHT_HOURS:
        return ScoreFactor(
            tr("Fair share"), points, FAIR_SHARE_POINTS, tr("Light recent load ({hours_text})", hours_text=hours_text)
        )
    if recent_hours <= BUSY_HOURS:
        return ScoreFactor(
            tr("Fair share"),
            points,
            FAIR_SHARE_POINTS,
            tr("Moderate recent load ({hours_text})", hours_text=hours_text),
        )
    return ScoreFactor(
        tr("Fair share"),
        points,
        FAIR_SHARE_POINTS,
        tr("Busy lately ({hours_text})", hours_text=hours_text),
        is_concern=True,
    )


# ------------------------------------------------------------------ service


class MatchingService(Service):
    def recommend_volunteers(self, session: Session, shift_id: int, *, limit: int = 10) -> list[VolunteerMatch]:
        """Best eligible volunteers for an upcoming shift, highest score first."""
        session.require(Permission.MANAGE_SCHEDULE)
        now = self._clock.now()
        overview = self._store.shifts.get_overview(shift_id)
        shift = overview.shift
        if shift.has_started(now):
            raise BusinessRuleError(tr("Smart Match works on upcoming shifts; this one has already started."))
        if overview.opportunity_status is not OpportunityStatus.OPEN:
            raise BusinessRuleError(
                tr(
                    "Publish '{opportunity_title}' (set it to Open) to use Smart Match.",
                    opportunity_title=overview.opportunity_title,
                )
            )
        if overview.is_full:
            return []

        opportunity = self._store.opportunities.get(shift.opportunity_id)
        already_on = self._store.assignments.volunteer_ids_on_shift(shift_id)
        busy = self._store.assignments.busy_volunteer_ids(shift.starts_at, shift.ends_at, exclude_shift_id=shift_id)
        participation = self._participation_by_id()
        visits = self._store.assignments.attended_count_by_volunteer(shift.opportunity_id)
        recent = self._recent_hours()

        matches: list[VolunteerMatch] = []
        for volunteer in self._store.volunteers.find_all(status=VolunteerStatus.ACTIVE):
            volunteer_id = volunteer.volunteer_id or 0
            if signup_blockers(
                volunteer=volunteer,
                overview=overview,
                min_age=opportunity.min_age,
                now=now,
                already_signed_up=volunteer_id in already_on,
                has_conflict=volunteer_id in busy,
            ):
                continue
            factors = score_match(
                volunteer=volunteer,
                shift=shift,
                opportunity=opportunity,
                participation=participation.get(volunteer_id),
                program_visits=visits.get(volunteer_id, 0),
                recent_hours=recent.get(volunteer_id, 0.0),
            )
            gaps = describe_access_gaps(volunteer.access_needs, opportunity.access_features, opportunity.title)
            matches.append(
                VolunteerMatch(total_score(factors), factors, volunteer, recent.get(volunteer_id, 0.0), tuple(gaps))
            )

        # People whose access needs this program meets come first; then score;
        # ties go to whoever has served least recently, then alphabetical.
        matches.sort(
            key=lambda m: (
                not m.fits_access_needs,
                -m.score,
                m.recent_hours,
                m.volunteer.last_name,
                m.volunteer.first_name,
            )
        )
        return matches[: max(limit, 0)]

    def recommend_shifts(
        self,
        session: Session,
        volunteer_id: int,
        *,
        limit: int = 5,
        diversify: bool = True,
        only_fitting_access: bool = True,
    ) -> list[ShiftMatch]:
        """
        Open upcoming shifts that best suit a volunteer ("Recommended for you").

        With ``diversify=False`` it returns *every* shift the volunteer can join,
        scored — used by the Find a shift screen's smart filter and Fit column.
        With ``only_fitting_access=False`` it also includes shifts whose program
        doesn't list support for one of the volunteer's access needs (each
        carries a note saying which).
        """
        session.require_self_or(Permission.MANAGE_SCHEDULE, volunteer_id)
        now = self._clock.now()
        volunteer = self._store.volunteers.get(volunteer_id)
        if volunteer.status is not VolunteerStatus.ACTIVE:
            return []

        upcoming = self._store.shifts.overviews(
            starts_after=now, opportunity_status=OpportunityStatus.OPEN, only_with_openings=True
        )
        opportunities = {o.opportunity_id: o for o in self._store.opportunities.find_all(status=OpportunityStatus.OPEN)}
        commitments = [
            record
            for record in self._store.assignments.history(volunteer_id)
            if record.assignment.status is not AssignmentStatus.CANCELLED
        ]
        signed_up = {record.assignment.shift_id for record in commitments}
        participation = self._participation_by_id().get(volunteer_id)
        visits = self._store.assignments.attended_count_by_opportunity(volunteer_id)

        matches: list[ShiftMatch] = []
        for overview in upcoming:
            shift = overview.shift
            opportunity = opportunities.get(shift.opportunity_id)
            if opportunity is None:
                continue
            clash = any(
                record.starts_at < shift.ends_at and shift.starts_at < record.ends_at
                for record in commitments
                if record.assignment.shift_id != shift.shift_id
            )
            if signup_blockers(
                volunteer=volunteer,
                overview=overview,
                min_age=opportunity.min_age,
                now=now,
                already_signed_up=shift.shift_id in signed_up,
                has_conflict=clash,
            ):
                continue
            factors = score_match(
                volunteer=volunteer,
                shift=shift,
                opportunity=opportunity,
                participation=participation,
                program_visits=visits.get(shift.opportunity_id, 0),
                recent_hours=None,  # same for every shift, so it can't change the ranking
            )
            gaps = describe_access_gaps(volunteer.access_needs, opportunity.access_features, opportunity.title)
            if gaps and only_fitting_access:
                continue
            matches.append(ShiftMatch(total_score(factors), factors, overview, tuple(gaps)))

        matches.sort(key=lambda m: (not m.fits_access_needs, -m.score, m.overview.shift.starts_at))
        if not diversify:
            return matches[: max(limit, 0)]
        # Diversify: a few picks from several programs beat five of the same one.
        picks: list[ShiftMatch] = []
        per_program: dict[int, int] = {}
        for match in matches:
            program = match.overview.shift.opportunity_id
            if per_program.get(program, 0) < MAX_PICKS_PER_PROGRAM:
                picks.append(match)
                per_program[program] = per_program.get(program, 0) + 1
        return picks[: max(limit, 0)]

    # ---------------------------------------------------------------- helpers

    def _participation_by_id(self) -> Mapping[int, VolunteerParticipation]:
        return {p.volunteer_id: p for p in self._store.volunteers.participation()}

    def _recent_hours(self) -> Mapping[int, float]:
        today = self._clock.now().date()
        return self._store.assignments.hours_by_volunteer(start=today - timedelta(days=RECENT_WINDOW_DAYS), end=today)
