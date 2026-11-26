"""The reference layout: the deterministic function that writes the true scene.

Application state (as the adapter's bound elements), a viewport size, a visual
preset and a design condition go in; exactly one scene comes out. Nothing here
is random and nothing is read from anywhere else, so the same four always give
the same scene. A layout family is a named design condition
(`core_ultra.layout_family`), so the family is fixed by the condition.

`DRAWN` lists, for each design factor, the values this engine draws. Any
combination of them is drawn; a design condition with any other value is
refused, never drawn as something else.

| Factor | Value | What is drawn |
| --- | --- | --- |
| navigation position | `top` | The toolbar's six elements in a bar across the top: create, sort and the filter from the left, save and undo at the right. A divider under it. |
| | `bottom` | The same bar across the bottom, the divider above it. |
| | `left` | The toolbar's elements stacked in a rail down the left side, each as wide as the rail allows: create, sort and the filter from the top, save and undo at the foot. A divider beside it. The rail is as wide as the widest filter field plus a margin either side. |
| panel arrangement | `list-left` | The document list as a column on the left of the area the navigation leaves free, the editor filling the rest. |
| | `list-right` | The same column on the right, the editor on the left. |
| | `list-top` | The list across the top as a grid: as many columns of rows as fit at the narrowest list's width, filled row by row. The editor fills the rest below. |
| density | `compact`, `preset`, `roomy` | The visual preset's heights (toolbar, control, row, title, notification) times `DENSITY`. |
| spacing | `tight`, `preset`, `loose` | The visual preset's distances (margin, gap and the paddings) times `SPACING`. |
| notification location | `bottom-right`, `bottom-left`, `bottom-centre` | The notification three margins up from the lower edge of the area the navigation leaves free: three margins in from that corner, or centred. |

Every style value and every size comes from the visual preset
(`core_ultra.design`); density and spacing scale a whole group of its tokens
by one factor and decide nothing else.

The layout knows the bound elements only by what the adapter says of them: the
part of the workspace each belongs to, its role and the command its binding
names. It never changes them. An element's state changes style values only,
never its box.

Nothing is made to fit. A workspace too large for the viewport is written as
it falls, and scene validation reports it.

It returns a candidate scene as JSON data. It is not a scene until scene
validation accepts it. D, Neural Scene must run without this module loaded, so
only the scene session's A, Reference path and the generator may import it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from core_ultra import typography
from core_ultra.design import Component, VisualPreset
from core_ultra.documents_adapter import BoundElement
from core_ultra.layout_family import FACTORS, DesignCondition
from core_ultra.scene import SCHEMA_VERSION

# What a density or a spacing value multiplies the visual preset's tokens by.
DENSITY = {"compact": 0.85, "preset": 1.0, "roomy": 1.15}
SPACING = {"tight": 0.75, "preset": 1.0, "loose": 1.25}

# For each design factor, the values this engine draws.
DRAWN = {
    "navigation_position": ("top", "left", "bottom"),
    "panel_arrangement": ("list-left", "list-right", "list-top"),
    "density": tuple(DENSITY),
    "spacing": tuple(SPACING),
    "notification_location": ("bottom-right", "bottom-left", "bottom-centre"),
}

_CLEAR = [0.0, 0.0, 0.0, 0.0]


@dataclass(frozen=True)
class _Area:
    """The edges of the part of the viewport the navigation leaves free."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left


def write_scene(
    bound_elements: Sequence[BoundElement],
    viewport: tuple[float, float],
    preset: VisualPreset,
    condition: DesignCondition,
) -> dict[str, Any]:
    """The true scene for these bound elements at this viewport size, in this
    visual preset, under this design condition."""
    for factor in FACTORS:
        value = getattr(condition, factor)
        if value not in DRAWN[factor]:
            raise ValueError(
                f"the reference layout does not draw {factor} {value!r}; it draws {', '.join(DRAWN[factor])}"
            )
    width, height = viewport
    writer = _Writer(preset, condition)
    parts = _Parts(bound_elements)

    elements = [writer.structural("s.root", "surface", None, "page", 0, 0, width, height)]
    area, navigation = writer.navigation(parts, width, height, condition.navigation_position)
    elements += navigation
    elements += writer.panels(parts, area, condition.panel_arrangement)
    elements += writer.notification(parts, area, condition.notification_location)
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


