"""Repository tests against a real (in-memory) SQLite database."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from servesync.core.errors import (
    DuplicateRecordError,
    RecordInUseError,
    RecordNotFoundError,
    ValidationError,
)
from servesync.data import DataStore
from servesync.models import (
    Assignment,
    AssignmentStatus,
    AvailabilitySlot,
    DayPart,
    OpportunityStatus,
    Theme,
    UserAccount,
    UserRole,
    VolunteerStatus,
    Weekday,
)
from tests.factories import fast_hash, make_opportunity, make_shift, make_volunteer

SATURDAY_9AM = datetime(2026, 11, 14, 9, 0)


def _int(value: int | None) -> int:
    assert value is not None
    return value


# --------------------------------------------------------------- volunteers


def test_add_and_get_volunteer_round_trip(store: DataStore) -> None:
    saved = store.volunteers.add(make_volunteer(notes="Prefers outdoor work."))
    loaded = store.volunteers.get(_int(saved.volunteer_id))
    assert loaded == saved
    assert loaded.skills == {"Tutoring", "Spanish"}
    assert loaded.availability == {AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING)}


def test_skill_names_are_shared_case_insensitively(store: DataStore) -> None:
    store.volunteers.add(make_volunteer(skills={"First Aid"}))
    second = store.volunteers.add(make_volunteer(email="b@example.org", skills={"first aid"}))
    assert second.skills == {"First Aid"}  # canonical spelling reused
    assert store.skills.list_names() == ["First Aid"]


def test_duplicate_email_becomes_field_error(store: DataStore) -> None:
    store.volunteers.add(make_volunteer())
    with pytest.raises(ValidationError) as caught:
        store.volunteers.add(make_volunteer(email="ANA.LOPEZ@example.org", first_name="Other"))
    assert "already uses this email" in caught.value.errors["email"]


def test_update_replaces_skills_and_availability(store: DataStore) -> None:
    saved = store.volunteers.add(make_volunteer())
    changed = store.volunteers.update(
        make_volunteer(
            volunteer_id=saved.volunteer_id,
            skills={"Driving"},
            availability={AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING)},
        )
    )
    assert changed.skills == {"Driving"}
    assert changed.availability == {AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING)}


def test_update_missing_volunteer_raises_not_found(store: DataStore) -> None:
    with pytest.raises(RecordNotFoundError):
        store.volunteers.update(make_volunteer(volunteer_id=999))


def test_add_rejects_already_saved_record(store: DataStore) -> None:
    saved = store.volunteers.add(make_volunteer())
    with pytest.raises(ValueError, match="already saved"):
        store.volunteers.add(saved)


def test_find_all_filters(store: DataStore) -> None:
    store.volunteers.add(make_volunteer())
    store.volunteers.add(
        make_volunteer(
            first_name="Ben",
            last_name="Brooks",
            email="ben@example.org",
            phone="404-555-0101",
            status=VolunteerStatus.APPLICANT,
            skills={"Driving"},
            availability={AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING)},
        )
    )
    assert [v.first_name for v in store.volunteers.find_all()] == ["Ben", "Ana"]  # sorted by last name
    assert [v.first_name for v in store.volunteers.find_all(status=VolunteerStatus.APPLICANT)] == ["Ben"]
    assert [v.first_name for v in store.volunteers.find_all(skill="driving")] == ["Ben"]
    assert [v.first_name for v in store.volunteers.find_all(search="ana lo")] == ["Ana"]
    assert [v.first_name for v in store.volunteers.find_all(search="404555")] == ["Ben"]
    slot = AvailabilitySlot(Weekday.SATURDAY, DayPart.MORNING)
    assert [v.first_name for v in store.volunteers.find_all(available_in=slot)] == ["Ana"]


def test_search_treats_wildcards_literally(store: DataStore) -> None:
    store.volunteers.add(make_volunteer())
    assert store.volunteers.find_all(search="%") == []
    assert store.volunteers.find_all(search="_") == []


def test_search_is_injection_safe(store: DataStore) -> None:
    store.volunteers.add(make_volunteer())
    assert store.volunteers.find_all(search="'; DROP TABLE volunteers; --") == []
    assert len(store.volunteers.find_all()) == 1


def test_count_by_status_includes_zero_counts(store: DataStore) -> None:
    store.volunteers.add(make_volunteer())
    assert store.volunteers.count_by_status() == {
        VolunteerStatus.APPLICANT: 0,
        VolunteerStatus.ACTIVE: 1,
        VolunteerStatus.INACTIVE: 0,
    }


def test_delete_volunteer_without_history(store: DataStore) -> None:
    saved = store.volunteers.add(make_volunteer())
    store.volunteers.delete(_int(saved.volunteer_id))
    assert not store.volunteers.exists(_int(saved.volunteer_id))
    with pytest.raises(RecordNotFoundError):
        store.volunteers.delete(_int(saved.volunteer_id))


# ---------------------------------------------- opportunities and shifts


def test_opportunity_round_trip_and_status(store: DataStore) -> None:
    saved = store.opportunities.add(make_opportunity())
    opportunity_id = _int(saved.opportunity_id)
    store.opportunities.set_status(opportunity_id, OpportunityStatus.CLOSED)
    assert store.opportunities.get(opportunity_id).status is OpportunityStatus.CLOSED
    assert store.opportunities.find_all(search="grocer")[0].opportunity_id == opportunity_id
    assert store.opportunities.count_by_status()[OpportunityStatus.CLOSED] == 1


def test_shift_requires_existing_opportunity(store: DataStore) -> None:
    with pytest.raises(RecordNotFoundError):
        store.shifts.add(make_shift(42, SATURDAY_9AM))


def test_shift_overview_reports_fill(store: DataStore) -> None:
    opportunity = store.opportunities.add(make_opportunity())
    shift = store.shifts.add(make_shift(_int(opportunity.opportunity_id), SATURDAY_9AM, capacity=2))
    volunteer = store.volunteers.add(make_volunteer())
    store.assignments.add(Assignment(_int(shift.shift_id), _int(volunteer.volunteer_id)))

    overview = store.shifts.get_overview(_int(shift.shift_id))
    assert (overview.filled, overview.open_spots, overview.is_full) == (1, 1, False)
    assert overview.opportunity_title == "Food Pantry"
    assert len(store.shifts.overviews(only_with_openings=True)) == 1


def test_cancelled_signups_do_not_hold_spots(store: DataStore) -> None:
    opportunity = store.opportunities.add(make_opportunity())
    shift = store.shifts.add(make_shift(_int(opportunity.opportunity_id), SATURDAY_9AM, capacity=1))
    volunteer = store.volunteers.add(make_volunteer())
    signup = store.assignments.add(Assignment(_int(shift.shift_id), _int(volunteer.volunteer_id)))
    store.assignments.update(
        Assignment(
            signup.shift_id,
            signup.volunteer_id,
            AssignmentStatus.CANCELLED,
            assignment_id=signup.assignment_id,
            signed_up_at=signup.signed_up_at,
        )
    )
    assert store.shifts.count_filled(_int(shift.shift_id)) == 0


def test_overviews_filter_by_date_window(store: DataStore) -> None:
    opportunity_id = _int(store.opportunities.add(make_opportunity()).opportunity_id)
    for week in range(3):
        store.shifts.add(make_shift(opportunity_id, SATURDAY_9AM + timedelta(weeks=week)))
    window = store.shifts.overviews(starts_after=SATURDAY_9AM + timedelta(days=1), limit=10)
    assert [o.shift.starts_at for o in window] == [SATURDAY_9AM + timedelta(weeks=1), SATURDAY_9AM + timedelta(weeks=2)]


# ------------------------------------------------------------ assignments


@pytest.fixture
def scheduled(store: DataStore) -> tuple[int, int, int]:
    """(opportunity_id, shift_id, volunteer_id) with one sign-up."""
    opportunity_id = _int(store.opportunities.add(make_opportunity()).opportunity_id)
    shift_id = _int(store.shifts.add(make_shift(opportunity_id, SATURDAY_9AM)).shift_id)
    volunteer_id = _int(store.volunteers.add(make_volunteer()).volunteer_id)
    store.assignments.add(Assignment(shift_id, volunteer_id))
    return opportunity_id, shift_id, volunteer_id


def test_duplicate_signup_is_rejected(store: DataStore, scheduled: tuple[int, int, int]) -> None:
    _, shift_id, volunteer_id = scheduled
    with pytest.raises(DuplicateRecordError, match="already signed up"):
        store.assignments.add(Assignment(shift_id, volunteer_id))


def test_signup_requires_existing_records(store: DataStore, scheduled: tuple[int, int, int]) -> None:
    _, shift_id, volunteer_id = scheduled
    with pytest.raises(RecordNotFoundError, match="Volunteer"):
        store.assignments.add(Assignment(shift_id, 999))
    with pytest.raises(RecordNotFoundError, match="Shift"):
        store.assignments.add(Assignment(999, volunteer_id))


def test_history_blocks_deletes(store: DataStore, scheduled: tuple[int, int, int]) -> None:
    opportunity_id, shift_id, volunteer_id = scheduled
    with pytest.raises(RecordInUseError, match="Inactive"):
        store.volunteers.delete(volunteer_id)
    with pytest.raises(RecordInUseError):
        store.shifts.delete(shift_id)
    with pytest.raises(RecordInUseError, match="Closed"):
        store.opportunities.delete(opportunity_id)
    # Nothing was removed by the failed attempts.
    assert store.volunteers.exists(volunteer_id) and store.shifts.exists(shift_id)


def test_conflict_detection(store: DataStore, scheduled: tuple[int, int, int]) -> None:
    _, shift_id, volunteer_id = scheduled  # booked 9:00-12:00
    overlapping = store.assignments.conflicting_shifts(
        volunteer_id, SATURDAY_9AM + timedelta(hours=2), SATURDAY_9AM + timedelta(hours=4)
    )
    assert [s.shift_id for s in overlapping] == [shift_id]
    touching = store.assignments.conflicting_shifts(
        volunteer_id, SATURDAY_9AM + timedelta(hours=3), SATURDAY_9AM + timedelta(hours=5)
    )
    assert touching == []
    excluded = store.assignments.conflicting_shifts(
        volunteer_id, SATURDAY_9AM, SATURDAY_9AM + timedelta(hours=1), exclude_shift_id=shift_id
    )
    assert excluded == []


def test_attendance_hours_flow_into_totals(store: DataStore, scheduled: tuple[int, int, int]) -> None:
    _, shift_id, volunteer_id = scheduled
    signup = store.assignments.find(shift_id, volunteer_id)
    assert signup is not None
    store.assignments.update(
        Assignment(
            shift_id,
            volunteer_id,
            AssignmentStatus.ATTENDED,
            2.75,
            signed_up_at=signup.signed_up_at,
            assignment_id=signup.assignment_id,
        )
    )
    assert store.assignments.total_hours() == 2.75
    assert (
        store.assignments.total_hours(volunteer_id=volunteer_id, start=date(2026, 11, 14), end=date(2026, 11, 14))
        == 2.75
    )
    assert store.assignments.total_hours(start=date(2026, 11, 15)) == 0.0

    stats = store.volunteers.get_participation(volunteer_id)
    assert (stats.total_hours, stats.shifts_attended, stats.reliability) == (2.75, 1, 1.0)
    assert store.assignments.roster(shift_id)[0].volunteer_name == "Ana Lopez"
    assert store.assignments.history(volunteer_id)[0].opportunity_title == "Food Pantry"


# ---------------------------------------------------------------- accounts


def test_account_lookup_is_case_insensitive(store: DataStore) -> None:
    store.accounts.add(UserAccount(username="admin", password_hash=fast_hash(), role=UserRole.ADMIN))
    found = store.accounts.find_by_username("ADMIN ")
    assert found is not None and found.role is UserRole.ADMIN
    with pytest.raises(ValidationError, match="taken"):
        store.accounts.add(UserAccount(username="Admin", password_hash=fast_hash(), role=UserRole.COORDINATOR))


def test_volunteer_account_link(store: DataStore) -> None:
    volunteer_id = _int(store.volunteers.add(make_volunteer()).volunteer_id)
    store.accounts.add(
        UserAccount(username="ana", password_hash=fast_hash(), role=UserRole.VOLUNTEER, volunteer_id=volunteer_id)
    )
    assert store.accounts.find_by_volunteer(volunteer_id) is not None
    with pytest.raises(ValidationError, match="already has an account"):
        store.accounts.add(
            UserAccount(username="ana2", password_hash=fast_hash(), role=UserRole.VOLUNTEER, volunteer_id=volunteer_id)
        )
    with pytest.raises(RecordNotFoundError):
        store.accounts.add(
            UserAccount(username="ghost", password_hash=fast_hash(), role=UserRole.VOLUNTEER, volunteer_id=999)
        )


def test_login_bookkeeping(store: DataStore) -> None:
    account = store.accounts.add(UserAccount(username="admin", password_hash=fast_hash(), role=UserRole.ADMIN))
    account_id = _int(account.account_id)
    lock = datetime(2030, 1, 1, 12, 0)
    store.accounts.record_failed_login(account_id, locked_until=None)
    store.accounts.record_failed_login(account_id, locked_until=lock)
    locked = store.accounts.get(account_id)
    assert (locked.failed_login_count, locked.locked_until) == (2, lock)

    store.accounts.record_successful_login(account_id, datetime(2026, 1, 1, 9, 0))
    cleared = store.accounts.get(account_id)
    assert (cleared.failed_login_count, cleared.locked_until) == (0, None)
    assert store.accounts.count_active(UserRole.ADMIN) == 1
    store.accounts.set_active(account_id, False)
    assert store.accounts.count_active(UserRole.ADMIN) == 0


# ---------------------------------------------------------------- settings


def test_settings_validate_and_persist(store: DataStore) -> None:
    assert store.settings.set_volunteer_hour_value("$34.67") == 34.67
    assert store.settings.volunteer_hour_value() == 34.67
    with pytest.raises(ValidationError):
        store.settings.set_volunteer_hour_value("free")
    with pytest.raises(ValidationError):
        store.settings.set_font_scale(5)
    store.settings.set_font_scale(1.25)
    store.settings.set_theme("high_contrast")
    assert store.settings.font_scale() == 1.25
    assert store.settings.theme() is Theme.HIGH_CONTRAST


def test_corrupted_setting_falls_back_to_default(store: DataStore) -> None:
    store.db.execute("UPDATE app_settings SET value = 'oops' WHERE key = 'ui_font_scale'")
    store.db.execute("UPDATE app_settings SET value = 'NEON' WHERE key = 'ui_theme'")
    assert store.settings.font_scale() == 1.0
    assert store.settings.theme() is Theme.LIGHT
