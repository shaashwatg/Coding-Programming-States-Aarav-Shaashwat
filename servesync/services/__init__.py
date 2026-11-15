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
from servesync.services.attendance_service import AttendanceService, KioskPerson, KioskResult, KioskState
from servesync.services.auth_service import AuthService
from servesync.services.clock import Clock, FixedClock, SystemClock
from servesync.services.coordination_service import CoordinationService, ReminderRow
from servesync.services.dashboard_service import (
    DashboardService,
    FeaturedEvent,
    LeaderSummary,
    RecruitmentInsight,
    VolunteerSummary,
)
from servesync.services.data_service import DataService, ImportPreview, ImportRow
from servesync.services.matching_service import MatchingService, ScoreFactor, ShiftMatch, VolunteerMatch
from servesync.services.opportunity_service import OpportunityService
from servesync.services.records_service import Milestone, RecordsService, Verification
from servesync.services.reports import ReportService
from servesync.services.scheduling_service import SchedulingService
from servesync.services.session import Permission, Session
from servesync.services.settings_service import SettingsService
from servesync.services.setup_service import SetupService
from servesync.services.staffing_service import (
    DriftAlert,
    PlanProposal,
    PlanResult,
    ShiftForecast,
    StaffingPlan,
    StaffingService,
    TurnoutOutlook,
)
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
    staffing: StaffingService
    coordination: CoordinationService
    records: RecordsService
    data: DataService

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
        scheduling = SchedulingService(store, clock)
        volunteers = VolunteerService(store, clock)
        opportunities = OpportunityService(store, clock)
        # When a spot frees up anywhere (an archived volunteer, a bigger shift), the waitlist moves up.
        for service in (scheduling, volunteers, opportunities):
            service.on_spots_freed = scheduling.fill_from_waitlists
        return cls(
            store=store,
            clock=clock,
            auth=AuthService(store, clock, password_iterations=password_iterations),
            volunteers=volunteers,
            opportunities=opportunities,
            scheduling=scheduling,
            attendance=AttendanceService(store, clock),
            matching=matching,
            dashboard=DashboardService(store, clock),
            reports=reports,
            assistant=AssistantService(store, clock, matching=matching, reports=reports),
            settings=SettingsService(store, clock),
            setup=SetupService(store, clock, password_iterations=password_iterations),
            staffing=StaffingService(store, clock, matching=matching, scheduling=scheduling),
            coordination=CoordinationService(store, clock),
            records=RecordsService(store, clock),
            data=DataService(store, clock),
        )


__all__ = [
    "Appearance",
    "AssistantService",
    "AttendanceService",
    "AuthService",
    "Clock",
    "CoordinationService",
    "DashboardService",
    "DataService",
    "DriftAlert",
    "FeaturedEvent",
    "FixedClock",
    "ImportPreview",
    "ImportRow",
    "KioskPerson",
    "KioskResult",
    "KioskState",
    "LeaderSummary",
    "MatchingService",
    "Milestone",
    "OpportunityService",
    "Permission",
    "PlanProposal",
    "PlanResult",
    "RecordsService",
    "RecruitmentInsight",
    "ReminderRow",
    "ReportService",
    "SchedulingService",
    "ScoreFactor",
    "Services",
    "Session",
    "SettingsService",
    "SetupService",
    "ShiftForecast",
    "ShiftMatch",
    "StaffingPlan",
    "StaffingService",
    "StatusChange",
    "SystemClock",
    "TurnoutOutlook",
    "Verification",
    "VolunteerMatch",
    "VolunteerService",
    "VolunteerSummary",
]
