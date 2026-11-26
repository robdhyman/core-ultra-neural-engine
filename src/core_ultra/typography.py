"""Text shaping and measurement, shared by the reference layout and the runtime renderer.

Text is shaped by Qt's text layout (HarfBuzz) with design metrics and no
hinting, at one reference size, and kept as glyph outlines. Because nothing is
hinted or rounded, a line at any type size is the reference line scaled, so a
measured width and a drawn width cannot disagree.

Qt runs on its off-screen platform: no window is ever created.

The font is Inter, read from the file in `assets/fonts/inter/` and from
nowhere else; `ASSETS.md` records its source and licence. It is a variable
font. Its weight axis is set to the type weight and its optical size axis is
pinned at `OPTICAL_SIZE`, both by axis value: asking Qt for a weight by name
picks the wrong instance at five of the nine weights, and with no axis set
macOS chooses the optical size from the pixel size, which would make a line's
outline depend on the size it was shaped at. A request equal to the font's own
defaults (weight 400, optical size 14) is dropped by Qt, which is why the
pinned optical size is not 14.

A machine may have another Inter installed. The face Qt selects is therefore
compared with the bundled file by its `head` table (version, checksum and
dates), and anything else is refused.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QPainterPath, QRawFont, QTextLayout, QTextOption

FONT_FAMILY = "Inter"
FONT_FILE = Path(__file__).parent / "assets" / "fonts" / "inter" / "Inter[opsz,wght].ttf"
OPTICAL_SIZE = 16.0
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
    data = FONT_FILE.read_bytes()
    loaded = QFontDatabase.addApplicationFontFromData(QByteArray(data))
    if FONT_FAMILY not in QFontDatabase.applicationFontFamilies(loaded):
        raise RuntimeError(f"{FONT_FILE} did not load as the font {FONT_FAMILY!r}; no other font is substituted")
    if bytes(QRawFont.fromFont(font(400.0)).fontTable("head")) != _table(data, "head"):
        raise RuntimeError(
            f"the font Qt selects for {FONT_FAMILY!r} is not the bundled {FONT_FILE.name}; "
            "another version is installed on this machine and no other font is substituted"
        )
    _application = existing
    return _application


def _table(data: bytes, tag: str) -> bytes:
    """One table of a TrueType file."""
    (count,) = struct.unpack(">H", data[4:6])
    for index in range(count):
        record = data[12 + 16 * index : 28 + 16 * index]
        if record[:4] == tag.encode():
            offset, length = struct.unpack(">II", record[8:16])
            return data[offset : offset + length]
    raise ValueError(f"the font file has no {tag!r} table")


def font_weight(weight: float) -> float:
    """The nearest of the nine weights 100 to 900. The font has every one."""
    return float(min(900, max(100, round(weight / 100) * 100)))


def font(weight: float, pixel_size: float = _REFERENCE_SIZE) -> QFont:
    """The font at this type weight, unhinted, with its optical size pinned."""
    font = QFont(FONT_FAMILY)
    font.setVariableAxis(QFont.Tag("wght"), font_weight(weight))
    font.setVariableAxis(QFont.Tag("opsz"), OPTICAL_SIZE)
    font.setPixelSize(int(pixel_size))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    # No silent substitution: a character the font lacks is an error, not a
    # glyph borrowed from another font.
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    return font


@lru_cache(maxsize=4096)
def shape(text: str, weight: float) -> ShapedLine:
    ensure_gui()
    layout = QTextLayout(text, font(weight))
    option = QTextOption()
    option.setUseDesignMetrics(True)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    line.setLineWidth(1e9)
    layout.endLayout()

    outline = QPainterPath()
    # The contours of a variable font's glyphs overlap. Filled by winding, an
    # overlap is ink; filled by the default rule it would be a hole.
    outline.setFillRule(Qt.FillRule.WindingFill)
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
