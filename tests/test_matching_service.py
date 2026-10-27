"""Smart Match: pure scoring, filtering of ineligible volunteers, and real demo-data behavior."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError
from servesync.data import DataStore
from servesync.data.seed import seed_demo_data
from servesync.models import (
    AvailabilitySlot,
    DayPart,
    OpportunityStatus,
    VolunteerParticipation,
    VolunteerStatus,
    Weekday,
)
from servesync.services import FixedClock, Services
from servesync.services.matching_service import MAX_PICKS_PER_PROGRAM, score_match, total_score
from tests.conftest import SATURDAY_9AM, World
from tests.factories import (
    COORDINATOR,
    FAST_ITERATIONS,
    make_opportunity,
    make_shift,
    make_volunteer,
    volunteer_session,
)


def _participation(attended: int, no_shows: int) -> VolunteerParticipation:
    return VolunteerParticipation(1, "Ana Lopez", VolunteerStatus.ACTIVE, 30.0, attended, no_shows, 0, 0, None)


# ----------------------------------------------------------- pure scoring


def test_ideal_volunteer_scores_100() -> None:
    factors = score_match(
        volunteer=make_volunteer(skills={"Food Handling"}),  # free Saturday mornings
        shift=make_shift(1, SATURDAY_9AM),
        opportunity=make_opportunity(),
        participation=_participation(10, 0),
        program_visits=5,
        recent_hours=0.0,
    )
    assert total_score(factors) == 100
    assert all(not factor.is_concern for factor in factors)


def test_weak_match_explains_every_concern() -> None:
    factors = score_match(
        volunteer=make_volunteer(skills={"Driving"}, availability=set()),
        shift=make_shift(1, SATURDAY_9AM),
        opportunity=make_opportunity(),
        participation=_participation(6, 4),
        program_visits=0,
        recent_hours=25.0,
    )
    concerns = [f.explanation for f in factors if f.is_concern]
    assert any("Saturday mornings" in c for c in concerns)
    assert any("Missing needed skills: Food Handling" in c for c in concerns)
    assert any("60%" in c for c in concerns)
    assert any("Busy lately" in c for c in concerns)
    assert total_score(factors) < 25


def test_newcomer_gets_neutral_reliability() -> None:
    factors = score_match(
        volunteer=make_volunteer(),
        shift=make_shift(1, SATURDAY_9AM),
        opportunity=make_opportunity(required_skills=set()),
        participation=None,
        program_visits=0,
        recent_hours=None,  # fair-share factor omitted
    )
    assert len(factors) == 4
    reliability = next(f for f in factors if f.name == "Reliability")
    assert reliability.points == pytest.approx(14.0) and "New volunteer" in reliability.explanation


# ------------------------------------------------------ service behavior


def test_recommendations_skip_ineligible_and_rank_best_first(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)  # Ben is already on it
    matches = services.matching.recommend_volunteers(COORDINATOR, world.shift_id)
    names = [m.volunteer.full_name for m in matches]
    assert "Ben Brooks" not in names and "Ivy Newman" not in names  # signed up / applicant
    assert names[0] == "Ana Lopez"  # available + has the skill
    assert [m.score for m in matches] == sorted((m.score for m in matches), reverse=True)


def test_full_shift_has_no_recommendations(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)
    assert services.matching.recommend_volunteers(COORDINATOR, world.shift_id) == []


def test_smart_match_needs_open_upcoming_shift(services: Services, clock: FixedClock, world: World) -> None:
    services.opportunities.change_status(COORDINATOR, world.opportunity_id, OpportunityStatus.CLOSED)
    with pytest.raises(BusinessRuleError, match="Publish"):
        services.matching.recommend_volunteers(COORDINATOR, world.shift_id)
    services.opportunities.change_status(COORDINATOR, world.opportunity_id, OpportunityStatus.OPEN)
    clock.set(SATURDAY_9AM)
    with pytest.raises(BusinessRuleError, match="already started"):
        services.matching.recommend_volunteers(COORDINATOR, world.shift_id)


def test_permissions(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.matching.recommend_volunteers(volunteer_session(world.ana_id), world.shift_id)
    with pytest.raises(PermissionDeniedError):
        services.matching.recommend_shifts(volunteer_session(world.ana_id), world.ben_id)


def test_shift_recommendations_are_diverse_and_skip_my_shifts(
    services: Services, store: DataStore, world: World
) -> None:
    for week in range(1, 5):
        store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(weeks=week)))
    cleanup = services.opportunities.create(
        COORDINATOR, make_opportunity(title="Park Cleanup", status=OpportunityStatus.OPEN, required_skills=set())
    )
    store.shifts.add(make_shift(cleanup.opportunity_id or 0, SATURDAY_9AM + timedelta(days=1)))
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)

    picks = services.matching.recommend_shifts(volunteer_session(world.ana_id), world.ana_id, limit=10)
    assert world.shift_id not in {p.overview.shift.shift_id for p in picks}
    food = [p for p in picks if p.overview.opportunity_title == "Food Pantry"]
    assert len(food) == MAX_PICKS_PER_PROGRAM
    assert any(p.overview.opportunity_title == "Park Cleanup" for p in picks)


def test_inactive_volunteer_gets_no_shift_recommendations(services: Services, world: World) -> None:
    services.volunteers.change_status(COORDINATOR, world.ana_id, VolunteerStatus.INACTIVE)
    assert services.matching.recommend_shifts(COORDINATOR, world.ana_id) == []


# --------------------------------------------------- against the demo data

SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore) -> Services:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    clock = FixedClock(datetime.combine(SEED_DAY, time(8, 0)))
    return Services.create(store, clock=clock, password_iterations=FAST_ITERATIONS)


def test_demo_recommendations_obey_every_hard_rule(demo: Services, store: DataStore) -> None:
    fun_run = next(
        o for o in demo.opportunities.upcoming_schedule(COORDINATOR, days=45) if "Fun Run" in o.opportunity_title
    )
    shift = fun_run.shift
    opportunity = store.opportunities.get(shift.opportunity_id)
    matches = demo.matching.recommend_volunteers(COORDINATOR, shift.shift_id or 0, limit=50)
    assert matches, "the demo 5K should have recommendations"
    for match in matches:
        volunteer = match.volunteer
        assert volunteer.status is VolunteerStatus.ACTIVE
        assert volunteer.age(on=shift.starts_at.date()) >= opportunity.min_age
        assert not store.assignments.conflicting_shifts(
            volunteer.volunteer_id or 0, shift.starts_at, shift.ends_at, exclude_shift_id=shift.shift_id
        )
    # The top picks are actually free at that time.
    slot = AvailabilitySlot(Weekday(shift.starts_at.weekday()), DayPart.from_hour(shift.starts_at.hour))
    assert all(slot in m.volunteer.availability for m in matches[:3])


def test_demo_persona_gets_personal_recommendations(demo: Services, store: DataStore) -> None:
    jordan = store.accounts.find_by_username("jordan.rivera")
    assert jordan is not None and jordan.volunteer_id is not None
    picks = demo.matching.recommend_shifts(volunteer_session(jordan.volunteer_id), jordan.volunteer_id)
    assert picks and picks[0].score >= 90
    assert all(store.opportunities.get(p.overview.shift.opportunity_id).min_age <= 16 for p in picks)


def test_demo_is_always_relative_to_today() -> None:
    """The demo 5K always lands on a Sunday at least three weeks out."""
    with DataStore.in_memory() as store:
        seed_demo_data(store, today=date(2026, 3, 4), password_iterations=FAST_ITERATIONS)
        run = next(o for o in store.opportunities.find_all() if "Fun Run" in o.title)
        (shift,) = store.shifts.for_opportunity(run.opportunity_id or 0)
        assert shift.starts_at.weekday() == Weekday.SUNDAY
        assert shift.starts_at.date() - date(2026, 3, 4) >= timedelta(days=21)


def test_undiversified_list_returns_every_joinable_shift(services: Services, store: DataStore, world: World) -> None:
    for week in range(1, 5):
        store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(weeks=week)))
    everything = services.matching.recommend_shifts(
        volunteer_session(world.ana_id), world.ana_id, limit=100, diversify=False
    )
    assert len(everything) == 5  # all Food Pantry shifts, no per-program cap
