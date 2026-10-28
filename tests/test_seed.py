"""Demo data must be realistic *and* obey every rule the app enforces."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import pairwise

import pytest

from servesync.core.errors import BusinessRuleError
from servesync.core.security import verify_password
from servesync.core.validators import calculate_age
from servesync.data import DataStore
from servesync.data.seed import DEMO_ORGANIZATION_NAME, DEMO_PASSWORD, SeedSummary, seed_demo_data
from servesync.models import AssignmentStatus, OpportunityStatus, VolunteerStatus
from tests.factories import FAST_ITERATIONS

TODAY = date(2026, 10, 26)


@pytest.fixture
def seeded(store: DataStore) -> tuple[DataStore, SeedSummary]:
    return store, seed_demo_data(store, today=TODAY, password_iterations=FAST_ITERATIONS)


def test_seed_produces_a_full_organization(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, summary = seeded
    assert store.settings.organization_name() == DEMO_ORGANIZATION_NAME
    assert summary.volunteers == 40 and summary.accounts == 4
    assert summary.shifts > 100 and summary.assignments > 500
    statuses = store.volunteers.count_by_status()
    assert all(statuses[s] > 0 for s in VolunteerStatus)  # pipeline has every stage
    assert all(n > 0 for n in store.opportunities.count_by_status().values())
    assert store.assignments.total_hours() == pytest.approx(summary.hours_served)


def test_seed_is_deterministic(store: DataStore) -> None:
    first = seed_demo_data(store, today=TODAY, password_iterations=FAST_ITERATIONS)
    other = DataStore.in_memory()
    try:
        second = seed_demo_data(other, today=TODAY, password_iterations=FAST_ITERATIONS)
    finally:
        other.close()
    assert first == second


def test_seed_refuses_non_empty_database(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, _ = seeded
    with pytest.raises(BusinessRuleError):
        seed_demo_data(store, today=TODAY, password_iterations=FAST_ITERATIONS)


def test_seed_never_overbooks_or_double_books(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, _ = seeded
    by_volunteer: defaultdict[int, list[tuple[object, object]]] = defaultdict(list)
    for overview in store.shifts.overviews():
        assert overview.filled <= overview.shift.capacity
        for entry in store.assignments.roster(overview.shift.shift_id or 0):
            by_volunteer[entry.assignment.volunteer_id].append((overview.shift.starts_at, overview.shift.ends_at))
    for intervals in by_volunteer.values():
        intervals.sort()
        for (_, previous_end), (next_start, _) in pairwise(intervals):
            assert next_start >= previous_end  # type: ignore[operator]


def test_seed_respects_age_rules_and_dates(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, _ = seeded
    volunteers = {v.volunteer_id: v for v in store.volunteers.find_all()}
    opportunities = {o.opportunity_id: o for o in store.opportunities.find_all()}
    for overview in store.shifts.overviews():
        opportunity = opportunities[overview.shift.opportunity_id]
        for entry in store.assignments.roster(overview.shift.shift_id or 0, include_cancelled=True):
            volunteer = volunteers[entry.assignment.volunteer_id]
            shift_day = overview.shift.starts_at.date()
            assert calculate_age(volunteer.birth_date, shift_day) >= opportunity.min_age
            assert volunteer.joined_on <= shift_day
            assert volunteer.status is not VolunteerStatus.APPLICANT
            is_past = shift_day < TODAY
            assert (entry.assignment.status is AssignmentStatus.SCHEDULED) == (not is_past)


def test_seed_has_draft_and_upcoming_work(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, _ = seeded
    drafts = store.opportunities.find_all(status=OpportunityStatus.DRAFT)
    assert drafts and store.shifts.for_opportunity(drafts[0].opportunity_id or 0) == []
    upcoming = [o for o in store.shifts.overviews() if o.shift.starts_at.date() >= TODAY]
    assert any(o.open_spots > 0 for o in upcoming)


def test_demo_accounts_sign_in(seeded: tuple[DataStore, SeedSummary]) -> None:
    store, _ = seeded
    hashes = set()
    for username in ("admin", "coordinator", "jordan.rivera", "priya.patel"):
        account = store.accounts.find_by_username(username)
        assert account is not None and verify_password(DEMO_PASSWORD, account.password_hash)
        hashes.add(account.password_hash)
    assert len(hashes) == 4  # every account has its own salt
    jordan = store.accounts.find_by_username("jordan.rivera")
    assert jordan is not None and jordan.volunteer_id is not None
    assert store.volunteers.get(jordan.volunteer_id).is_minor(on=TODAY)
