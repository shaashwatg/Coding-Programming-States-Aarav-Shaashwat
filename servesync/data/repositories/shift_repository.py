"""Persistence for shifts plus the schedule-oriented ``ShiftOverview`` queries."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from typing import Any

from servesync.core.errors import RecordInUseError, RecordNotFoundError
from servesync.core.i18n import mark, tr
from servesync.data.converters import datetime_from_db, datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.models import OpportunityCategory, OpportunityStatus, RoleOverview, Shift, ShiftOverview, ShiftRole

_ENTITY = mark("Shift")

_SELECT_SHIFT = "SELECT shift_id, opportunity_id, starts_at, ends_at, capacity, notes, impact_amount FROM shifts"

_SELECT_ROLES = """
    SELECT r.role_id, r.shift_id, r.name, r.capacity, r.required_skill, r.position,
           COUNT(a.assignment_id) AS filled
    FROM shift_roles AS r
    LEFT JOIN assignments AS a ON a.role_id = r.role_id AND a.status <> 'CANCELLED'
"""

_SELECT_OVERVIEW = """
    SELECT s.shift_id, s.opportunity_id, s.starts_at, s.ends_at, s.capacity, s.notes, s.impact_amount,
           o.title AS opportunity_title, o.category, o.location, o.status AS opportunity_status,
           f.filled
    FROM shifts AS s
    JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
    JOIN shift_fill    AS f ON f.shift_id = s.shift_id
