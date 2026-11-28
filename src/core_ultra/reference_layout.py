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
| navigation position | `top` | The toolbar's six elements in a bar across the top, in the order create, sort, the filter, save, undo. A divider under it. |
| | `bottom` | The same bar across the bottom, the divider above it. |
| | `left` | The toolbar's elements stacked in a rail down the left side: create, sort and the filter from the top, save and undo at the foot. A divider beside it. The rail is as wide as the widest filter field plus a margin either side. |
| panel arrangement | `list-left` | The document list as a column on the left of the area the navigation leaves free, the editor filling the rest. |
| | `list-right` | The same column on the right, the editor on the left. |
| | `list-top` | The list across the top as a grid: as many columns of rows as fit at the narrowest list's width, filled row by row. The editor fills the rest below. |
| density | `compact`, `preset`, `roomy` | The visual preset's heights (toolbar, control, row, title, notification) times `DENSITY`. Where the layout declares a least text inset, `compact` stops short of it: see below. |
| spacing | `tight`, `preset`, `loose` | The visual preset's distances (margin, gap and the paddings) times `SPACING`. |
| notification location | `bottom-right`, `bottom-left`, `bottom-centre` | The notification three margins up from the lower edge of the area the navigation leaves free: three margins in from that corner, or centred. |
| grouping | `parts` | One container for each part of the workspace: the toolbar's, a panel for the list and a panel for the editor. |
| | `tasks` | The toolbar's elements in two containers inside the toolbar's: create, sort and the filter, which act on the documents, and save and undo, which act on the work in hand. A divider is drawn between the two. |
| | `sheet` | The list and the editor on one panel, with a divider between them, in place of a panel each. |
| alignment | `justified` | The toolbar's elements at both ends of a bar, save and undo at the right; across a rail, each as wide as the rail allows. The list's heading, the label of an empty list and the editor's revision at the left. |
| | `start` | The toolbar's elements packed from the left of a bar; in a rail each button as wide as its text, at the left. Heading, label and revision at the left. |
| | `centre` | The run of the toolbar's elements centred in a bar; in a rail each button as wide as its text, in the middle. Heading, label and revision centred in their part. |

Grouping changes which container holds an element and no bound element's box.
Alignment moves boxes and changes no element's container. Where text sits
inside its own box is the runtime renderer's rule and no factor changes it.
A design condition from a layout that declares no grouping or no alignment
is drawn in `parts` and `justified`, which is what the engine drew before
those factors existed.

Every style value and every size comes from the visual preset
(`core_ultra.design`); density and spacing scale a whole group of its tokens
by one factor and decide nothing else.

The least text inset. The runtime renderer starts a text as far from the left
edge of its box as the line is from the top, so a low box sets its text near
its edge. A layout may declare `least_text_inset`, in viewport units. Then
`compact` lowers an element that holds text only as far as leaves that much
above and below its line, and so that much before it, and never makes it
higher than the visual preset states: a preset already tighter than the
inset is drawn at its own heights. An element without text, the toolbar's bar
among them, is scaled as before, and so are `preset` and `roomy`. A layout
that declares none is drawn as before the rule existed.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from core_ultra import typography
from core_ultra.design import Component, VisualPreset
from core_ultra.documents_adapter import BoundElement
from core_ultra.layout_family import FACTORS, DesignCondition
from core_ultra.scene import SCHEMA_VERSION

# What a density or a spacing value multiplies the visual preset's tokens by.
DENSITY = {"compact": 0.85, "preset": 1.0, "roomy": 1.15}
SPACING = {"tight": 0.75, "preset": 1.0, "loose": 1.25}

# How the scene's elements are grouped into containers, and where an element
# narrower than the room it has is put. The first of each is what the engine
# drew before the factor existed, and what it draws for a design condition
# whose layout does not declare the factor.
GROUPING = ("parts", "tasks", "sheet")
ALIGNMENT = ("justified", "start", "centre")

