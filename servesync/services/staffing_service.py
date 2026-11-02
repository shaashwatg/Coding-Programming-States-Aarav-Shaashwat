"""
Staffing Studio — three looks ahead, so a coordinator can act before a problem.

* **Attendance forecast.** A full roster can still come up short. Each signed-up
  person counts as their own show-up rate (newcomers as Smart Match's neutral
  70%), so the expected turnout of a shift is the sum of those rates.
* **Autopilot.** Drafts a whole schedule at once. Smart Match ranks people for one
  shift at a time; Autopilot shares people *across* shifts: it staffs the hardest
  shift first, so the only person who can do a job isn't spent on an easy one, and
  it spreads the work with a limit per person and a penalty for hours already
  planned. It only drafts: nobody is signed up until a coordinator approves.
* **Re-engagement.** Finds experienced volunteers who have quietly stopped
  coming, and suggests the shift most likely to bring each one back.

Everything is explainable arithmetic on this organization's own records, and
every sign-up still goes through ``SchedulingService.sign_up``, which re-checks
every hard rule (age, status, double-booking, capacity).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from servesync.core.errors import ServeSyncError
from servesync.core.i18n import tr
from servesync.data import DataStore
from servesync.models import (
    AssignmentStatus,
    OpportunityStatus,
    ShiftOverview,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
)
from servesync.services.base import Service
from servesync.services.clock import Clock
from servesync.services.matching_service import NEWCOMER_RELIABILITY, MatchingService, ShiftMatch, VolunteerMatch
from servesync.services.scheduling_service import SchedulingService
from servesync.services.session import Permission, Session

#: How far ahead the forecast and Autopilot look.
PLANNING_WINDOW_DAYS = 14
#: Expected turnout (as a share of capacity) at or above which a shift is on track or worth watching.
ON_TRACK_SHARE = 0.75
WATCH_SHARE = 0.5
#: Autopilot only drafts strong matches: someone usually free, scoring at least this.
MIN_PLAN_SCORE = 60
#: Autopilot asks no one for more than this many extra shifts in one plan.
MAX_PLANNED_SHIFTS_PER_PERSON = 2
#: Score points a candidate loses for each hour already in this plan (fair share).
PLANNED_HOUR_PENALTY = 2.0
#: Experienced volunteers count as drifting after this long without serving.
DRIFT_AFTER_DAYS = 45
MAX_REENGAGEMENT_ALERTS = 8
#: Large enough to return every eligible volunteer from Smart Match.
ALL_CANDIDATES = 100_000


class TurnoutOutlook(Enum):
    ON_TRACK = "ON_TRACK"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"

    @property
    def label(self) -> str:
        if self is TurnoutOutlook.ON_TRACK:
            return tr("On track")
        return tr("Watch") if self is TurnoutOutlook.WATCH else tr("At risk")


@dataclass(frozen=True, slots=True)
class ShiftForecast:
    """One upcoming shift and the turnout its roster's history predicts."""

    overview: ShiftOverview
    expected_turnout: float

    @property
    def outlook(self) -> TurnoutOutlook:
        return outlook_for(self.expected_turnout, self.overview.shift.capacity)


@dataclass(frozen=True, slots=True)
class PlanProposal:
    """One drafted sign-up, with the reasons a coordinator needs to judge it."""

    overview: ShiftOverview
    match: VolunteerMatch

    @property
    def volunteer(self) -> Volunteer:
        return self.match.volunteer


@dataclass(frozen=True, slots=True)
class StaffingPlan:
    proposals: tuple[PlanProposal, ...]
    open_spots: int  # every open spot in the window, drafted or not

    @property
    def spots_left_open(self) -> int:
        return self.open_spots - len(self.proposals)


