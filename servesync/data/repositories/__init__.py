"""Repositories: one class per aggregate, each owning its SQL."""

from servesync.data.repositories.account_repository import AccountRepository
from servesync.data.repositories.assignment_repository import AssignmentRepository
from servesync.data.repositories.opportunity_repository import OpportunityRepository
from servesync.data.repositories.preference_repository import PreferenceRepository
from servesync.data.repositories.settings_repository import SettingKey, SettingsRepository
from servesync.data.repositories.shift_repository import ShiftRepository
from servesync.data.repositories.skill_repository import SkillRepository, SkillUsage
from servesync.data.repositories.volunteer_repository import VolunteerRepository

__all__ = [
    "AccountRepository",
    "AssignmentRepository",
    "OpportunityRepository",
    "PreferenceRepository",
    "SettingKey",
    "SettingsRepository",
    "ShiftRepository",
    "SkillRepository",
    "SkillUsage",
    "VolunteerRepository",
]
