"""Persistence for the change history and for volunteers' deletion requests."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from servesync.core.errors import DuplicateRecordError, RecordNotFoundError
from servesync.core.i18n import tr
from servesync.data.converters import datetime_from_db, datetime_to_db, escape_like
from servesync.data.repositories.base import Repository
from servesync.models import ChangeEntry, DeletionRequest

#: The history screen shows at most this many of the newest changes at once.
HISTORY_LIMIT = 500


class ChangeLogRepository(Repository):
    def add(
        self,
        *,
        changed_at: datetime,
        changed_by: str,
        action: str,
        entity: str,
        entity_id: int | None,
        label: str,
        details: str = "",
    ) -> None:
        self._db.execute(
            """INSERT INTO change_log (changed_at, changed_by, action, entity, entity_id, label, details)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime_to_db(changed_at), changed_by[:80], action, entity, entity_id, label[:160], details[:500]),
        )

    def recent(self, *, entity: str | None = None, search: str = "", limit: int = HISTORY_LIMIT) -> list[ChangeEntry]:
        """Newest first, optionally one kind of record and/or a name or user containing ``search``."""
        clauses, params = [], []
        if entity:
            clauses.append("entity = ?")
            params.append(entity)
        if search:
            clauses.append("(label LIKE ? ESCAPE '\\' OR changed_by LIKE ? ESCAPE '\\')")
            pattern = f"%{escape_like(search)}%"
            params += [pattern, pattern]
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.query_all(
            f"SELECT * FROM change_log{where} ORDER BY changed_at DESC, change_id DESC LIMIT ?", (*params, limit)
        )
        return [self._to_entry(row) for row in rows]

    def remove_name(self, name: str, replacement: str) -> None:
        """Take a person's name out of the history once their details are removed on request."""
        self._db.execute(
            "UPDATE change_log SET label = replace(label, ?, ?) WHERE instr(label, ?) > 0", (name, replacement, name)
        )

    @staticmethod
    def _to_entry(row: sqlite3.Row) -> ChangeEntry:
        return ChangeEntry(
            change_id=row["change_id"],
            changed_at=datetime_from_db(row["changed_at"]),
            changed_by=row["changed_by"],
            action=row["action"],
            entity=row["entity"],
            entity_id=row["entity_id"],
            label=row["label"],
            details=row["details"],
        )


class DeletionRequestRepository(Repository):
    _SELECT = """SELECT r.*, v.first_name || ' ' || v.last_name AS volunteer_name
                 FROM deletion_requests AS r JOIN volunteers AS v ON v.volunteer_id = r.volunteer_id"""

    def add(self, volunteer_id: int, requested_at: datetime, reason: str) -> DeletionRequest:
        try:
            cursor = self._db.execute(
                "INSERT INTO deletion_requests (volunteer_id, requested_at, reason) VALUES (?, ?, ?)",
                (volunteer_id, datetime_to_db(requested_at), reason),
            )
        except DuplicateRecordError as exc:
            raise DuplicateRecordError(
                tr("You already have a request waiting. A coordinator will reply soon.")
            ) from exc
        return self.get(int(cursor.lastrowid or 0))

    def get(self, request_id: int) -> DeletionRequest:
        row = self._db.query_one(f"{self._SELECT} WHERE r.request_id = ?", (request_id,))
        if row is None:
            raise RecordNotFoundError(tr("Request"), request_id)
        return self._to_request(row)

    def pending(self) -> list[DeletionRequest]:
        rows = self._db.query_all(f"{self._SELECT} WHERE r.status = 'PENDING' ORDER BY r.requested_at")
        return [self._to_request(row) for row in rows]

    def latest_for(self, volunteer_id: int) -> DeletionRequest | None:
        row = self._db.query_one(
            f"{self._SELECT} WHERE r.volunteer_id = ? ORDER BY r.requested_at DESC, r.request_id DESC LIMIT 1",
            (volunteer_id,),
        )
        return None if row is None else self._to_request(row)

    def close(self, request_id: int, *, status: str, handled_by: str, handled_at: datetime, response: str) -> None:
        self._db.execute(
            """UPDATE deletion_requests SET status = ?, handled_by = ?, handled_at = ?, response = ?
               WHERE request_id = ? AND status = 'PENDING'""",
            (status, handled_by, datetime_to_db(handled_at), response, request_id),
        )

    @staticmethod
    def _to_request(row: sqlite3.Row) -> DeletionRequest:
        return DeletionRequest(
            request_id=row["request_id"],
            volunteer_id=row["volunteer_id"],
            volunteer_name=row["volunteer_name"],
            requested_at=datetime_from_db(row["requested_at"]),
            reason=row["reason"],
            status=row["status"],
            handled_by=row["handled_by"],
            handled_at=datetime_from_db(row["handled_at"]) if row["handled_at"] else None,
            response=row["response"],
        )
