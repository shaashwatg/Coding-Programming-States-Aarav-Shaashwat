"""Persistence for sign-in accounts. Password hashes never leave this layer in logs."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime
from typing import Any

from servesync.core.errors import DuplicateRecordError, RecordNotFoundError, ValidationError
from servesync.data.converters import optional_datetime_from_db, optional_datetime_to_db
from servesync.data.repositories.base import Repository
from servesync.models import UserAccount, UserRole

_ENTITY = "Account"

_SELECT_ACCOUNT = """
    SELECT account_id, username, password_hash, role, volunteer_id, is_active,
           failed_login_count, locked_until, last_login_at
    FROM user_accounts
"""


class AccountRepository(Repository):
    # ----------------------------------------------------------------- writes

    def add(self, account: UserAccount) -> UserAccount:
        self._require_new(account.account_id, _ENTITY)
        with self._db.transaction():
            if account.volunteer_id is not None and not self._exists(
                "volunteers", "volunteer_id", account.volunteer_id
            ):
                raise RecordNotFoundError("Volunteer", account.volunteer_id)
            try:
                cursor = self._db.execute(
                    """
                    INSERT INTO user_accounts (username, password_hash, role, volunteer_id, is_active,
                                               failed_login_count, locked_until, last_login_at)
                    VALUES (:username, :password_hash, :role, :volunteer_id, :is_active,
                            :failed_login_count, :locked_until, :last_login_at)
                    """,
                    self._to_params(account),
                )
            except DuplicateRecordError as exc:
                if exc.field == "volunteer_id":
                    raise ValidationError.single("volunteer_id", "This volunteer already has an account.") from exc
                raise ValidationError.single("username", "That username is already taken.") from exc
        return dataclasses.replace(account, account_id=int(cursor.lastrowid or 0))

    def update_password_hash(self, account_id: int, password_hash: str) -> None:
        self._update(account_id, "password_hash = ?", (password_hash,))

    def set_active(self, account_id: int, is_active: bool) -> None:
        self._update(account_id, "is_active = ?", (int(is_active),))

    def record_failed_login(self, account_id: int, *, locked_until: datetime | None) -> None:
        self._update(
            account_id,
            "failed_login_count = failed_login_count + 1, locked_until = ?",
            (optional_datetime_to_db(locked_until),),
        )

    def record_successful_login(self, account_id: int, when: datetime) -> None:
        self._update(
            account_id,
            "failed_login_count = 0, locked_until = NULL, last_login_at = ?",
            (optional_datetime_to_db(when),),
        )

    def unlock(self, account_id: int) -> None:
        """Clear failed attempts and any lockout (used after an administrator resets a password)."""
        self._update(account_id, "failed_login_count = 0, locked_until = NULL", ())

    # ------------------------------------------------------------------ reads

    def exists(self, account_id: int) -> bool:
        return self._exists("user_accounts", "account_id", account_id)

    def get(self, account_id: int) -> UserAccount:
        row = self._db.query_one(f"{_SELECT_ACCOUNT} WHERE account_id = ?", (account_id,))
        if row is None:
            raise RecordNotFoundError(_ENTITY, account_id)
        return self._to_account(row)

    def find_by_username(self, username: str) -> UserAccount | None:
        """Case-insensitive lookup (the column uses COLLATE NOCASE)."""
        row = self._db.query_one(f"{_SELECT_ACCOUNT} WHERE username = ?", (username.strip(),))
        return None if row is None else self._to_account(row)

    def find_by_volunteer(self, volunteer_id: int) -> UserAccount | None:
        row = self._db.query_one(f"{_SELECT_ACCOUNT} WHERE volunteer_id = ?", (volunteer_id,))
        return None if row is None else self._to_account(row)

    def find_all(self) -> list[UserAccount]:
        rows = self._db.query_all(f"{_SELECT_ACCOUNT} ORDER BY role, username")
        return [self._to_account(row) for row in rows]

    def count_active(self, role: UserRole) -> int:
        """Used to stop the last active administrator from being deactivated."""
        return int(
            self._db.query_value(
                "SELECT COUNT(*) FROM user_accounts WHERE role = ? AND is_active = 1", (role.value,), default=0
            )
        )

    # ---------------------------------------------------------------- helpers

    def _update(self, account_id: int, assignments_sql: str, params: tuple[Any, ...]) -> None:
        cursor = self._db.execute(
            f"UPDATE user_accounts SET {assignments_sql} WHERE account_id = ?", (*params, account_id)
        )
        if cursor.rowcount == 0:
            raise RecordNotFoundError(_ENTITY, account_id)

    @staticmethod
    def _to_params(account: UserAccount) -> dict[str, Any]:
        return {
            "username": account.username,
            "password_hash": account.password_hash,
            "role": account.role.value,
            "volunteer_id": account.volunteer_id,
            "is_active": int(account.is_active),
            "failed_login_count": account.failed_login_count,
            "locked_until": optional_datetime_to_db(account.locked_until),
            "last_login_at": optional_datetime_to_db(account.last_login_at),
        }

    @staticmethod
    def _to_account(row: sqlite3.Row) -> UserAccount:
        return UserAccount(
            username=row["username"],
            password_hash=row["password_hash"],
            role=UserRole(row["role"]),
            volunteer_id=row["volunteer_id"],
            is_active=bool(row["is_active"]),
            failed_login_count=row["failed_login_count"],
            locked_until=optional_datetime_from_db(row["locked_until"]),
            last_login_at=optional_datetime_from_db(row["last_login_at"]),
            account_id=row["account_id"],
        )
