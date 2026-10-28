"""
The design system's accessibility claims, verified by arithmetic.

Contrast uses the WCAG 2.x relative-luminance formula. Every theme must meet:

* 7:1 for every text color on every background it can sit on (1.4.6, AAA)
* 3:1 for input borders and the focus ring (1.4.11 Non-text Contrast; 2.4.13)
* 7:1 for text on filled buttons (primary and call-to-action)
"""

from __future__ import annotations

import pytest

from servesync.models import Theme
from servesync.ui.theme import (
    DARK,
    HIGH_CONTRAST,
    LIGHT,
    MIN_TARGET,
    PALETTES,
    Palette,
    build_stylesheet,
    resolve_theme,
)


def luminance(color: str) -> float:
    red, green, blue = (int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


THEMES = [LIGHT, DARK, HIGH_CONTRAST]
TEXT_TOKENS = ("text", "text_muted", "primary", "info", "attention", "danger", "success")
BACKGROUNDS = ("window", "surface", "surface_alt")


@pytest.mark.parametrize("palette", THEMES, ids=lambda p: p.name)
@pytest.mark.parametrize("token", TEXT_TOKENS)
def test_text_meets_aaa_contrast_everywhere(palette: Palette, token: str) -> None:
    for background in BACKGROUNDS:
        ratio = contrast(getattr(palette, token), getattr(palette, background))
        assert ratio >= 7.0, f"{palette.name}: {token} on {background} is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", THEMES, ids=lambda p: p.name)
def test_boundaries_and_focus_are_visible(palette: Palette) -> None:
    for background in ("window", "surface"):
        assert contrast(palette.line_strong, getattr(palette, background)) >= 3.0
        assert contrast(palette.focus, getattr(palette, background)) >= 3.0
    assert palette.focus_width >= 2


@pytest.mark.parametrize("palette", THEMES, ids=lambda p: p.name)
def test_button_labels_meet_aaa(palette: Palette) -> None:
    assert contrast(palette.on_primary, palette.primary) >= 7.0
    assert contrast(palette.on_cta, palette.cta) >= 7.0
    assert contrast(palette.topbar_text, palette.topbar) >= 7.0
    assert contrast(palette.on_selection, palette.selection) >= 7.0


def test_every_theme_has_a_palette_or_follows_the_system() -> None:
    assert set(PALETTES) | {Theme.SYSTEM} == set(Theme)
    assert resolve_theme(Theme.SYSTEM) in (Theme.LIGHT, Theme.DARK)
    assert resolve_theme(Theme.HIGH_CONTRAST) is Theme.HIGH_CONTRAST


def test_targets_grow_with_text_size() -> None:
    normal = build_stylesheet(LIGHT, 13.0)
    large = build_stylesheet(LIGHT, 26.0)
    assert f"min-height: {MIN_TARGET - 8}px" in normal  # navigation: 44 px target minus padding
    assert f"min-height: {MIN_TARGET * 2 - 8}px" in large
