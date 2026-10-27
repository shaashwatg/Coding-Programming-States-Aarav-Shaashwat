"""Domain model tests: objects validate themselves and enforce cross-field rules."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta

import pytest

from servesync.core.errors import ValidationError
from servesync.core.security import hash_password, needs_rehash, verify_password
from servesync.models import (
    Assignment,
    AssignmentStatus,
    AvailabilitySlot,
    DayPart,
    Shift,
    UserAccount,
    UserRole,
    VolunteerParticipation,
    VolunteerStatus,
    Weekday,
)
from tests.factories import FAST_ITERATIONS, fast_hash, make_opportunity, make_volunteer

# -------------------------------------------------------------- volunteer


def test_volunteer_normalizes_fields() -> None:
    volunteer = make_volunteer(email="ANA.Lopez@Example.org", skills=["cpr", "CPR", " Tutoring "])
    assert volunteer.email == "ana.lopez@example.org"
    assert volunteer.phone == "3125550142"
    assert volunteer.display_phone == "(312) 555-0142"
    assert volunteer.skills == frozenset({"cpr", "Tutoring"})


def test_volunteer_reports_all_invalid_fields_at_once() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(first_name="", email="bad", phone="911-555-0100")
    assert {"first_name", "email", "phone"} <= set(caught.value.errors)


def test_volunteer_must_meet_minimum_age_on_join_date() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(birth_date=date(2013, 1, 1), joined_on=date(2025, 1, 1))
    assert "birth_date" in caught.value.errors


def test_minor_requires_guardian_contact() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(birth_date=date(2009, 1, 1), joined_on=date(2025, 1, 1))
    assert "guardian" in caught.value.errors["emergency_contact_name"]

    minor = make_volunteer(
        birth_date=date(2009, 1, 1),
        joined_on=date(2025, 1, 1),
        emergency_contact_name="Rosa Lopez (parent)",
        emergency_contact_phone="312-555-0199",
    )
    assert minor.is_minor(on=date(2025, 1, 1))


def test_emergency_contact_needs_name_and_distinct_phone() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(emergency_contact_phone="(312) 555-0142")
    assert "emergency_contact_name" in caught.value.errors
    assert "emergency_contact_phone" in caught.value.errors


def test_join_date_cannot_be_in_future() -> None:
    with pytest.raises(ValidationError) as caught:
        make_volunteer(joined_on=date.today() + timedelta(days=1))
    assert "joined_on" in caught.value.errors


def test_replace_revalidates() -> None:
    volunteer = make_volunteer()
    with pytest.raises(ValidationError):
        dataclasses.replace(volunteer, email="not-an-email")


def test_availability_matching() -> None:
    volunteer = make_volunteer()
    saturday_morning = datetime(2026, 11, 14, 9, 0)  # a Saturday
    assert volunteer.is_available_at(saturday_morning)
    assert not volunteer.is_available_at(saturday_morning.replace(hour=14))


def test_day_part_classification() -> None:
    assert DayPart.from_hour(0) is DayPart.MORNING
    assert DayPart.from_hour(12) is DayPart.AFTERNOON
    assert DayPart.from_hour(17) is DayPart.EVENING
    with pytest.raises(ValueError):
        DayPart.from_hour(24)


def test_availability_slot_label_and_sorting() -> None:
    slots = [AvailabilitySlot(Weekday.SUNDAY, DayPart.MORNING), AvailabilitySlot(Weekday.MONDAY, DayPart.EVENING)]
    assert sorted(slots, key=lambda slot: slot.sort_key)[0].weekday is Weekday.MONDAY
    assert slots[0].label == "Sun Morning"


# ------------------------------------------------------------ opportunity


def test_opportunity_cannot_lower_minimum_age() -> None:
    with pytest.raises(ValidationError) as caught:
        make_opportunity(min_age=12)
    assert "min_age" in caught.value.errors


def test_opportunity_requires_meaningful_description() -> None:
    with pytest.raises(ValidationError) as caught:
        make_opportunity(description="Help")
    assert "description" in caught.value.errors


# ------------------------------------------------------------------ shift


def test_shift_end_must_follow_start() -> None:
    start = datetime(2026, 11, 14, 9, 0)
    with pytest.raises(ValidationError) as caught:
        Shift(1, start, start - timedelta(hours=1), 5)
    assert "after the start" in caught.value.errors["ends_at"]


def test_shift_length_limits_catch_am_pm_mistakes() -> None:
    start = datetime(2026, 11, 14, 9, 0)
    with pytest.raises(ValidationError, match="AM/PM"):
        Shift(1, start, start + timedelta(hours=13), 5)
    with pytest.raises(ValidationError, match="at least 15 minutes"):
        Shift(1, start, start + timedelta(minutes=10), 5)


def test_shift_capacity_bounds() -> None:
    start = datetime(2026, 11, 14, 9, 0)
    with pytest.raises(ValidationError):
        Shift(1, start, start + timedelta(hours=2), 0)


def test_shift_properties_and_overlap() -> None:
    start = datetime(2026, 11, 14, 9, 0)
    shift = Shift(1, start, start + timedelta(hours=3), 5)
    assert shift.duration_hours == 3.0
    assert shift.weekday is Weekday.SATURDAY
    assert shift.overlaps(start + timedelta(hours=2), start + timedelta(hours=4))
    assert not shift.overlaps(start + timedelta(hours=3), start + timedelta(hours=5))  # touching is fine


# ------------------------------------------------------------- assignment


def test_hours_only_when_attended() -> None:
    with pytest.raises(ValidationError, match="Enter the hours"):
        Assignment(1, 1, AssignmentStatus.ATTENDED)
    with pytest.raises(ValidationError, match="only be recorded"):
        Assignment(1, 1, AssignmentStatus.NO_SHOW, hours_served=2)
    assert Assignment(1, 1, "attended", "2.5").counted_hours == 2.5


def test_cancelled_assignment_frees_spot() -> None:
    assert not AssignmentStatus.CANCELLED.holds_a_spot
    assert AssignmentStatus.NO_SHOW.holds_a_spot


# ---------------------------------------------------------------- account


def test_account_refuses_plain_text_password() -> None:
    with pytest.raises(ValidationError) as caught:
        UserAccount(username="admin", password_hash="password123", role=UserRole.ADMIN)
    assert "password" in caught.value.errors


def test_account_role_and_volunteer_link_must_agree() -> None:
    with pytest.raises(ValidationError):
        UserAccount(username="vol", password_hash=fast_hash(), role=UserRole.VOLUNTEER)
    with pytest.raises(ValidationError):
        UserAccount(username="boss", password_hash=fast_hash(), role=UserRole.ADMIN, volunteer_id=3)


def test_account_repr_hides_hash() -> None:
    account = UserAccount(username="admin", password_hash=fast_hash(), role=UserRole.ADMIN)
    assert "pbkdf2" not in repr(account)


def test_account_lock_window() -> None:
    now = datetime(2026, 1, 1, 12, 0)
    account = UserAccount(
        username="admin", password_hash=fast_hash(), role=UserRole.ADMIN, locked_until=now + timedelta(minutes=5)
    )
    assert account.is_locked(now)
    assert not account.is_locked(now + timedelta(minutes=6))


# --------------------------------------------------------------- security


def test_password_hash_round_trip() -> None:
    encoded = hash_password("Riverbend2026", iterations=FAST_ITERATIONS)
    assert verify_password("Riverbend2026", encoded)
    assert not verify_password("riverbend2026", encoded)


def test_each_hash_uses_a_unique_salt() -> None:
    assert hash_password("same", iterations=FAST_ITERATIONS) != hash_password("same", iterations=FAST_ITERATIONS)


@pytest.mark.parametrize("bad", ["", "garbage", "pbkdf2_sha256$x$y$z", "md5$1$abc$def", "pbkdf2_sha256$0$AA==$AA=="])
def test_verify_password_never_crashes_on_malformed_hash(bad: str) -> None:
    assert verify_password("anything", bad) is False


def test_needs_rehash_detects_weaker_cost() -> None:
    assert needs_rehash(hash_password("x", iterations=FAST_ITERATIONS))
    assert needs_rehash("garbage")


# ------------------------------------------------------------ read models


def test_reliability_is_none_without_history() -> None:
    base = VolunteerParticipation(1, "Ana Lopez", VolunteerStatus.ACTIVE, 0.0, 0, 0, 0, 0, None)
    assert base.reliability is None
    assert dataclasses.replace(base, shifts_attended=9, no_shows=1).reliability == 0.9
