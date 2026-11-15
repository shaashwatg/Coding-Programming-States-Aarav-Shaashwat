"""
Persistence for shift waitlists and the notices shown on a volunteer's Home page.

A waitlist entry only exists while someone is waiting: it is removed when they
are signed up or leave. Notices store *what happened* (a kind and a shift), not
sentences, so each person reads them in their own language.
"""

from __future__ import annotations

from datetime import datetime

from servesync.core.errors import DuplicateRecordError
from servesync.core.i18n import tr
from servesync.data.converters import datetime_from_db, datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.data.repositories.volunteer_repository import display_name_sql
from servesync.models import Notice, NoticeKind, WaitlistEntry


class WaitlistRepository(Repository):
    def add(self, shift_id: int, volunteer_id: int, joined_at: datetime) -> None:
        try:
            self._db.execute(
                "INSERT INTO waitlist (shift_id, volunteer_id, joined_at) VALUES (?, ?, ?)",
                (shift_id, volunteer_id, datetime_to_db(joined_at)),
            )
        except DuplicateRecordError as exc:
            raise DuplicateRecordError(tr("You're already on the waitlist for this shift.")) from exc

    def remove(self, shift_id: int, volunteer_id: int) -> bool:
        """Take someone off a shift's waitlist. Returns False if they weren't on it."""
        cursor = self._db.execute(
            "DELETE FROM waitlist WHERE shift_id = ? AND volunteer_id = ?", (shift_id, volunteer_id)
        )
        return cursor.rowcount > 0

    def entries(self, shift_id: int) -> list[WaitlistEntry]:
        """Everyone waiting for this shift, first come first served."""
        rows = self._db.query_all(
            f"""
            SELECT w.entry_id, w.shift_id, w.volunteer_id, w.joined_at, {display_name_sql("v")} AS volunteer_name
            FROM waitlist AS w
            JOIN volunteers AS v ON v.volunteer_id = w.volunteer_id
            WHERE w.shift_id = ?
            ORDER BY w.joined_at, w.entry_id
            """,
            (shift_id,),
        )
        return [
            WaitlistEntry(
                entry_id=row["entry_id"],
                shift_id=row["shift_id"],
                volunteer_id=row["volunteer_id"],
                volunteer_name=row["volunteer_name"],
                joined_at=datetime_from_db(row["joined_at"]),
            )
            for row in rows
        ]

    def shifts_for(self, volunteer_id: int) -> list[int]:
        rows = self._db.query_all("SELECT shift_id FROM waitlist WHERE volunteer_id = ?", (volunteer_id,))
        return [row["shift_id"] for row in rows]


class NoticeRepository(Repository):
    def add(self, volunteer_id: int, kind: NoticeKind, shift_id: int, created_at: datetime) -> None:
        self._db.execute(
            "INSERT INTO notices (volunteer_id, kind, shift_id, created_at) VALUES (?, ?, ?, ?)",
            (volunteer_id, kind.value, shift_id, datetime_to_db(created_at)),
        )

    def for_volunteer(self, volunteer_id: int) -> list[Notice]:
        """Notices the person hasn't dismissed yet, newest first."""
        rows = self._db.query_all(
            """
            SELECT n.notice_id, n.volunteer_id, n.kind, n.created_at, n.shift_id,
                   s.starts_at, s.ends_at, o.title AS opportunity_title, COALESCE(r.name, '') AS role_name
            FROM notices AS n
            JOIN shifts        AS s ON s.shift_id = n.shift_id
            JOIN opportunities AS o ON o.opportunity_id = s.opportunity_id
            LEFT JOIN assignments AS a ON a.shift_id = n.shift_id AND a.volunteer_id = n.volunteer_id
            LEFT JOIN shift_roles AS r ON r.role_id = a.role_id
            WHERE n.volunteer_id = ? AND n.dismissed = 0
            ORDER BY n.created_at DESC, n.notice_id DESC
            """,
            (volunteer_id,),
        )
        return [
            Notice(
                notice_id=row["notice_id"],
                volunteer_id=row["volunteer_id"],
                kind=NoticeKind(row["kind"]),
                created_at=datetime_from_db(row["created_at"]),
                shift_id=row["shift_id"],
                opportunity_title=row["opportunity_title"],
                starts_at=datetime_from_db(row["starts_at"]),
                ends_at=datetime_from_db(row["ends_at"]),
                role_name=row["role_name"],
            )
            for row in rows
        ]

    def owner(self, notice_id: int) -> int | None:
        value = self._db.query_value("SELECT volunteer_id FROM notices WHERE notice_id = ?", (notice_id,))
        return int(value) if value is not None else None

    def delete_for_volunteer(self, volunteer_id: int) -> None:
        self._db.execute("DELETE FROM notices WHERE volunteer_id = ?", (volunteer_id,))

    def dismiss(self, notice_id: int) -> None:
        self._db.execute("UPDATE notices SET dismissed = 1 WHERE notice_id = ?", (notice_id,))