# For each design factor, the values this engine draws.
DRAWN = {
    "navigation_position": ("top", "left", "bottom"),
    "panel_arrangement": ("list-left", "list-right", "list-top"),
    "density": tuple(DENSITY),
    "spacing": tuple(SPACING),
    "notification_location": ("bottom-right", "bottom-left", "bottom-centre"),
    "grouping": GROUPING,
    "alignment": ALIGNMENT,
}
UNDECLARED = {"grouping": GROUPING[0], "alignment": ALIGNMENT[0]}

_CLEAR = [0.0, 0.0, 0.0, 0.0]


class _Placed(NamedTuple):
    """A bound element with the component it is drawn as and its box."""

    element: BoundElement
    component: Component
    x: float
    y: float
    width: float
    height: float


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
    least_text_inset: float = 0.0,
) -> dict[str, Any]:
    """The true scene for these bound elements at this viewport size, in this
    visual preset, under this design condition. `least_text_inset` is the
    layout's (`Layout.least_text_inset`); zero is a layout that declares none."""
    values = {}
    for factor in FACTORS:
        value = getattr(condition, factor)
        if value is None and factor in UNDECLARED:
            value = UNDECLARED[factor]
        if value not in DRAWN[factor]:
            raise ValueError(
                f"the reference layout does not draw {factor} {value!r}; it draws {', '.join(DRAWN[factor])}"
            )
        values[factor] = value
    width, height = viewport
    writer = _Writer(preset, values, least_text_inset)
    parts = _Parts(bound_elements)

    elements = [writer.structural("s.root", "surface", None, "page", 0, 0, width, height)]
    area, navigation = writer.navigation(parts, width, height, values["navigation_position"])
    elements += navigation
    elements += writer.panels(parts, area, values["panel_arrangement"])
    elements += writer.notification(parts, area, values["notification_location"])
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
    and spacing, in one grouping and alignment."""

    def __init__(self, preset: VisualPreset, values: Mapping[str, str], least_text_inset: float = 0.0) -> None:
        """`values` is a value for each of `FACTORS`, every one of them drawn."""
        self.preset = preset
        self.least_text_inset = least_text_inset
        self.density = DENSITY[values["density"]]
        self.spacing = SPACING[values["spacing"]]
        self.grouping = values["grouping"]
        self.alignment = values["alignment"]
        self.margin = self.space("margin")
        self.gap = self.space("gap")

    def space(self, name: str) -> float:
        """One of the preset's distances at this spacing."""
        return self.preset.spacing[name] * self.spacing

    def high(self, component: Component) -> float:
        """A component's height at this density. Under a least text inset, a
        component that holds text is lowered no further than leaves that much
        above and below its line, and is never made higher than the preset
        states."""
        high = component.height * self.density
        if self.least_text_inset > 0 and self.density < 1 and component.type is not None:
            floor = typography.line_height(*component.type) + 2 * self.least_text_inset
            high = max(high, min(component.height, floor))
        return high

    def aligned(self, start: float, room: float, width: float) -> float:
        """Where something `width` wide begins in `room`: at its start, or in
        its middle when the alignment is `centre`."""
        return start + (room - width) / 2 if self.alignment == "centre" else start

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

    def _button_width(self, element: BoundElement) -> float:
        """A button as wide as its text and its padding."""
        component = self._button(element)
        return typography.measure(element.text, *component.type) + 2 * (component.padding * self.spacing)

    def bar(self, parts: _Parts, width: float, bar_y: float, bar: float) -> list[dict[str, Any]]:
        """The toolbar's elements in a row, each centred on the bar's height.

        Create, sort and the filter run from the left. `justified` puts save
        and undo at the right edge when there is room to spare; `start` lets
        them follow the filter; `centre` does the same and centres the run of
        six in the bar.
        """
        create, sort, label, field, save, undo = self._toolbar_elements(parts)
        text = self.preset.component("label")
        box = self.preset.component("field")
        line = typography.line_height(*text.type)
        sizes = self.preset.dimensions

        def placed(element: BoundElement, component: Component, x: float, wide: float, high: float) -> _Placed:
            return _Placed(element, component, x, bar_y + (bar - high) / 2, wide, high)

        leading = []
        x = self.margin
        for element in (create, sort):
            leading.append(placed(element, self._button(element), x, self._button_width(element), self.high(self._button(element))))
            x += self._button_width(element) + self.gap
        label_width = typography.measure(label.text, *text.type)
        leading.append(placed(label, text, x, label_width, line))
        x += label_width + self.gap

        # The filter field takes the room left before save and undo, within its limits.
        trailing_width = self._button_width(save) + self.gap + self._button_width(undo)
        field_width = min(max(width - self.margin - trailing_width - self.gap - x, sizes["filter-width-min"]), sizes["filter-width-max"])
        leading.append(placed(field, box, x, field_width, self.high(box)))
        packed = x + field_width + self.gap
        x = max(packed, width - self.margin - trailing_width) if self.alignment == "justified" else packed
        trailing = [
            placed(save, self._button(save), x, self._button_width(save), self.high(self._button(save))),
            placed(undo, self._button(undo), x + self._button_width(save) + self.gap, self._button_width(undo), self.high(self._button(undo))),
        ]

        if self.alignment == "centre":
            # As much room before the run as after it.
            shift = max((width - self.margin - (x + trailing_width)) / 2, 0.0)
            leading = [item._replace(x=item.x + shift) for item in leading]
            trailing = [item._replace(x=item.x + shift) for item in trailing]

        # For the grouping `tasks`: two containers, each as wide as what it
        # holds and as high as the bar, and a divider as high as a button
        # half a gap before the second.
        thick = self.preset.component("divider").height
        tall = self.high(self._button(save))
        first, last = leading[0], leading[-1]
        save_x, end = trailing[0].x, trailing[-1].x + trailing[-1].width
        return self._toolbar(
            leading,
            trailing,
            documents=(first.x, bar_y, last.x + last.width - first.x, bar),
            divider=(save_x - self.gap / 2 - thick / 2, bar_y + (bar - tall) / 2, thick, tall),
            editing=(save_x, bar_y, end - save_x, bar),
        )

    def rail(self, parts: _Parts, rail: float, height: float) -> list[dict[str, Any]]:
        """The toolbar's elements in a column: create, sort and the filter
        from the top, save and undo at the foot.

        `justified` gives every button the rail's inside width. `start` and
        `centre` leave a button as wide as its text, at the rail's left or in
        its middle. The filter field always has the inside width.
        """
        create, sort, label, field, save, undo = self._toolbar_elements(parts)
        left, inside = self.margin, rail - 2 * self.margin

        def button(element: BoundElement, y: float) -> _Placed:
            component = self._button(element)
            if self.alignment == "justified":
                return _Placed(element, component, left, y, inside, self.high(component))
            wide = self._button_width(element)
            return _Placed(element, component, self.aligned(left, inside, wide), y, wide, self.high(component))

        leading = []
        y = self.margin
        for element in (create, sort):
            leading.append(button(element, y))
            y += leading[-1].height + self.gap

        text = self.preset.component("label")
        line = typography.line_height(*text.type)
        label_width = typography.measure(label.text, *text.type)
        leading.append(_Placed(label, text, self.aligned(left, inside, label_width), y, label_width, line))
        y += line + self.gap
        box = self.preset.component("field")
        leading.append(_Placed(field, box, left, y, inside, self.high(box)))
        head_bottom = y + self.high(box)

        undo_high, save_high = self.high(self._button(undo)), self.high(self._button(save))
        undo_y = height - self.margin - undo_high
        save_y = undo_y - self.gap - save_high
        trailing = [button(save, save_y), button(undo, undo_y)]

        # For the grouping `tasks`: two containers, each as wide as the
        # rail's inside and as high as what it holds, and a divider across
        # the rail half a gap above the second.
        thick = self.preset.component("divider").height
        return self._toolbar(
            leading,
            trailing,
            documents=(left, self.margin, inside, head_bottom - self.margin),
            divider=(left, save_y - self.gap / 2 - thick / 2, inside, thick),
            editing=(left, save_y, inside, undo_y + undo_high - save_y),
        )

    def _toolbar(
        self,
        leading: list[_Placed],
        trailing: list[_Placed],
        *,
        documents: tuple[float, float, float, float],
        divider: tuple[float, float, float, float],
        editing: tuple[float, float, float, float],
    ) -> list[dict[str, Any]]:
        """The toolbar's six elements as scene elements: all in the toolbar's
        container, or, in the grouping `tasks`, in two containers by what
        they act on (create, sort and the filter act on the documents, save
        and undo on the work in hand) with a divider between the two."""

        def written(items: list[_Placed], parent: str) -> list[dict[str, Any]]:
            return [self.bound(item.element, item.component, parent, item.x, item.y, item.width, item.height) for item in items]

        if self.grouping != "tasks":
            return written(leading, "s.toolbar") + written(trailing, "s.toolbar")
        return [
            self.structural("s.toolbar.documents", "container", "s.toolbar", "toolbar", *documents),
            *written(leading, "s.toolbar.documents"),
            self.structural("s.toolbar.divider", "divider", "s.toolbar", "divider", *divider),
            self.structural("s.toolbar.editing", "container", "s.toolbar", "toolbar", *editing),
            *written(trailing, "s.toolbar.editing"),
        ]

    # --- the list and the editor --------------------------------------------

    def panels(self, parts: _Parts, area: _Area, arrangement: str) -> list[dict[str, Any]]:
        """The document list and the editor, inside the area the navigation
        leaves free. Each is a panel of its own, or, in the grouping `sheet`,
        both lie on one panel with a divider between them."""
        sizes = self.preset.dimensions
        top = area.top + self.margin
        list_width = min(max(sizes["list-share"] * area.width, sizes["list-width-min"]), sizes["list-width-max"])
        sheet = self.grouping == "sheet"
        list_parent, editor_parent = ("s.workspace", "s.workspace") if sheet else ("s.list", "s.editor")
        thick = self.preset.component("divider").height
        between = (self.margin - thick) / 2

        if arrangement == "list-top":
            # A grid as wide as the area, the editor under it.
            list_x, wide = area.left + self.margin, area.width - 2 * self.margin
            inset = self.space("row-inset")
            narrowest = sizes["list-width-min"] - 2 * inset
            columns = max(1, math.floor((wide - 2 * inset + self.gap) / (narrowest + self.gap)))
            listed, list_high = self.list(parts, list_parent, list_x, top, wide, columns)
            list_box = (list_x, top, wide, list_high)
            editor_y = top + list_high + self.margin
            editor_box = (list_x, editor_y, wide, area.bottom - self.margin - editor_y)
            split = (list_x, top + list_high + between, wide, thick)
        else:
            if arrangement == "list-left":
                list_x = area.left + self.margin
                editor_x = area.left + (2 * self.margin + list_width)
                editor_box = (editor_x, top, area.right - editor_x - self.margin, area.bottom - top - self.margin)
                split_x = list_x + list_width + between
            else:
                list_x = area.right - self.margin - list_width
                editor_x = area.left + self.margin
                editor_box = (editor_x, top, list_x - self.margin - editor_x, area.bottom - top - self.margin)
                split_x = list_x - self.margin + between
            listed, list_high = self.list(parts, list_parent, list_x, top, list_width, 1)
            list_box = (list_x, top, list_width, list_high)
            split = (split_x, top, thick, area.bottom - top - self.margin)
        edited = self.editor(parts, editor_parent, *editor_box)

        if not sheet:
            return [
                self.structural("s.list", "panel", "s.root", "panel", *list_box),
                *listed,
                self.structural("s.editor", "panel", "s.root", "panel", *editor_box),
                *edited,
            ]
        left = area.left + self.margin
        return [
            self.structural("s.workspace", "panel", "s.root", "panel", left, top, area.width - 2 * self.margin, area.bottom - top - self.margin),
            *listed,
            self.structural("s.workspace.divider", "divider", "s.workspace", "divider", *split),
            *edited,
        ]

    def list(self, parts: _Parts, parent: str, x: float, top: float, list_width: float, columns: int) -> tuple[list[dict[str, Any]], float]:
        """The list's heading and its rows in `columns` columns, filled row by
        row, and how high they stand together. The heading and the label of
        an empty list begin where a row's text begins, or are centred."""
        heading = parts.one("list", "heading")
        rows = parts.take("list", "list-item", "open")
        empty = parts.take("list", "label")
        row, row_open = self.preset.component("row"), self.preset.component("row-open")
        inset, padding = self.space("row-inset"), self.space("panel-padding")

        row_x = x + inset
        # Headings and labels start where a row's text starts.
        text_x = row_x + (self.high(row) - typography.line_height(*row.type)) / 2

        def heading_x(wide: float) -> float:
            """Where a heading or a label begins: where a row's text begins, or centred over the list."""
            return x + (list_width - wide) / 2 if self.alignment == "centre" else text_x

        title = self.preset.component("heading")
        line = typography.line_height(*title.type)
        y = top + padding
        heading_width = typography.measure(heading.text, *title.type)
        placed = [self.bound(heading, title, parent, heading_x(heading_width), y, heading_width, line)]
        y += line + self.gap

        row_width = (list_width - 2 * inset - (columns - 1) * self.gap) / columns
        for index, element in enumerate(rows):
            is_open = any(relationship["relation"] == "shown_in" for relationship in element.relationships)
            component = row_open if is_open else row
            column = index % columns
            placed.append(self.bound(element, component, parent, row_x + column * (row_width + self.gap), y, row_width, self.high(component)))
            if column == columns - 1 or index == len(rows) - 1:
                y += self.high(component)
        if rows:
            y += inset

        text = self.preset.component("label")
        for label in empty:
            line = typography.line_height(*text.type)
            label_width = typography.measure(label.text, *text.type)
            placed.append(self.bound(label, text, parent, heading_x(label_width), y, label_width, line))
            y += line + padding
        return placed, y - top

    def editor(self, parts: _Parts, parent: str, x: float, y: float, width: float, height: float) -> list[dict[str, Any]]:
        """The editor's elements in the box given: the title field, the
        revision under it at the left or centred, and the body filling the
        rest; or, with no document open, a label in the middle."""
        areas = parts.take("editor", "text-area", "edit")
        text = self.preset.component("label")
        line = typography.line_height(*text.type)

        if not areas:
            label = parts.one("editor", "label")
            label_width = typography.measure(label.text, *text.type)
            return [self.bound(label, text, parent, x + (width - label_width) / 2, y + (height - line) / 2, label_width, line)]

        (body,) = areas
        title = parts.one("editor", "text-field", "rename")
        revision = parts.one("editor", "label")
        title_field = self.preset.component("title-field")
        padding = self.space("editor-padding")
        title_high = self.high(title_field)
        inner_x = x + padding
        inner_width = width - 2 * padding
        revision_y = y + padding + title_high + self.gap
        revision_width = typography.measure(revision.text, *text.type)
        body_y = revision_y + line + self.gap
        return [
            self.bound(title, title_field, parent, inner_x, y + padding, inner_width, title_high),
            self.bound(revision, text, parent, self.aligned(inner_x, inner_width, revision_width), revision_y, revision_width, line),
            self.bound(body, self.preset.component("editor-body"), parent, inner_x, body_y, inner_width, y + height - padding - body_y),
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
