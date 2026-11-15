"""Staffing Studio: the forecast's arithmetic, Autopilot's rules, and re-engagement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from servesync.core.errors import PermissionDeniedError
from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, AssignmentStatus, Theme, VolunteerStatus
from servesync.services import FixedClock, Services, TurnoutOutlook
from servesync.services.staffing_service import (
    DRIFT_AFTER_DAYS,
    MAX_PLANNED_SHIFTS_PER_PERSON,
    MIN_PLAN_SCORE,
    expected_turnout,
    outlook_for,
)
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.pages.staffing_page import PROPOSAL_ROLE, StaffingPage
from tests.factories import FAST_ITERATIONS

SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore) -> Services:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    return Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(8, 0))), password_iterations=FAST_ITERATIONS
    )


@pytest.mark.parametrize(
    ("turnout", "capacity", "outlook"),
    [
        (7.5, 10, TurnoutOutlook.ON_TRACK),
        (7.4, 10, TurnoutOutlook.WATCH),
        (5.0, 10, TurnoutOutlook.WATCH),
        (4.9, 10, TurnoutOutlook.AT_RISK),
        (0.0, 0, TurnoutOutlook.AT_RISK),
    ],
)
def test_outlook_thresholds(turnout: float, capacity: int, outlook: TurnoutOutlook) -> None:
    assert outlook_for(turnout, capacity) is outlook


def test_newcomers_count_as_the_neutral_rate(demo: Services) -> None:
    records = {p.volunteer_id: p for p in demo.store.volunteers.participation()}
    assert expected_turnout([], records) == 0.0
    assert expected_turnout([-1, -2], records) == 1.4  # two people with no record


def test_forecast_never_exceeds_who_is_signed_up(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    forecasts = demo.staffing.forecast(session)
    assert forecasts
    assert all(0 <= f.expected_turnout <= f.overview.filled for f in forecasts)


def test_plan_obeys_every_rule_and_all_of_it_can_be_signed_up(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    plan = demo.staffing.draft_plan(session)
    assert plan.proposals and plan.spots_left_open >= 0

    per_person: dict[int, list[datetime]] = {}
    per_shift: dict[int, int] = {}
    for proposal in plan.proposals:
        assert proposal.match.score >= MIN_PLAN_SCORE
        assert proposal.match.is_usually_free and proposal.match.fits_access_needs
        per_person.setdefault(proposal.volunteer.volunteer_id or 0, []).append(proposal.overview.shift.starts_at)
        shift_id = proposal.overview.shift.shift_id or 0
        per_shift[shift_id] = per_shift.get(shift_id, 0) + 1
        assert per_shift[shift_id] <= proposal.overview.open_spots
    assert all(len(times) <= MAX_PLANNED_SHIFTS_PER_PERSON for times in per_person.values())

    # The real sign-up rules re-check everything: a sound plan loses nobody.
    result = demo.staffing.approve(session, plan.proposals)
    assert result.skipped == () and len(result.assignment_ids) == len(plan.proposals)


def test_a_shift_starting_this_minute_is_left_out(store: DataStore) -> None:
    """Regression: the demo has shifts at 9:00, and at exactly 9:00 drafting used to fail."""
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    services = Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(9, 0))), password_iterations=FAST_ITERATIONS
    )
    session = services.auth.sign_in("coordinator", DEMO_PASSWORD)
    now = datetime.combine(SEED_DAY, time(9, 0))
    plan = services.staffing.draft_plan(session)
    assert all(not p.overview.shift.has_started(now) for p in plan.proposals)
    assert all(not f.overview.shift.has_started(now) for f in services.staffing.forecast(session))


def test_drafting_saves_nothing(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    before = demo.store.assignments.count_by_status()
    demo.staffing.draft_plan(session)
    assert demo.store.assignments.count_by_status() == before


def test_approve_explains_a_spot_taken_since_the_draft(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    proposal = demo.staffing.draft_plan(session).proposals[0]
    demo.scheduling.sign_up(session, proposal.overview.shift.shift_id or 0, proposal.volunteer.volunteer_id or 0)
    result = demo.staffing.approve(session, [proposal])
    assert result.assignment_ids == ()
    assert result.skipped[0].startswith(proposal.volunteer.full_name)


def test_undo_reverses_an_approval(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    before = demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED]
    result = demo.staffing.approve(session, demo.staffing.draft_plan(session).proposals)
    assert demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED] > before
    assert demo.staffing.undo(session, result.assignment_ids) == len(result.assignment_ids)
    assert demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED] == before
    assert demo.staffing.undo(session, result.assignment_ids) == 0  # already undone: harmless


def test_drifting_volunteers_are_experienced_and_have_nothing_upcoming(demo: Services) -> None:
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    alerts = demo.staffing.drifting_volunteers(session)
    assert len(alerts) == 3  # the demo's lapsed regulars
    for alert in alerts:
        assert alert.participation.status is VolunteerStatus.ACTIVE
        assert alert.participation.upcoming_shifts == 0
        assert alert.days_away >= DRIFT_AFTER_DAYS
    hours = [alert.participation.total_hours for alert in alerts]
    assert hours == sorted(hours, reverse=True)


def test_volunteers_cannot_use_staffing_studio(demo: Services) -> None:
    session = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    with pytest.raises(PermissionDeniedError):
        demo.staffing.draft_plan(session)
    with pytest.raises(PermissionDeniedError):
        demo.staffing.forecast(session)
    with pytest.raises(PermissionDeniedError):
        demo.staffing.drifting_volunteers(session)


@pytest.fixture
def page(demo: Services, qapp: QApplication, qtbot) -> Iterator[StaffingPage]:  # type: ignore[no-untyped-def]
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    session = demo.auth.sign_in("coordinator", DEMO_PASSWORD)
    widget = StaffingPage(AppContext(demo, session, AppEvents()))
    qtbot.addWidget(widget)
    widget.reload()
    yield widget


def test_page_signs_up_only_what_stays_ticked_and_can_undo(page: StaffingPage, demo: Services) -> None:
    drafted = page.plan_list.count()
    assert drafted > 1 and len(page.selected_proposals()) == drafted
    page.plan_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    unticked = page.plan_list.item(0).data(PROPOSAL_ROLE)
    assert len(page.selected_proposals()) == drafted - 1
    assert str(drafted - 1) in page.approve_button.text()

    before = demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED]
    page.approve_button.click()
    assert demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED] == before + drafted - 1
    assert demo.store.assignments.find(unticked.overview.shift.shift_id, unticked.volunteer.volunteer_id) is None

    page.undo_button.click()
    assert demo.store.assignments.count_by_status()[AssignmentStatus.SCHEDULED] == before
    assert not page.undo_button.isEnabled()


def test_page_disables_approval_when_nothing_is_ticked(page: StaffingPage) -> None:
    for row in range(page.plan_list.count()):
        page.plan_list.item(row).setCheckState(Qt.CheckState.Unchecked)
    assert not page.approve_button.isEnabled()
