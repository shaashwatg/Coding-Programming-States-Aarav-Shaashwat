"""
Input validation library — the first line of ServeSync's defensive programming.

Every validator follows the same contract:

1. Accept a *raw* value exactly as a user (or a file) supplied it.
2. Perform **syntactic** checks — is it shaped correctly?
   (e.g. "does this look like an email address?", "is this MM/DD/YYYY?")
3. Perform **semantic** checks — does it make sense in the real world?
   (e.g. "a birth date cannot be in the future", "911 is not an area code",
   "February 30 does not exist")
4. Return a *normalized* value (trimmed, lower-cased, canonical type) or raise
   :class:`InvalidInputError` with a friendly, specific message.

The FBLA rating sheet awards top marks for "input validation applied on both
syntactical and semantic levels," so each docstring states which checks are
which. Business rules that need the database (overlapping shifts, capacity)
live in the service layer; these validators are pure functions with no I/O,
which makes them fast and trivial to unit-test.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import date, datetime
from enum import Enum
from typing import Any, TypeVar, cast

from servesync.core.errors import ValidationError

T = TypeVar("T")
E = TypeVar("E", bound=Enum)


class InvalidInputError(ValueError):
    """Raised by a single validator; the message is shown directly to the user."""


# ---------------------------------------------------------------------------
# Error collection — lets a form report every bad field at once
# ---------------------------------------------------------------------------


class ErrorCollector:
    """
    Runs validators field-by-field and gathers every failure.

    Usage::

        errors = ErrorCollector()
        email = errors.check("email", clean_email, raw_email)
        phone = errors.check("phone", clean_phone, raw_phone)
        errors.raise_if_any()   # raises ValidationError listing both problems

    When a check fails, the *original* value is returned so the caller can keep
    going and collect the remaining errors; :meth:`raise_if_any` guarantees the
    half-validated values are never actually used.
    """

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}

    def check(self, field: str, validator: Callable[..., T], value: Any, *args: Any, **kwargs: Any) -> T:
        try:
            return validator(value, *args, **kwargs)
        except InvalidInputError as exc:
            self.add(field, str(exc))
            return cast(T, value)

    def add(self, field: str, message: str) -> None:
        """Record an error; only the first error for each field is kept."""
        self._errors.setdefault(field, message)

    @property
    def has_errors(self) -> bool:
        return bool(self._errors)

    def raise_if_any(self) -> None:
        if self._errors:
            raise ValidationError(self._errors)


def validate_field(field: str, validator: Callable[..., T], value: Any, *args: Any, **kwargs: Any) -> T:
    """Run one validator and convert its failure into a :class:`ValidationError`."""
    try:
        return validator(value, *args, **kwargs)
    except InvalidInputError as exc:
        raise ValidationError.single(field, str(exc)) from exc


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_WHITESPACE_RUN = re.compile(r"\s+")
# Control characters (except tab/newline/carriage return) sneak in through
# copy-paste from PDFs and spreadsheets and corrupt reports — strip them.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _as_text(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidInputError(f"{label} must be text.")
    return value


def clean_text(
    value: object,
    label: str,
    *,
    max_length: int,
    required: bool = True,
    multiline: bool = False,
) -> str:
    """
    Normalize free text.

    Syntactic: must be text; control characters removed; whitespace collapsed
    (single-line fields) or trimmed per line (multi-line fields).
    Semantic: required fields cannot be blank; length is capped so a pasted
    novel cannot break the layout of a printed report.
    """
    text = _CONTROL_CHARS.sub("", _as_text(value, label))
    if multiline:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        text = "\n".join(lines).strip()
    else:
        text = _WHITESPACE_RUN.sub(" ", text).strip()

    if required and not text:
        raise InvalidInputError(f"{label} is required.")
    if len(text) > max_length:
        raise InvalidInputError(f"{label} must be {max_length} characters or fewer (currently {len(text)}).")
    return text


# Letters from any alphabet, plus space, apostrophe, hyphen and period —
# supports names such as "O'Brien", "Mary-Kate", "José", and "St. John".
_NAME_PATTERN = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '\-.])*$")
NAME_MAX_LENGTH = 50


def clean_name(value: object, label: str = "Name") -> str:
    """
    Validate a person's first or last name.

    Syntactic: letters, spaces, apostrophes, hyphens and periods only; must
    start with a letter. Curly apostrophes are normalized to straight ones.
    Semantic: cannot end with a separator; length 1-50.
    """
    text = clean_text(value, label, max_length=NAME_MAX_LENGTH).replace("’", "'")
    if not _NAME_PATTERN.match(text):
        raise InvalidInputError(f"{label} can contain only letters, spaces, apostrophes, hyphens, and periods.")
    if text[-1] in " '-":
        raise InvalidInputError(f"{label} cannot end with a space, apostrophe, or hyphen.")
    return text


def clean_optional_name(value: object, label: str = "Name") -> str:
    """Like :func:`clean_name`, but blank is allowed (returns "")."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return clean_name(value, label)


