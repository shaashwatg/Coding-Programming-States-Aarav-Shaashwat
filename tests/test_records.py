"""Verification codes, milestone certificates, results in the Program impact report, and report sections."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, Assignment, AssignmentStatus, OpportunityCategory, ServiceRecord, Theme
from servesync.services import FixedClock, Services
from servesync.services.records_service import (
    CODE_ALPHABET,
    milestones_reached,
    new_code,
    normalize_code,
)
from servesync.services.reports import ReportKind, ReportSection
from servesync.services.reports.export import to_html
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.records_dialogs import CertificatesPanel, VerifyDialog
from tests.factories import FAST_ITERATIONS

SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore) -> Services:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    return Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(12))), password_iterations=FAST_ITERATIONS
    )


def _people(demo: Services) -> tuple[object, object, int]:
    leader = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    priya = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    return leader, priya, priya.volunteer_id or 0


# ------------------------------------------------------------------- codes


@pytest.mark.parametrize("typed", ["k7q2-9xfm", " K7Q2 9XFM ", "K7Q29XFM"])
def test_codes_are_accepted_however_they_are_typed(typed: str) -> None:
    assert normalize_code(typed) == "K7Q29XFM"


@pytest.mark.parametrize("typed", ["", "K7Q2", "K7Q2-9XFM-1", "O0O0-O0O0", "K7Q2-9XF!"])
def test_impossible_codes_are_explained(typed: str) -> None:
    with pytest.raises(ValidationError):
        normalize_code(typed)


def test_new_codes_use_only_unambiguous_characters() -> None:
    codes = {new_code() for _ in range(500)}
    assert len(codes) == 500
    assert all(len(code) == 8 and set(code) <= set(CODE_ALPHABET) for code in codes)
    assert not set("0O1IL") & set(CODE_ALPHABET)


def test_an_issued_record_verifies_and_shows_later_corrections(demo: Services) -> None:
    leader, priya, priya_id = _people(demo)
    start, end = date(2026, 8, 1), SEED_DAY
    code = demo.records.issue_service_record(priya, priya_id, start, end)  # type: ignore[arg-type]
    outcome = demo.records.verify(leader, code.lower())  # type: ignore[arg-type]
    assert outcome.genuine and outcome.document is not None
    assert outcome.document.volunteer_name == "Priya Patel" and not outcome.changed_since
    issued_hours = outcome.document.hours

    served = next(
        r
        for r in demo.store.assignments.history(priya_id)
        if r.assignment.status is AssignmentStatus.ATTENDED and start <= r.starts_at.date() <= end
    )
    demo.store.assignments.update(
        Assignment(
            served.assignment.shift_id,
            priya_id,
            AssignmentStatus.ATTENDED,
            0.5,
            served.assignment.signed_up_at,
            served.assignment.assignment_id,
            served.assignment.role_id,
        )
    )
    later = demo.records.verify(leader, code)  # type: ignore[arg-type]
    assert later.changed_since and later.current_hours is not None and later.current_hours < issued_hours


def test_an_unknown_code_is_not_genuine(demo: Services) -> None:
    leader, _priya, _ = _people(demo)
    assert not demo.records.verify(leader, "ABCD-EFGH").genuine  # type: ignore[arg-type]


def test_only_leaders_verify_and_people_only_issue_their_own(demo: Services) -> None:
    leader, priya, priya_id = _people(demo)
    with pytest.raises(PermissionDeniedError):
        demo.records.verify(priya, "ABCD-EFGH")  # type: ignore[arg-type]
    jordan = demo.store.accounts.find_by_username("jordan.rivera")
    assert jordan is not None and jordan.volunteer_id is not None
    with pytest.raises(PermissionDeniedError):
        demo.records.issue_service_record(priya, jordan.volunteer_id, date(2026, 8, 1), SEED_DAY)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        demo.records.issue_service_record(leader, priya_id, SEED_DAY, date(2026, 8, 1))  # type: ignore[arg-type]


# -------------------------------------------------------------- milestones


def _served(day: date, hours: float) -> ServiceRecord:
    moment = datetime.combine(day, time(9))
    assignment = Assignment(1, 1, AssignmentStatus.ATTENDED, hours, moment)
    return ServiceRecord(assignment, "Program", OpportunityCategory.EDUCATION, moment, moment + timedelta(hours=hours))


def test_milestones_are_dated_by_the_shift_that_crossed_them() -> None:
    records = [_served(date(2026, 9, d), 6) for d in range(1, 10)]  # 54 hours over nine days
    assert [(m.hours, m.reached_on.day) for m in milestones_reached(records)] == [(25, 5), (50, 9)]
    assert milestones_reached([]) == []


def test_certificates_only_for_reached_milestones(demo: Services) -> None:
    _leader, priya, priya_id = _people(demo)
    reached = [m.hours for m in demo.records.milestones(priya, priya_id)]  # type: ignore[arg-type]
    assert 25 in reached and 100 not in reached
    code, html = demo.records.milestone_certificate(priya, priya_id, 25)  # type: ignore[arg-type]
    assert "Priya Patel" in html and f"{code[:4]}-{code[4:]}" in html
    with pytest.raises(BusinessRuleError, match="hasn't been reached"):
        demo.records.milestone_certificate(priya, priya_id, 100)  # type: ignore[arg-type]
    with pytest.raises(BusinessRuleError):
        demo.records.milestone_certificate(priya, priya_id, 30)  # type: ignore[arg-type]


# ------------------------------------------------------------------ reports


def test_program_impact_shows_results_in_each_programs_unit(demo: Services) -> None:
    leader, _priya, _ = _people(demo)
    filters = demo.reports.default_filters(ReportKind.PROGRAM_IMPACT, leader)  # type: ignore[arg-type]
    report = demo.reports.build(leader, ReportKind.PROGRAM_IMPACT, filters)  # type: ignore[arg-type]
    pantry = next(row for row in report.rows if row["program"] == "Weekend Food Pantry Distribution")
    assert pantry["unit"] == "families served" and pantry["result"] > 0


def test_impact_summary_sections_can_be_left_out(demo: Services) -> None:
    leader, _priya, _ = _people(demo)
    filters = demo.reports.default_filters(ReportKind.IMPACT_SUMMARY, leader)  # type: ignore[arg-type]
    report = demo.reports.build(leader, ReportKind.IMPACT_SUMMARY, filters)  # type: ignore[arg-type]
    everything = to_html(report)
    brief = to_html(report, sections={ReportSection.FIGURES})
    assert "What stands out" in everything and "Details" in everything
    assert "What stands out" not in brief and "Details" not in brief


# ---------------------------------------------------------------- screens


@pytest.fixture
def ui(qapp: QApplication) -> Iterator[None]:
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    yield


def test_verify_screen_confirms_or_explains(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    leader, priya, priya_id = _people(demo)
    code = demo.records.issue_service_record(priya, priya_id, date(2026, 8, 1), SEED_DAY)  # type: ignore[arg-type]
    dialog = VerifyDialog(AppContext(demo, leader, AppEvents()))  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.code.setText("nope")
    dialog.check()
    assert not dialog.problem.isHidden() and "8 letters" in dialog.problem.text()
    dialog.code.setText(code)
    dialog.check()
    assert dialog.problem.isHidden() and dialog.answer.text().startswith("Genuine.")


def test_certificates_panel_lists_reached_and_next(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    _leader, priya, _ = _people(demo)
    panel = CertificatesPanel(AppContext(demo, priya, AppEvents()))  # type: ignore[arg-type]
    qtbot.addWidget(panel)
    panel.refresh()
    texts = [label.text() for label in panel.findChildren(QLabel) if not label.isHidden()]
    assert any("reached" in text for text in texts) and any("to go" in text for text in texts)


def test_the_demo_codes_in_the_readme_verify(demo: Services) -> None:
    from servesync.data.seed import DEMO_CERTIFICATE_CODE, DEMO_RECORD_CODE

    leader, _priya, _ = _people(demo)
    record = demo.records.verify(leader, f"{DEMO_RECORD_CODE[:4]}-{DEMO_RECORD_CODE[4:]}")  # type: ignore[arg-type]
    certificate = demo.records.verify(leader, DEMO_CERTIFICATE_CODE)  # type: ignore[arg-type]
    assert record.genuine and not record.changed_since
    assert certificate.genuine and certificate.document is not None and certificate.document.milestone == 50
