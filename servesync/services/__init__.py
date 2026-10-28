"""
Service layer — the organization's business rules.

The user interface talks only to these services; services talk to the
``DataStore``. Build everything at once with :meth:`Services.create`::

    services = Services.create(store)
    session = services.auth.sign_in("coordinator", password)
    picks = services.matching.recommend_volunteers(session, shift_id)
"""

from __future__ import annotations

from dataclasses import dataclass

from servesync.core.security import DEFAULT_ITERATIONS
from servesync.data import DataStore
from servesync.models import Appearance
from servesync.services.assistant import AssistantService
from servesync.services.attendance_service import AttendanceService
from servesync.services.auth_service import AuthService
from servesync.services.clock import Clock, FixedClock, SystemClock
from servesync.services.dashboard_service import (
    DashboardService,
    FeaturedEvent,
    LeaderSummary,
    RecruitmentInsight,
    VolunteerSummary,
)
from servesync.services.matching_service import MatchingService, ScoreFactor, ShiftMatch, VolunteerMatch
from servesync.services.opportunity_service import OpportunityService
from servesync.services.reports import ReportService
from servesync.services.scheduling_service import SchedulingService
from servesync.services.session import Permission, Session
from servesync.services.settings_service import SettingsService
from servesync.services.setup_service import SetupService
from servesync.services.volunteer_service import StatusChange, VolunteerService


@dataclass(frozen=True, slots=True)
class Services:
    """Composition root: one place that wires every service to the same store and clock."""

    store: DataStore
    clock: Clock
    auth: AuthService
    volunteers: VolunteerService
    opportunities: OpportunityService
    scheduling: SchedulingService
    attendance: AttendanceService
    matching: MatchingService
    dashboard: DashboardService
    reports: ReportService
    assistant: AssistantService
    settings: SettingsService
    setup: SetupService

    @classmethod
    def create(
        cls,
        store: DataStore,
        *,
        clock: Clock | None = None,
        password_iterations: int = DEFAULT_ITERATIONS,
    ) -> Services:
        clock = clock or SystemClock()
        matching = MatchingService(store, clock)
        reports = ReportService(store, clock)
        return cls(
            store=store,
            clock=clock,
            auth=AuthService(store, clock, password_iterations=password_iterations),
            volunteers=VolunteerService(store, clock),
            opportunities=OpportunityService(store, clock),
            scheduling=SchedulingService(store, clock),
            attendance=AttendanceService(store, clock),
            matching=matching,
            dashboard=DashboardService(store, clock),
            reports=reports,
            assistant=AssistantService(store, clock, matching=matching, reports=reports),
            settings=SettingsService(store, clock),
            setup=SetupService(store, clock, password_iterations=password_iterations),
        )


__all__ = [
    "Appearance",
    "AssistantService",
    "AttendanceService",
    "AuthService",
    "Clock",
    "DashboardService",
    "FeaturedEvent",
    "FixedClock",
    "LeaderSummary",
    "MatchingService",
    "OpportunityService",
    "Permission",
    "RecruitmentInsight",
    "ReportService",
    "SchedulingService",
    "ScoreFactor",
    "Services",
    "Session",
    "SettingsService",
    "SetupService",
    "ShiftMatch",
    "StatusChange",
    "SystemClock",
    "VolunteerMatch",
    "VolunteerService",
    "VolunteerSummary",
]
