"""Text shaping and measurement, shared by the reference layout and the runtime renderer.

Text is shaped by Qt's text layout (HarfBuzz) with design metrics and no
hinting, at one reference size, and kept as glyph outlines. Because nothing is
hinted or rounded, a line at any type size is the reference line scaled, so a
measured width and a drawn width cannot disagree.

Qt runs on its off-screen platform: no window is ever created.

The font is a starting choice for the tracer, a system font that is read and
never redistributed. The font set with recorded provenance arrives with the
visual presets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QPainterPath, QTextLayout, QTextOption

FONT_FAMILY = "Helvetica Neue"
_REFERENCE_SIZE = 100

_application: QGuiApplication | None = None


class TextNotDrawable(Exception):
    """The font has no glyph for a character of the application's text."""


@dataclass(frozen=True)
class ShapedLine:
    """One line of text at the reference size. `outline` has its origin at the
    line's top left corner and must not be modified."""

    outline: QPainterPath
    advance: float
    ascent: float
    descent: float


def ensure_gui() -> QGuiApplication:
    """The process's Qt application, created off screen if there is none yet."""
    global _application
    if _application is not None:
        return _application
    existing = QGuiApplication.instance()
    if existing is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        existing = QGuiApplication([])
    if FONT_FAMILY not in QFontDatabase.families():
        raise RuntimeError(f"the font {FONT_FAMILY!r} is not installed; no other font is substituted")
    _application = existing
    return _application


def font_weight(weight: float) -> QFont.Weight:
    """The nearest of the nine named weights. The font system then matches the
    nearest face the family has."""
    return QFont.Weight(min(900, max(100, round(weight / 100) * 100)))


@lru_cache(maxsize=4096)
def shape(text: str, weight: float) -> ShapedLine:
    ensure_gui()
    font = QFont(FONT_FAMILY)
    font.setPixelSize(_REFERENCE_SIZE)
    font.setWeight(font_weight(weight))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    # No silent substitution: a character the font lacks is an error, not a
    # glyph borrowed from another font.
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)

    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setUseDesignMetrics(True)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(1e9)
    layout.endLayout()

    outline = QPainterPath()
    for run in layout.glyphRuns():
        raw_font = run.rawFont()
        for glyph, position in zip(run.glyphIndexes(), run.positions()):
            if glyph == 0:
                raise TextNotDrawable(f"{FONT_FAMILY} has no glyph for a character of {text!r}")
            outline.addPath(raw_font.pathForGlyph(glyph).translated(position))
    return ShapedLine(outline, line.naturalTextWidth(), line.ascent(), line.descent())


def reference_scale(type_size: float) -> float:
    """The factor that takes a reference-size line to this type size."""
    return type_size / _REFERENCE_SIZE


def measure(text: str, type_size: float, type_weight: float) -> float:
    """The advance width of the text at this type size, in viewport units."""
    return shape(text, type_weight).advance * reference_scale(type_size)


def line_height(type_size: float, type_weight: float) -> float:
    """Ascent plus descent at this type size, in viewport units."""
    line = shape("", type_weight)
    return (line.ascent + line.descent) * reference_scale(type_size)