"""


class ShiftRepository(Repository):
    # ----------------------------------------------------------------- writes

    def add(self, shift: Shift) -> Shift:
        self._require_new(shift.shift_id, _ENTITY)
        with self._db.transaction():
            if not self._exists("opportunities", "opportunity_id", shift.opportunity_id):
                raise RecordNotFoundError(tr("Opportunity"), shift.opportunity_id)
            cursor = self._db.execute(
                """
                INSERT INTO shifts (opportunity_id, starts_at, ends_at, capacity, notes)
                VALUES (:opportunity_id, :starts_at, :ends_at, :capacity, :notes)
                """,
                self._to_params(shift),
            )
            shift_id = int(cursor.lastrowid or 0)
            # Every shift has at least one role, so every sign-up has a role to fill.
            self._db.execute(
                "INSERT INTO shift_roles (shift_id, name, capacity) VALUES (?, '', ?)", (shift_id, shift.capacity)
            )
        return dataclasses.replace(shift, shift_id=shift_id)

    def update(self, shift: Shift) -> Shift:
        shift_id = self._require_saved(shift.shift_id, _ENTITY)
        with self._db.transaction():
            if not self._exists("opportunities", "opportunity_id", shift.opportunity_id):
                raise RecordNotFoundError(tr("Opportunity"), shift.opportunity_id)
            cursor = self._db.execute(
                """
                UPDATE shifts
                SET opportunity_id = :opportunity_id, starts_at = :starts_at, ends_at = :ends_at,
                    capacity = :capacity, notes = :notes,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
                WHERE shift_id = :shift_id
                """,
                self._to_params(shift) | {"shift_id": shift_id},
            )
            if cursor.rowcount == 0:
                raise RecordNotFoundError(_ENTITY, shift_id)
        return shift

    def replace_roles(self, shift_id: int, roles: list[ShiftRole]) -> list[RoleOverview]:
        """
        Make ``roles`` the shift's roles, in order, and set the shift's capacity to their total.

        Roles with a ``role_id`` are updated, new ones are added, and missing ones are
        removed. The service has already checked that no current sign-up is in a removed
        role; cancelled sign-ups that pointed at one move to the first remaining role, so
        their history is kept.
        """
        with self._db.transaction():
            current = {overview.role.role_id for overview in self.roles(shift_id)}
            kept: list[int] = []
            for position, role in enumerate(roles):
                params = {
                    "shift_id": shift_id,
                    "name": role.name,
                    "capacity": role.capacity,
                    "required_skill": role.required_skill,
                    "position": position,
                }
                if role.role_id in current:
                    self._db.execute(
                        """UPDATE shift_roles SET name = :name, capacity = :capacity,
                           required_skill = :required_skill, position = :position
                           WHERE role_id = :role_id AND shift_id = :shift_id""",
                        params | {"role_id": role.role_id},
                    )
                    kept.append(role.role_id or 0)
                else:
                    cursor = self._db.execute(
                        """INSERT INTO shift_roles (shift_id, name, capacity, required_skill, position)
                           VALUES (:shift_id, :name, :capacity, :required_skill, :position)""",
                        params,
                    )
                    kept.append(int(cursor.lastrowid or 0))
            for removed in current - set(kept):
                self._db.execute("UPDATE assignments SET role_id = ? WHERE role_id = ?", (kept[0], removed))
                self._db.execute("DELETE FROM shift_roles WHERE role_id = ?", (removed,))
            self._db.execute(
                "UPDATE shifts SET capacity = ? WHERE shift_id = ?", (sum(role.capacity for role in roles), shift_id)
            )
        return self.roles(shift_id)

    def set_single_role_capacity(self, shift_id: int, capacity: int) -> None:
        """Keep a one-role shift's role the same size as the shift (used when a shift is resized)."""
        self._db.execute("UPDATE shift_roles SET capacity = ? WHERE shift_id = ?", (capacity, shift_id))

    def set_impact(self, shift_id: int, amount: int) -> Shift:
        cursor = self._db.execute("UPDATE shifts SET impact_amount = ? WHERE shift_id = ?", (amount, shift_id))
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, shift_id)
        return self.get(shift_id)

    def delete(self, shift_id: int) -> None:
        """Delete a shift only if nobody has signed up for it."""
        try:
            cursor = self._db.execute("DELETE FROM shifts WHERE shift_id = ?", (shift_id,))
        except RecordInUseError as exc:
            raise RecordInUseError(
                tr(
                    "Volunteers have signed up for this shift. Cancel their sign-ups "
                    "first, or keep the shift for the record."
                )
            ) from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, shift_id)

    # ------------------------------------------------------------------ reads

    def get(self, shift_id: int) -> Shift:
        row = self._db.query_one(f"{_SELECT_SHIFT} WHERE shift_id = ?", (shift_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, shift_id)
        return self._to_shift(row)

    def exists(self, shift_id: int) -> bool:
        return self._exists("shifts", "shift_id", shift_id)

    def for_opportunity(self, opportunity_id: int) -> list[Shift]:
        rows = self._db.query_all(f"{_SELECT_SHIFT} WHERE opportunity_id = ? ORDER BY starts_at", (opportunity_id,))
        return [self._to_shift(row) for row in rows]

    def roles(self, shift_id: int) -> list[RoleOverview]:
        """The shift's roles in display order, each with how many spots are taken."""
        rows = self._db.query_all(
            f"{_SELECT_ROLES} WHERE r.shift_id = ? GROUP BY r.role_id ORDER BY r.position, r.role_id", (shift_id,)
        )
        return [self._to_role(row) for row in rows]

    def get_role(self, role_id: int) -> RoleOverview:
        row = self._db.query_one(f"{_SELECT_ROLES} WHERE r.role_id = ? GROUP BY r.role_id", (role_id,))
        if row is None:
            raise RecordNotFoundError(tr("Role"), role_id)
        return self._to_role(row)

    def count_filled(self, shift_id: int) -> int:
        """Sign-ups currently holding a spot (everything except cancellations)."""
        return int(self._db.query_value("SELECT filled FROM shift_fill WHERE shift_id = ?", (shift_id,), default=0))

    def get_overview(self, shift_id: int) -> ShiftOverview:
        row = self._db.query_one(f"{_SELECT_OVERVIEW} WHERE s.shift_id = ?", (shift_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, shift_id)
        return self._to_overview(row)

    def overviews(
        self,
        *,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        opportunity_id: int | None = None,
        opportunity_status: OpportunityStatus | None = None,
        only_with_openings: bool = False,
        limit: int | None = None,
    ) -> list[ShiftOverview]:
        """Schedule rows (shift + opportunity + fill count) in chronological order."""
        clauses: list[str] = []
        params: list[Any] = []
        if starts_after is not None:
            clauses.append("s.starts_at >= ?")
            params.append(datetime_to_db(starts_after))
        if starts_before is not None:
            clauses.append("s.starts_at < ?")
            params.append(datetime_to_db(starts_before))
        if opportunity_id is not None:
            clauses.append("s.opportunity_id = ?")
            params.append(opportunity_id)
        if opportunity_status is not None:
            clauses.append("o.status = ?")
            params.append(opportunity_status.value)
        if only_with_openings:
            clauses.append("f.filled < s.capacity")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"{_SELECT_OVERVIEW}{where} ORDER BY s.starts_at, o.title COLLATE NOCASE"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(int(limit), 0))
        return [self._to_overview(row) for row in self._db.query_all(sql, params)]

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _to_params(shift: Shift) -> dict[str, Any]:
        return {
            "opportunity_id": shift.opportunity_id,
            "starts_at": datetime_to_db(shift.starts_at),
            "ends_at": datetime_to_db(shift.ends_at),
            "capacity": shift.capacity,
            "notes": shift.notes,
        }

    @staticmethod
    def _to_shift(row: sqlite3.Row) -> Shift:
        return Shift(
            opportunity_id=row["opportunity_id"],
            starts_at=datetime_from_db(row["starts_at"]),
            ends_at=datetime_from_db(row["ends_at"]),
            capacity=row["capacity"],
            notes=row["notes"],
            impact_amount=row["impact_amount"],
            shift_id=row["shift_id"],
        )

    @staticmethod
    def _to_role(row: sqlite3.Row) -> RoleOverview:
        role = ShiftRole(
            name=row["name"],
            capacity=row["capacity"],
            required_skill=row["required_skill"],
            shift_id=row["shift_id"],
            position=row["position"],
            role_id=row["role_id"],
        )
        return RoleOverview(role, row["filled"])

    @classmethod
    def _to_overview(cls, row: sqlite3.Row) -> ShiftOverview:
        return ShiftOverview(
            shift=cls._to_shift(row),
            opportunity_title=row["opportunity_title"],
            category=OpportunityCategory(row["category"]),
            location=row["location"],
            opportunity_status=OpportunityStatus(row["opportunity_status"]),
            filled=row["filled"],
        )
