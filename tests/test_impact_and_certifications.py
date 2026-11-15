"""Program results, the impact summary, and certifications as a hard rule everywhere."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.data.seed import DEMO_CERTIFICATION, DEMO_CERTIFIED_PROGRAM, DEMO_PASSWORD, seed_demo_data
from servesync.models import Certification, OpportunityStatus, VolunteerStatus
from servesync.services import FixedClock, Services
from servesync.services.reports import ReportFilters, ReportKind
from servesync.services.rules import missing_certifications
from servesync.ui.report_files import save_pdf
from tests.factories import FAST_ITERATIONS, make_volunteer

SEED_DAY = date(2026, 10, 26)
NOW = datetime.combine(SEED_DAY, time(12, 0))
MIN_AGE_FOR_CERTIFIED_PROGRAM = 16
CHART_WIDTH, CHART_HEIGHT = 1000, 340  # about what the Reports page sends to the PDF


@pytest.fixture
def demo(store: DataStore) -> Services:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    return Services.create(store, clock=FixedClock(NOW), password_iterations=FAST_ITERATIONS)


def _program(services: Services, title: str = DEMO_CERTIFIED_PROGRAM) -> int:
    return next(o.opportunity_id or 0 for o in services.store.opportunities.find_all() if o.title == title)


# --------------------------------------------------------------------- impact


def _wide(services: Services) -> ReportFilters:
    return ReportFilters(date(2026, 1, 1), SEED_DAY)


def test_result_needs_a_started_shift_a_unit_and_a_sensible_number(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    overviews = demo.store.shifts.overviews(opportunity_status=OpportunityStatus.OPEN)
    past = next(o for o in overviews if o.shift.ends_at < NOW and o.opportunity_title == DEMO_CERTIFIED_PROGRAM)
    future = next(o for o in overviews if o.shift.starts_at > NOW and o.opportunity_title == DEMO_CERTIFIED_PROGRAM)
    assert demo.attendance.record_impact(session, past.shift.shift_id or 0, 12).impact_amount == 12
    with pytest.raises(BusinessRuleError, match="started"):
        demo.attendance.record_impact(session, future.shift.shift_id or 0, 12)
    for bad in (-1, 1_000_001, "many"):
        with pytest.raises(ValidationError):
            demo.attendance.record_impact(session, past.shift.shift_id or 0, bad)

    opportunity = demo.store.opportunities.get(past.shift.opportunity_id)
    demo.store.opportunities.update(dataclasses.replace(opportunity, impact_unit=""))
    with pytest.raises(BusinessRuleError, match="measures"):
        demo.attendance.record_impact(session, past.shift.shift_id or 0, 12)


def test_volunteers_cannot_record_results(demo: Services) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    with pytest.raises(PermissionDeniedError):
        demo.attendance.record_impact(session, 1, 5)


def test_impact_summary_adds_up_results_and_flags_missing_ones(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    filters = _wide(demo)
    report = demo.reports.build(session, ReportKind.IMPACT_SUMMARY, filters)
    expected: dict[str, int] = {}
    finished = demo.store.shifts.overviews(
        starts_after=datetime.combine(filters.start, time.min), starts_before=datetime.combine(SEED_DAY, time.max)
    )
    for overview in finished:
        if overview.shift.ends_at <= NOW and overview.shift.impact_amount is not None:
            title = overview.opportunity_title
            expected[title] = expected.get(title, 0) + overview.shift.impact_amount
    for row in report.rows:
        assert row["result"] == expected.get(str(row["program"]), 0)
    assert any("no result recorded" in insight for insight in report.insights)
    assert any("families served" in insight for insight in report.insights)


def test_impact_summary_hours_match_the_other_reports(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    filters = _wide(demo)
    impact = demo.reports.build(session, ReportKind.IMPACT_SUMMARY, filters)
    program = demo.reports.build(session, ReportKind.PROGRAM_IMPACT, filters)
    assert sum(float(str(r["hours"])) for r in impact.rows) == pytest.approx(
        sum(float(str(r["hours"])) for r in program.rows)
    )


def test_impact_summary_fits_on_one_page(demo: Services, qapp: QApplication, tmp_path: Path) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    report = demo.reports.build(session, ReportKind.IMPACT_SUMMARY, _wide(demo))
    path = tmp_path / "impact.pdf"
    chart = QImage(CHART_WIDTH, CHART_HEIGHT, QImage.Format.Format_RGB32)
    chart.fill(0xFFFFFF)
    save_pdf(report, path, None, [chart])
    document = QPdfDocument()
    document.load(str(path))
    assert document.pageCount() == 1


# -------------------------------------------------------------- certifications

CPR = "First Aid"


def test_missing_and_expired_certifications_are_found_case_insensitively() -> None:
    day = date(2026, 11, 1)
    volunteer = make_volunteer(certifications=frozenset({Certification("CPR", day)}))
    assert missing_certifications(volunteer, {"cpr"}, day) == []  # valid through its last day
    assert missing_certifications(volunteer, {"cpr"}, day + timedelta(days=1)) == ["cpr"]
    assert missing_certifications(volunteer, {"Driving", "cpr"}, day) == ["Driving"]
    assert missing_certifications(volunteer, set(), day) == []


def _upcoming_certified_shift(services: Services) -> int:
    overviews = services.store.shifts.overviews(starts_after=NOW, only_with_openings=True)
    return next(o.shift.shift_id or 0 for o in overviews if o.opportunity_title == DEMO_CERTIFIED_PROGRAM)


def _uncertified_person(services: Services, shift_id: int) -> int:
    shift = services.store.shifts.get(shift_id)
    on_shift = services.store.assignments.volunteer_ids_on_shift(shift_id)
    busy = services.store.assignments.busy_volunteer_ids(shift.starts_at, shift.ends_at, exclude_shift_id=shift_id)
    for volunteer in services.store.volunteers.find_all(status=VolunteerStatus.ACTIVE):
        volunteer_id = volunteer.volunteer_id or 0
        uncertified = volunteer.certification(DEMO_CERTIFICATION) is None and volunteer_id not in on_shift | busy
        if uncertified and volunteer.age(shift.starts_at.date()) >= MIN_AGE_FOR_CERTIFIED_PROGRAM:
            return volunteer_id
    raise AssertionError("demo data should have someone without the certification")


def test_every_way_of_scheduling_someone_enforces_the_certification(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    shift_id = _upcoming_certified_shift(demo)
    volunteer_id = _uncertified_person(demo, shift_id)

    # 1. Manual sign-up
    with pytest.raises(BusinessRuleError, match=DEMO_CERTIFICATION):
        demo.scheduling.sign_up(session, shift_id, volunteer_id)
    # 2. Smart Match, both directions
    matches = demo.matching.recommend_volunteers(session, shift_id, limit=1000)
    assert volunteer_id not in {m.volunteer.volunteer_id for m in matches}
    shifts = demo.matching.recommend_shifts(session, volunteer_id, limit=1000, diversify=False)
    assert shift_id not in {m.overview.shift.shift_id for m in shifts}
    # 3. Autopilot
    plan = demo.staffing.draft_plan(session, days=60)
    for proposal in plan.proposals:
        if proposal.overview.opportunity_title == DEMO_CERTIFIED_PROGRAM:
            assert proposal.volunteer.certification(DEMO_CERTIFICATION) is not None

    # A current certification lifts the rule at once.
    demo.volunteers.add_certification(session, volunteer_id, DEMO_CERTIFICATION, SEED_DAY + timedelta(days=200))
    assert demo.scheduling.sign_up(session, shift_id, volunteer_id).volunteer_id == volunteer_id


def test_certification_must_last_until_the_shift_not_just_today(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    shift_id = _upcoming_certified_shift(demo)
    volunteer_id = _uncertified_person(demo, shift_id)
    shift = demo.store.shifts.get(shift_id)
    days_until = (shift.starts_at.date() - SEED_DAY).days
    if days_until > 1:
        demo.volunteers.add_certification(session, volunteer_id, DEMO_CERTIFICATION, SEED_DAY + timedelta(days=1))
        with pytest.raises(BusinessRuleError, match=DEMO_CERTIFICATION):
            demo.scheduling.sign_up(session, shift_id, volunteer_id)


def test_walk_ins_and_the_kiosk_enforce_it_too(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    overviews = demo.store.shifts.overviews(starts_before=NOW)
    past = next(o for o in reversed(overviews) if o.opportunity_title == DEMO_CERTIFIED_PROGRAM)
    shift_id = past.shift.shift_id or 0
    volunteer_id = _uncertified_person(demo, shift_id)
    with pytest.raises(BusinessRuleError, match=DEMO_CERTIFICATION):
        demo.attendance.record_walk_in(session, shift_id, volunteer_id)

    # Someone whose certification ran out after signing up can't check in at the kiosk.
    open_shift = demo.attendance.kiosk_shifts(session)[0]
    program = demo.store.opportunities.get(open_shift.shift.opportunity_id)
    demo.store.opportunities.update(dataclasses.replace(program, required_certifications=frozenset({CPR})))
    entry = demo.attendance.roster(session, open_shift.shift.shift_id or 0)[0]
    with pytest.raises(BusinessRuleError, match="see a coordinator"):
        demo.attendance.kiosk_tap(session, entry.assignment.assignment_id or 0)


@pytest.mark.parametrize(
    ("name", "expires", "field"),
    [
        ("", SEED_DAY + timedelta(days=30), "certification_name"),
        ("x", SEED_DAY + timedelta(days=30), "certification_name"),
        ("CPR", SEED_DAY, "certification_expires"),
        ("CPR", date(2020, 1, 1), "certification_expires"),
    ],
)
def test_certifications_are_validated(demo: Services, name: str, expires: date, field: str) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    with pytest.raises(ValidationError) as caught:
        demo.volunteers.add_certification(session, 1, name, expires)
    assert field in caught.value.errors


def test_renewing_replaces_instead_of_duplicating(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    later = SEED_DAY + timedelta(days=400)
    demo.volunteers.add_certification(session, 1, "CPR", SEED_DAY + timedelta(days=30))
    saved = demo.volunteers.add_certification(session, 1, "cpr", later)
    assert [c.expires_on for c in saved.certifications if c.name.casefold() == "cpr"] == [later]
    removed = demo.volunteers.remove_certification(session, 1, "CPR")
    assert removed.certification("cpr") is None


def test_volunteers_cannot_certify_themselves(demo: Services) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    with pytest.raises(PermissionDeniedError):
        demo.volunteers.add_certification(session, session.volunteer_id or 0, "CPR", SEED_DAY + timedelta(days=30))


def test_editing_a_profile_keeps_certifications(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    demo.volunteers.add_certification(session, 1, "CPR", SEED_DAY + timedelta(days=30))
    volunteer = demo.volunteers.get(session, 1)
    volunteer.certifications = frozenset()  # the profile form doesn't carry them
    assert demo.volunteers.update_profile(session, volunteer).certification("CPR") is not None


def test_expiring_certifications_are_listed_soonest_first(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    expiring = demo.volunteers.expiring_certifications(session)
    assert expiring
    days = [certification.expires_on for _, certification in expiring]
    assert days == sorted(days)


def test_demo_rosters_obey_the_new_rule(demo: Services) -> None:
    overviews = demo.store.shifts.overviews(starts_after=NOW)
    for overview in overviews:
        required = demo.store.opportunities.get(overview.shift.opportunity_id).required_certifications
        for entry in demo.store.assignments.roster(overview.shift.shift_id or 0):
            person = demo.store.volunteers.get(entry.assignment.volunteer_id)
            assert not {name for name in required if person.certification(name) is None}
