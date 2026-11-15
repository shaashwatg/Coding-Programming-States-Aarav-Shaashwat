"""
Roles within a shift: "Registration x2, Water station x6".

A shift's spots are divided among its roles. Each role has its own capacity
and may require one skill (only people with that skill can take it). Every
shift has at least one role; a shift created without any gets one general
role, stored with an empty name and shown as "General" in either language.
"""

from __future__ import annotations

from dataclasses import dataclass

from servesync.config import MAX_SHIFT_CAPACITY
from servesync.core.i18n import tr
from servesync.core.validators import ErrorCollector, clean_text, parse_int
from servesync.models._common import SKILL_MAX_LENGTH, validate_optional_id

ROLE_NAME_MAX_LENGTH = 40
MAX_ROLES_PER_SHIFT = 12


@dataclass(slots=True)
class ShiftRole:
    """One kind of job on a shift, with how many people it needs."""

    name: str  # "" is the shift's general role
    capacity: int
    required_skill: str = ""  # "" = anyone can take it
    shift_id: int | None = None
    position: int = 0  # display order within the shift
    role_id: int | None = None

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        self.name = errors.check(
            "name", clean_text, self.name, tr("Role name"), max_length=ROLE_NAME_MAX_LENGTH, required=False
        )
        self.capacity = errors.check(
            "capacity", parse_int, self.capacity, tr("People needed"), minimum=1, maximum=MAX_SHIFT_CAPACITY
        )
        self.required_skill = errors.check(
            "required_skill",
            clean_text,
            self.required_skill,
            tr("Required skill"),
            max_length=SKILL_MAX_LENGTH,
            required=False,
        )
        self.shift_id = errors.check("shift_id", validate_optional_id, self.shift_id, tr("Shift ID"))
        self.position = errors.check("position", parse_int, self.position, tr("Order"), minimum=0, maximum=1000)
        self.role_id = errors.check("role_id", validate_optional_id, self.role_id, tr("Role ID"))
        errors.raise_if_any()

    @property
    def is_general(self) -> bool:
        return not self.name

    @property
    def display_name(self) -> str:
        """The name to show: the general role's name is translated; leaders' own names are kept as typed."""
        return self.name or tr("General")

    def fits(self, skills: frozenset[str]) -> bool:
        """True if someone with these skills may take this role."""
        if not self.required_skill:
            return True
        wanted = self.required_skill.casefold()
        return any(skill.casefold() == wanted for skill in skills)


@dataclass(frozen=True, slots=True)
class RoleOverview:
    """A role plus how many of its spots are taken."""

    role: ShiftRole
    filled: int

    @property
    def open_spots(self) -> int:
        return max(self.role.capacity - self.filled, 0)

    @property
    def is_full(self) -> bool:
        return self.filled >= self.role.capacity
