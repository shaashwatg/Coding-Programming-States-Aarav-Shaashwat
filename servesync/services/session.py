"""
Signed-in sessions and role-based access control.

Every service method receives the caller's :class:`Session` and checks a
:class:`Permission` before doing anything. Checking in the service layer
(not just hiding buttons in the UI) means a volunteer can never reach a
leader-only action, no matter which screen or script calls it.

    Role          Permissions
    -----------   -----------------------------------------------------
    ADMIN         everything
    COORDINATOR   volunteers, opportunities, scheduling, attendance, reports
    VOLUNTEER     none of the above — but may act on *their own* record
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from servesync.core.errors import PermissionDeniedError
from servesync.models import UserRole


class Permission(Enum):
    MANAGE_VOLUNTEERS = auto()
    MANAGE_OPPORTUNITIES = auto()
    MANAGE_SCHEDULE = auto()
    RECORD_ATTENDANCE = auto()
    VIEW_REPORTS = auto()
    MANAGE_ACCOUNTS = auto()
    MANAGE_SETTINGS = auto()
    DELETE_RECORDS = auto()


_ACTION_TEXT: Mapping[Permission, str] = MappingProxyType(
    {
        Permission.MANAGE_VOLUNTEERS: "manage volunteer records",
        Permission.MANAGE_OPPORTUNITIES: "manage opportunities and shifts",
        Permission.MANAGE_SCHEDULE: "schedule other volunteers",
        Permission.RECORD_ATTENDANCE: "record attendance",
        Permission.VIEW_REPORTS: "view organization reports",
        Permission.MANAGE_ACCOUNTS: "manage sign-in accounts",
        Permission.MANAGE_SETTINGS: "change organization settings",
        Permission.DELETE_RECORDS: "permanently delete records",
    }
)

_LEADER_PERMISSIONS = frozenset(
    {
        Permission.MANAGE_VOLUNTEERS,
        Permission.MANAGE_OPPORTUNITIES,
        Permission.MANAGE_SCHEDULE,
        Permission.RECORD_ATTENDANCE,
        Permission.VIEW_REPORTS,
    }
)

#: Read-only mapping so no code can grant a role extra rights at runtime.
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = MappingProxyType(
    {
        UserRole.ADMIN: frozenset(Permission),
        UserRole.COORDINATOR: _LEADER_PERMISSIONS,
        UserRole.VOLUNTEER: frozenset(),
    }
)


@dataclass(frozen=True, slots=True)
class Session:
    """Who is signed in. Created by ``AuthService.sign_in``; immutable afterwards."""

    account_id: int
    username: str
    role: UserRole
    volunteer_id: int | None = None

    @property
    def is_leader(self) -> bool:
        return self.role.is_leader

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise PermissionDeniedError(f"Your role ({self.role.label}) is not allowed to {_ACTION_TEXT[permission]}.")

    def is_self(self, volunteer_id: int) -> bool:
        return self.volunteer_id is not None and self.volunteer_id == volunteer_id

    def require_self_or(self, permission: Permission, volunteer_id: int) -> None:
        """Allow a volunteer to act on their own record; otherwise require ``permission``."""
        if not self.is_self(volunteer_id):
            self.require(permission)