@dataclass(frozen=True, slots=True)
class PlanResult:
    """What approving a plan did: sign-ups made, and any that could no longer happen."""

    assignment_ids: tuple[int, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriftAlert:
    """An experienced volunteer who has stopped coming, and a shift to invite them to."""

    participation: VolunteerParticipation
    days_away: int
    suggestion: ShiftMatch | None


def outlook_for(expected_turnout: float, capacity: int) -> TurnoutOutlook:
    """Classify a shift by expected turnout as a share of capacity (pure, so it is easy to test)."""
    share = 0.0 if capacity <= 0 else expected_turnout / capacity
    if share >= ON_TRACK_SHARE:
        return TurnoutOutlook.ON_TRACK
    return TurnoutOutlook.WATCH if share >= WATCH_SHARE else TurnoutOutlook.AT_RISK


def expected_turnout(signed_up: Sequence[int], participation: Mapping[int, VolunteerParticipation]) -> float:
    """Sum of each signed-up person's show-up rate; newcomers count as the neutral rate."""
    total = 0.0
    for volunteer_id in signed_up:
        record = participation.get(volunteer_id)
        reliability = record.reliability if record else None
        total += NEWCOMER_RELIABILITY if reliability is None else reliability
    return round(total, 1)


def allocate(needs: Sequence[tuple[ShiftOverview, Sequence[VolunteerMatch]]]) -> list[PlanProposal]:
    """
    Share volunteers across shifts (pure: ranked candidates in, drafted sign-ups out).

    A greedy heuristic: shifts with the least slack (strong candidates minus open
    spots) choose first; within a shift, the best score after the fair-share penalty
    wins. It respects a limit per person and never drafts overlapping shifts.
    """
    strong = [(overview, [m for m in matches if _is_strong(m)]) for overview, matches in needs]
    strong.sort(key=lambda need: (len(need[1]) - need[0].open_spots, need[0].shift.starts_at))

    planned: dict[int, list[ShiftOverview]] = {}
    proposals: list[PlanProposal] = []

    def adjusted_score(match: VolunteerMatch) -> float:
        hours = sum(o.shift.duration_hours for o in planned.get(match.volunteer.volunteer_id or 0, []))
        return match.score - PLANNED_HOUR_PENALTY * hours

    for overview, candidates in strong:
        available = list(candidates)
        for _ in range(overview.open_spots):
            free = [m for m in available if _can_take(planned.get(m.volunteer.volunteer_id or 0, []), overview)]
            if not free:
                break
            best = max(free, key=adjusted_score)
            available.remove(best)
            planned.setdefault(best.volunteer.volunteer_id or 0, []).append(overview)
            proposals.append(PlanProposal(overview, best))
    proposals.sort(key=lambda p: (p.overview.shift.starts_at, -p.match.score))
    return proposals


def _is_strong(match: VolunteerMatch) -> bool:
    """Autopilot leaves anyone with an access gap for a person to arrange, rather than assuming."""
    return match.score >= MIN_PLAN_SCORE and match.is_usually_free and match.fits_access_needs


def _can_take(already: Sequence[ShiftOverview], overview: ShiftOverview) -> bool:
    if len(already) >= MAX_PLANNED_SHIFTS_PER_PERSON:
        return False
    shift = overview.shift
    return not any(o.shift.starts_at < shift.ends_at and shift.starts_at < o.shift.ends_at for o in already)


class StaffingService(Service):
    def __init__(
        self, store: DataStore, clock: Clock, *, matching: MatchingService, scheduling: SchedulingService
    ) -> None:
        super().__init__(store, clock)
        self._matching = matching
        self._scheduling = scheduling

    def forecast(self, session: Session, *, days: int = PLANNING_WINDOW_DAYS) -> list[ShiftForecast]:
        """Expected turnout for every open upcoming shift in the window, soonest first."""
        session.require(Permission.MANAGE_SCHEDULE)
        participation = {p.volunteer_id: p for p in self._store.volunteers.participation()}
        forecasts = []
        for overview in self._upcoming(days):
            roster = self._store.assignments.roster(overview.shift.shift_id or 0)
            signed_up = [entry.assignment.volunteer_id for entry in roster if entry.assignment.status.holds_a_spot]
            forecasts.append(ShiftForecast(overview, expected_turnout(signed_up, participation)))
        return forecasts

    def draft_plan(self, session: Session, *, days: int = PLANNING_WINDOW_DAYS) -> StaffingPlan:
        """Draft sign-ups for the open spots in the window. Saves nothing."""
        session.require(Permission.MANAGE_SCHEDULE)
        needs = [
            (overview, self._matching.recommend_volunteers(session, overview.shift.shift_id or 0, limit=ALL_CANDIDATES))
            for overview in self._upcoming(days)
            if not overview.is_full
        ]
        return StaffingPlan(tuple(allocate(needs)), sum(overview.open_spots for overview, _ in needs))

    def approve(self, session: Session, proposals: Sequence[PlanProposal]) -> PlanResult:
        """
        Sign up the approved proposals. Each goes through the normal sign-up rules, so
        if something changed since the draft (a shift filled up), that one is skipped
        and explained while the rest still go through.
        """
        session.require(Permission.MANAGE_SCHEDULE)
        made: list[int] = []
        skipped: list[str] = []
        for proposal in proposals:
            try:
                saved = self._scheduling.sign_up(
                    session, proposal.overview.shift.shift_id or 0, proposal.volunteer.volunteer_id or 0
                )
            except ServeSyncError as error:
                skipped.append(f"{proposal.volunteer.full_name}: {error.message}")
            else:
                made.append(saved.assignment_id or 0)
        return PlanResult(tuple(made), tuple(skipped))

    def undo(self, session: Session, assignment_ids: Sequence[int]) -> int:
        """Cancel the sign-ups a plan made, unless they have since been changed. Returns how many."""
        session.require(Permission.MANAGE_SCHEDULE)
        undone = 0
        for assignment_id in assignment_ids:
            if self._store.assignments.get(assignment_id).status is AssignmentStatus.SCHEDULED:
                self._scheduling.cancel(session, assignment_id)
                undone += 1
        return undone

    def drifting_volunteers(self, session: Session) -> list[DriftAlert]:
        """Active volunteers with service history, nothing upcoming, and a long gap; most hours first."""
        session.require(Permission.MANAGE_VOLUNTEERS)
        today = self._clock.now().date()
        drifting = [
            p
            for p in self._store.volunteers.participation()
            if p.status is VolunteerStatus.ACTIVE
            and p.upcoming_shifts == 0
            and p.last_served_on is not None
            and (today - p.last_served_on).days >= DRIFT_AFTER_DAYS
        ]
        drifting.sort(key=lambda p: (-p.total_hours, p.full_name))
        alerts = []
        for record in drifting[:MAX_REENGAGEMENT_ALERTS]:
            picks = self._matching.recommend_shifts(session, record.volunteer_id, limit=1)
            days_away = (today - record.last_served_on).days if record.last_served_on else 0
            alerts.append(DriftAlert(record, days_away, picks[0] if picks else None))
        return alerts

    def _upcoming(self, days: int) -> list[ShiftOverview]:
        now = self._clock.now()
        return self._store.shifts.overviews(
            starts_after=now, starts_before=now + timedelta(days=days), opportunity_status=OpportunityStatus.OPEN
        )
