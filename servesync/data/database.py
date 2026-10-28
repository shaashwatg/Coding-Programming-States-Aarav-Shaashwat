"""
SQLite connection manager: connections, transactions, and error translation.

Why SQLite
----------
* **Embedded & serverless** — the database engine ships inside Python's
  standard library, so a judge (or a nonprofit) installs nothing extra and
  needs no internet connection.
* **ACID transactions** — a sign-up either fully saves or not at all, even if
  the laptop battery dies mid-write.
* **Relational integrity** — foreign keys, UNIQUE and CHECK constraints act
  as a second safety net behind the Python validators ("defense in depth").
* **Single portable file** — easy to back up, reset, or hand to a judge.

Design notes
------------
* One long-lived connection: a desktop app has one user and one UI thread.
* ``isolation_level=None`` turns off Python's implicit transactions so this
  class controls them explicitly. Nested ``transaction()`` blocks become
  SAVEPOINTs, letting a service combine several repository calls atomically.
* All ``sqlite3`` exceptions are translated into ServeSync domain errors with
  user-safe messages; technical details go to the log file instead.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

from servesync.core.errors import DataStoreError, DuplicateRecordError, RecordInUseError
from servesync.core.i18n import tr

logger = logging.getLogger(__name__)

IN_MEMORY = ":memory:"
_BUSY_TIMEOUT_MS = 5000

#: Query parameters may be a positional sequence or a mapping of named values.
Params = Sequence[Any] | dict[str, Any]

_UNIQUE_FAILURE = re.compile(r"UNIQUE constraint failed: (?P<columns>.+)")


@contextmanager
def translate_sqlite_errors() -> Iterator[None]:
    """
    Convert low-level ``sqlite3`` exceptions into domain errors.

    Repositories may catch these and re-raise with an even more specific
    message (e.g. "Another volunteer already uses this email address").
    """
    try:
        yield
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        unique = _UNIQUE_FAILURE.search(message)
        if unique:
            column = unique.group("columns").split(",")[0].strip().split(".")[-1]
            raise DuplicateRecordError(
                tr("That {replace} is already in use.", replace=column.replace("_", " ")), field=column
            ) from exc
        if "FOREIGN KEY" in message:
            raise RecordInUseError(
                tr("This record is linked to other records, so it cannot be changed this way.")
            ) from exc
        logger.error("Integrity rule rejected a write: %s", message)
        raise DataStoreError(tr("A value was outside the allowed range and was not saved.")) from exc
    except sqlite3.OperationalError as exc:
        logger.exception("SQLite operational error")
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            raise DataStoreError(tr("The data file is busy. Close any other ServeSync windows and try again.")) from exc
        if "readonly" in text or "unable to open" in text or "disk" in text:
            raise DataStoreError(
                tr("ServeSync could not read or write its data file. Check that the disk has free space.")
            ) from exc
        raise DataStoreError(tr("A database operation failed. Details were saved to the log.")) from exc
    except sqlite3.DatabaseError as exc:
        logger.exception("SQLite database error")
        if "not a database" in str(exc).lower():
            raise DataStoreError(tr("The data file is damaged or is not a ServeSync database.")) from exc
        raise DataStoreError(tr("A database operation failed. Details were saved to the log.")) from exc
    except sqlite3.Error as exc:  # ProgrammingError, InterfaceError, ...
        logger.exception("Unexpected SQLite error")
        raise DataStoreError(tr("An unexpected database error occurred. Details were saved to the log.")) from exc


class Database:
    """Owns the SQLite connection and provides safe query/transaction helpers."""

    def __init__(self, path: Path | str = IN_MEMORY) -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None
        self._transaction_depth = 0

    # ------------------------------------------------------------------ setup

    @property
    def path(self) -> str:
        return self._path

    @property
    def is_in_memory(self) -> bool:
        return self._path == IN_MEMORY

    @property
    def in_transaction(self) -> bool:
        return self._transaction_depth > 0

    def connect(self) -> sqlite3.Connection:
        """Open the connection on first use and apply safety settings."""
        if self._connection is not None:
            return self._connection

        if not self.is_in_memory:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with translate_sqlite_errors():
            connection = sqlite3.connect(self._path, isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
        try:
            with translate_sqlite_errors():
                connection.row_factory = sqlite3.Row  # rows readable by column name
                connection.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite!
                connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
                if not self.is_in_memory:
                    # Write-ahead logging: readers never block the writer, and a
                    # crash mid-write cannot corrupt committed data.
                    connection.execute("PRAGMA journal_mode = WAL")
        except DataStoreError:
            connection.close()  # e.g. a damaged file: never leak the handle
            raise
        self._connection = connection
        logger.info("Opened database %s", self._path)
        return connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            self._transaction_depth = 0
            logger.info("Closed database %s", self._path)

    def __enter__(self) -> Database:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # ----------------------------------------------------------- transactions

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Run a block atomically: commit on success, roll back on any exception.

        Nested calls create SAVEPOINTs, so an inner failure that is caught and
        handled does not undo the outer work::

            with db.transaction():
                volunteers.add(v)          # outer work
                with db.transaction():     # savepoint
                    ...
        """
        connection = self.connect()
        savepoint = f"sp_{self._transaction_depth}" if self._transaction_depth else None
        with translate_sqlite_errors():
            # IMMEDIATE takes the write lock up front, avoiding mid-transaction
            # "database is locked" surprises.
            connection.execute(f"SAVEPOINT {savepoint}" if savepoint else "BEGIN IMMEDIATE")
        self._transaction_depth += 1
        try:
            yield connection
        except BaseException:
            self._transaction_depth -= 1
            self._rollback(connection, savepoint)
            raise
        self._transaction_depth -= 1
        try:
            with translate_sqlite_errors():
                connection.execute(f"RELEASE SAVEPOINT {savepoint}" if savepoint else "COMMIT")
        except DataStoreError:
            self._rollback(connection, savepoint)
            raise

    @staticmethod
    def _rollback(connection: sqlite3.Connection, savepoint: str | None) -> None:
        try:
            if savepoint:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            elif connection.in_transaction:
                connection.execute("ROLLBACK")
        except sqlite3.Error:  # pragma: no cover - rollback failure is logged, original error wins
            logger.exception("Rollback failed")

    # ---------------------------------------------------------------- queries
    # Every query uses "?" / ":name" placeholders. Values are NEVER formatted
    # into SQL strings, which makes SQL injection impossible.

    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        with translate_sqlite_errors():
            return self.connect().execute(sql, params)

    def execute_many(self, sql: str, rows: Iterable[Params]) -> sqlite3.Cursor:
        with translate_sqlite_errors():
            return self.connect().executemany(sql, rows)

    def query_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        with translate_sqlite_errors():
            row: sqlite3.Row | None = self.connect().execute(sql, params).fetchone()
            return row

    def query_all(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        with translate_sqlite_errors():
            return list(self.connect().execute(sql, params).fetchall())

    def query_value(self, sql: str, params: Params = (), default: Any = None) -> Any:
        """Return the first column of the first row, or ``default`` if there is none."""
        row = self.query_one(sql, params)
        return default if row is None or row[0] is None else row[0]
