"""Opportunities and shifts: lifecycle, scheduling rules, and visibility."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from servesync.core.errors import (
    BusinessRuleError,
    PermissionDeniedError,
    RecordNotFoundError,
    ValidationError,
)
from servesync.data import DataStore
from servesync.models import AssignmentStatus, OpportunityStatus
from servesync.services import FixedClock, Services
from tests.conftest import NOW, SATURDAY_9AM, World
from tests.factories import COORDINATOR, make_opportunity, make_shift, volunteer_session


def test_volunteers_see_only_open_programs(services: Services, world: World) -> None:
    draft = services.opportunities.create(
        COORDINATOR, make_opportunity(title="Secret Plans", status=OpportunityStatus.DRAFT)
    )
    me = volunteer_session(world.ana_id)
    assert [o.title for o in services.opportunities.find_all(me)] == ["Food Pantry"]
    assert len(services.opportunities.find_all(COORDINATOR)) == 2
    with pytest.raises(RecordNotFoundError):
        services.opportunities.get(me, draft.opportunity_id or 0)


def test_volunteers_cannot_create_programs(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.opportunities.create(volunteer_session(world.ana_id), make_opportunity())


def test_update_keeps_status_controlled_by_lifecycle(services: Services, world: World) -> None:
    current = services.opportunities.get(COORDINATOR, world.opportunity_id)
    saved = services.opportunities.update(
        COORDINATOR, dataclasses.replace(current, title="Food Pantry (Weekend)", status=OpportunityStatus.DRAFT)
    )
    assert saved.title == "Food Pantry (Weekend)" and saved.status is OpportunityStatus.OPEN


def test_raising_min_age_is_blocked_if_it_strands_a_volunteer(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)
    current = services.opportunities.get(COORDINATOR, world.opportunity_id)
    with pytest.raises(ValidationError, match="Tess Young is already scheduled"):
        services.opportunities.update(COORDINATOR, dataclasses.replace(current, min_age=18))


def test_closing_cancels_upcoming_signups(services: Services, store: DataStore, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    assert services.opportunities.change_status(COORDINATOR, world.opportunity_id, OpportunityStatus.CLOSED) == 1
    assert store.assignments.find(world.shift_id, world.ana_id).status is AssignmentStatus.CANCELLED  # type: ignore[union-attr]
    with pytest.raises(BusinessRuleError, match="back to Draft"):
        services.opportunities.change_status(COORDINATOR, world.opportunity_id, OpportunityStatus.DRAFT)


def test_new_shifts_must_be_in_future_and_program_not_closed(services: Services, world: World) -> None:
    with pytest.raises(ValidationError, match="future"):
        services.opportunities.add_shift(COORDINATOR, make_shift(world.opportunity_id, NOW - timedelta(days=1)))
    services.opportunities.change_status(COORDINATOR, world.opportunity_id, OpportunityStatus.CLOSED)
    with pytest.raises(BusinessRuleError, match="closed"):
        services.opportunities.add_shift(COORDINATOR, make_shift(world.opportunity_id, SATURDAY_9AM))


def test_weekly_shifts(services: Services, world: World) -> None:
    first = make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(weeks=1), capacity=6)
    created = services.opportunities.add_weekly_shifts(COORDINATOR, first, "4")
    assert [s.starts_at for s in created] == [first.starts_at + timedelta(weeks=n) for n in range(4)]
    assert all(s.capacity == 6 for s in created)
    with pytest.raises(ValidationError, match="between 1 and 52"):
        services.opportunities.add_weekly_shifts(COORDINATOR, first, 60)


def test_capacity_cannot_drop_below_signups(services: Services, store: DataStore, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)
    shift = store.shifts.get(world.shift_id)
    with pytest.raises(ValidationError, match="can't be lower than 2"):
        services.opportunities.update_shift(COORDINATOR, dataclasses.replace(shift, capacity=1))


def test_moving_a_shift_checks_for_double_booking(services: Services, store: DataStore, world: World) -> None:
    other_program = services.opportunities.create(
        COORDINATOR, make_opportunity(title="Park Cleanup", status=OpportunityStatus.OPEN)
    )
    afternoon = services.opportunities.add_shift(
        COORDINATOR, make_shift(other_program.opportunity_id or 0, SATURDAY_9AM + timedelta(hours=4))
    )
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, afternoon.shift_id or 0, world.ana_id)

    morning = store.shifts.get(world.shift_id)
    clash = dataclasses.replace(
        morning, starts_at=morning.starts_at + timedelta(hours=2), ends_at=morning.ends_at + timedelta(hours=2)
    )
    with pytest.raises(BusinessRuleError, match="double-book Ana Lopez"):
        services.opportunities.update_shift(COORDINATOR, clash)

    earlier = dataclasses.replace(
        morning, starts_at=morning.starts_at - timedelta(hours=1), ends_at=morning.ends_at - timedelta(hours=1)
    )
    assert services.opportunities.update_shift(COORDINATOR, earlier).starts_at == SATURDAY_9AM - timedelta(hours=1)


def test_started_shifts_are_frozen(services: Services, store: DataStore, clock: FixedClock, world: World) -> None:
    clock.set(SATURDAY_9AM + timedelta(minutes=5))
    shift = store.shifts.get(world.shift_id)
    with pytest.raises(BusinessRuleError, match="already started"):
        services.opportunities.update_shift(COORDINATOR, dataclasses.replace(shift, capacity=9))


def test_schedule_views(services: Services, world: World) -> None:
    services.opportunities.create(COORDINATOR, make_opportunity(title="Draft Program", status=OpportunityStatus.DRAFT))
    upcoming = services.opportunities.upcoming_schedule(volunteer_session(world.ana_id), days=7)
    assert [o.shift.shift_id for o in upcoming] == [world.shift_id]
    assert services.opportunities.upcoming_schedule(COORDINATOR, days=1) == []  # Saturday is 5 days away
