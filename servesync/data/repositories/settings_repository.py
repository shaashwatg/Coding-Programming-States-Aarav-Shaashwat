"""
Typed access to organization settings and accessibility preferences.

Settings live in a simple key/value table, but nothing outside this class
touches raw strings: each setting has a typed getter that validates what it
reads (falling back to a safe default if a value is ever corrupted) and a
setter that validates what it writes.
"""

from __future__ import annotations

import logging
import math
from enum import Enum

from servesync.config import DEFAULT_VOLUNTEER_HOUR_VALUE
from servesync.core.i18n import tr
from servesync.core.validators import InvalidInputError, clean_text, parse_enum, validate_field
from servesync.data.repositories.base import Repository
from servesync.models import Appearance, Theme
from servesync.models.preferences import MAX_FONT_SCALE, MIN_FONT_SCALE, parse_font_scale

logger = logging.getLogger(__name__)

MAX_HOUR_VALUE = 500.0
#: Computer-wide copy of the most recent comfort settings, used before sign-in.
_DEVICE_PREFIX = "ui_"


def _parse_hour_value(raw: object) -> float:
    """Syntactic: a dollar amount ("36.14" or "$36.14"). Semantic: $0.01-$500."""
    try:
        number = float(str(raw).strip().lstrip("$").replace(",", ""))
    except ValueError as exc:
        raise InvalidInputError(tr("Hour value must be a dollar amount such as 36.14.")) from exc
    if not math.isfinite(number) or not 0 < number <= MAX_HOUR_VALUE:
        raise InvalidInputError(
            tr("Hour value must be between $0.01 and ${MAX_HOUR_VALUE:,.0f}.", MAX_HOUR_VALUE=MAX_HOUR_VALUE)
        )
    return round(number, 2)


class SettingKey(str, Enum):
    ORGANIZATION_NAME = "organization_name"
    MISSION_STATEMENT = "mission_statement"
    VOLUNTEER_HOUR_VALUE = "volunteer_hour_value"
    FONT_SCALE = "ui_font_scale"
    THEME = "ui_theme"


class SettingsRepository(Repository):
    # ------------------------------------------------------------ primitives

    def _get(self, key: SettingKey) -> str | None:
        value = self._db.query_value("SELECT value FROM app_settings WHERE key = ?", (key.value,))
        return None if value is None else str(value)

    def _set(self, key: SettingKey, value: str) -> None:
        self._db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value
            """,
            (key.value, value),
        )

    def _get_float(self, key: SettingKey, default: float, low: float, high: float) -> float:
        raw = self._get(key)
        try:
            value = float(raw) if raw is not None else default
        except ValueError:
            value = math.nan
        if not math.isfinite(value) or not low <= value <= high:
            logger.warning("Setting %s had invalid value %r; using default %s", key.value, raw, default)
            return default
        return value

    # --------------------------------------------------------- organization

    def organization_name(self) -> str:
        return self._get(SettingKey.ORGANIZATION_NAME) or tr("My Nonprofit")

    def set_organization_name(self, name: str) -> str:
        cleaned = validate_field("organization_name", clean_text, name, tr("Organization name"), max_length=80)
        self._set(SettingKey.ORGANIZATION_NAME, cleaned)
        return cleaned

    def mission_statement(self) -> str:
        return self._get(SettingKey.MISSION_STATEMENT) or ""

    def set_mission_statement(self, mission: str) -> str:
        cleaned = validate_field(
            "mission_statement", clean_text, mission, tr("Mission statement"), max_length=300, required=False
        )
        self._set(SettingKey.MISSION_STATEMENT, cleaned)
        return cleaned

    def volunteer_hour_value(self) -> float:
        """Dollar value of one volunteer hour used in impact reports."""
        return self._get_float(SettingKey.VOLUNTEER_HOUR_VALUE, DEFAULT_VOLUNTEER_HOUR_VALUE, 0.01, MAX_HOUR_VALUE)

    def set_volunteer_hour_value(self, value: object) -> float:
        amount = validate_field("volunteer_hour_value", _parse_hour_value, value)
        self._set(SettingKey.VOLUNTEER_HOUR_VALUE, f"{amount:.2f}")
        return amount

    # -------------------------------------------------------- accessibility

    def font_scale(self) -> float:
        return self._get_float(SettingKey.FONT_SCALE, 1.0, MIN_FONT_SCALE, MAX_FONT_SCALE)

    def set_font_scale(self, scale: object) -> float:
        value = validate_field("font_scale", parse_font_scale, scale)
        self._set(SettingKey.FONT_SCALE, f"{value:.2f}")
        return value

    def device_appearance(self) -> Appearance:
        """Comfort settings last used on this computer (shown on the sign-in screen)."""
        keys = [_DEVICE_PREFIX + key for key in Appearance().to_settings()]
        rows = self._db.query_all(
            f"SELECT key, value FROM app_settings WHERE key IN ({', '.join('?' for _ in keys)})", keys
        )
        stored = {str(row["key"]).removeprefix(_DEVICE_PREFIX): str(row["value"]) for row in rows}
        # Files from earlier versions stored "ui_theme" and "ui_font_scale" — the same keys, so they carry over.
        return Appearance.from_settings(stored, Appearance(theme=Theme.LIGHT))

    def set_device_appearance(self, appearance: Appearance) -> None:
        with self._db.transaction():
            self._db.execute_many(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value
                """,
                [(_DEVICE_PREFIX + key, value) for key, value in appearance.to_settings().items()],
            )

    def theme(self) -> Theme:
        raw = self._get(SettingKey.THEME)
        try:
            return Theme(raw)
        except ValueError:
            logger.warning("Setting ui_theme had invalid value %r; using LIGHT", raw)
            return Theme.LIGHT

    def set_theme(self, theme: Theme | str) -> Theme:
        parsed: Theme = validate_field("theme", parse_enum, theme, Theme, tr("Theme"))
        self._set(SettingKey.THEME, parsed.value)
        return parsed
