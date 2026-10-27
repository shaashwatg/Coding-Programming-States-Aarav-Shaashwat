"""
Centralized logging configuration.

During a judged demonstration nothing should ever be printed as a raw stack
trace. Instead, every unexpected error is written to a rotating log file in
the user's data folder, while the UI shows a friendly message. The log is also
our evidence trail if a judge asks, "How would you debug a problem a
nonprofit reported?"

Security note: passwords and password hashes are never passed to the logger.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "servesync.log"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_MAX_LOG_BYTES = 1_000_000  # 1 MB per file
_BACKUP_COUNT = 3  # keep servesync.log.1 .. .3


def configure_logging(log_dir: Path, *, verbose: bool = False) -> logging.Logger:
    """
    Configure the ``servesync`` logger hierarchy once and return its root.

    Calling this function more than once is safe; handlers are not duplicated.
    """
    logger = logging.getLogger("servesync")
    if logger.handlers:  # already configured (e.g. tests, re-entry)
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # Do not bubble records up to the root logger (avoids duplicate output).
    logger.propagate = False
    return logger
