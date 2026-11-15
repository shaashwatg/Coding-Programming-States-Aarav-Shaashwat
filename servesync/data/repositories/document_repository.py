"""Persistence for issued documents (service records and certificates) and their verification codes."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from servesync.core.errors import DuplicateRecordError
from servesync.data.converters import date_from_db, date_to_db, datetime_from_db, datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.models import IssuedDocument


class DocumentRepository(Repository):
    def add(
        self,
        *,
        code: str,
        kind: str,
        volunteer_id: int,
        hours: float,
        issued_at: datetime,
        issued_by: str,
        period_start: date | None = None,
        period_end: date | None = None,
        milestone: int | None = None,
    ) -> bool:
        """Record an issued document. Returns False if the code is already taken (the caller picks another)."""
        try:
            self._db.execute(
                """INSERT INTO issued_documents (code, kind, volunteer_id, period_start, period_end, hours,
                                                 milestone, issued_at, issued_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    kind,
                    volunteer_id,
                    date_to_db(period_start) if period_start else None,
                    date_to_db(period_end) if period_end else None,
                    hours,
                    milestone,
                    datetime_to_db(issued_at),
                    issued_by,
                ),
            )
        except DuplicateRecordError:
            return False
        return True

    def find(self, code: str) -> IssuedDocument | None:
        row = self._db.query_one(
            """SELECT d.*, v.first_name || ' ' || v.last_name AS volunteer_name
               FROM issued_documents AS d JOIN volunteers AS v ON v.volunteer_id = d.volunteer_id
               WHERE d.code = ?""",
            (code,),
        )
        return None if row is None else self._to_document(row)

    @staticmethod
    def _to_document(row: sqlite3.Row) -> IssuedDocument:
        return IssuedDocument(
            code=row["code"],
            kind=row["kind"],
            volunteer_id=row["volunteer_id"],
            volunteer_name=row["volunteer_name"],
            hours=row["hours"],
            issued_at=datetime_from_db(row["issued_at"]),
            issued_by=row["issued_by"],
            period_start=date_from_db(row["period_start"]) if row["period_start"] else None,
            period_end=date_from_db(row["period_end"]) if row["period_end"] else None,
            milestone=row["milestone"],
        )
