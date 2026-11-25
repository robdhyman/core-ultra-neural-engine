"""The runtime renderer: deterministic vector drawing of a validated scene, and hit testing.

Drawing is Qt's painter on an off-screen image. No browser engine is in its
path: the project depends on PySide6-Essentials, which does not contain
QtWebEngine.

Both `draw` and `hit_test` take a `Scene`, which only scene validation can
produce, and both get an element's outline from `outline_of`. The shape a
pointer hits is therefore the shape that was filled.

What is drawn, per element, in the scene's drawing order:

- the box as a rounded rectangle, filled with `fill`;
- a border of `border_width` in `border_colour`, inside the outline;
- for a bound element with text, the text as filled glyph outlines in
  `text_colour`, on the box's vertical centre. A button's text is centred
  horizontally; other text starts as far from the left edge as the line is
  from the top edge.

`opacity` multiplies the element's own fill, border and text. Text is never
elided, wrapped or clipped. `elevation` is carried by the scene and not drawn
yet.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from core_ultra import typography
from core_ultra.documents_adapter import BoundElement
from core_ultra.scene import Element, Scene


def outline_of(element: Element) -> QPainterPath:
    """The element's drawn shape, in viewport units."""
    path = QPainterPath()
    radius = element.style.corner_radius
    path.addRoundedRect(QRectF(element.x, element.y, element.width, element.height), radius, radius)
    return path


def text_origin(element: Element) -> tuple[float, float]:
    """Top left corner of the element's line of text, in viewport units."""
    style = element.style
    line = typography.shape(element.bound.text, style.type_weight)
    scale = typography.reference_scale(style.type_size)
    inset = (element.height - (line.ascent + line.descent) * scale) / 2
    if element.bound.role == "button":
        x = element.x + (element.width - line.advance * scale) / 2
    else:
        x = element.x + max(inset, 0.0)
    return x, element.y + inset


def draw(scene: Scene, scale: float = 1.0) -> np.ndarray:
    """Draw the scene. Returns RGBA pixels, shape (height, width, 4), 8 bits a channel.

    `scale` is pixels per viewport unit. The scene is drawn as vectors at that
    scale, never drawn small and enlarged.
    """
    _require_scene(scene)
    if not (isinstance(scale, (int, float)) and math.isfinite(scale) and scale > 0):
        raise ValueError(f"scale is {scale!r}; it is a finite number above zero")
    typography.ensure_gui()

    width = math.ceil(scene.viewport_width * scale - 1e-9)
    height = math.ceil(scene.viewport_height * scale - 1e-9)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(scale, scale)
        for element in scene.elements:
            _draw_element(painter, element)
    finally:
        painter.end()

    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
    return pixels.reshape(height, image.bytesPerLine() // 4, 4)[:, :width].copy()


def hit_test(scene: Scene, x: float, y: float) -> BoundElement | None:
    """The bound element drawn topmost at this point, in viewport units, or None.

    A structural element with a visible fill covers whatever was drawn before
    it, as it does in the image.
    """
    _require_scene(scene)
    point = QPointF(x, y)
    for element in reversed(scene.elements):
        if not outline_of(element).contains(point):
            continue
        if element.bound is not None:
            return element.bound
        if element.style.fill[3] * element.style.opacity > 0:
            return None
    return None


def write_png(image: np.ndarray, path: str | Path) -> None:
    """Save pixels returned by `draw` as a PNG file."""
    height, width, _ = image.shape
    data = np.ascontiguousarray(image)
    if not QImage(data.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).save(str(path), "PNG"):
        raise OSError(f"could not write {path}")


def _require_scene(scene: object) -> None:
    if not isinstance(scene, Scene):
        raise TypeError("the runtime renderer reads a validated Scene; pass the candidate through scene.validate")


def _colour(rgba: tuple[float, float, float, float]) -> QColor:
    return QColor.fromRgbF(*rgba)


def _draw_element(painter: QPainter, element: Element) -> None:
    style = element.style
    painter.setOpacity(style.opacity)

    if style.fill[3] > 0:
        painter.fillPath(outline_of(element), _colour(style.fill))

    if style.border_width > 0 and style.border_colour[3] > 0:
        # Stroked along a line half a border in from the outline, so the
        # border lies wholly inside the shape that is hit.
        half = style.border_width / 2
        centre_line = QPainterPath()
        radius = max(style.corner_radius - half, 0.0)
        centre_line.addRoundedRect(
            QRectF(element.x + half, element.y + half, element.width - style.border_width, element.height - style.border_width),
            radius,
            radius,
        )
        painter.strokePath(centre_line, QPen(_colour(style.border_colour), style.border_width))

    if element.bound is not None and element.bound.text:
        line = typography.shape(element.bound.text, style.type_weight)
        x, y = text_origin(element)
        scale = typography.reference_scale(style.type_size)
        painter.save()
        painter.translate(x, y)
        painter.scale(scale, scale)
        painter.fillPath(line.outline, _colour(style.text_colour))
        painter.restore()
