"""
Skills catalogue shared by volunteers (skills they have) and opportunities
(skills they need). Stored once in ``skills`` and linked through junction
tables — a many-to-many relationship in third normal form.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from servesync.data.converters import chunked, placeholders
from servesync.data.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class SkillUsage:
    name: str
    volunteer_count: int
    opportunity_count: int


class SkillRepository(Repository):
    def list_names(self) -> list[str]:
        rows = self._db.query_all("SELECT name FROM skills ORDER BY name COLLATE NOCASE")
        return [row["name"] for row in rows]

    def ensure_ids(self, names: Iterable[str]) -> dict[str, int]:
        """
        Return ``{casefolded name: skill_id}``, creating any skills that are new.

        Matching is case-insensitive, so "first aid" reuses an existing
        "First Aid" instead of creating a near-duplicate.
        """
        unique = sorted({name for name in names if name})
        if not unique:
            return {}
        self._db.execute_many(
            "INSERT INTO skills (name) VALUES (?) ON CONFLICT (name) DO NOTHING",
            [(name,) for name in unique],
        )
        ids: dict[str, int] = {}
        for batch in chunked(unique):
            rows = self._db.query_all(
                f"SELECT skill_id, name FROM skills WHERE name IN ({placeholders(batch)})",
                tuple(batch),
            )
            ids.update({row["name"].casefold(): row["skill_id"] for row in rows})
        return ids

    def usage(self) -> list[SkillUsage]:
        """How many volunteers have, and opportunities need, each skill (for gap analysis)."""
        rows = self._db.query_all(
            """
            SELECT s.name,
                   (SELECT COUNT(*) FROM volunteer_skills   AS vs WHERE vs.skill_id = s.skill_id) AS volunteer_count,
                   (SELECT COUNT(*) FROM opportunity_skills AS os WHERE os.skill_id = s.skill_id) AS opportunity_count
            FROM skills AS s
            ORDER BY s.name COLLATE NOCASE
            """
        )
        return [SkillUsage(row["name"], row["volunteer_count"], row["opportunity_count"]) for row in rows]

    def delete_unused(self) -> int:
        """Remove skills nobody has or needs; returns how many were removed."""
        cursor = self._db.execute(
            """
            DELETE FROM skills
            WHERE skill_id NOT IN (SELECT skill_id FROM volunteer_skills)
              AND skill_id NOT IN (SELECT skill_id FROM opportunity_skills)
            """
        )
        return cursor.rowcount
