"""Roles within a shift, waitlists with automatic promotion, Home notices, and certification types."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from servesync.core.errors import BusinessRuleError, PermissionDeniedError, ValidationError
from servesync.data import DataStore
from servesync.models import (
    AssignmentStatus,
    Certification,
    CredentialKind,
    NoticeKind,
    RoleOverview,
    ShiftRole,
    VolunteerStatus,
)
from servesync.services import FixedClock, Services
from servesync.services.dashboard_service import expiring_soon
from servesync.services.reports.model import ReportFilters, ReportKind
from servesync.services.rules import best_role, check_roles, walk_in_role
from servesync.services.staffing_service import allocate
from tests.conftest import NOW, SATURDAY_9AM, World
from tests.factories import COORDINATOR, make_opportunity, make_shift, make_volunteer, volunteer_session


def _role(name: str, capacity: int, skill: str = "", filled: int = 0, role_id: int = 1) -> RoleOverview:
    return RoleOverview(ShiftRole(name, capacity, skill, role_id=role_id, position=role_id), filled)


def _split_roles(services: Services, shift_id: int) -> list[RoleOverview]:
    """Make the world's 2-spot shift into Cooking x1 (needs Food Handling) and Setup x1."""
    return services.scheduling.set_roles(
        COORDINATOR, shift_id, [ShiftRole("Cooking", 1, "Food Handling"), ShiftRole("Setup", 1)]
    )


def _add_person(store: DataStore, name: str, phone: str, **fields: object) -> int:
    volunteer = store.volunteers.add(
        make_volunteer(first_name=name, email=f"{name.lower()}@example.org", phone=phone, **fields)
    )
    assert volunteer.volunteer_id is not None
    return volunteer.volunteer_id


# ---------------------------------------------------------------- pure rules


def test_best_role_puts_skilled_people_in_skilled_roles() -> None:
    roles = [_role("Setup", 3, role_id=1), _role("First aid", 1, "First Aid/CPR", role_id=2)]
    assert best_role(roles, frozenset({"first aid/cpr"})).role.name == "First aid"  # type: ignore[union-attr]
    assert best_role(roles, frozenset()).role.name == "Setup"  # type: ignore[union-attr]
    full = [_role("Setup", 1, filled=1), _role("First aid", 1, "First Aid/CPR", role_id=2)]
    assert best_role(full, frozenset()) is None


def test_walk_ins_always_get_a_role_even_when_full() -> None:
    roles = [_role("Setup", 1, filled=1), _role("First aid", 1, "First Aid/CPR", filled=1, role_id=2)]
    assert walk_in_role(roles, frozenset()).role.name == "Setup"


@pytest.mark.parametrize(
    ("roles", "field"),
    [
        ([], "roles"),
        ([ShiftRole("A", 1), ShiftRole("a", 1)], "role_1_name"),
        ([ShiftRole(f"R{i}", 1) for i in range(13)], "roles"),
    ],
)
def test_role_lists_are_checked(roles: list[ShiftRole], field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        check_roles(roles, [])
    assert field in caught.value.errors


def test_a_role_cannot_shrink_below_or_drop_the_people_in_it() -> None:
    current = [_role("Setup", 4, filled=3, role_id=1), _role("Greeter", 2, filled=1, role_id=2)]
    with pytest.raises(ValidationError) as caught:
        check_roles([ShiftRole("Setup", 2, role_id=1)], current)
    assert "role_0_capacity" in caught.value.errors and "Greeter" in caught.value.errors["roles"]


def test_role_names_are_validated() -> None:
    with pytest.raises(ValidationError):
        ShiftRole("x" * 41, 1)
    with pytest.raises(ValidationError):
        ShiftRole("Setup", 0)
    assert ShiftRole("", 3).display_name == "General"


# ------------------------------------------------------------------- roles


def test_every_new_shift_starts_with_one_general_role(services: Services, world: World) -> None:
    (role,) = services.scheduling.roles(COORDINATOR, world.shift_id)
    assert role.role.is_general and role.role.capacity == 2


def test_setting_roles_sets_the_shift_capacity(services: Services, store: DataStore, world: World) -> None:
    services.scheduling.set_roles(COORDINATOR, world.shift_id, [ShiftRole("Cooking", 3), ShiftRole("Setup", 2)])
    assert store.shifts.get(world.shift_id).capacity == 5


def test_sign_up_fills_roles_by_skill(services: Services, world: World) -> None:
    _split_roles(services, world.shift_id)
    ana = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)  # has Food Handling
    ben = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)
    names = {role.role.role_id: role.role.name for role in services.scheduling.roles(COORDINATOR, world.shift_id)}
    assert (names[ana.role_id or 0], names[ben.role_id or 0]) == ("Cooking", "Setup")


