"""Validator tests — each group covers syntactic (format) and semantic (meaning) rules."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from servesync.core.errors import ValidationError
from servesync.core.validators import (
    ErrorCollector,
    InvalidInputError,
    calculate_age,
    clean_email,
    clean_name,
    clean_phone,
    clean_text,
    clean_username,
    format_phone,
    parse_date,
    parse_datetime,
    parse_enum,
    parse_hours,
    parse_int,
    suggest_email_correction,
    validate_birth_date,
    validate_field,
    validate_password_strength,
)
from servesync.models import VolunteerStatus

# ------------------------------------------------------------------- text


def test_clean_text_collapses_whitespace_and_strips_control_characters() -> None:
    assert clean_text("  Food \t\x07 Pantry  ", "Title", max_length=50) == "Food Pantry"


def test_clean_text_multiline_keeps_line_breaks() -> None:
    assert clean_text(" line one  \r\nline two ", "Notes", max_length=50, multiline=True) == "line one\nline two"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_clean_text_required_rejects_blank(value: object) -> None:
    with pytest.raises(InvalidInputError, match="required"):
        clean_text(value, "Title", max_length=10)


def test_clean_text_enforces_maximum_length() -> None:
    with pytest.raises(InvalidInputError, match="10 characters or fewer"):
        clean_text("x" * 11, "Title", max_length=10)


def test_clean_text_rejects_non_text() -> None:
    with pytest.raises(InvalidInputError, match="must be text"):
        clean_text(42, "Title", max_length=10)


# ------------------------------------------------------------------- names


@pytest.mark.parametrize("name", ["O'Brien", "Mary-Kate", "José", "St. John", "Nguyễn", "Ana María"])
def test_clean_name_accepts_real_world_names(name: str) -> None:
    assert clean_name(name) == name


def test_clean_name_normalizes_curly_apostrophe() -> None:
    assert clean_name("O’Connell") == "O'Connell"


@pytest.mark.parametrize("name", ["J0hn", "Ann@", "-Ann", "R2D2"])
def test_clean_name_rejects_bad_characters(name: str) -> None:  # syntactic
    with pytest.raises(InvalidInputError):
        clean_name(name)


def test_clean_name_rejects_trailing_separator() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="cannot end"):
        clean_name("Mary-")


# ------------------------------------------------------------------- email


def test_clean_email_normalizes_case() -> None:
    assert clean_email("  Ana.Lopez@Example.ORG ") == "ana.lopez@example.org"


@pytest.mark.parametrize(
    "email",
    ["plainaddress", "a@b", "two@@example.org", "space here@example.org", "a@example.c0m"],
)
def test_clean_email_rejects_malformed_addresses(email: str) -> None:  # syntactic
    with pytest.raises(InvalidInputError):
        clean_email(email)


@pytest.mark.parametrize(
    "email",
    [".ana@example.org", "ana.@example.org", "an..a@example.org", "ana@-example.org", "ana@example..org"],
)
def test_clean_email_rejects_misplaced_dots_and_hyphens(email: str) -> None:  # semantic
    with pytest.raises(InvalidInputError):
        clean_email(email)


def test_clean_email_enforces_local_part_length() -> None:  # semantic (RFC limit)
    with pytest.raises(InvalidInputError, match="too long"):
        clean_email("a" * 65 + "@example.org")


def test_suggest_email_correction_catches_common_typos() -> None:
    assert suggest_email_correction("sam@gmial.com") == "sam@gmail.com"
    assert suggest_email_correction("sam@example.org") is None


# ------------------------------------------------------------------- phone


@pytest.mark.parametrize("raw", ["(312) 555-0142", "312.555.0142", "312-555-0142", "+1 312 555 0142", "13125550142"])
def test_clean_phone_accepts_common_formats(raw: str) -> None:
    assert clean_phone(raw) == "3125550142"


def test_clean_phone_rejects_letters() -> None:  # syntactic
    with pytest.raises(InvalidInputError, match="only digits"):
        clean_phone("312-555-CALL")


def test_clean_phone_rejects_wrong_digit_count() -> None:  # syntactic
    with pytest.raises(InvalidInputError, match="10 digits"):
        clean_phone("555-0142")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("(012) 555-0142", "cannot start with 0 or 1"),
        ("(911) 555-0142", "service code"),
        ("(312) 155-0142", "cannot start"),
    ],
)
def test_clean_phone_applies_numbering_plan_rules(raw: str, reason: str) -> None:  # semantic
    with pytest.raises(InvalidInputError, match=reason):
        clean_phone(raw)


def test_clean_phone_optional_blank_is_allowed() -> None:
    assert clean_phone("", required=False) == ""


def test_format_phone() -> None:
    assert format_phone("3125550142") == "(312) 555-0142"
    assert format_phone("") == ""


# ------------------------------------------------------------- dates/times


@pytest.mark.parametrize("raw", ["2026-03-07", "03/07/2026", "3/7/2026"])
def test_parse_date_accepts_iso_and_us_formats(raw: str) -> None:
    assert parse_date(raw) == date(2026, 3, 7)


def test_parse_date_rejects_unknown_format() -> None:  # syntactic
    with pytest.raises(InvalidInputError, match="MM/DD/YYYY"):
        parse_date("March 7th")


def test_parse_date_rejects_impossible_calendar_date() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="not a real calendar date"):
        parse_date("02/30/2026")


def test_parse_date_rejects_out_of_range_year() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="1900 and 2100"):
        parse_date("01/01/0026")


@pytest.mark.parametrize(
    "raw",
    ["2026-11-14 09:30", "2026-11-14T09:30", "11/14/2026 9:30 AM", "11/14/2026 9:30am", "11/14/2026 09:30"],
)
def test_parse_datetime_formats(raw: str) -> None:
    assert parse_datetime(raw) == datetime(2026, 11, 14, 9, 30)


def test_parse_datetime_drops_seconds() -> None:
    assert parse_datetime(datetime(2026, 1, 1, 8, 15, 42, 99)) == datetime(2026, 1, 1, 8, 15)


def test_parse_datetime_rejects_impossible_time() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="not a real date and time"):
        parse_datetime("11/14/2026 13:30 PM")


def test_calculate_age_is_birthday_aware() -> None:
    assert calculate_age(date(2010, 6, 15), date(2026, 6, 14)) == 15
    assert calculate_age(date(2010, 6, 15), date(2026, 6, 15)) == 16


def test_birth_date_cannot_be_in_future() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="cannot be after"):
        validate_birth_date("2030-01-01", minimum_age=14, as_of=date(2026, 1, 1))


def test_birth_date_enforces_minimum_age() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="at least 14"):
        validate_birth_date("2015-01-01", minimum_age=14, as_of=date(2026, 1, 1))


def test_birth_date_rejects_implausible_age() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="120 years"):
        validate_birth_date("1901-01-01", minimum_age=14, as_of=date(2026, 1, 1))


# ----------------------------------------------------------------- numbers


def test_parse_int_accepts_text_with_commas() -> None:
    assert parse_int("1,200", "Count", minimum=0, maximum=5000) == 1200


@pytest.mark.parametrize("raw", ["3.5", "ten", True])
def test_parse_int_rejects_non_integers(raw: object) -> None:  # syntactic
    with pytest.raises(InvalidInputError, match="whole number"):
        parse_int(raw, "Count", minimum=0, maximum=10)


def test_parse_int_enforces_range() -> None:  # semantic
    with pytest.raises(InvalidInputError, match="between 1 and 10"):
        parse_int(11, "Count", minimum=1, maximum=10)


def test_parse_hours_rounds_to_two_decimals() -> None:
    assert parse_hours("2.555") == 2.56


@pytest.mark.parametrize(
    ("raw", "reason"), [("0", "greater than zero"), ("25", "more than 24"), ("nan", "real number")]
)
def test_parse_hours_rejects_unreasonable_values(raw: str, reason: str) -> None:  # semantic
    with pytest.raises(InvalidInputError, match=reason):
        parse_hours(raw)


# ------------------------------------------------------------------- enums


def test_parse_enum_accepts_value_name_and_case() -> None:
    assert parse_enum("active", VolunteerStatus, "Status") is VolunteerStatus.ACTIVE
    assert parse_enum(VolunteerStatus.INACTIVE, VolunteerStatus, "Status") is VolunteerStatus.INACTIVE


def test_parse_enum_rejects_unknown_value() -> None:
    with pytest.raises(InvalidInputError, match="not a valid"):
        parse_enum("retired", VolunteerStatus, "Status")


# ---------------------------------------------------------------- accounts


def test_clean_username() -> None:
    assert clean_username("  Jordan.Rivera ") == "jordan.rivera"
    with pytest.raises(InvalidInputError):
        clean_username("1jordan")


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short1", "at least 10"),
        ("onlyletters", "letter and one number"),
        ("1234567890", "letter and one number"),
        ("jordan2026xx", "cannot contain your username"),
    ],
)
def test_password_policy(password: str, reason: str) -> None:
    with pytest.raises(InvalidInputError, match=reason):
        validate_password_strength(password, username="jordan")


def test_password_policy_accepts_strong_password() -> None:
    assert validate_password_strength("Riverbend 2026 rocks", username="jordan") == "Riverbend 2026 rocks"


# ------------------------------------------------------- error collection


def test_error_collector_reports_every_bad_field() -> None:
    errors = ErrorCollector()
    errors.check("email", clean_email, "nope")
    errors.check("phone", clean_phone, "123")
    errors.check("name", clean_name, "Valid Name")
    with pytest.raises(ValidationError) as caught:
        errors.raise_if_any()
    assert set(caught.value.errors) == {"email", "phone"}


def test_validate_field_wraps_single_error() -> None:
    with pytest.raises(ValidationError) as caught:
        validate_field("email", clean_email, "nope")
    assert "email" in caught.value.errors


# -------------------------------------------------------------------- links


def test_clean_url_adds_https_and_keeps_path() -> None:
    from servesync.core.validators import clean_url

    assert clean_url("example.org/stories/pantry") == "https://example.org/stories/pantry"
    assert clean_url("HTTPS://Example.org/A") == "https://Example.org/A"
    assert clean_url("", required=False) == ""


@pytest.mark.parametrize(
    "bad", ["javascript:alert(1)", "file:///etc/passwd", "ftp://example.org", "http://localhost", "not a url"]
)
def test_clean_url_rejects_unsafe_or_fake_links(bad: str) -> None:
    from servesync.core.validators import clean_url

    with pytest.raises(InvalidInputError):
        clean_url(bad)
