"""
User accounts and roles.

ServeSync serves two audiences named in the FBLA prompt:
organization leaders (ADMIN / COORDINATOR) and volunteers (VOLUNTEER, linked
to their own volunteer record for a self-service portal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from servesync.core.security import ALGORITHM
from servesync.core.validators import ErrorCollector, InvalidInputError, clean_username, parse_enum
from servesync.models._common import validate_optional_id
from servesync.models.enums import UserRole


def _require_hash(value: object) -> str:
    """Semantic guard: refuse anything that is not an encoded hash (never plain text)."""
    if not isinstance(value, str) or not value.startswith(f"{ALGORITHM}$") or value.count("$") != 3:
        raise InvalidInputError("Password must be stored as a secure hash.")
    return value


@dataclass(slots=True)
class UserAccount:
    """A sign-in identity. ``password_hash`` is hidden from ``repr`` and logs."""

    username: str
    password_hash: str = field(repr=False)
    role: UserRole
    volunteer_id: int | None = None
    is_active: bool = True
    failed_login_count: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    account_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        self.username = errors.check("username", clean_username, self.username)
        self.password_hash = errors.check("password", _require_hash, self.password_hash)
        self.role = errors.check("role", parse_enum, self.role, UserRole, "Role")
        self.volunteer_id = errors.check("volunteer_id", validate_optional_id, self.volunteer_id, "Volunteer")
        self.account_id = errors.check("account_id", validate_optional_id, self.account_id, "Account ID")
        if not isinstance(self.is_active, bool):
            errors.add("is_active", "Active flag must be true or false.")
        if (
            isinstance(self.failed_login_count, bool)
            or not isinstance(self.failed_login_count, int)
            or self.failed_login_count < 0
        ):
            errors.add("failed_login_count", "Failed sign-in count must be zero or more.")

        # Semantic: volunteer accounts must point at a volunteer; leaders must not.
        if self.role is UserRole.VOLUNTEER and self.volunteer_id is None:
            errors.add("volunteer_id", "A volunteer account must be linked to a volunteer record.")
        if isinstance(self.role, UserRole) and self.role.is_leader and self.volunteer_id is not None:
            errors.add("volunteer_id", "Leader accounts are not linked to a volunteer record.")
        errors.raise_if_any()

    def is_locked(self, now: datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or datetime.now())