# Letters plus the separators people actually write: "she/her", "they / them",
# "he, they", "ze/hir", "any pronouns".
_PRONOUN_PATTERN = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ /,'\-])*$")
PRONOUNS_MAX_LENGTH = 30


def clean_pronouns(value: object, label: str = "Pronouns") -> str:
    """
    Optional pronouns, written however the person writes them.

    Syntactic: letters with / , ' - or spaces between; spacing around slashes
    is tidied ("she / her" -> "she/her"). Semantic: 30 characters or fewer.
    The app never guesses or assigns pronouns; it only shows what a person shares.
    """
    text = clean_text(value, label, max_length=PRONOUNS_MAX_LENGTH, required=False)
    if not text:
        return ""
    text = re.sub(r"\s*/\s*", "/", text)
    if not _PRONOUN_PATTERN.match(text) or text[-1] in "/,'- ":
        raise InvalidInputError(f"{label} can contain letters with / or , between them, for example she/her.")
    return text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

_EMAIL_SHAPE = re.compile(r"^(?P<local>[A-Za-z0-9._%+\-]+)@(?P<domain>[A-Za-z0-9.\-]+)$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$")
EMAIL_MAX_LENGTH = 254  # RFC 5321 path limit
EMAIL_LOCAL_MAX_LENGTH = 64

# Frequent typos of popular providers — used for a gentle "Did you mean…?" hint.
_DOMAIN_TYPOS: dict[str, str] = {
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gamil.com": "gmail.com",
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "hotmial.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "iclod.com": "icloud.com",
}


def clean_email(value: object) -> str:
    """
    Validate and normalize an email address (returned lower-case).

    Syntactic: exactly one "@"; allowed characters only; domain has a dot.
    Semantic: RFC length limits; no leading/trailing/consecutive dots; each
    domain label is 1-63 characters and does not start or end with a hyphen;
    the top-level domain is alphabetic (".org", not ".123").
    """
    text = clean_text(value, "Email address", max_length=EMAIL_MAX_LENGTH).lower()
    if " " in text:
        raise InvalidInputError("Email address cannot contain spaces.")

    match = _EMAIL_SHAPE.match(text)
    if match is None:
        raise InvalidInputError("Email address must look like name@example.org.")

    local, domain = match.group("local"), match.group("domain")
    if len(local) > EMAIL_LOCAL_MAX_LENGTH:
        raise InvalidInputError("The part before the @ is too long (64 characters maximum).")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise InvalidInputError("Email address has a misplaced period before the @.")

    labels = domain.split(".")
    if len(labels) < 2:
        raise InvalidInputError("Email domain must include an ending such as .org or .com.")
    if any(not _DOMAIN_LABEL.match(label) for label in labels):
        raise InvalidInputError("Email domain is not valid (check for extra periods or hyphens).")
    top_level = labels[-1]
    if not top_level.isalpha() or len(top_level) < 2:
        raise InvalidInputError("Email domain must end with a real ending such as .org or .com.")
    return text


def suggest_email_correction(email: str) -> str | None:
    """
    Return a corrected address if the domain is a common typo, else ``None``.

    This is advisory only (the UI shows "Did you mean …?"), because a rare but
    legitimate domain must never be rejected outright.
    """
    local, _, domain = email.lower().partition("@")
    fix = _DOMAIN_TYPOS.get(domain)
    return f"{local}@{fix}" if fix else None


# ---------------------------------------------------------------------------
# Phone (North American Numbering Plan)
# ---------------------------------------------------------------------------

_PHONE_ALLOWED = re.compile(r"^[0-9\s().\-+]+$")


def clean_phone(value: object, label: str = "Phone number", *, required: bool = True) -> str:
    """
    Validate a U.S./Canada phone number and return its 10 digits.

    Syntactic: only digits, spaces, parentheses, periods, hyphens, and "+";
    10 digits, or 11 digits beginning with country code 1.
    Semantic: NANP rules — area code and exchange cannot start with 0 or 1,
    and N11 codes (211, 311, 411, 911 …) are service numbers, not area codes.
    Returns "" for an empty optional field.
    """
    text = clean_text(value, label, max_length=25, required=required)
    if not text:
        return ""
    if not _PHONE_ALLOWED.match(text):
        raise InvalidInputError(f"{label} can contain only digits, spaces, and ( ) - . + characters.")

    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise InvalidInputError(f"{label} must have 10 digits, for example (206) 555-0142.")

    area_code, exchange = digits[:3], digits[3:6]
    if area_code[0] in "01":
        raise InvalidInputError(f"{label}: area code {area_code} is not valid (it cannot start with 0 or 1).")
    if area_code[1:] == "11":
        raise InvalidInputError(f"{label}: {area_code} is a service code, not an area code.")
    if exchange[0] in "01":
        raise InvalidInputError(f"{label}: the three digits after the area code cannot start with 0 or 1.")
    return digits


