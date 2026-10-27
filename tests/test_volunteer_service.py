"""Volunteer records and the recruitment pipeline."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError
from servesync.data import DataStore
from servesync.models import AssignmentStatus, VolunteerStatus
from servesync.services import FixedClock, Services
from tests.conftest import SATURDAY_9AM, World
from tests.factories import ADMIN, COORDINATOR, make_shift, make_volunteer, volunteer_session


def test_coordinator_registers_applicant(services: Services) -> None:
    saved = services.volunteers.register(COORDINATOR, make_volunteer(status=VolunteerStatus.APPLICANT))
    assert saved.volunteer_id is not None and saved.status is VolunteerStatus.APPLICANT


def test_volunteers_cannot_register_others(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.volunteers.register(volunteer_session(world.ana_id), make_volunteer(email="x@example.org"))


def test_new_volunteers_cannot_start_inactive(services: Services) -> None:
    with pytest.raises(BusinessRuleError, match="Applicant or Active"):
        services.volunteers.register(COORDINATOR, make_volunteer(status=VolunteerStatus.INACTIVE))


def test_possible_duplicates_by_phone(services: Services, world: World) -> None:
    lookalike = make_volunteer(first_name="Annie", email="annie@example.org")  # same phone as Ana
    assert [v.volunteer_id for v in services.volunteers.possible_duplicates(COORDINATOR, lookalike)] == [world.ana_id]


def test_pipeline_approval_and_rules(services: Services, world: World) -> None:
    result = services.volunteers.change_status(COORDINATOR, world.applicant_id, VolunteerStatus.ACTIVE)
    assert result.volunteer.status is VolunteerStatus.ACTIVE and result.cancelled_signups == 0
    with pytest.raises(BusinessRuleError, match="can't move"):
        services.volunteers.change_status(COORDINATOR, world.ana_id, VolunteerStatus.APPLICANT)


def test_archiving_cancels_only_upcoming_signups(
    services: Services, store: DataStore, clock: FixedClock, world: World
) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    next_week = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(weeks=1)))
    services.scheduling.sign_up(COORDINATOR, next_week.shift_id or 0, world.ana_id)

    clock.set(SATURDAY_9AM + timedelta(hours=4))  # first shift is now in the past
    services.attendance.check_in_everyone(COORDINATOR, world.shift_id)
    result = services.volunteers.change_status(COORDINATOR, world.ana_id, VolunteerStatus.INACTIVE)

    assert result.cancelled_signups == 1
    statuses = [r.assignment.status for r in store.assignments.history(world.ana_id)]
    assert statuses == [AssignmentStatus.CANCELLED, AssignmentStatus.ATTENDED]  # history kept


def test_volunteer_edits_own_profile_but_not_leader_fields(services: Services, store: DataStore, world: World) -> None:
    me = volunteer_session(world.ana_id)
    current = services.volunteers.get(me, world.ana_id)
    edited = dataclasses.replace(
        current, phone="(512) 555-0177", notes="I made myself a VIP", status=VolunteerStatus.INACTIVE
    )
    saved = services.volunteers.update_profile(me, edited)
    assert saved.phone == "5125550177"
    assert saved.notes == current.notes and saved.status is VolunteerStatus.ACTIVE


def test_leader_edits_notes_but_status_needs_change_status(services: Services, world: World) -> None:
    current = services.volunteers.get(COORDINATOR, world.ana_id)
    saved = services.volunteers.update_profile(
        COORDINATOR, dataclasses.replace(current, notes="Great with kids", status=VolunteerStatus.INACTIVE)
    )
    assert saved.notes == "Great with kids" and saved.status is VolunteerStatus.ACTIVE


def test_volunteers_cannot_see_each_other(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.volunteers.get(volunteer_session(world.ana_id), world.ben_id)
    with pytest.raises(PermissionDeniedError):
        services.volunteers.search(volunteer_session(world.ana_id))


def test_upcoming_lists_future_scheduled_shifts(services: Services, store: DataStore, world: World) -> None:
    later = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(weeks=2)))
    services.scheduling.sign_up(COORDINATOR, later.shift_id or 0, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    upcoming = services.volunteers.upcoming(volunteer_session(world.ana_id), world.ana_id)
    assert [r.starts_at for r in upcoming] == [SATURDAY_9AM, SATURDAY_9AM + timedelta(weeks=2)]


def test_only_admins_delete(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.volunteers.delete(COORDINATOR, world.ben_id)
    services.volunteers.delete(ADMIN, world.ben_id)
