"""
Repository base class.

The Repository pattern hides *how* data is stored behind methods that speak
the domain's language (``volunteers.find_all(status=ACTIVE)``). The service and UI
layers never see SQL, so the storage engine could change without touching
them — and every query is written, reviewed and tested in exactly one place.
"""

from __future__ import annotations

from servesync.data.database import Database


class Repository:
    """Holds the shared :class:`Database` reference for a concrete repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _require_saved(self, record_id: int | None, entity: str) -> int:
        """Guard against programmer error: updating a record that was never saved."""
        if record_id is None:
            raise ValueError(f"{entity} has not been saved yet; call add() first.")
        return record_id

    def _require_new(self, record_id: int | None, entity: str) -> None:
        """Guard against programmer error: adding a record that already has an ID."""
        if record_id is not None:
            raise ValueError(f"{entity} #{record_id} is already saved; call update() instead.")

    def _exists(self, table: str, id_column: str, record_id: int) -> bool:
        # Table/column names come only from our own code, never from users.
        sql = f"SELECT 1 FROM {table} WHERE {id_column} = ?"
        return self._db.query_one(sql, (record_id,)) is not None