def format_phone(digits: str) -> str:
    """Format 10 stored digits for display: ``2065550142`` -> ``(206) 555-0142``."""
    if len(digits) != 10 or not digits.isdigit():
        return digits
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


# ---------------------------------------------------------------------------
# Dates and times
# ---------------------------------------------------------------------------

_DATE_FORMATS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "%m/%d/%Y"),
)

# Patterns are matched after normalization: upper-case, "T" -> space, and a
# single space before AM/PM.
_DATETIME_FORMATS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}$"), "%Y-%m-%d %H:%M"),
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}:\d{2}$"), "%Y-%m-%d %H:%M:%S"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} [AP]M$"), "%m/%d/%Y %I:%M %p"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}$"), "%m/%d/%Y %H:%M"),
)
_MERIDIEM_SUFFIX = re.compile(r"\s*([AP]M)$")


def parse_date(value: object, label: str = "Date") -> date:
    """
    Parse a calendar date.

    Syntactic: accepts ``YYYY-MM-DD`` or ``MM/DD/YYYY`` (or a ``date`` object).
    Semantic: the date must exist (rejects 02/30/2026) and fall between 1900
    and 2100, which catches two-digit-year and keypad slips.
    """
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = clean_text(value, label, max_length=20)
        fmt = next((f for pattern, f in _DATE_FORMATS if pattern.match(text)), None)
        if fmt is None:
            raise InvalidInputError(f"{label} must be written as MM/DD/YYYY or YYYY-MM-DD.")
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError as exc:
            raise InvalidInputError(f"{label} '{text}' is not a real calendar date.") from exc

    if not 1900 <= parsed.year <= 2100:
        raise InvalidInputError(f"{label} must be between the years 1900 and 2100.")
    return parsed