def test_a_role_needing_a_skill_explains_why(services: Services, world: World) -> None:
    cooking, _setup = _split_roles(services, world.shift_id)
    reasons = services.scheduling.why_not_eligible(COORDINATOR, world.shift_id, world.ben_id, cooking.role.role_id)
    assert any("needs Food Handling" in reason for reason in reasons)
    with pytest.raises(BusinessRuleError, match="needs Food Handling"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id, cooking.role.role_id)


def test_open_spots_only_in_a_skilled_role_say_so(services: Services, world: World) -> None:
    _split_roles(services, world.shift_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)  # takes Setup
    reasons = services.scheduling.why_not_eligible(COORDINATOR, world.shift_id, world.ben_id)
    assert any("open spots on this shift need Food Handling" in reason for reason in reasons)


def test_a_role_with_people_in_it_cannot_be_removed(services: Services, world: World) -> None:
    cooking, _setup = _split_roles(services, world.shift_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    with pytest.raises(ValidationError):
        services.scheduling.set_roles(COORDINATOR, world.shift_id, [ShiftRole("Setup", 2)])
    kept = services.scheduling.set_roles(
        COORDINATOR, world.shift_id, [ShiftRole("Cooking", 1, "Food Handling", role_id=cooking.role.role_id)]
    )
    assert [role.role.name for role in kept] == ["Cooking"]


def test_removing_a_role_keeps_cancelled_history(services: Services, store: DataStore, world: World) -> None:
    cooking, setup = _split_roles(services, world.shift_id)
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id)  # Setup
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)
    services.scheduling.set_roles(
        COORDINATOR, world.shift_id, [ShiftRole("Cooking", 2, "Food Handling", role_id=cooking.role.role_id)]
    )
    history = store.assignments.get(signup.assignment_id or 0)
    assert history.status is AssignmentStatus.CANCELLED and history.role_id == cooking.role.role_id
    assert setup.role.role_id not in {r.role.role_id for r in services.scheduling.roles(COORDINATOR, world.shift_id)}


def test_resizing_a_shift_with_several_roles_is_refused(services: Services, store: DataStore, world: World) -> None:
    _split_roles(services, world.shift_id)
    shift = store.shifts.get(world.shift_id)
    shift.capacity = 4
    with pytest.raises(ValidationError, match="each role"):
        services.opportunities.update_shift(COORDINATOR, shift)


def test_change_role_checks_the_new_role(services: Services, world: World) -> None:
    cooking, setup = _split_roles(services, world.shift_id)
    signup = services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ben_id, setup.role.role_id)
    with pytest.raises(BusinessRuleError, match="needs Food Handling"):
        services.scheduling.change_role(COORDINATOR, signup.assignment_id or 0, cooking.role.role_id or 0)


def test_the_database_rejects_a_role_from_another_shift(services: Services, store: DataStore, world: World) -> None:
    from servesync.core.errors import DataStoreError
    from servesync.models import Assignment

    other = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(days=7)))
    (foreign,) = store.shifts.roles(other.shift_id or 0)
    with pytest.raises(DataStoreError):
        store.assignments.add(Assignment(world.shift_id, world.ana_id, role_id=foreign.role.role_id))


