"""The reference layout: the deterministic function that writes the true scene.

This is the minimal version for the A, Reference tracer: one arrangement of the
document list (a header with the heading and the create button, a divider, a
panel of rows) in one set of plain style values. Visual presets, design
conditions and layout families replace the constants below when the generator
is built.

It returns a candidate scene as JSON data. It is not a scene until scene
validation accepts it. D, Neural Scene must run without this module loaded, so
nothing outside the scene session's A, Reference path may import it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core_ultra import typography
from core_ultra.documents_adapter import BoundElement
from core_ultra.scene import SCHEMA_VERSION

_MARGIN = 24.0
_HEADER_HEIGHT = 72.0
_BUTTON_HEIGHT = 36.0
_BUTTON_PADDING = 16.0
_ROW_HEIGHT = 44.0
_PANEL_INSET = 4.0

_CLEAR = [0.0, 0.0, 0.0, 0.0]
_PAGE = [0.96, 0.96, 0.97, 1.0]
_PANEL = [1.0, 1.0, 1.0, 1.0]
_LINE = [0.85, 0.85, 0.88, 1.0]
_INK = [0.10, 0.11, 0.13, 1.0]
_ON_ACCENT = [1.0, 1.0, 1.0, 1.0]
_ACCENT = [0.14, 0.37, 0.86, 1.0]
_ACCENT_HOVER = [0.24, 0.46, 0.92, 1.0]
_ACCENT_PRESSED = [0.09, 0.28, 0.70, 1.0]
_FOCUS_RING = [0.04, 0.16, 0.48, 1.0]
_ROW_HOVER = [0.93, 0.95, 0.99, 1.0]
_ROW_PRESSED = [0.86, 0.90, 0.98, 1.0]
_DISABLED_OPACITY = 0.4

_HEADING_TYPE = (22.0, 700.0)
_BUTTON_TYPE = (14.0, 500.0)
_ROW_TYPE = (15.0, 400.0)


def write_scene(bound_elements: Sequence[BoundElement], viewport: tuple[float, float]) -> dict[str, Any]:
    """The true scene for these bound elements at this viewport size."""
    width, height = viewport
    headings = [element for element in bound_elements if element.role == "heading"]
    buttons = [element for element in bound_elements if element.role == "button"]
    rows = [element for element in bound_elements if element.role == "list-item"]
    unknown = sorted({element.role for element in bound_elements} - {"heading", "button", "list-item"})
    if unknown or len(headings) != 1 or len(buttons) != 1:
        raise ValueError("the reference layout arranges one heading, one button and list items")

    elements = [
        _element("s.root", "surface", None, 0, 0, width, height, fill=_PAGE),
        _element("s.header", "container", "s.root", 0, 0, width, _HEADER_HEIGHT),
        _element("s.divider", "divider", "s.root", 0, _HEADER_HEIGHT, width, 1, fill=_LINE),
    ]

    heading = headings[0]
    size, weight = _HEADING_TYPE
    line = typography.line_height(size, weight)
    elements.append(
        _bound(
            heading,
            "s.header",
            _MARGIN,
            (_HEADER_HEIGHT - line) / 2,
            typography.measure(heading.text, size, weight),
            line,
            type_size=size,
            type_weight=weight,
        )
    )

    button = buttons[0]
    size, weight = _BUTTON_TYPE
    button_width = typography.measure(button.text, size, weight) + 2 * _BUTTON_PADDING
    elements.append(
        _bound(
            button,
            "s.header",
            width - _MARGIN - button_width,
            (_HEADER_HEIGHT - _BUTTON_HEIGHT) / 2,
            button_width,
            _BUTTON_HEIGHT,
            fill={"hover": _ACCENT_HOVER, "pressed": _ACCENT_PRESSED}.get(button.state, _ACCENT),
            text_colour=_ON_ACCENT,
            corner_radius=8,
            type_size=size,
            type_weight=weight,
        )
    )

    if rows:
        top = _HEADER_HEIGHT + _MARGIN
        elements.append(
            _element(
                "s.list",
                "panel",
                "s.root",
                _MARGIN,
                top,
                width - 2 * _MARGIN,
                len(rows) * _ROW_HEIGHT + 2 * _PANEL_INSET,
                fill=_PANEL,
                border_colour=_LINE,
                border_width=1,
                corner_radius=12,
            )
        )
        size, weight = _ROW_TYPE
        for index, row in enumerate(rows):
            elements.append(
                _bound(
                    row,
                    "s.list",
                    _MARGIN + _PANEL_INSET,
                    top + _PANEL_INSET + index * _ROW_HEIGHT,
                    width - 2 * (_MARGIN + _PANEL_INSET),
                    _ROW_HEIGHT,
                    fill={"hover": _ROW_HOVER, "pressed": _ROW_PRESSED}.get(row.state, _CLEAR),
                    corner_radius=8,
                    type_size=size,
                    type_weight=weight,
                )
            )

    return {
        "kind": "scene",
        "schema_version": SCHEMA_VERSION,
        "viewport": {"width": width, "height": height},
        "elements": elements,
    }


def _element(
    element_id: str,
    element_type: str,
    parent: str | None,
    x: float,
    y: float,
    width: float,
    height: float,
    **style: Any,
) -> dict[str, Any]:
    values = {
        "fill": _CLEAR,
        "text_colour": _INK,
        "border_colour": _CLEAR,
        "border_width": 0.0,
        "corner_radius": 0.0,
        "elevation": 0.0,
        "opacity": 1.0,
        "type_size": _ROW_TYPE[0],
        "type_weight": _ROW_TYPE[1],
    }
    values.update(style)
    return {
        "id": element_id,
        "type": element_type,
        "parent": parent,
        "box": {"x": float(x), "y": float(y), "width": float(width), "height": float(height)},
        "style": {name: list(value) if isinstance(value, list) else float(value) for name, value in values.items()},
    }


def _bound(element: BoundElement, parent: str, x: float, y: float, width: float, height: float, **style: Any) -> dict[str, Any]:
    """A bound element's entry. Its state changes style values only."""
    if element.state == "focused":
        style.update(border_colour=_FOCUS_RING, border_width=2)
    if element.state == "disabled":
        style.update(opacity=_DISABLED_OPACITY)
    item = _element(f"b.{element.identity}", "bound", parent, x, y, width, height, **style)
    item["bound"] = element.to_json()
    return item
