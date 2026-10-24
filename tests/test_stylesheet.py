"""Colour contrast in the stylesheet, checked from source so a regression fails `make check`.

Backs `.claude/rules/web-ui.md` (colour tokens exist for both schemes and text meets WCAG AA).
"""

import re
from functools import cache
from pathlib import Path

import pytest

import repocop

STYLESHEET = Path(repocop.__file__).resolve().parent / "static" / "css" / "app.css"
DARK_SCHEME = "@media (prefers-color-scheme: dark)"
AA_TEXT_CONTRAST = 4.5
TEXT_COLOURS = ("fg", "muted", "link", "human", "repocop", "danger")
SURFACES = ("bg", "panel")
BADGE_FILLS = ("human", "repocop", "danger", "muted")  # status badges draw --bg text on these
PAIRS = [(text, surface) for text in TEXT_COLOURS for surface in SURFACES] + [
    ("bg", fill) for fill in BADGE_FILLS
]


def root_colours(css: str) -> dict[str, str]:
    match = re.search(r":root\s*{([^}]*)}", css)
    assert match, "no :root block"
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", match.group(1)))


@cache
def scheme_colours() -> dict[str, dict[str, str]]:
    light, dark = STYLESHEET.read_text(encoding="utf-8").split(DARK_SCHEME, 1)
    return {"light": root_colours(light), "dark": root_colours(dark)}


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_stylesheet_dark_scheme_redefines_every_colour() -> None:
    colours = scheme_colours()
    assert colours["dark"].keys() == colours["light"].keys()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize(("text", "surface"), PAIRS)
def test_stylesheet_text_meets_aa_contrast(scheme: str, text: str, surface: str) -> None:
    colours = scheme_colours()[scheme]
    assert contrast(colours[text], colours[surface]) >= AA_TEXT_CONTRAST
