"""Sign-ups, cancellations, and attendance."""

from __future__ import annotations

from datetime import timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.models import AssignmentStatus, OpportunityStatus
from servesync.services import FixedClock, Services
from tests.conftest import SATURDAY_9AM, World
from tests.factories import COORDINATOR, make_opportunity, make_shift, volunteer_session

# ------------------------------------------------------------------ sign-up


def test_volunteer_signs_self_up(services: Services, store: DataStore, world: World) -> None:
    signup = services.scheduling.sign_up(volunteer_session(world.ana_id), world.shift_id, world.ana_id)
    assert signup.status is AssignmentStatus.SCHEDULED
    assert store.shifts.count_filled(world.shift_id) == 1


def test_volunteer_cannot_sign_up_someone_else(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.scheduling.sign_up(volunteer_session(world.ana_id), world.shift_id, world.ben_id)


def test_capacity_is_enforced(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)
    with pytest.raises(BusinessRuleError, match="full"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)


def test_duplicate_signup_is_explained(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    with pytest.raises(BusinessRuleError, match="already signed up"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)


def test_applicants_and_minors_are_screened(services: Services, world: World) -> None:
    with pytest.raises(BusinessRuleError, match="Applicant"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.applicant_id)

    adults_only = services.opportunities.create(
        COORDINATOR, make_opportunity(title="Night Shelter", min_age=18, status=OpportunityStatus.OPEN)
    )
    shift = services.opportunities.add_shift(
        COORDINATOR, make_shift(adults_only.opportunity_id or 0, SATURDAY_9AM + timedelta(days=1))
    )
    with pytest.raises(BusinessRuleError, match="aged 18\\+; Tess will be 16"):
        services.scheduling.sign_up(COORDINATOR, shift.shift_id or 0, world.teen_id)


def test_double_booking_is_prevented(services: Services, world: World) -> None:
    other = services.opportunities.create(COORDINATOR, make_opportunity(title="Cleanup", status=OpportunityStatus.OPEN))
    overlapping = services.opportunities.add_shift(
        COORDINATOR, make_shift(other.opportunity_id or 0, SATURDAY_9AM + timedelta(hours=1))
    )
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    with pytest.raises(BusinessRuleError, match="another shift at that time"):
        services.scheduling.sign_up(COORDINATOR, overlapping.shift_id or 0, world.ana_id)


def test_why_not_eligible_lists_reasons(services: Services, world: World) -> None:
    assert services.scheduling.why_not_eligible(COORDINATOR, world.shift_id, world.ana_id) == []
    reasons = services.scheduling.why_not_eligible(COORDINATOR, world.shift_id, world.applicant_id)
    assert len(reasons) == 1 and "Applicant" in reasons[0]


def test_cancel_and_sign_up_again_reuses_record(services: Services, world: World) -> None:
    me = volunteer_session(world.ana_id)
    first = services.scheduling.sign_up(me, world.shift_id, world.ana_id)
    cancelled = services.scheduling.cancel(me, first.assignment_id or 0)
    assert cancelled.status is AssignmentStatus.CANCELLED
    again = services.scheduling.sign_up(me, world.shift_id, world.ana_id)
    assert again.assignment_id == first.assignment_id and again.status is AssignmentStatus.SCHEDULED


def test_cancel_rules(services: Services, clock: FixedClock, world: World) -> None:
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    with pytest.raises(PermissionDeniedError):
        services.scheduling.cancel(volunteer_session(world.ben_id), signup.assignment_id or 0)
    clock.set(SATURDAY_9AM + timedelta(minutes=1))
    with pytest.raises(BusinessRuleError, match="already started"):
        services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)


def test_cannot_sign_up_after_start(services: Services, clock: FixedClock, world: World) -> None:
    clock.set(SATURDAY_9AM)
    with pytest.raises(BusinessRuleError, match="already started"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)


# --------------------------------------------------------------- attendance


@pytest.fixture
def started(services: Services, clock: FixedClock, world: World) -> int:
    """Ana and Ben signed up; the clock is now 30 minutes into the shift. Returns Ana's sign-up id."""
    ana = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)
    clock.set(SATURDAY_9AM + timedelta(minutes=30))
    return ana.assignment_id or 0


def test_attendance_waits_for_shift_start(services: Services, world: World) -> None:
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    with pytest.raises(BusinessRuleError, match="once the shift has started"):
        services.attendance.record_attendance(COORDINATOR, signup.assignment_id or 0)


def test_record_attendance_defaults_to_full_shift(services: Services, started: int) -> None:
    assert services.attendance.record_attendance(COORDINATOR, started).hours_served == 3.0
    assert services.attendance.record_attendance(COORDINATOR, started, "2.5").hours_served == 2.5


def test_hours_cannot_exceed_shift_length(services: Services, started: int) -> None:
    with pytest.raises(ValidationError) as caught:
        services.attendance.record_attendance(COORDINATOR, started, 4)
    assert "cannot be more than 3" in caught.value.errors["hours_served"]


def test_volunteers_cannot_record_attendance(services: Services, world: World, started: int) -> None:
    with pytest.raises(PermissionDeniedError):
        services.attendance.record_attendance(volunteer_session(world.ana_id), started)


def test_no_show_and_check_in_everyone(services: Services, store: DataStore, world: World, started: int) -> None:
    services.attendance.mark_no_show(COORDINATOR, started)
    assert services.attendance.check_in_everyone(COORDINATOR, world.shift_id) == 1  # Ben only
    stats = store.volunteers.get_participation(world.ana_id)
    assert (stats.no_shows, stats.shifts_attended) == (1, 0)
    assert store.assignments.total_hours() == 3.0


def test_cancelled_signup_is_not_a_no_show(services: Services, clock: FixedClock, world: World) -> None:
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)
    clock.set(SATURDAY_9AM + timedelta(hours=1))
    with pytest.raises(BusinessRuleError, match="isn't a no-show"):
        services.attendance.mark_no_show(COORDINATOR, signup.assignment_id or 0)


def test_walk_ins(services: Services, store: DataStore, world: World, started: int) -> None:
    walk_in = services.attendance.record_walk_in(COORDINATOR, world.shift_id, world.teen_id, "2")
    assert walk_in.status is AssignmentStatus.ATTENDED and walk_in.hours_served == 2.0
    assert store.shifts.count_filled(world.shift_id) == 3  # walk-ins may exceed capacity
    with pytest.raises(BusinessRuleError, match="Applicant"):
        services.attendance.record_walk_in(COORDINATOR, world.shift_id, world.applicant_id)
    # An existing sign-up is simply marked attended.
    assert services.attendance.record_walk_in(COORDINATOR, world.shift_id, world.ana_id).assignment_id == started


def test_roster_requires_leader(services: Services, world: World, started: int) -> None:
    assert [e.volunteer_name for e in services.attendance.roster(COORDINATOR, world.shift_id)] == [
        "Ben Brooks",
        "Ana Lopez",
    ]
    with pytest.raises(PermissionDeniedError):
        services.attendance.roster(volunteer_session(world.ana_id), world.shift_id)
