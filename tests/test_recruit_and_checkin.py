"""Applying from the sign-in screen, referrals, the check-in kiosk, and hour goals."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, AssignmentStatus, RecruitmentSource, ServiceRecord, Theme, VolunteerStatus
from servesync.services import FixedClock, Services
from servesync.services.reports.analytics import referral_counts
from servesync.services.reports.model import DatePreset, ReportKind
from servesync.services.rules import hour_goal_progress
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.application_dialog import ApplicationDialog
from servesync.ui.dialogs.auth_dialogs import LoginDialog
from servesync.ui.dialogs.goal_dialog import HourGoalPanel
from servesync.ui.dialogs.kiosk_dialog import KioskDialog
from tests.factories import FAST_ITERATIONS, make_volunteer

SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore) -> Services:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    return Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(12, 0))), password_iterations=FAST_ITERATIONS
    )


@pytest.fixture
def ui(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)


# ------------------------------------------------------------------- applying


def test_an_application_can_only_create_an_applicant(demo: Services) -> None:
    applicant = make_volunteer(
        email="new.person@example.org",
        phone="206-555-0177",
        status=VolunteerStatus.ACTIVE,  # a tampered form can't approve itself
        notes="Approved already!",
        referred_by="Priya Patel",
    )
    saved = demo.volunteers.apply(applicant)
    assert saved.status is VolunteerStatus.APPLICANT
    assert saved.notes == "" and saved.referred_by == "Priya Patel"


def test_an_application_does_not_reveal_who_is_on_file(demo: Services) -> None:
    existing = demo.store.volunteers.find_by_email("priya.patel@example.org")
    assert existing is not None
    duplicate = make_volunteer(email="someone.else@example.org", phone=existing.phone)
    with pytest.raises(BusinessRuleError) as caught:
        demo.volunteers.apply(duplicate)
    assert "Priya" not in caught.value.message and "Patel" not in caught.value.message


def test_application_form_shows_problems_beside_fields(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ApplicationDialog(demo)
    qtbot.addWidget(dialog)
    dialog.first_name.setText("J0rdan")
    dialog.save_button.click()
    assert dialog.saved is None and dialog._fields["first_name"][1].text()


def test_application_form_saves_an_applicant_with_a_referrer(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ApplicationDialog(demo)
    qtbot.addWidget(dialog)
    dialog.first_name.setText("Sam")
    dialog.last_name.setText("Okafor")
    dialog.email.setText("sam.okafor@example.org")
    dialog.phone.setText("206-555-0178")
    dialog.referred_by.setText("Priya Patel")
    dialog.birth_date.setDate(QDate(1990, 1, 1))
    dialog.save_button.click()
    assert dialog.saved is not None and dialog.saved.status is VolunteerStatus.APPLICANT
    assert demo.store.volunteers.get(dialog.saved.volunteer_id or 0).referred_by == "Priya Patel"


def test_recruitment_report_names_the_top_referrer(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    filters = demo.reports.default_filters(ReportKind.RECRUITMENT, session)
    report = demo.reports.build(session, ReportKind.RECRUITMENT, filters)
    assert any("Priya Patel has referred" in insight for insight in report.insights)
    assert DatePreset.SCHOOL_YEAR  # the preset goals count from also exists for reports


def test_a_minor_must_list_a_parent_or_guardian(demo: Services) -> None:
    fifteen = SEED_DAY.replace(year=SEED_DAY.year - 15)
    with pytest.raises(ValidationError) as caught:
        demo.volunteers.apply(
            make_volunteer(email="teen@example.org", phone="206-555-0179", birth_date=fifteen, joined_on=SEED_DAY)
        )
    assert "parent or guardian" in caught.value.errors["emergency_contact_name"]
    saved = demo.volunteers.apply(
        make_volunteer(
            email="teen@example.org",
            phone="206-555-0179",
            birth_date=fifteen,
            joined_on=SEED_DAY,
            emergency_contact_name="Maria Lopez",
            emergency_contact_phone="206-555-0180",
        )
    )
    assert saved.status is VolunteerStatus.APPLICANT


def test_referral_counts_treat_spellings_of_one_name_as_one_person() -> None:
    people = [
        make_volunteer(referred_by="Priya Patel"),
        make_volunteer(referred_by="priya  patel"),
        make_volunteer(referred_by="Priya Patel"),
        make_volunteer(referred_by="Jordan Rivera"),
        make_volunteer(referred_by=""),
    ]
    assert referral_counts(people) == [("Priya Patel", 3), ("Jordan Rivera", 1)]


def test_recruitment_report_shows_who_brings_in_the_most_volunteers(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    filters = demo.reports.default_filters(ReportKind.RECRUITMENT, session)
    report = demo.reports.build(session, ReportKind.RECRUITMENT, filters)
    assert {"referred", "top_referrer"} <= {column.key for column in report.columns}
    referral_row = next(row for row in report.rows if row["source"] == RecruitmentSource.REFERRAL.label)
    assert referral_row["referred"] > 0 and str(referral_row["top_referrer"]).startswith("Priya Patel (")
    chart = next(chart for chart in report.charts if chart.title == "Who brings in the most volunteers")
    assert chart.labels[0] == "Priya Patel" and list(chart.values) == sorted(chart.values, reverse=True)
    everyone = demo.store.volunteers.find_all()
    assert sum(row["referred"] for row in report.rows) == sum(1 for v in everyone if v.referred_by)


def test_sign_in_screen_offers_become_a_volunteer(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = LoginDialog(demo)
    qtbot.addWidget(dialog)
    assert dialog.apply_button.text() == "Become a volunteer"


def test_a_volunteer_cannot_change_who_referred_them(demo: Services) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    volunteer = demo.volunteers.get(session, session.volunteer_id or 0)
    volunteer.referred_by = "Someone Else"
    assert demo.volunteers.update_profile(session, volunteer).referred_by == ""


# --------------------------------------------------------------------- kiosk


def _person_on_open_shift(services: Services) -> tuple[int, str, int]:
    session = services.auth.sign_in("coordinator", DEMO_PASSWORD)
    shift_id = services.attendance.kiosk_shifts(session)[0].shift.shift_id or 0
    entry = services.attendance.roster(session, shift_id)[0]
    return shift_id, entry.volunteer_phone[-4:], entry.assignment.assignment_id or 0


def test_kiosk_checks_someone_in_for_the_full_shift(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    shift_id, digits, assignment_id = _person_on_open_shift(demo)
    people = demo.attendance.kiosk_lookup(session, shift_id, digits)
    assert assignment_id in {p.assignment_id for p in people}
    assert all(p.short_name.endswith(".") for p in people)  # never a full name on a shared screen
    result = demo.attendance.kiosk_check_in(session, assignment_id)
    assert result.assignment.status is AssignmentStatus.ATTENDED and result.hours == 4
    with pytest.raises(BusinessRuleError, match="already checked in"):
        demo.attendance.kiosk_check_in(session, assignment_id)


@pytest.mark.parametrize("digits", ["", "12", "12345", "abcd"])
def test_kiosk_rejects_malformed_digits(demo: Services, digits: str) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    shift_id, _, _ = _person_on_open_shift(demo)
    with pytest.raises(BusinessRuleError, match="last 4 digits"):
        demo.attendance.kiosk_lookup(session, shift_id, digits)


def test_kiosk_window_opens_30_minutes_early_and_closes_at_the_end(store: DataStore) -> None:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)

    def open_at(hour: int, minute: int) -> list[int]:
        clock = FixedClock(datetime.combine(SEED_DAY, time(hour, minute)))
        services = Services.create(store, clock=clock, password_iterations=FAST_ITERATIONS)
        session = services.auth.sign_in("coordinator", DEMO_PASSWORD)
        return [o.shift.starts_at.hour for o in services.attendance.kiosk_shifts(session) if o.shift.capacity == 8]

    assert 7 in open_at(6, 30)
    assert 7 not in open_at(6, 29)
    assert 7 not in open_at(11, 0)
    assert 11 in open_at(11, 0)


def test_volunteers_cannot_run_the_kiosk(demo: Services) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    with pytest.raises(PermissionDeniedError):
        demo.attendance.kiosk_shifts(session)


def test_kiosk_needs_the_leaders_password_to_close(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    dialog = KioskDialog(AppContext(demo, session, AppEvents()))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.reject()  # Esc
    assert dialog.isVisible()
    dialog.exit_password.setText("wrong-password")
    dialog.exit_button.click()
    assert dialog.isVisible()
    dialog.exit_password.setText(DEMO_PASSWORD)
    dialog.exit_button.click()
    assert not dialog.isVisible()


def test_kiosk_screen_checks_in_and_reports_goal_progress(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    dialog = KioskDialog(AppContext(demo, session, AppEvents()))
    qtbot.addWidget(dialog)
    priya = demo.store.volunteers.find_by_email("priya.patel@example.org")
    assert priya is not None
    dialog.digits.setText(priya.phone[-4:])
    dialog.check_in_button.click()
    assert "Thanks, Priya" in dialog.message.text() and "goal" in dialog.message.text()
    assert dialog.digits.text() == ""


# ---------------------------------------------------------------------- goals


def _record(volunteer_id: int, day: date, hours: float) -> ServiceRecord:
    from servesync.models import Assignment, OpportunityCategory

    moment = datetime.combine(day, time(9))
    assignment = Assignment(1, volunteer_id, status=AssignmentStatus.ATTENDED, hours_served=hours, signed_up_at=moment)
    return ServiceRecord(
        assignment, "Program", next(iter(OpportunityCategory)), moment, moment + timedelta(hours=hours)
    )


def test_goal_progress_counts_this_school_year_and_judges_pace() -> None:
    volunteer = make_volunteer(hour_goal=100, hour_goal_due=date(2027, 6, 1))
    records = [
        _record(1, date(2026, 7, 31), 12),
        _record(1, date(2026, 8, 1), 10),
        _record(1, date(2026, 10, 1), 12),
        _record(1, date(2026, 10, 2), 8),
    ]
    progress = hour_goal_progress(volunteer, records, date(2026, 11, 1))
    assert progress is not None
    assert progress.served == 30  # the July shift belongs to last school year
    assert progress.remaining == 70 and not progress.reached
    assert progress.expected_by_now == pytest.approx(100 * 92 / 304, abs=0.01)
    assert not progress.on_pace  # 30 served, just under the 30.26 expected by now
    assert progress.hours_per_week == pytest.approx(70 / (212 / 7), abs=0.1)


def test_no_goal_means_no_progress() -> None:
    assert hour_goal_progress(make_volunteer(), [], date(2026, 11, 1)) is None


def test_goal_needs_both_parts() -> None:
    with pytest.raises(ValidationError):
        make_volunteer(hour_goal=10)


@pytest.mark.parametrize(
    ("hours", "due", "field"),
    [
        (0, date(2027, 6, 1), "hour_goal"),
        (2001, date(2027, 6, 1), "hour_goal"),
        ("lots", date(2027, 6, 1), "hour_goal"),
        (40, SEED_DAY, "hour_goal_due"),
        (40, date(2020, 1, 1), "hour_goal_due"),
    ],
)
def test_goal_is_validated_for_format_and_meaning(demo: Services, hours: object, due: date, field: str) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    with pytest.raises(ValidationError) as caught:
        demo.volunteers.set_hour_goal(session, session.volunteer_id or 0, hours, due)
    assert field in caught.value.errors


def test_goal_panel_and_profile_edit_keep_the_goal(demo: Services, ui: None, qtbot) -> None:  # type: ignore[no-untyped-def]
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    panel = HourGoalPanel(AppContext(demo, session, AppEvents()))
    qtbot.addWidget(panel)
    panel.refresh()
    assert "of 80 hours" in panel.summary.text() and panel.bar.value() > 0
    panel.clear_button.click()
    assert demo.volunteers.get(session, session.volunteer_id or 0).hour_goal is None


def test_someone_else_cannot_set_my_goal(demo: Services) -> None:
    priya = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    jordan = demo.auth.sign_in("jordan.rivera", DEMO_PASSWORD)
    with pytest.raises(PermissionDeniedError):
        demo.volunteers.set_hour_goal(priya, jordan.volunteer_id or 0, 10, date(2027, 6, 1))
