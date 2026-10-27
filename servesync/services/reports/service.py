"""
ReportService — gathers the facts for a report and hands them to the pure
analytics functions. Permission checks live here, like every other service.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from servesync.core.errors import ValidationError
from servesync.services.base import Service
from servesync.services.reports import analytics
from servesync.services.reports.model import DatePreset, Report, ReportFilters, ReportKind
from servesync.services.session import Permission, Session


class ReportService(Service):
    def default_filters(self, kind: ReportKind, session: Session) -> ReportFilters:
        """Sensible starting filters: a service record covers the school year; others the last 30 days."""
        preset = DatePreset.SCHOOL_YEAR if kind is ReportKind.SERVICE_RECORD else DatePreset.LAST_30_DAYS
        start, end = preset.resolve(self._clock.now().date())
        return ReportFilters(start, end, volunteer_id=session.volunteer_id)

    def build(self, session: Session, kind: ReportKind, filters: ReportFilters) -> Report:
        """Run one report. Leaders can run any report; volunteers only their own service record."""
        volunteer = None
        if kind is ReportKind.SERVICE_RECORD:
            volunteer_id = filters.volunteer_id or session.volunteer_id
            if volunteer_id is None:
                raise ValidationError.single("volunteer_id", "Choose the volunteer this service record is for.")
            session.require_self_or(Permission.VIEW_REPORTS, volunteer_id)
            volunteer = self._store.volunteers.get(volunteer_id)
        else:
            session.require(Permission.VIEW_REPORTS)
        if filters.opportunity_id is not None and not self._store.opportunities.exists(filters.opportunity_id):
            raise ValidationError.single("opportunity_id", "That program no longer exists. Choose another.")

        inputs = analytics.ReportInputs(
            facts=self._store.assignments.service_facts(start=filters.start, end=filters.end),
            shifts=self._store.shifts.overviews(
                starts_after=datetime.combine(filters.start, time.min),
                starts_before=datetime.combine(filters.end + timedelta(days=1), time.min),
            ),
            volunteers=self._store.volunteers.find_all(),
            opportunities={o.opportunity_id or 0: o for o in self._store.opportunities.find_all()},
            hour_value=self._store.settings.volunteer_hour_value(),
            now=self._clock.now(),
            organization_name=self._store.settings.organization_name(),
        )
        if volunteer is not None:
            return analytics.service_record(inputs, filters, volunteer)
        builders = {
            ReportKind.VOLUNTEER_HOURS: analytics.volunteer_hours,
            ReportKind.PROGRAM_IMPACT: analytics.program_impact,
            ReportKind.SHIFT_ATTENDANCE: analytics.shift_attendance,
            ReportKind.RECRUITMENT: analytics.recruitment,
        }
        return builders[kind](inputs, filters)