def test_smart_match_and_autopilot_fill_roles_by_skill(services: Services, world: World) -> None:
    _split_roles(services, world.shift_id)
    matches = services.matching.recommend_volunteers(COORDINATOR, world.shift_id, limit=10)
    by_name = {m.volunteer.first_name: m.role.role.name for m in matches if m.role}
    assert by_name["Ana"] == "Cooking"
    overview = services.opportunities.shift_overview(COORDINATOR, world.shift_id)
    roles = services.scheduling.roles(COORDINATOR, world.shift_id)
    # Two strong candidates who both fit only "Setup": the plan drafts one, never two, into its one spot.
    strong = [m for m in matches if m.role and m.role.role.name == "Setup"]
    plan = allocate([(overview, strong * 2)], {world.shift_id: roles})
    assert sum(1 for p in plan if p.role and p.role.role.name == "Setup") <= 1


# ---------------------------------------------------------------- waitlist


def _fill(services: Services, world: World) -> None:
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    services.scheduling.sign_up(COORDINATOR, world.shift_id, world.teen_id)


def test_only_a_full_shift_has_a_waitlist(services: Services, world: World) -> None:
    with pytest.raises(BusinessRuleError, match="Sign up instead"):
        services.scheduling.join_waitlist(volunteer_session(world.ben_id), world.shift_id, world.ben_id)
    _fill(services, world)
    assert services.scheduling.join_waitlist(volunteer_session(world.ben_id), world.shift_id, world.ben_id) == 1
    with pytest.raises(BusinessRuleError, match="already on the waitlist"):
        services.scheduling.join_waitlist(volunteer_session(world.ben_id), world.shift_id, world.ben_id)


def test_waiting_wont_help_someone_kept_out_for_another_reason(services: Services, world: World) -> None:
    _fill(services, world)
    reasons = services.scheduling.why_not_waitlist(COORDINATOR, world.shift_id, world.applicant_id)
    assert reasons and any("approved" in reason for reason in reasons)


def test_a_cancellation_signs_up_the_next_person_and_tells_them(
    services: Services, store: DataStore, world: World
) -> None:
    _fill(services, world)
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    signup = store.assignments.find(world.shift_id, world.ana_id)
    assert signup is not None
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)
    promoted = store.assignments.find(world.shift_id, world.ben_id)
    assert promoted is not None and promoted.status is AssignmentStatus.SCHEDULED
    assert services.scheduling.waitlist(COORDINATOR, world.shift_id) == []
    (notice,) = services.scheduling.notices(volunteer_session(world.ben_id), world.ben_id)
    assert notice.kind is NoticeKind.WAITLIST_PROMOTED and notice.shift_id == world.shift_id


def test_promotion_skips_someone_now_busy_but_keeps_their_place(
    services: Services, store: DataStore, world: World
) -> None:
    _fill(services, world)
    carol = _add_person(store, "Carol", "404-555-0110")
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, carol)
    clash = store.shifts.add(make_shift(world.opportunity_id, SATURDAY_9AM + timedelta(hours=1), capacity=3))
    services.scheduling.sign_up(COORDINATOR, clash.shift_id or 0, world.ben_id)  # Ben is busy then now
    signup = store.assignments.find(world.shift_id, world.ana_id)
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)  # type: ignore[union-attr]
    assert store.assignments.find(world.shift_id, carol) is not None
    assert [e.volunteer_id for e in services.scheduling.waitlist(COORDINATOR, world.shift_id)] == [world.ben_id]


def test_more_room_and_archiving_both_move_the_waitlist(services: Services, store: DataStore, world: World) -> None:
    _fill(services, world)
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    shift = store.shifts.get(world.shift_id)
    shift.capacity = 3
    services.opportunities.update_shift(COORDINATOR, shift)
    assert store.assignments.find(world.shift_id, world.ben_id) is not None

    carol = _add_person(store, "Carol", "404-555-0110")
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, carol)
    services.volunteers.change_status(COORDINATOR, world.teen_id, VolunteerStatus.INACTIVE)  # frees a spot
    assert store.assignments.find(world.shift_id, carol) is not None