class _Writer:
    """Writes the workspace's elements in one visual preset, at one density
    and spacing."""

    def __init__(self, preset: VisualPreset, condition: DesignCondition) -> None:
        self.preset = preset
        self.density = DENSITY[condition.density]
        self.spacing = SPACING[condition.spacing]
        self.margin = self.space("margin")
        self.gap = self.space("gap")

    def space(self, name: str) -> float:
        """One of the preset's distances at this spacing."""
        return self.preset.spacing[name] * self.spacing

    def high(self, component: Component) -> float:
        """A component's height at this density."""
        return component.height * self.density

    # --- navigation ---------------------------------------------------------

    def navigation(self, parts: _Parts, width: float, height: float, position: str) -> tuple[_Area, list[dict[str, Any]]]:
        """The toolbar's container, its divider and its elements, and the area
        they leave free."""
        divider = self.preset.component("divider").height
        if position == "left":
            rail = self.preset.dimensions["filter-width-max"] + 2 * self.margin
            placed = [
                self.structural("s.toolbar", "container", "s.root", "toolbar", 0, 0, rail, height),
                self.structural("s.divider", "divider", "s.root", "divider", rail, 0, divider, height),
                *self.rail(parts, rail, height),
            ]
            return _Area(rail, 0.0, width, height), placed
        bar = self.high(self.preset.component("toolbar"))
        if position == "top":
            bar_y, divider_y, area = 0.0, bar, _Area(0.0, bar, width, height)
        else:
            bar_y, divider_y, area = height - bar, height - bar - divider, _Area(0.0, 0.0, width, height - bar)
        placed = [
            self.structural("s.toolbar", "container", "s.root", "toolbar", 0, bar_y, width, bar),
            self.structural("s.divider", "divider", "s.root", "divider", 0, divider_y, width, divider),
            *self.bar(parts, width, bar_y, bar),
        ]
        return area, placed

    def _toolbar_elements(self, parts: _Parts) -> tuple[BoundElement, ...]:
        return (
            parts.one("toolbar", "button", "create"),
            parts.one("toolbar", "button", "sort"),
            parts.one("toolbar", "label"),
            parts.one("toolbar", "text-field", "filter"),
            parts.one("toolbar", "button", "save"),
            parts.one("toolbar", "button", "undo"),
        )

    def _button(self, element: BoundElement) -> Component:
        return self.preset.component("button-primary" if element.binding["command"] == "create" else "button-quiet")

    def bar(self, parts: _Parts, width: float, bar_y: float, bar: float) -> list[dict[str, Any]]:
        """The toolbar's elements in a row, each centred on the bar's height."""
        create, sort, label, field, save, undo = self._toolbar_elements(parts)

        def button_width(element: BoundElement) -> float:
            component = self._button(element)
            return typography.measure(element.text, *component.type) + 2 * (component.padding * self.spacing)

        def place_button(element: BoundElement, x: float) -> dict[str, Any]:
            high = self.high(self._button(element))
            return self.bound(element, self._button(element), "s.toolbar", x, bar_y + (bar - high) / 2, button_width(element), high)

        placed = []
        x = self.margin
        for element in (create, sort):
            placed.append(place_button(element, x))
            x += button_width(element) + self.gap

        text = self.preset.component("label")
        line = typography.line_height(*text.type)
        label_width = typography.measure(label.text, *text.type)
        placed.append(self.bound(label, text, "s.toolbar", x, bar_y + (bar - line) / 2, label_width, line))
        x += label_width + self.gap

        # The filter field takes the room left before Save and Undo, within its
        # limits. Save and Undo sit at the right edge when there is room to spare.
        box = self.preset.component("field")
        sizes = self.preset.dimensions
        trailing = button_width(save) + self.gap + button_width(undo)
        field_width = min(max(width - self.margin - trailing - self.gap - x, sizes["filter-width-min"]), sizes["filter-width-max"])
        placed.append(self.bound(field, box, "s.toolbar", x, bar_y + (bar - self.high(box)) / 2, field_width, self.high(box)))
        x = max(x + field_width + self.gap, width - self.margin - trailing)
        placed.append(place_button(save, x))
        placed.append(place_button(undo, x + button_width(save) + self.gap))
        return placed

    def rail(self, parts: _Parts, rail: float, height: float) -> list[dict[str, Any]]:
        """The toolbar's elements in a column, each as wide as the rail's inside: create,
        sort and the filter from the top, save and undo at the foot."""
        create, sort, label, field, save, undo = self._toolbar_elements(parts)
        x, inside = self.margin, rail - 2 * self.margin

        placed = []
        y = self.margin
        for element in (create, sort):
            high = self.high(self._button(element))
            placed.append(self.bound(element, self._button(element), "s.toolbar", x, y, inside, high))
            y += high + self.gap

        text = self.preset.component("label")
        line = typography.line_height(*text.type)
        placed.append(self.bound(label, text, "s.toolbar", x, y, typography.measure(label.text, *text.type), line))
        y += line + self.gap
        box = self.preset.component("field")
        placed.append(self.bound(field, box, "s.toolbar", x, y, inside, self.high(box)))

        undo_high, save_high = self.high(self._button(undo)), self.high(self._button(save))
        undo_y = height - self.margin - undo_high
        placed.append(self.bound(save, self._button(save), "s.toolbar", x, undo_y - self.gap - save_high, inside, save_high))
        placed.append(self.bound(undo, self._button(undo), "s.toolbar", x, undo_y, inside, undo_high))
        return placed

    # --- the list and the editor --------------------------------------------

    def panels(self, parts: _Parts, area: _Area, arrangement: str) -> list[dict[str, Any]]:
        """The document list and the editor, inside the area the navigation leaves free."""
        sizes = self.preset.dimensions
        top = area.top + self.margin
        list_width = min(max(sizes["list-share"] * area.width, sizes["list-width-min"]), sizes["list-width-max"])
        if arrangement == "list-left":
            listed = self.list(parts, area.left + self.margin, top, list_width, 1)
            editor_x = area.left + (2 * self.margin + list_width)
            return listed + self.editor(parts, editor_x, top, area.right - editor_x - self.margin, area.bottom - top - self.margin)
        if arrangement == "list-right":
            list_x = area.right - self.margin - list_width
            listed = self.list(parts, list_x, top, list_width, 1)
            editor_x = area.left + self.margin
            return listed + self.editor(parts, editor_x, top, list_x - self.margin - editor_x, area.bottom - top - self.margin)
        # list-top: a grid as wide as the area, the editor under it.
        x, wide = area.left + self.margin, area.width - 2 * self.margin
        inset = self.space("row-inset")
        narrowest = sizes["list-width-min"] - 2 * inset
        columns = max(1, math.floor((wide - 2 * inset + self.gap) / (narrowest + self.gap)))
        listed = self.list(parts, x, top, wide, columns)
        panel = listed[0]["box"]
        editor_y = panel["y"] + panel["height"] + self.margin
        return listed + self.editor(parts, x, editor_y, wide, area.bottom - self.margin - editor_y)

    def list(self, parts: _Parts, x: float, top: float, list_width: float, columns: int) -> list[dict[str, Any]]:
        """The list's panel, as tall as what it holds, then its heading and its
        rows in `columns` columns, filled row by row."""
        heading = parts.one("list", "heading")
        rows = parts.take("list", "list-item", "open")
        empty = parts.take("list", "label")
        row, row_open = self.preset.component("row"), self.preset.component("row-open")
        inset, padding = self.space("row-inset"), self.space("panel-padding")

        row_x = x + inset
        # Headings and labels start where a row's text starts.
        text_x = row_x + (self.high(row) - typography.line_height(*row.type)) / 2

        title = self.preset.component("heading")
        line = typography.line_height(*title.type)
        y = top + padding
        placed = [self.bound(heading, title, "s.list", text_x, y, typography.measure(heading.text, *title.type), line)]
        y += line + self.gap

        row_width = (list_width - 2 * inset - (columns - 1) * self.gap) / columns
        for index, element in enumerate(rows):
            is_open = any(relationship["relation"] == "shown_in" for relationship in element.relationships)
            component = row_open if is_open else row
            column = index % columns
            placed.append(self.bound(element, component, "s.list", row_x + column * (row_width + self.gap), y, row_width, self.high(component)))
            if column == columns - 1 or index == len(rows) - 1:
                y += self.high(component)
        if rows:
            y += inset

        text = self.preset.component("label")
        for label in empty:
            line = typography.line_height(*text.type)
            placed.append(self.bound(label, text, "s.list", text_x, y, typography.measure(label.text, *text.type), line))
            y += line + padding

        panel = self.structural("s.list", "panel", "s.root", "panel", x, top, list_width, y - top)
        return [panel, *placed]

    def editor(self, parts: _Parts, x: float, y: float, width: float, height: float) -> list[dict[str, Any]]:
        panel = self.structural("s.editor", "panel", "s.root", "panel", x, y, width, height)
        areas = parts.take("editor", "text-area", "edit")
        text = self.preset.component("label")
        line = typography.line_height(*text.type)

        if not areas:
            label = parts.one("editor", "label")
            label_width = typography.measure(label.text, *text.type)
            return [panel, self.bound(label, text, "s.editor", x + (width - label_width) / 2, y + (height - line) / 2, label_width, line)]

        (body,) = areas
        title = parts.one("editor", "text-field", "rename")
        revision = parts.one("editor", "label")
        title_field = self.preset.component("title-field")
        padding = self.space("editor-padding")
        title_high = self.high(title_field)
        inner_x = x + padding
        inner_width = width - 2 * padding
        revision_y = y + padding + title_high + self.gap
        body_y = revision_y + line + self.gap
        return [
            panel,
            self.bound(title, title_field, "s.editor", inner_x, y + padding, inner_width, title_high),
            self.bound(revision, text, "s.editor", inner_x, revision_y, typography.measure(revision.text, *text.type), line),
            self.bound(
                body, self.preset.component("editor-body"), "s.editor", inner_x, body_y, inner_width, y + height - padding - body_y
            ),
        ]

    def notification(self, parts: _Parts, area: _Area, location: str) -> list[dict[str, Any]]:
        component = self.preset.component("notification")
        high = self.high(component)
        placed = []
        for status in parts.take("notification", "status"):
            # As wide as its text plus the inset the runtime renderer gives a
            # line of text: as far from the left edge as from the top.
            inset = (high - typography.line_height(*component.type)) / 2
            box_width = typography.measure(status.text, *component.type) + 2 * inset
            if location == "bottom-left":
                x = area.left + 3 * self.margin
            elif location == "bottom-centre":
                x = area.left + (area.width - box_width) / 2
            else:
                x = area.right - 3 * self.margin - box_width
            placed.append(self.bound(status, component, "s.root", x, area.bottom - 3 * self.margin - high, box_width, high))
        return placed

    def structural(
        self, element_id: str, element_type: str, parent: str | None, component: str, x: float, y: float, width: float, height: float
    ) -> dict[str, Any]:
        return self._element(element_id, element_type, parent, x, y, width, height, self.preset.component(component).style())

    def bound(
        self, element: BoundElement, component: Component, parent: str, x: float, y: float, width: float, height: float
    ) -> dict[str, Any]:
        """A bound element's entry. Its state changes style values only."""
        item = self._element(f"b.{element.identity}", "bound", parent, x, y, width, height, component.style(element.state))
        item["bound"] = element.to_json()
        return item

    def _element(
        self, element_id: str, element_type: str, parent: str | None, x: float, y: float, width: float, height: float, style: dict[str, Any]
    ) -> dict[str, Any]:
        """An element with every style value: what its component states, and
        for the rest no fill, no border, no shadow, full opacity and the
        preset's body text."""
        size, weight = self.preset.type["body"]
        values = {
            "fill": _CLEAR,
            "text_colour": list(self.preset.colours["ink"]),
            "border_colour": _CLEAR,
            "border_width": 0.0,
            "corner_radius": 0.0,
            "elevation": 0.0,
            "opacity": 1.0,
            "type_size": size,
            "type_weight": weight,
        }
        values.update(style)
        return {
            "id": element_id,
            "type": element_type,
            "parent": parent,
            "box": {"x": float(x), "y": float(y), "width": float(width), "height": float(height)},
            "style": {name: list(value) if isinstance(value, list) else float(value) for name, value in values.items()},
        }
