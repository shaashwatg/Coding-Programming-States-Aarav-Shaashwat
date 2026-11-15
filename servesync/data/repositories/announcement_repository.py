"""Persistence for announcements: a leader's note to a program or to one shift."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from servesync.core.errors import RecordNotFoundError
from servesync.core.i18n import tr
from servesync.data.converters import datetime_from_db, datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.models import Announcement

_SELECT = """
    SELECT an.announcement_id, an.opportunity_id, an.shift_id, an.body, an.posted_by, an.posted_at,
           o.title AS opportunity_title, s.starts_at AS shift_starts_at
    FROM announcements AS an
    LEFT JOIN shifts AS s ON s.shift_id = an.shift_id
    JOIN opportunities AS o ON o.opportunity_id = COALESCE(an.opportunity_id, s.opportunity_id)
"""


class AnnouncementRepository(Repository):
    def add(
        self, *, body: str, posted_by: str, posted_at: datetime, opportunity_id: int | None, shift_id: int | None
    ) -> Announcement:
        cursor = self._db.execute(
            """INSERT INTO announcements (opportunity_id, shift_id, body, posted_by, posted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (opportunity_id, shift_id, body, posted_by, datetime_to_db(posted_at)),
        )
        return self.get(int(cursor.lastrowid or 0))

    def get(self, announcement_id: int) -> Announcement:
        row = self._db.query_one(f"{_SELECT} WHERE an.announcement_id = ?", (announcement_id,))
        if row is None:
            raise RecordNotFoundError(tr("Announcement"), announcement_id)
        return self._to_announcement(row)

    def delete(self, announcement_id: int) -> None:
        cursor = self._db.execute("DELETE FROM announcements WHERE announcement_id = ?", (announcement_id,))
        if cursor.rowcount == 0:
            raise RecordNotFoundError(tr("Announcement"), announcement_id)

    def for_target(self, *, opportunity_id: int | None = None, shift_id: int | None = None) -> list[Announcement]:
        """Notes posted to one program or one shift, newest first."""
        rows = self._db.query_all(
            f"{_SELECT} WHERE an.opportunity_id IS ? AND an.shift_id IS ? ORDER BY an.posted_at DESC",
            (opportunity_id, shift_id),
        )
        return [self._to_announcement(row) for row in rows]

    def for_volunteer(self, volunteer_id: int, *, now: datetime, since: datetime) -> list[Announcement]:
        """
        Notes for the shifts this person is signed up for (still to come), and for those
        shifts' programs, posted since ``since``. Newest first.
        """
        rows = self._db.query_all(
            f"""
            WITH mine AS (
                SELECT s2.shift_id, s2.opportunity_id
                FROM assignments AS a
                JOIN shifts AS s2 ON s2.shift_id = a.shift_id
                WHERE a.volunteer_id = :volunteer AND a.status = 'SCHEDULED' AND s2.ends_at > :now
            )
            {_SELECT}
            WHERE an.posted_at >= :since
              AND (an.shift_id IN (SELECT shift_id FROM mine)
                   OR an.opportunity_id IN (SELECT opportunity_id FROM mine))
            ORDER BY an.posted_at DESC
            """,
            {"volunteer": volunteer_id, "now": datetime_to_db(now), "since": datetime_to_db(since)},
        )
        return [self._to_announcement(row) for row in rows]

    @staticmethod
    def _to_announcement(row: sqlite3.Row) -> Announcement:
        return Announcement(
            announcement_id=row["announcement_id"],
            body=row["body"],
            posted_by=row["posted_by"],
            posted_at=datetime_from_db(row["posted_at"]),
            opportunity_title=row["opportunity_title"],
            opportunity_id=row["opportunity_id"],
            shift_id=row["shift_id"],
            shift_starts_at=datetime_from_db(row["shift_starts_at"]) if row["shift_starts_at"] else None,
        )