def test_archived_volunteers_leave_every_waitlist(services: Services, world: World) -> None:
    _fill(services, world)
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    services.volunteers.change_status(COORDINATOR, world.ben_id, VolunteerStatus.INACTIVE)
    assert services.scheduling.waitlist(COORDINATOR, world.shift_id) == []


def test_nobody_is_promoted_once_the_shift_starts(store: DataStore, world: World) -> None:
    early = Services.create(store, clock=FixedClock(NOW))
    _fill(early, world)
    early.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    late = Services.create(store, clock=FixedClock(SATURDAY_9AM + timedelta(minutes=5)))
    assert late.scheduling.fill_from_waitlist(world.shift_id) == []


def test_people_only_see_and_dismiss_their_own_notices(services: Services, world: World) -> None:
    _fill(services, world)
    services.scheduling.join_waitlist(COORDINATOR, world.shift_id, world.ben_id)
    signup = services.store.assignments.find(world.shift_id, world.ana_id)
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)  # type: ignore[union-attr]
    (notice,) = services.scheduling.notices(volunteer_session(world.ben_id), world.ben_id)
    with pytest.raises(PermissionDeniedError):
        services.scheduling.notices(volunteer_session(world.ana_id), world.ben_id)
    with pytest.raises(PermissionDeniedError):
        services.scheduling.dismiss_notice(volunteer_session(world.ana_id), notice.notice_id)
    services.scheduling.dismiss_notice(volunteer_session(world.ben_id), notice.notice_id)
    assert services.scheduling.notices(volunteer_session(world.ben_id), world.ben_id) == []


def test_leaving_the_waitlist(services: Services, world: World) -> None:
    _fill(services, world)
    session = volunteer_session(world.ben_id)
    services.scheduling.join_waitlist(session, world.shift_id, world.ben_id)
    services.scheduling.leave_waitlist(session, world.shift_id, world.ben_id)
    assert services.scheduling.waitlist_position(session, world.shift_id, world.ben_id) is None
    with pytest.raises(BusinessRuleError):
        services.scheduling.leave_waitlist(session, world.shift_id, world.ben_id)


# ----------------------------------------------- certifications and waivers


def test_a_waiver_is_saved_with_its_type_and_issue_date(services: Services, world: World) -> None:
    saved = services.volunteers.add_certification(
        COORDINATOR,
        world.ana_id,
        "Liability waiver",
        date(2027, 6, 1),
        kind=CredentialKind.WAIVER,
        issued_on=date(2026, 6, 1),
    )
    item = saved.certification("Liability waiver")
    assert item is not None and item.kind is CredentialKind.WAIVER and item.issued_on == date(2026, 6, 1)


