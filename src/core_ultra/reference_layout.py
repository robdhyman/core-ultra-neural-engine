"""The reference layout: the deterministic function that writes the true scene.

One arrangement of the document workspace in one set of plain style values: a
toolbar across the top, the document list on the left, the editor filling the
rest, and the notification over the lower right corner. Visual presets, design
conditions and layout families replace the constants below when the generator
is built.

The layout knows the bound elements only by what the adapter says of them: the
part of the workspace each belongs to, its role and the command its binding
names. It never changes them. An element's state changes style values only,
never its box.

Nothing is made to fit. A workspace too large for the viewport is written as
it falls, and scene validation reports it.

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

_MARGIN = 16.0
_GAP = 8.0
_TOOLBAR_HEIGHT = 56.0
_CONTROL_HEIGHT = 36.0
_BUTTON_PADDING = 14.0
_FILTER_WIDTH = (96.0, 240.0)
_LIST_SHARE = 0.34
_LIST_WIDTH = (220.0, 320.0)
_ROW_HEIGHT = 40.0
_ROW_INSET = 4.0
_PANEL_PADDING = 12.0
_EDITOR_PADDING = 16.0
_TITLE_HEIGHT = 40.0
_NOTIFICATION_HEIGHT = 40.0

_CLEAR = [0.0, 0.0, 0.0, 0.0]
_PAGE = [0.95, 0.95, 0.96, 1.0]
_SURFACE = [1.0, 1.0, 1.0, 1.0]
_WELL = [0.98, 0.98, 0.99, 1.0]
_LINE = [0.85, 0.85, 0.88, 1.0]
_FIELD_LINE = [0.72, 0.74, 0.79, 1.0]
_FIELD_LINE_HOVER = [0.48, 0.51, 0.58, 1.0]
_FIELD_PRESSED = [0.94, 0.96, 0.99, 1.0]
_INK = [0.10, 0.11, 0.13, 1.0]
_MUTED = [0.40, 0.42, 0.47, 1.0]
_ON_ACCENT = [1.0, 1.0, 1.0, 1.0]
_ACCENT = [0.14, 0.37, 0.86, 1.0]
_ACCENT_HOVER = [0.24, 0.46, 0.92, 1.0]
_ACCENT_PRESSED = [0.09, 0.28, 0.70, 1.0]
_QUIET = [0.93, 0.94, 0.96, 1.0]
_QUIET_HOVER = [0.88, 0.90, 0.93, 1.0]
_QUIET_PRESSED = [0.82, 0.84, 0.89, 1.0]
_FOCUS_RING = [0.04, 0.16, 0.48, 1.0]
_ROW_OPEN = [0.90, 0.93, 0.99, 1.0]
_ROW_HOVER = [0.93, 0.95, 0.99, 1.0]
_ROW_PRESSED = [0.84, 0.88, 0.97, 1.0]
_NOTIFICATION = [0.13, 0.14, 0.17, 1.0]
_DISABLED_OPACITY = 0.4

_HEADING_TYPE = (20.0, 700.0)
_BUTTON_TYPE = (14.0, 500.0)
_ROW_TYPE = (15.0, 400.0)
_ROW_OPEN_WEIGHT = 500.0
_TITLE_TYPE = (18.0, 500.0)
_LABEL_TYPE = (13.0, 400.0)
_BODY_TYPE = (15.0, 400.0)
_NOTIFICATION_TYPE = (14.0, 500.0)

_PANEL = {"fill": _SURFACE, "border_colour": _LINE, "border_width": 1, "corner_radius": 12, "elevation": 2}


def write_scene(bound_elements: Sequence[BoundElement], viewport: tuple[float, float]) -> dict[str, Any]:
    """The true scene for these bound elements at this viewport size."""
    width, height = viewport
    parts = _Parts(bound_elements)
    top = _TOOLBAR_HEIGHT + _MARGIN
    list_width = min(max(_LIST_SHARE * width, _LIST_WIDTH[0]), _LIST_WIDTH[1])

    elements = [
        _element("s.root", "surface", None, 0, 0, width, height, fill=_PAGE),
        _element("s.toolbar", "container", "s.root", 0, 0, width, _TOOLBAR_HEIGHT, fill=_SURFACE),
        _element("s.divider", "divider", "s.root", 0, _TOOLBAR_HEIGHT, width, 1, fill=_LINE),
    ]
    elements += _toolbar(parts, width)
    elements += _list(parts, top, list_width)
    editor_x = 2 * _MARGIN + list_width
    elements += _editor(parts, editor_x, top, width - editor_x - _MARGIN, height - top - _MARGIN)
    elements += _notification(parts, width, height)
    parts.require_all_placed()

    return {
        "kind": "scene",
        "schema_version": SCHEMA_VERSION,
        "viewport": {"width": width, "height": height},
        "elements": elements,
    }


class _Parts:
    """The bound elements, found by workspace part, role and binding command."""

    def __init__(self, bound_elements: Sequence[BoundElement]) -> None:
        self._remaining = list(bound_elements)

    def take(self, part: str, role: str, command: str | None = None) -> list[BoundElement]:
        found = [
            element
            for element in self._remaining
            if element.role == role
            and (element.binding or {}).get("command") == command
            and {"relation": "part_of", "target": f"workspace.{part}"} in [dict(r) for r in element.relationships]
        ]
        self._remaining = [element for element in self._remaining if element not in found]
        return found

    def one(self, part: str, role: str, command: str | None = None) -> BoundElement:
        found = self.take(part, role, command)
        if len(found) != 1:
            raise ValueError(f"the reference layout places exactly one {command or ''} {role} in the {part}".replace("  ", " "))
        return found[0]

    def require_all_placed(self) -> None:
        if self._remaining:
            names = ", ".join(element.identity for element in self._remaining)
            raise ValueError(f"the reference layout has no place for: {names}")


def _toolbar(parts: _Parts, width: float) -> list[dict[str, Any]]:
    create = parts.one("toolbar", "button", "create")
    sort = parts.one("toolbar", "button", "sort")
    label = parts.one("toolbar", "label")
    field = parts.one("toolbar", "text-field", "filter")
    save = parts.one("toolbar", "button", "save")
    undo = parts.one("toolbar", "button", "undo")

    y = (_TOOLBAR_HEIGHT - _CONTROL_HEIGHT) / 2
    size, weight = _BUTTON_TYPE

    def button_width(element: BoundElement) -> float:
        return typography.measure(element.text, size, weight) + 2 * _BUTTON_PADDING

    placed = []
    x = _MARGIN
    for element in (create, sort):
        placed.append(_button(element, x, y, button_width(element)))
        x += button_width(element) + _GAP

    label_size, label_weight = _LABEL_TYPE
    line = typography.line_height(label_size, label_weight)
    label_width = typography.measure(label.text, label_size, label_weight)
    placed.append(
        _bound(
            label, "s.toolbar", x, (_TOOLBAR_HEIGHT - line) / 2, label_width, line,
            text_colour=_MUTED, type_size=label_size, type_weight=label_weight,
        )
    )
    x += label_width + _GAP

    # The filter field takes the room left before Save and Undo, within its
    # limits. Save and Undo sit at the right edge when there is room to spare.
    trailing = button_width(save) + _GAP + button_width(undo)
    field_width = min(max(width - _MARGIN - trailing - _GAP - x, _FILTER_WIDTH[0]), _FILTER_WIDTH[1])
    placed.append(_field(field, "s.toolbar", x, y, field_width, _CONTROL_HEIGHT, _ROW_TYPE))
    x = max(x + field_width + _GAP, width - _MARGIN - trailing)
    placed.append(_button(save, x, y, button_width(save)))
    placed.append(_button(undo, x + button_width(save) + _GAP, y, button_width(undo)))
    return placed


def _button(element: BoundElement, x: float, y: float, width: float) -> dict[str, Any]:
    size, weight = _BUTTON_TYPE
    if element.binding["command"] == "create":
        style = {"fill": _ACCENT, "text_colour": _ON_ACCENT}
        states = {"hover": {"fill": _ACCENT_HOVER}, "pressed": {"fill": _ACCENT_PRESSED}}
    else:
        style = {"fill": _QUIET, "border_colour": _LINE, "border_width": 1}
        states = {"hover": {"fill": _QUIET_HOVER}, "pressed": {"fill": _QUIET_PRESSED}}
    return _bound(
        element, "s.toolbar", x, y, width, _CONTROL_HEIGHT, states,
        corner_radius=8, type_size=size, type_weight=weight, **style,
    )


def _field(
    element: BoundElement, parent: str, x: float, y: float, width: float, height: float, type_: tuple[float, float], fill: list[float] = _SURFACE
) -> dict[str, Any]:
    return _bound(
        element, parent, x, y, width, height,
        {"hover": {"border_colour": _FIELD_LINE_HOVER}, "pressed": {"fill": _FIELD_PRESSED}},
        fill=fill, border_colour=_FIELD_LINE, border_width=1, corner_radius=8, type_size=type_[0], type_weight=type_[1],
    )


def _list(parts: _Parts, top: float, list_width: float) -> list[dict[str, Any]]:
    heading = parts.one("list", "heading")
    rows = parts.take("list", "list-item", "open")
    empty = parts.take("list", "label")

    row_size, row_weight = _ROW_TYPE
    row_x = _MARGIN + _ROW_INSET
    # Headings and labels start where a row's text starts.
    text_x = row_x + (_ROW_HEIGHT - typography.line_height(row_size, row_weight)) / 2

    size, weight = _HEADING_TYPE
    line = typography.line_height(size, weight)
    y = top + _PANEL_PADDING
    placed = [
        _bound(
            heading, "s.list", text_x, y, typography.measure(heading.text, size, weight), line,
            type_size=size, type_weight=weight,
        )
    ]
    y += line + _GAP

    for row in rows:
        style: dict[str, Any] = {"fill": _CLEAR, "type_weight": row_weight}
        if any(relationship["relation"] == "shown_in" for relationship in row.relationships):
            style = {"fill": _ROW_OPEN, "type_weight": _ROW_OPEN_WEIGHT}
        placed.append(
            _bound(
                row, "s.list", row_x, y, list_width - 2 * _ROW_INSET, _ROW_HEIGHT,
                {"hover": {"fill": _ROW_HOVER}, "pressed": {"fill": _ROW_PRESSED}},
                corner_radius=8, type_size=row_size, **style,
            )
        )
        y += _ROW_HEIGHT
    if rows:
        y += _ROW_INSET

    size, weight = _LABEL_TYPE
    for label in empty:
        line = typography.line_height(size, weight)
        placed.append(
            _bound(
                label, "s.list", text_x, y, typography.measure(label.text, size, weight), line,
                text_colour=_MUTED, type_size=size, type_weight=weight,
            )
        )
        y += line + _PANEL_PADDING

    panel = _element("s.list", "panel", "s.root", _MARGIN, top, list_width, y - top, **_PANEL)
    return [panel, *placed]


def _editor(parts: _Parts, x: float, y: float, width: float, height: float) -> list[dict[str, Any]]:
    panel = _element("s.editor", "panel", "s.root", x, y, width, height, **_PANEL)
    areas = parts.take("editor", "text-area", "edit")
    size, weight = _LABEL_TYPE
    line = typography.line_height(size, weight)

    if not areas:
        label = parts.one("editor", "label")
        label_width = typography.measure(label.text, size, weight)
        return [
            panel,
            _bound(
                label, "s.editor", x + (width - label_width) / 2, y + (height - line) / 2, label_width, line,
                text_colour=_MUTED, type_size=size, type_weight=weight,
            ),
        ]

    (body,) = areas
    title = parts.one("editor", "text-field", "rename")
    revision = parts.one("editor", "label")
    inner_x = x + _EDITOR_PADDING
    inner_width = width - 2 * _EDITOR_PADDING
    revision_y = y + _EDITOR_PADDING + _TITLE_HEIGHT + _GAP
    body_y = revision_y + line + _GAP
    return [
        panel,
        _field(title, "s.editor", inner_x, y + _EDITOR_PADDING, inner_width, _TITLE_HEIGHT, _TITLE_TYPE),
        _bound(
            revision, "s.editor", inner_x, revision_y, typography.measure(revision.text, size, weight), line,
            text_colour=_MUTED, type_size=size, type_weight=weight,
        ),
        _field(
            body, "s.editor", inner_x, body_y, inner_width, y + height - _EDITOR_PADDING - body_y, _BODY_TYPE, fill=_WELL
        ),
    ]


def _notification(parts: _Parts, width: float, height: float) -> list[dict[str, Any]]:
    size, weight = _NOTIFICATION_TYPE
    placed = []
    for status in parts.take("notification", "status"):
        # As wide as its text plus the inset the runtime renderer gives a line
        # of text: as far from the left edge as from the top.
        inset = (_NOTIFICATION_HEIGHT - typography.line_height(size, weight)) / 2
        box_width = typography.measure(status.text, size, weight) + 2 * inset
        placed.append(
            _bound(
                status, "s.root", width - 3 * _MARGIN - box_width, height - 3 * _MARGIN - _NOTIFICATION_HEIGHT,
                box_width, _NOTIFICATION_HEIGHT,
                fill=_NOTIFICATION, text_colour=_ON_ACCENT, corner_radius=10, elevation=8,
                type_size=size, type_weight=weight,
            )
        )
    return placed


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


def _bound(
    element: BoundElement,
    parent: str,
    x: float,
    y: float,
    width: float,
    height: float,
    states: dict[str, dict[str, Any]] | None = None,
    **style: Any,
) -> dict[str, Any]:
    """A bound element's entry. Its state changes style values only."""
    style.update((states or {}).get(element.state, {}))
    if element.state == "focused":
        style.update(border_colour=_FOCUS_RING, border_width=2)
    if element.state == "disabled":
        style.update(opacity=_DISABLED_OPACITY)
    item = _element(f"b.{element.identity}", "bound", parent, x, y, width, height, **style)
    item["bound"] = element.to_json()
    return item
