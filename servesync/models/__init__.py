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
    DayPart,
    MessageDuration,
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
    RosterEntry,
    ServiceFact,
    ServiceRecord,
    ShiftOverview,
    VolunteerParticipation,
)
from servesync.models.volunteer import AvailabilitySlot, Volunteer, access_gaps

__all__ = [
    "AccessNeed",
    "ActivityItem",
    "ActivityKind",
    "Appearance",
    "Assignment",
    "AssignmentStatus",
    "AvailabilitySlot",
    "DayPart",
    "MessageDuration",
    "Opportunity",
    "OpportunityCategory",
    "OpportunityStatus",
    "RecruitmentSource",
    "RosterEntry",
    "ServiceFact",
    "ServiceRecord",
    "Shift",
    "ShiftOverview",
    "Theme",
    "UserAccount",
    "UserRole",
    "Volunteer",
    "VolunteerParticipation",
    "VolunteerStatus",
    "Weekday",
    "access_gaps",
]
