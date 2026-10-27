"""
Dashboard summaries — the "at a glance" numbers for each audience.

Leaders see what needs action (applicants to review, understaffed shifts)
plus this month's impact; volunteers see their own hours and what's next.
Gathering these here keeps the screens free of database logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from servesync.models import (
    ActivityItem,
    AssignmentStatus,
    Opportunity,
    OpportunityStatus,
    RecruitmentSource,
    ServiceRecord,
    ShiftOverview,
    Volunteer,
    VolunteerParticipation,
    VolunteerStatus,
)
from servesync.services.base import Service
from servesync.services.session import Permission, Session

ATTENTION_WINDOW_DAYS = 7
FEATURE_WINDOW_DAYS = 45


@dataclass(frozen=True, slots=True)
class FeaturedEvent:
    """The "Happening next" banner: the biggest upcoming event that still needs people."""

    overview: ShiftOverview
    opportunity: Opportunity


@dataclass(frozen=True, slots=True)
class RecruitmentInsight:
    """Which channel brings in the most volunteers (drives the dashboard callout)."""

    top_source: RecruitmentSource
    top_count: int
    total: int

    @property
    def share(self) -> float:
        return 0.0 if self.total == 0 else self.top_count / self.total


@dataclass(frozen=True, slots=True)
class LeaderSummary:
    organization_name: str
    active_volunteers: int
    applicants: tuple[Volunteer, ...]  # oldest application first
    understaffed: tuple[ShiftOverview, ...]  # next 7 days, soonest first
    hours_this_month: float
    hour_value: float

    @property
    def open_spots(self) -> int:
        return sum(overview.open_spots for overview in self.understaffed)

    @property
    def value_this_month(self) -> float:
        return round(self.hours_this_month * self.hour_value, 2)


@dataclass(frozen=True, slots=True)
class VolunteerSummary:
    volunteer: Volunteer
    participation: VolunteerParticipation
    upcoming: tuple[ServiceRecord, ...]  # soonest first
    hour_value: float

    @property
    def community_value(self) -> float:
        """Dollar value of this volunteer's hours to the community."""
        return round(self.participation.total_hours * self.hour_value, 2)


class DashboardService(Service):
    def leader_summary(self, session: Session) -> LeaderSummary:
        session.require(Permission.VIEW_REPORTS)
        now = self._clock.now()
        today = now.date()
        applicants = sorted(
            self._store.volunteers.find_all(status=VolunteerStatus.APPLICANT),
            key=lambda volunteer: (volunteer.joined_on, volunteer.last_name),
        )
        understaffed = self._store.shifts.overviews(
            starts_after=now,
            starts_before=now + timedelta(days=ATTENTION_WINDOW_DAYS),
            opportunity_status=OpportunityStatus.OPEN,
            only_with_openings=True,
        )
        return LeaderSummary(
            organization_name=self._store.settings.organization_name(),
            active_volunteers=self._store.volunteers.count_by_status()[VolunteerStatus.ACTIVE],
            applicants=tuple(applicants),
            understaffed=tuple(understaffed),
            hours_this_month=self._store.assignments.total_hours(start=today.replace(day=1), end=today),
            hour_value=self._store.settings.volunteer_hour_value(),
        )

    def featured_event(self, session: Session) -> FeaturedEvent | None:
        """
        Pick one upcoming shift to spotlight: within the next few weeks, open for
        sign-ups, still needing people; the largest wins, then the soonest.
        One clear banner, never a carousel.
        """
        now = self._clock.now()
        candidates = self._store.shifts.overviews(
            starts_after=now,
            starts_before=now + timedelta(days=FEATURE_WINDOW_DAYS),
            opportunity_status=OpportunityStatus.OPEN,
            only_with_openings=True,
        )
        if not candidates:
            return None
        best = max(candidates, key=lambda o: (o.shift.capacity, -o.shift.starts_at.timestamp()))
        return FeaturedEvent(best, self._store.opportunities.get(best.shift.opportunity_id))

    def activity_feed(self, session: Session, *, limit: int = 8) -> list[ActivityItem]:
        """Latest sign-ups, service, and applications (leaders only — it names people)."""
        session.require(Permission.VIEW_REPORTS)
        return self._store.assignments.recent_activity(now=self._clock.now(), limit=limit)

    def recruitment_insight(self, session: Session) -> RecruitmentInsight | None:
        session.require(Permission.VIEW_REPORTS)
        counts = self._store.volunteers.count_by_source()
        total = sum(counts.values())
        if total == 0:
            return None
        top_source, top_count = max(counts.items(), key=lambda item: item[1])
        return RecruitmentInsight(top_source, top_count, total)

    def volunteer_summary(self, session: Session, volunteer_id: int) -> VolunteerSummary:
        session.require_self_or(Permission.MANAGE_VOLUNTEERS, volunteer_id)
        now = self._clock.now()
        upcoming = sorted(
            (
                record
                for record in self._store.assignments.history(volunteer_id)
                if record.assignment.status is AssignmentStatus.SCHEDULED and record.starts_at > now
            ),
            key=lambda record: record.starts_at,
        )
        return VolunteerSummary(
            volunteer=self._store.volunteers.get(volunteer_id),
            participation=self._store.volunteers.get_participation(volunteer_id),
            upcoming=tuple(upcoming),
            hour_value=self._store.settings.volunteer_hour_value(),
        )
