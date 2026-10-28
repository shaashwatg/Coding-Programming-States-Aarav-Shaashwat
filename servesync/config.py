"""
Application configuration and file-system locations.

Why this module exists
----------------------
A standalone desktop program must never assume it can write next to its own
executable: on Windows, ``C:\\Program Files`` is read-only for normal users,
and a PyInstaller bundle may unpack to a temporary folder. We therefore store
user data (the database and logs) in the operating system's per-user
application-data directory, and read bundled, read-only resources (icons,
stylesheets) from the bundle folder.

Every path can be overridden with the ``SERVESYNC_DATA_DIR`` environment
variable, which is how the automated tests and the demo-reset tool point the
app at a throwaway folder.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from servesync import __app_name__

# ---------------------------------------------------------------------------
# Business constants (single source of truth — never hard-code these inline)
# ---------------------------------------------------------------------------

#: Minimum age to register as a volunteer (common nonprofit policy; minors
#: aged 14-17 are allowed but flagged so leaders can collect guardian consent).
MINIMUM_VOLUNTEER_AGE: int = 14

#: Age at which a volunteer is no longer considered a minor.
ADULT_AGE: int = 18

#: Longest single shift we accept. Anything longer is almost certainly a
#: typo (e.g. 8 PM entered instead of 8 AM) and is rejected semantically.
MAX_SHIFT_HOURS: int = 12

#: Largest capacity for one shift — keeps reports and rosters sensible.
MAX_SHIFT_CAPACITY: int = 500

#: National value of one volunteer hour in U.S. dollars.
#: Source: Independent Sector & the Do Good Institute (University of Maryland),
#: "Value of Volunteer Time," released April 21, 2026 (2025 wage data).
#: https://independentsector.org/research/value-of-volunteer-time/
#: Stored as an editable setting so an organization can use its state value.
DEFAULT_VOLUNTEER_HOUR_VALUE: float = 36.14

#: Environment variable that overrides where user data is stored.
DATA_DIR_ENV_VAR: str = "SERVESYNC_DATA_DIR"

DATABASE_FILENAME: str = "servesync.db"
LOG_DIRNAME: str = "logs"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """
    Folder that holds read-only bundled resources (icons, stylesheets).

    PyInstaller unpacks bundled files into ``sys._MEIPASS``; in development we
    use the package folder itself.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def default_data_dir() -> Path:
    """
    Per-user, writable folder for the database and logs.

    * Windows: ``%APPDATA%\\ServeSync``
    * macOS:   ``~/Library/Application Support/ServeSync``
    * Linux:   ``$XDG_DATA_HOME/ServeSync`` or ``~/.local/share/ServeSync``
    """
    override = os.environ.get(DATA_DIR_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()

    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return base / __app_name__


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved, immutable set of paths the application uses."""

    data_dir: Path
    database_file: Path
    log_dir: Path

    @classmethod
    def resolve(cls, data_dir: Path | None = None) -> AppPaths:
        """Build the path set, creating folders that do not exist yet."""
        root = data_dir if data_dir is not None else default_data_dir()
        log_dir = root / LOG_DIRNAME
        log_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            data_dir=root,
            database_file=root / DATABASE_FILENAME,
            log_dir=log_dir,
        )
