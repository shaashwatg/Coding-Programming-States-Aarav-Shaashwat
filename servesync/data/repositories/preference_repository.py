"""
Per-account comfort preferences (theme, text size, motion, spacing...).

A thin key/value store; :class:`servesync.models.Appearance` decides what the
keys mean and repairs damaged values, so this class never interprets them.
"""

from __future__ import annotations

from collections.abc import Mapping

from servesync.data.repositories.base import Repository

MAX_KEY_LENGTH = 40
MAX_VALUE_LENGTH = 40


class PreferenceRepository(Repository):
    def get_all(self, account_id: int) -> dict[str, str]:
        rows = self._db.query_all("SELECT key, value FROM account_preferences WHERE account_id = ?", (account_id,))
        return {row["key"]: row["value"] for row in rows}

    def set_many(self, account_id: int, values: Mapping[str, str]) -> None:
        """Insert or replace several preferences at once (all-or-nothing)."""
        for key, value in values.items():
            if not 0 < len(key) <= MAX_KEY_LENGTH or len(value) > MAX_VALUE_LENGTH:
                raise ValueError(f"Preference {key!r} is too long to store.")
        with self._db.transaction():
            self._db.execute_many(
                """
                INSERT INTO account_preferences (account_id, key, value) VALUES (?, ?, ?)
                ON CONFLICT (account_id, key) DO UPDATE SET value = excluded.value
                """,
                [(account_id, key, value) for key, value in values.items()],
            )
