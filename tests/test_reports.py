"""Customizable reports: filters, math, insights, permissions, and export."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest

from servesync.core.errors import PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.data.seed import seed_demo_data
from servesync.models import OpportunityCategory
from servesync.services import FixedClock, Services
from servesync.services.reports import DatePreset, ReportFilters, ReportKind, ValueKind, format_value
from servesync.services.reports.analytics import percent
from servesync.services.reports.export import chosen_columns, csv_cell, suggested_filename, to_csv, to_html
from servesync.services.reports.model import ReportColumn
from tests.conftest import NOW, SATURDAY_9AM, World
from tests.factories import ADMIN, COORDINATOR, FAST_ITERATIONS, make_opportunity, make_shift, volunteer_session

TODAY = NOW.date()
WIDE = ReportFilters(TODAY - timedelta(days=60), TODAY + timedelta(days=30))

# --------------------------------------------------------------- filters


def test_presets_resolve_to_inclusive_ranges() -> None:
    today = date(2026, 3, 15)
    assert DatePreset.THIS_MONTH.resolve(today) == (date(2026, 3, 1), today)
    assert DatePreset.LAST_MONTH.resolve(today) == (date(2026, 2, 1), date(2026, 2, 28))
    assert DatePreset.SCHOOL_YEAR.resolve(today) == (date(2025, 8, 1), today)
    assert DatePreset.SCHOOL_YEAR.resolve(date(2026, 9, 1)) == (date(2026, 8, 1), date(2026, 9, 1))
    start, end = DatePreset.LAST_90_DAYS.resolve(today)
    assert (end - start).days + 1 == 90


def test_filters_validate_syntax_and_meaning() -> None:
    assert ReportFilters("01/02/2026", "2026-01-31").days == 30  # type: ignore[arg-type]
    with pytest.raises(ValidationError) as caught:
        ReportFilters(date(2026, 2, 1), date(2026, 1, 1))
    assert "end" in caught.value.errors
    with pytest.raises(ValidationError):
        ReportFilters(date(2020, 1, 1), date(2026, 1, 1))  # more than five years
    with pytest.raises(ValidationError):
        ReportFilters("02/30/2026", "03/01/2026")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "value", "text"),
    [
        (ValueKind.HOURS, 3.0, "3"),
        (ValueKind.HOURS, 2.5, "2.5"),
        (ValueKind.PERCENT, 66.6, "67%"),
        (ValueKind.MONEY, 1234.5, "$1,234"),
        (ValueKind.MONEY, 36.14, "$36.14"),
        (ValueKind.DATE, date(2026, 11, 7), "Nov 7, 2026"),
        (ValueKind.COUNT, None, "–"),
    ],
)
def test_values_format_for_people(kind: ValueKind, value: object, text: str) -> None:
    assert format_value(kind, value) == text


def test_percent_is_undefined_without_a_whole() -> None:
    assert percent(1, 0) is None
    assert percent(1, 3) == 33.3


# ------------------------------------------------------------ the math


@pytest.fixture
def served(services: Services, world: World, clock: FixedClock) -> World:
    """Ana attends 3 h; Tess no-shows; the shift is in the past."""
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)
    clock.set(SATURDAY_9AM + timedelta(hours=4))
    roster = services.store.assignments.roster(world.shift_id)
    for entry in roster:
        if entry.assignment.volunteer_id == world.ana_id:
            services.attendance.record_attendance(COORDINATOR, entry.assignment.assignment_id or 0, hours=3)
        else:
            services.attendance.mark_no_show(COORDINATOR, entry.assignment.assignment_id or 0)
    return world


def test_volunteer_hours_report(services: Services, served: World) -> None:
    report = services.reports.build(COORDINATOR, ReportKind.VOLUNTEER_HOURS, WIDE)
    rows = {row["name"]: row for row in report.rows}
    assert rows["Ana Lopez"]["hours"] == 3 and rows["Ana Lopez"]["reliability"] == 100.0
    assert rows["Tess Young"]["no_shows"] == 1 and rows["Tess Young"]["reliability"] == 0.0
    assert rows["Ben Brooks"]["hours"] == 0  # active but idle: listed so leaders can check in
    assert "Ivy Newman" not in rows  # applicants without sign-ups aren't listed
    assert report.rows[0]["name"] == "Ana Lopez"  # most hours first
    assert any("didn't serve" in insight for insight in report.insights)


def test_program_and_shift_reports(services: Services, served: World) -> None:
    program = services.reports.build(COORDINATOR, ReportKind.PROGRAM_IMPACT, WIDE).rows[0]
    assert (program["shifts"], program["spots"], program["signed_up"], program["fill_rate"]) == (1, 2, 2, 100.0)
    assert program["show_up_rate"] == 50.0 and program["hours"] == 3
    shift = services.reports.build(COORDINATOR, ReportKind.SHIFT_ATTENDANCE, WIDE).rows[0]
    assert (shift["attended"], shift["no_shows"], shift["unrecorded"]) == (1, 1, 0)


def test_unrecorded_attendance_is_flagged(services: Services, world: World, clock: FixedClock) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    clock.set(SATURDAY_9AM + timedelta(hours=1))
    report = services.reports.build(COORDINATOR, ReportKind.SHIFT_ATTENDANCE, WIDE)
    assert report.rows[0]["unrecorded"] == 1
    assert any("attendance to record" in insight for insight in report.insights)


def test_program_filter_scopes_every_report(services: Services, served: World) -> None:
    other = services.store.opportunities.add(
        make_opportunity(title="Library Reading", category=OpportunityCategory.EDUCATION, required_skills=set())
    )
    services.store.shifts.add(make_shift(other.opportunity_id or 0, SATURDAY_9AM + timedelta(days=1)))
    scoped = ReportFilters(WIDE.start, WIDE.end, opportunity_id=other.opportunity_id)
    assert services.reports.build(COORDINATOR, ReportKind.VOLUNTEER_HOURS, scoped).rows == ()
    assert [r["program"] for r in services.reports.build(COORDINATOR, ReportKind.PROGRAM_IMPACT, scoped).rows] == [
        "Library Reading"
    ]
    by_category = ReportFilters(WIDE.start, WIDE.end, category=OpportunityCategory.FOOD_SECURITY)
    assert len(services.reports.build(COORDINATOR, ReportKind.SHIFT_ATTENDANCE, by_category).rows) == 1


def test_missing_program_filter_is_explained(services: Services, world: World) -> None:
    with pytest.raises(ValidationError, match="no longer exists"):
        services.reports.build(
            COORDINATOR, ReportKind.PROGRAM_IMPACT, ReportFilters(WIDE.start, WIDE.end, opportunity_id=999)
        )


def test_recruitment_report_counts_channels(services: Services, world: World) -> None:
    report = services.reports.build(COORDINATOR, ReportKind.RECRUITMENT, ReportFilters(date(2025, 1, 1), TODAY))
    other = next(row for row in report.rows if row["source"] == "Other")
    assert (other["total"], other["active"], other["applicants"]) == (4, 3, 1)


# --------------------------------------------------------- permissions


def test_volunteers_only_see_their_own_service_record(services: Services, served: World) -> None:
    me = volunteer_session(served.ana_id)
    with pytest.raises(PermissionDeniedError):
        services.reports.build(me, ReportKind.VOLUNTEER_HOURS, WIDE)
    with pytest.raises(PermissionDeniedError):
        services.reports.build(
            me, ReportKind.SERVICE_RECORD, ReportFilters(WIDE.start, WIDE.end, volunteer_id=served.ben_id)
        )
    record = services.reports.build(me, ReportKind.SERVICE_RECORD, WIDE)  # defaults to themself
    assert [row["hours"] for row in record.rows] == [3]
    assert record.context[0] == "Volunteer: Ana Lopez"


def test_leaders_must_choose_whose_record(services: Services) -> None:
    with pytest.raises(ValidationError, match="Choose the volunteer"):
        services.reports.build(ADMIN, ReportKind.SERVICE_RECORD, WIDE)


# --------------------------------------------------------------- export


def test_csv_respects_column_choice_and_blocks_formulas(services: Services, served: World) -> None:
    report = services.reports.build(COORDINATOR, ReportKind.VOLUNTEER_HOURS, WIDE)
    text = to_csv(report, ["name", "hours", "reliability"])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Volunteer", "Hours", "Show-up rate (%)"]
    assert ["Ana Lopez", "3", "100"] in rows
    assert csv_cell(ReportColumn("name", "Name"), "=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert csv_cell(ReportColumn("n", "N", ValueKind.HOURS), -2.5) == "-2.5"  # real numbers are not escaped
    assert csv_cell(ReportColumn("d", "D", ValueKind.DATE), date(2026, 1, 2)) == "2026-01-02"


def test_default_columns_and_html_escape(services: Services, served: World) -> None:
    report = services.reports.build(COORDINATOR, ReportKind.VOLUNTEER_HOURS, WIDE)
    assert "email" not in [c.key for c in chosen_columns(report, None)]
    html = to_html(report)
    assert "Volunteer hours" in html and "Ana Lopez" in html
    services.store.settings.set_organization_name("<script>Org</script>")
    escaped = to_html(services.reports.build(COORDINATOR, ReportKind.VOLUNTEER_HOURS, WIDE))
    assert "<script>" not in escaped and "&lt;script&gt;" in escaped
    assert suggested_filename(report, "csv").startswith("servesync-volunteer-hours-")


def test_service_record_html_has_signature_line(services: Services, served: World) -> None:
    record = services.reports.build(volunteer_session(served.ana_id), ReportKind.SERVICE_RECORD, WIDE)
    assert "Coordinator signature" in to_html(record)


# --------------------------------------------- demo data: totals reconcile


@pytest.fixture(scope="module")
def demo() -> Iterator[Services]:
    store = DataStore.in_memory()
    seed_demo_data(store, password_iterations=FAST_ITERATIONS)
    yield Services.create(store, password_iterations=FAST_ITERATIONS)
    store.close()


@pytest.mark.parametrize("preset", [DatePreset.LAST_30_DAYS, DatePreset.LAST_90_DAYS, DatePreset.THIS_YEAR])
def test_every_report_agrees_on_total_hours(demo: Services, preset: DatePreset) -> None:
    filters = ReportFilters(*preset.resolve(demo.clock.now().date()))
    expected = demo.store.assignments.total_hours(start=filters.start, end=filters.end)
    for kind in (
        ReportKind.VOLUNTEER_HOURS,
        ReportKind.PROGRAM_IMPACT,
        ReportKind.SHIFT_ATTENDANCE,
        ReportKind.RECRUITMENT,
    ):
        report = demo.reports.build(ADMIN, kind, filters)
        total = sum(float(row["hours"]) for row in report.rows)  # type: ignore[arg-type]
        assert total == pytest.approx(expected), kind


def test_demo_reports_produce_insights_and_charts(demo: Services) -> None:
    filters = ReportFilters(*DatePreset.LAST_90_DAYS.resolve(demo.clock.now().date()))
    for kind in (
        ReportKind.VOLUNTEER_HOURS,
        ReportKind.PROGRAM_IMPACT,
        ReportKind.SHIFT_ATTENDANCE,
        ReportKind.RECRUITMENT,
    ):
        report = demo.reports.build(ADMIN, kind, filters)
        assert report.insights and report.charts and report.figures, kind
        assert all(len(c.labels) == len(c.values) for c in report.charts)


def test_trend_buckets_cover_the_whole_range(demo: Services) -> None:
    from servesync.services.reports.analytics import hours_trend

    monthly = hours_trend([], ReportFilters(date(2026, 1, 1), date(2026, 6, 30)))  # > 92 days: monthly
    assert monthly.labels == ("Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026")
    weekly = hours_trend([], ReportFilters(date(2026, 11, 4), date(2026, 11, 20)))  # buckets start on Mondays
    assert weekly.labels == ("Nov 2", "Nov 9", "Nov 16") and weekly.is_empty


def test_report_generation_time_is_recorded(services: Services, world: World) -> None:
    report = services.reports.build(COORDINATOR, ReportKind.PROGRAM_IMPACT, WIDE)
    assert report.generated_at == datetime(2026, 11, 2, 8, 0)
    assert report.is_empty is False  # the world has one shift in range
