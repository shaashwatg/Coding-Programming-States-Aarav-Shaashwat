"""
Application exception hierarchy.

Design rule: low-level exceptions (``sqlite3.IntegrityError``, ``ValueError``
and so on) never escape to the user interface. Each layer translates them
into one of these domain exceptions, and every one carries a message that is
safe and helpful to show to a non-technical nonprofit coordinator.

    ServeSyncError
    ├── ValidationError          bad user input (one or more fields)
    ├── RecordNotFoundError      an ID that does not exist
    ├── DuplicateRecordError     a UNIQUE rule would be broken
    ├── RecordInUseError         deleting would erase service history
    ├── BusinessRuleError        input is valid but the action is not allowed
    ├── PermissionDeniedError    the signed-in role may not do this
    ├── AuthenticationError      wrong username/password, locked account
    └── DataStoreError           the database itself failed (disk, corruption)
"""

from __future__ import annotations

from collections.abc import Mapping


class ServeSyncError(Exception):
    """Base class for every expected, user-presentable error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ValidationError(ServeSyncError):
    """
    One or more input fields are invalid.

    ``errors`` maps a field name (e.g. ``"email"``) to a human-readable
    message, so a form can highlight every bad field at once instead of making
    the user fix them one at a time.
    """

    def __init__(self, errors: Mapping[str, str]) -> None:
        if not errors:
            raise ValueError("ValidationError requires at least one field error.")
        self.errors: dict[str, str] = dict(errors)
        summary = "; ".join(self.errors.values())
        super().__init__(summary)

    @classmethod
    def single(cls, field: str, message: str) -> ValidationError:
        """Convenience constructor for a single-field error."""
        return cls({field: message})


class RecordNotFoundError(ServeSyncError):
    """A requested record (by ID or key) does not exist."""

    def __init__(self, entity: str, key: object) -> None:
        super().__init__(f"{entity} #{key} could not be found. It may have been removed.")
        self.entity = entity
        self.key = key


class DuplicateRecordError(ServeSyncError):
    """Saving would violate a uniqueness rule (e.g. two volunteers, one email)."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class RecordInUseError(ServeSyncError):
    """
    A delete was blocked because other records depend on this one.

    ServeSync never hard-deletes service history; leaders archive instead
    (e.g. mark a volunteer Inactive or close an opportunity).
    """


class BusinessRuleError(ServeSyncError):
    """Input is well-formed, but the requested action breaks a business rule."""


class PermissionDeniedError(ServeSyncError):
    """The signed-in user's role does not allow this action."""


class AuthenticationError(ServeSyncError):
    """Sign-in failed. The message never reveals which part was wrong."""


class DataStoreError(ServeSyncError):
    """The database could not complete an operation (disk full, locked, corrupt)."""