@pytest.mark.parametrize(
    ("issued", "expires", "field"),
    [
        (date(2026, 12, 1), date(2027, 6, 1), "certification_issued"),  # issued in the future
        (date(2010, 1, 1), date(2027, 6, 1), "certification_issued"),  # a typo in the year
        (date(2026, 6, 1), date(2026, 6, 1), "certification_expires"),  # expires before it's valid (and past)
        ("13/45/2026", date(2027, 6, 1), "certification_issued"),  # not a date
    ],
)
def test_certification_dates_are_checked(
    services: Services, world: World, issued: object, expires: date, field: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        services.volunteers.add_certification(
            COORDINATOR, world.ana_id, "CPR", expires, kind=CredentialKind.CERTIFICATION, issued_on=issued
        )
    assert field in caught.value.errors


def test_a_waiver_requirement_blocks_sign_up_and_says_why(services: Services, store: DataStore, world: World) -> None:
    opportunity = store.opportunities.get(world.opportunity_id)
    opportunity.required_certifications = frozenset({"Liability waiver"})
    store.opportunities.update(opportunity)
    with pytest.raises(BusinessRuleError, match="Liability waiver"):
        services.scheduling.sign_up(COORDINATOR, world.shift_id, world.ana_id)
    assert all(
        m.volunteer.volunteer_id != world.ana_id
        for m in services.matching.recommend_volunteers(COORDINATOR, world.shift_id)
    )


def test_the_dashboard_lists_only_items_expiring_in_the_next_30_days() -> None:
    today = date(2026, 11, 2)
    person = make_volunteer(status=VolunteerStatus.ACTIVE)
    person.certifications = frozenset(
        {
            Certification("CPR", today + timedelta(days=10)),
            Certification("Background Check", today + timedelta(days=30)),
            Certification("Food Handler Card", today - timedelta(days=1)),  # already expired: report, not dashboard
            Certification("Liability waiver", today + timedelta(days=31), CredentialKind.WAIVER),
        }
    )
    assert [item.name for _v, item in expiring_soon([person], today)] == ["CPR", "Background Check"]


def test_certification_expiry_report(services: Services, store: DataStore, world: World) -> None:
    services.volunteers.add_certification(COORDINATOR, world.ana_id, "CPR", NOW.date() + timedelta(days=12))
    store.volunteers.save_certification(world.ben_id, Certification("Food Handler Card", date(2026, 10, 1)))
    store.volunteers.save_certification(world.ben_id, Certification("Forklift", date(2028, 1, 1)))  # out of range
    filters = ReportFilters(NOW.date(), NOW.date())
    report = services.reports.build(COORDINATOR, ReportKind.CERTIFICATION_EXPIRY, filters)
    assert [(row["item"], row["days_left"]) for row in report.rows] == [("Food Handler Card", -32), ("CPR", 12)]
    assert report.figures[0].value == "1" and report.figures[1].value == "1"
    assert not ReportKind.CERTIFICATION_EXPIRY.uses_period

    opportunity = store.opportunities.get(world.opportunity_id)
    opportunity.required_certifications = frozenset({"cpr"})
    store.opportunities.update(opportunity)
    scoped = services.reports.build(
        COORDINATOR, ReportKind.CERTIFICATION_EXPIRY, ReportFilters(NOW.date(), NOW.date(), world.opportunity_id)
    )
    assert [row["item"] for row in scoped.rows] == ["CPR"] and scoped.rows[0]["needed_by"] == "Food Pantry"


def test_only_leaders_record_credentials(services: Services, world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        services.volunteers.add_certification(
            volunteer_session(world.ana_id), world.ana_id, "CPR", NOW.date() + timedelta(days=90)
        )


def test_a_second_program_does_not_affect_waitlists_elsewhere(services: Services, store: DataStore) -> None:
    """Promotion is per shift: freeing a spot on one shift never signs anyone up for another."""
    program = store.opportunities.add(make_opportunity(title="Park Cleanup", required_skills=frozenset()))
    first = store.shifts.add(make_shift(program.opportunity_id or 0, datetime(2026, 11, 8, 9), capacity=1))
    second = store.shifts.add(make_shift(program.opportunity_id or 0, datetime(2026, 11, 15, 9), capacity=1))
    a = _add_person(store, "Ann", "404-555-0120")
    b = _add_person(store, "Bo", "404-555-0121")
    services.scheduling.sign_up(COORDINATOR, first.shift_id or 0, a)
    services.scheduling.sign_up(COORDINATOR, second.shift_id or 0, b)
    services.scheduling.join_waitlist(COORDINATOR, second.shift_id or 0, a)
    signup = store.assignments.find(first.shift_id or 0, a)
    services.scheduling.cancel(COORDINATOR, signup.assignment_id or 0)  # type: ignore[union-attr]
    assert store.assignments.find(second.shift_id or 0, a) is None
