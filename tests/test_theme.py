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


@pytest.mark.parametrize("palette", THEMES, ids=lambda p: p.name)
def test_sidebar_text_and_focus_are_visible(palette: Palette) -> None:
    for background in (palette.sidebar, palette.sidebar_hover, palette.sidebar_active):
        assert contrast(palette.sidebar_text, background) >= 7.0
    assert contrast(palette.sidebar_muted, palette.sidebar) >= 7.0
    assert contrast(palette.sidebar_focus, palette.sidebar) >= 3.0
    assert contrast(palette.sidebar_accent, palette.sidebar_active) >= 3.0


def test_every_theme_has_a_palette_or_follows_the_system() -> None:
    assert set(PALETTES) | {Theme.SYSTEM} == set(Theme)
    assert resolve_theme(Theme.SYSTEM) in (Theme.LIGHT, Theme.DARK)
    assert resolve_theme(Theme.HIGH_CONTRAST) is Theme.HIGH_CONTRAST


def test_targets_grow_with_text_size() -> None:
    normal = build_stylesheet(LIGHT, 13.0)
    large = build_stylesheet(LIGHT, 26.0)
    assert f"min-height: {MIN_TARGET - 8}px" in normal  # navigation: 44 px target minus padding
    assert f"min-height: {MIN_TARGET * 2 - 8}px" in large


def test_the_palette_follows_the_cal_design_system() -> None:
    """Near-black ink and primary, one blue accent; charts in ink, blue, green, in that order."""
    from servesync.ui import theme

    assert LIGHT.primary == LIGHT.text == theme.INK == "#111111"
    assert LIGHT.window == "#FFFFFF" and LIGHT.surface_alt == "#F5F5F5"
    assert LIGHT.focus == theme.BLUE and LIGHT.chart == (theme.INK, theme.BLUE, theme.GREEN)
    assert LIGHT.attention_fill == theme.AMBER and LIGHT.success_fill == theme.GREEN


def test_light_fills_are_never_text_on_a_light_background() -> None:
    from servesync.ui import theme

    text_tokens = {getattr(LIGHT, token) for token in TEXT_TOKENS}
    assert not {theme.AMBER, theme.GREEN, theme.BLUE} & text_tokens
    assert contrast(LIGHT.on_attention, LIGHT.attention_fill) >= 7.0  # dark text on amber fills


@pytest.mark.parametrize("palette", THEMES, ids=lambda p: p.name)
def test_text_on_cards_meets_aaa(palette: Palette) -> None:
    for token in TEXT_TOKENS:
        assert contrast(getattr(palette, token), palette.surface_alt) >= 7.0, token


def test_screens_never_hard_code_colors() -> None:
    """Pages, widgets and dialogs ask the theme for a color by meaning, never by hex value."""
    import re
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "servesync" / "ui"
    offenders = [
        f"{path.relative_to(ui)}: {match}"
        for folder in ("pages", "widgets", "dialogs")
        for path in (ui / folder).glob("*.py")
        for match in re.findall(r"#[0-9A-Fa-f]{6}\b", path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_stylesheet_has_no_gradients_or_zebra_stripes() -> None:
    sheet = build_stylesheet(LIGHT, 13.0)
    assert "gradient" not in sheet
    assert "alternate-background-color" not in sheet