def parse_datetime(value: object, label: str = "Date and time") -> datetime:
    """
    Parse a date and time to minute precision (seconds are dropped).

    Syntactic: ``YYYY-MM-DD HH:MM``, ``YYYY-MM-DDTHH:MM``, ``MM/DD/YYYY HH:MM``,
    or ``MM/DD/YYYY H:MM AM``.
    Semantic: the moment must exist and fall between 1900 and 2100. Time-zone
    aware values are converted to local time so every stored value compares
    consistently.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = clean_text(value, label, max_length=25)
        text = _MERIDIEM_SUFFIX.sub(r" \1", raw.upper().replace("T", " "))
        fmt = next((f for pattern, f in _DATETIME_FORMATS if pattern.match(text)), None)
        if fmt is None:
            raise InvalidInputError(f"{label} must be written like 2026-11-14 09:30 or 11/14/2026 9:30 AM.")
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError as exc:
            raise InvalidInputError(f"{label} '{raw}' is not a real date and time.") from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    if not 1900 <= parsed.year <= 2100:
        raise InvalidInputError(f"{label} must be between the years 1900 and 2100.")
    return parsed.replace(second=0, microsecond=0)


def calculate_age(birth_date: date, on: date) -> int:
    """Whole years between ``birth_date`` and ``on`` (birthday-aware)."""
    had_birthday = (on.month, on.day) >= (birth_date.month, birth_date.day)
    return on.year - birth_date.year - (0 if had_birthday else 1)


def validate_birth_date(value: object, *, minimum_age: int, as_of: date) -> date:
    """
    Validate a birth date for volunteer registration.

    Syntactic: any format accepted by :func:`parse_date`.
    Semantic: not in the future, not older than 120 years, and the volunteer
    is at least ``minimum_age`` on ``as_of`` (the date they joined).
    """
    born = parse_date(value, "Birth date")
    if born > as_of:
        raise InvalidInputError("Birth date cannot be after the date the volunteer joined.")
    age = calculate_age(born, as_of)
    if age > 120:
        raise InvalidInputError("Birth date is more than 120 years ago — please double-check the year.")
    if age < minimum_age:
        raise InvalidInputError(f"Volunteers must be at least {minimum_age} years old (this person was {age}).")
    return born


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_INTEGER_TEXT = re.compile(r"^[+-]?\d+$")


def parse_int(value: object, label: str, *, minimum: int, maximum: int) -> int:
    """
    Parse a whole number.

    Syntactic: an ``int`` or digit-only text (booleans and "3.5" are rejected).
    Semantic: must fall within ``minimum``..``maximum``.
    """
    if isinstance(value, bool):  # bool is a subclass of int — reject explicitly
        raise InvalidInputError(f"{label} must be a whole number.")
    if isinstance(value, int):
        number = value
    else:
        text = clean_text(value, label, max_length=12).replace(",", "")
        if not _INTEGER_TEXT.match(text):
            raise InvalidInputError(f"{label} must be a whole number.")
        number = int(text)
    if not minimum <= number <= maximum:
        raise InvalidInputError(f"{label} must be between {minimum} and {maximum}.")
    return number


def parse_hours(value: object, label: str = "Hours", *, maximum: float = 24.0) -> float:
    """
    Parse a number of service hours (rounded to two decimals).

    Syntactic: a number or numeric text such as "2.5".
    Semantic: finite, greater than zero, and no more than ``maximum``.
    """
    if isinstance(value, bool):
        raise InvalidInputError(f"{label} must be a number.")
    if isinstance(value, (int, float)):
        hours = float(value)
    else:
        text = clean_text(value, label, max_length=10)
        try:
            hours = float(text)
        except ValueError as exc:
            raise InvalidInputError(f"{label} must be a number such as 2 or 2.5.") from exc
    if not math.isfinite(hours):
        raise InvalidInputError(f"{label} must be a real number.")
    if hours <= 0:
        raise InvalidInputError(f"{label} must be greater than zero.")
    if hours > maximum:
        raise InvalidInputError(f"{label} cannot be more than {maximum:g}.")
    return round(hours, 2)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


def parse_enum(value: object, enum_type: type[E], label: str) -> E:
    """
    Convert user/database text to an enum member.

    Accepts a member, its value, or its name (case-insensitive).
    """
    if isinstance(value, enum_type):
        return value
    text = clean_text(value, label, max_length=40).upper().replace(" ", "_")
    for member in enum_type:
        if text in (str(member.value).upper(), member.name.upper()):
            return member
    raise InvalidInputError(f"'{value}' is not a valid {label.lower()}.")


# ---------------------------------------------------------------------------
# Web links
# ---------------------------------------------------------------------------

_URL_HOST = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")
URL_MAX_LENGTH = 300


def clean_url(value: object, label: str = "Link", *, required: bool = False) -> str:
    """
    Validate a web link (returned with an https:// prefix if none was typed).

    Syntactic: no spaces; a host name with a dot; at most 300 characters.
    Semantic: only http/https links are allowed, so a pasted ``javascript:``
    or ``file:`` link can never be opened from the app; the host must end in
    a real top-level domain such as .org.
    """
    text = clean_text(value, label, max_length=URL_MAX_LENGTH, required=required)
    if not text:
        return ""
    if " " in text:
        raise InvalidInputError(f"{label} cannot contain spaces.")
    if "://" not in text:
        if ":" in text.split("/")[0]:
            raise InvalidInputError(f"{label} must be a web address starting with https://.")
        text = f"https://{text}"
    scheme, _, rest = text.partition("://")
    if scheme.lower() not in ("http", "https"):
        raise InvalidInputError(f"{label} must be a web address starting with https://.")
    host = rest.split("/")[0].split("?")[0].split("#")[0].lower()
    if not _URL_HOST.match(host):
        raise InvalidInputError(f"{label} needs a real website address, such as https://example.org/story.")
    return f"{scheme.lower()}://{rest}"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

_USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9._\-]{2,29}$")
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


def clean_username(value: object) -> str:
    """
    Validate a sign-in name (returned lower-case).

    Syntactic: 3-30 characters; letters, digits, period, underscore, hyphen.
    Semantic: must start with a letter so it is never confused with an ID.
    """
    text = clean_text(value, "Username", max_length=30).lower()
    if not _USERNAME_PATTERN.match(text):
        raise InvalidInputError(
            "Username must be 3-30 characters, start with a letter, and use only "
            "letters, numbers, periods, underscores, or hyphens."
        )
    return text


def validate_password_strength(password: object, username: str = "") -> str:
    """
    Enforce the password policy (the password itself is never altered).

    Syntactic: 10-128 characters; no control characters.
    Semantic: contains a letter and a digit; is not one repeated character;
    does not contain the username.
    """
    if not isinstance(password, str):
        raise InvalidInputError("Password must be text.")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise InvalidInputError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise InvalidInputError(f"Password must be {PASSWORD_MAX_LENGTH} characters or fewer.")
    if _CONTROL_CHARS.search(password):
        raise InvalidInputError("Password contains characters that cannot be typed.")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise InvalidInputError("Password must include at least one letter and one number.")
    if len(set(password)) == 1:
        raise InvalidInputError("Password cannot be a single repeated character.")
    if len(username) >= 3 and username.lower() in password.lower():
        raise InvalidInputError("Password cannot contain your username.")
    return password
