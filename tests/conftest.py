"""Shared pytest fixtures."""

from __future__ import annotations

import os

# Interface tests run headless ("offscreen"), so they work on any machine or CI server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

import pytest

from servesync.core.i18n import Language, set_language
from servesync.data import DataStore
from servesync.models import AvailabilitySlot, DayPart, OpportunityStatus, VolunteerStatus, Weekday
from servesync.services import FixedClock, Services
from tests.factories import FAST_ITERATIONS, make_opportunity, make_shift, make_volunteer

#: Fixed "now" for service tests: Monday, November 2, 2026, 8:00 AM.
NOW = datetime(2026, 11, 2, 8, 0)
#: Saturday of that week, 9:00 AM — the standard test shift.
SATURDAY_9AM = datetime(2026, 11, 7, 9, 0)


@pytest.fixture(autouse=True)
def _english_by_default() -> Iterator[None]:
    """The interface language is app-wide state; every test starts (and ends) in English."""
    set_language(Language.ENGLISH)
    yield
    set_language(Language.ENGLISH)


@pytest.fixture
def store() -> Iterator[DataStore]:
    """A fresh, migrated, in-memory database for every test (fully isolated)."""
    data_store = DataStore.in_memory()
    yield data_store
    data_store.close()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def services(store: DataStore, clock: FixedClock) -> Services:
    return Services.create(store, clock=clock, password_iterations=FAST_ITERATIONS)


@dataclass(frozen=True)
class World:
    """A tiny organization: one open program, one Saturday shift (2 spots), four people."""

    opportunity_id: int
    shift_id: int
    ana_id: int  # adult, active, free Saturday mornings, has Food Handling
    ben_id: int  # adult, active, no matching availability or skills
    teen_id: int  # 16 years old, active
    applicant_id: int  # not yet approved


def _saved(value: int | None) -> int:
    assert value is not None
    return value


@pytest.fixture
def world(store: DataStore) -> World:
    opportunity = store.opportunities.add(make_opportunity(status=OpportunityStatus.OPEN))
    opportunity_id = _saved(opportunity.opportunity_id)
    shift = store.shifts.add(make_shift(opportunity_id, SATURDAY_9AM, capacity=2))
    ana = store.volunteers.add(
        make_volunteer(
            skills={"Food Handling"},
            availability={AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING)},
        )
    )
    ben = store.volunteers.add(
        make_volunteer(
            first_name="Ben",
            last_name="Brooks",
            email="ben@example.org",
            phone="404-555-0101",
            skills={"Driving"},
            availability={AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING)},
        )
    )
    teen = store.volunteers.add(
        make_volunteer(
            first_name="Tess",
            last_name="Young",
            email="tess@example.org",
            phone="404-555-0102",
            birth_date=date(2010, 5, 1),
            joined_on=date(2025, 6, 1),
            emergency_contact_name="Rae Young (parent)",
            emergency_contact_phone="404-555-0103",
        )
    )
    applicant = store.volunteers.add(
        make_volunteer(
            first_name="Ivy",
            last_name="Newman",
            email="ivy@example.org",
            phone="404-555-0104",
            status=VolunteerStatus.APPLICANT,
        )
    )
    return World(
        opportunity_id,
        _saved(shift.shift_id),
        _saved(ana.volunteer_id),
        _saved(ben.volunteer_id),
        _saved(teen.volunteer_id),
        _saved(applicant.volunteer_id),
    )
