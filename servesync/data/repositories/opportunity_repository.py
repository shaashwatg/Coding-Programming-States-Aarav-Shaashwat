"""Persistence for service opportunities and the skills they require."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from servesync.core.errors import RecordInUseError, RecordNotFoundError
from servesync.core.i18n import mark, tr
from servesync.data.converters import chunked, contains_pattern, placeholders
from servesync.data.database import Database
from servesync.data.repositories.base import Repository
from servesync.data.repositories.skill_repository import SkillRepository
from servesync.models import AccessNeed, Opportunity, OpportunityCategory, OpportunityStatus

_ENTITY = mark("Opportunity")

_SELECT_OPPORTUNITY = """
    SELECT opportunity_id, title, description, category, location, coordinator_name, min_age, status,
           story_video_url
    FROM opportunities
"""


class OpportunityRepository(Repository):
    def __init__(self, db: Database, skills: SkillRepository) -> None:
        super().__init__(db)
        self._skills = skills

    # ----------------------------------------------------------------- writes

    def add(self, opportunity: Opportunity) -> Opportunity:
        self._require_new(opportunity.opportunity_id, _ENTITY)
        with self._db.transaction():
            cursor = self._db.execute(
                """
                INSERT INTO opportunities (title, description, category, location, coordinator_name, min_age, status,
                                           story_video_url)
                VALUES (:title, :description, :category, :location, :coordinator_name, :min_age, :status,
                        :story_video_url)
                """,
                self._to_params(opportunity),
            )
            new_id = int(cursor.lastrowid or 0)
            self._write_required_skills(new_id, opportunity.required_skills)
            self._write_access_features(new_id, opportunity.access_features)
        # Re-read so callers get canonical values (e.g. existing skill spellings).
        return self.get(new_id)

    def update(self, opportunity: Opportunity) -> Opportunity:
        opportunity_id = self._require_saved(opportunity.opportunity_id, _ENTITY)
        with self._db.transaction():
            cursor = self._db.execute(
                """
                UPDATE opportunities
                SET title = :title, description = :description, category = :category,
                    location = :location, coordinator_name = :coordinator_name,
                    min_age = :min_age, status = :status, story_video_url = :story_video_url,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
                WHERE opportunity_id = :opportunity_id
                """,
                self._to_params(opportunity) | {"opportunity_id": opportunity_id},
            )
            if cursor.rowcount == 0:
                raise RecordNotFoundError(_ENTITY, opportunity_id)
            self._db.execute("DELETE FROM opportunity_skills WHERE opportunity_id = ?", (opportunity_id,))
            self._db.execute("DELETE FROM opportunity_access_features WHERE opportunity_id = ?", (opportunity_id,))
            self._write_required_skills(opportunity_id, opportunity.required_skills)
            self._write_access_features(opportunity_id, opportunity.access_features)
        return self.get(opportunity_id)

    def set_status(self, opportunity_id: int, status: OpportunityStatus) -> None:
        cursor = self._db.execute(
            """
            UPDATE opportunities
            SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
            WHERE opportunity_id = ?
            """,
            (status.value, opportunity_id),
        )
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, opportunity_id)

    def delete(self, opportunity_id: int) -> None:
        """Delete an opportunity (and its shifts) only if nobody ever signed up."""
        try:
            cursor = self._db.execute("DELETE FROM opportunities WHERE opportunity_id = ?", (opportunity_id,))
        except RecordInUseError as exc:
            raise RecordInUseError(
                tr(
                    "Volunteers have signed up for this opportunity, so its history is "
                    "kept. Set its status to Closed instead."
                )
            ) from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, opportunity_id)

    # ------------------------------------------------------------------ reads

    def get(self, opportunity_id: int) -> Opportunity:
        row = self._db.query_one(f"{_SELECT_OPPORTUNITY} WHERE opportunity_id = ?", (opportunity_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, opportunity_id)
        return self._hydrate([row])[0]

    def exists(self, opportunity_id: int) -> bool:
        return self._exists("opportunities", "opportunity_id", opportunity_id)

    def find_all(
        self,
        *,
        status: OpportunityStatus | None = None,
        category: OpportunityCategory | None = None,
        search: str = "",
    ) -> list[Opportunity]:
        """Opportunities matching every filter given, sorted by title."""
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if category is not None:
            clauses.append("category = ?")
            params.append(category.value)
        text = search.strip()
        if text:
            pattern = contains_pattern(text)
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.query_all(f"{_SELECT_OPPORTUNITY}{where} ORDER BY title COLLATE NOCASE", params)
        return self._hydrate(rows)

    def count_by_status(self) -> dict[OpportunityStatus, int]:
        counts = dict.fromkeys(OpportunityStatus, 0)
        for row in self._db.query_all("SELECT status, COUNT(*) AS total FROM opportunities GROUP BY status"):
            counts[OpportunityStatus(row["status"])] = row["total"]
        return counts

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_params(opportunity: Opportunity) -> dict[str, Any]:
        return {
            "title": opportunity.title,
            "description": opportunity.description,
            "category": opportunity.category.value,
            "location": opportunity.location,
            "coordinator_name": opportunity.coordinator_name,
            "min_age": opportunity.min_age,
            "status": opportunity.status.value,
            "story_video_url": opportunity.story_video_url,
        }

    def _write_required_skills(self, opportunity_id: int, skills: frozenset[str]) -> None:
        skill_ids = self._skills.ensure_ids(skills)
        self._db.execute_many(
            "INSERT INTO opportunity_skills (opportunity_id, skill_id) VALUES (?, ?)",
            [(opportunity_id, skill_id) for skill_id in skill_ids.values()],
        )

    def _write_access_features(self, opportunity_id: int, features: frozenset[AccessNeed]) -> None:
        self._db.execute_many(
            "INSERT INTO opportunity_access_features (opportunity_id, feature) VALUES (?, ?)",
            [(opportunity_id, feature.value) for feature in features],
        )

    def _hydrate(self, rows: Sequence[sqlite3.Row]) -> list[Opportunity]:
        ids = [row["opportunity_id"] for row in rows]
        skills: defaultdict[int, set[str]] = defaultdict(set)
        features: defaultdict[int, set[AccessNeed]] = defaultdict(set)
        for batch in chunked(ids):
            for feature_row in self._db.query_all(
                f"""SELECT opportunity_id, feature FROM opportunity_access_features
                    WHERE opportunity_id IN ({placeholders(batch)})""",
                tuple(batch),
            ):
                features[feature_row["opportunity_id"]].add(AccessNeed(feature_row["feature"]))
            for skill_row in self._db.query_all(
                f"""SELECT os.opportunity_id, sk.name FROM opportunity_skills AS os
                    JOIN skills AS sk ON sk.skill_id = os.skill_id
                    WHERE os.opportunity_id IN ({placeholders(batch)})""",
                tuple(batch),
            ):
                skills[skill_row["opportunity_id"]].add(skill_row["name"])
        return [
            Opportunity(
                title=row["title"],
                description=row["description"],
                category=OpportunityCategory(row["category"]),
                location=row["location"],
                coordinator_name=row["coordinator_name"],
                min_age=row["min_age"],
                status=OpportunityStatus(row["status"]),
                required_skills=frozenset(skills[row["opportunity_id"]]),
                story_video_url=row["story_video_url"],
                access_features=frozenset(features[row["opportunity_id"]]),
                opportunity_id=row["opportunity_id"],
            )
            for row in rows
        ]
