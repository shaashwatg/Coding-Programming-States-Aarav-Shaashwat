"""
Comfort preferences — how each person wants ServeSync to look and behave.

Preferences belong to the *account*, not the computer: a nonprofit's shared
front-desk laptop may be used by a volunteer with low vision in the morning
and a coordinator with ADHD in the afternoon, and each should get their own
setup the moment they sign in. The most recent choices are also kept as the
computer's default, so the sign-in screen stays readable for whoever used it
last.

Stored as plain key/value text, so this class owns both directions:
``to_settings`` writes, ``from_settings`` reads and *repairs* (any missing or
damaged value falls back to the default instead of crashing the app).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields

from servesync.core.i18n import Language, mark, tr
from servesync.core.validators import ErrorCollector, InvalidInputError, parse_enum
from servesync.models.enums import MessageDuration, Theme

logger = logging.getLogger(__name__)

MIN_FONT_SCALE = 0.85
MAX_FONT_SCALE = 2.0

_TRUE = "1"
_FALSE = "0"


def parse_font_scale(raw: object, label: str = mark("Text size")) -> float:
    """Semantic: text size between 85% and 200% of normal."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise InvalidInputError(tr("{label} must be a number.", label=tr(label)))
    if not MIN_FONT_SCALE <= float(raw) <= MAX_FONT_SCALE:
        raise InvalidInputError(
            tr(
                "{label} must be between {MIN_FONT_SCALE:.0%} and {MAX_FONT_SCALE:.0%}.",
                label=tr(label),
                MIN_FONT_SCALE=MIN_FONT_SCALE,
                MAX_FONT_SCALE=MAX_FONT_SCALE,
            )
        )
    return round(float(raw), 2)


def _parse_flag(raw: object, label: str) -> bool:
    if not isinstance(raw, bool):
        raise InvalidInputError(tr("{label} must be on or off.", label=tr(label)))
    return raw


@dataclass(frozen=True, slots=True)
class Appearance:
    """
    One person's comfort settings. Each maps to a WCAG 2.2 success criterion.

    ============================  ==============================================
    Field                         Why it exists
    ============================  ==============================================
    theme                         1.4.6 Contrast (Enhanced, AAA) — High contrast
                                  meets 7:1; System follows the OS dark mode
    font_scale                    1.4.4 Resize Text — 85%-200%, nothing clipped
    reduce_motion                 2.3.3 Animation from Interactions (AAA)
    text_spacing                  1.4.12 Text Spacing — wider letters and words
                                  (helps many dyslexic readers)
    simplified                    Cognitive load: hides secondary panels so
                                  each screen has one job
    message_duration              2.2.1 Timing Adjustable / 2.2.3 No Timing
    language                      3.1.1 Language of Page — English or Spanish,
                                  for the many volunteers and families who
                                  read Spanish more comfortably
    ============================  ==============================================
    """

    theme: Theme = Theme.SYSTEM
    font_scale: float = 1.0
    reduce_motion: bool = False
    text_spacing: bool = False
    simplified: bool = False
    message_duration: MessageDuration = MessageDuration.STANDARD
    language: Language = Language.ENGLISH

    def __post_init__(self) -> None:
        errors = ErrorCollector()
        theme = errors.check("theme", parse_enum, self.theme, Theme, tr("Theme"))
        scale = errors.check("font_scale", parse_font_scale, self.font_scale)
        duration = errors.check(
            "message_duration", parse_enum, self.message_duration, MessageDuration, tr("Message timing")
        )
        language = errors.check("language", parse_enum, self.language, Language, tr("Language"))
        for name, label in (
            ("reduce_motion", tr("Reduce motion")),
            ("text_spacing", tr("Extra text spacing")),
            ("simplified", tr("Simplified layout")),
        ):
            errors.check(name, _parse_flag, getattr(self, name), label)
        errors.raise_if_any()
        # frozen dataclass: normalized values are written through object.__setattr__
        object.__setattr__(self, "theme", theme)
        object.__setattr__(self, "font_scale", scale)
        object.__setattr__(self, "message_duration", duration)
        object.__setattr__(self, "language", language)

    # ------------------------------------------------------------ storage

    def to_settings(self) -> dict[str, str]:
        """Text form for the key/value preferences table."""
        return {
            "theme": self.theme.value,
            "font_scale": f"{self.font_scale:.2f}",
            "reduce_motion": _TRUE if self.reduce_motion else _FALSE,
            "text_spacing": _TRUE if self.text_spacing else _FALSE,
            "simplified": _TRUE if self.simplified else _FALSE,
            "message_duration": self.message_duration.value,
            "language": self.language.value,
        }

    @classmethod
    def from_settings(cls, values: Mapping[str, str], fallback: Appearance | None = None) -> Appearance:
        """
        Read stored text back, value by value. Anything missing or damaged
        takes the ``fallback`` value, and a damaged value is logged.
        """
        base = fallback or cls()
        chosen: dict[str, object] = {}
        for field in fields(cls):
            raw = values.get(field.name)
            if raw is None:
                chosen[field.name] = getattr(base, field.name)
                continue
            try:
                chosen[field.name] = _decode(field.name, raw)
            except (InvalidInputError, ValueError):
                logger.warning(
                    "Preference %s had invalid value %r; using %r", field.name, raw, getattr(base, field.name)
                )
                chosen[field.name] = getattr(base, field.name)
        return cls(**chosen)  # type: ignore[arg-type]  # values decoded per field above


def _decode(name: str, raw: str) -> object:
    if name == "theme":
        return Theme(raw)
    if name == "message_duration":
        return MessageDuration(raw)
    if name == "language":
        return Language(raw)
    if name == "font_scale":
        return parse_font_scale(float(raw))
    if raw not in (_TRUE, _FALSE):
        raise InvalidInputError(tr("{name} must be 0 or 1.", name=name))
    return raw == _TRUE
