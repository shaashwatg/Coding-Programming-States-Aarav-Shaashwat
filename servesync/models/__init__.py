"""
Domain models — the vocabulary of the problem, independent of storage or UI.

Import from here so the rest of the program never depends on file layout::

    from servesync.models import Volunteer, Shift, AssignmentStatus
"""

from servesync.models.account import UserAccount
from servesync.models.assignment import Assignment
from servesync.models.enums import (
    AccessNeed,
    ActivityKind,
    AssignmentStatus,
    CredentialKind,
    DayPart,
    MessageDuration,
    NoticeKind,
    OpportunityCategory,
    OpportunityStatus,
    RecruitmentSource,
    Theme,
    UserRole,
    VolunteerStatus,
    Weekday,
)
from servesync.models.opportunity import Opportunity, Shift
from servesync.models.preferences import Appearance
from servesync.models.read_models import (
    ActivityItem,
    Notice,
    RosterEntry,
    ServiceFact,
    ServiceRecord,
    ShiftOverview,
    VolunteerParticipation,
    WaitlistEntry,
)
from servesync.models.role import RoleOverview, ShiftRole
from servesync.models.volunteer import AvailabilitySlot, Certification, Volunteer, access_gaps

__all__ = [
    "AccessNeed",
    "ActivityItem",
    "ActivityKind",
    "Appearance",
    "Assignment",
    "AssignmentStatus",
    "AvailabilitySlot",
    "Certification",
    "CredentialKind",
    "DayPart",
    "MessageDuration",
    "Notice",
    "NoticeKind",
    "Opportunity",
    "OpportunityCategory",
    "OpportunityStatus",
    "RecruitmentSource",
    "RoleOverview",
    "RosterEntry",
    "ServiceFact",
    "ServiceRecord",
    "Shift",
    "ShiftOverview",
    "ShiftRole",
    "Theme",
    "UserAccount",
    "UserRole",
    "Volunteer",
    "VolunteerParticipation",
    "VolunteerStatus",
    "WaitlistEntry",
    "Weekday",
    "access_gaps",
]
