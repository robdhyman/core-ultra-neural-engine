"""The reference layout: the deterministic function that writes the true scene.

One arrangement of the document workspace: a toolbar across the top, the
document list on the left, the editor filling the rest, and the notification
over the lower right corner. Every style value and every size comes from the
visual preset it is given (`core_ultra.design`); nothing about how the
workspace looks is decided here. Design conditions and layout families join
the arrangement when the generator is built.

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
from core_ultra.design import Component, VisualPreset
from core_ultra.documents_adapter import BoundElement
from core_ultra.scene import SCHEMA_VERSION

_CLEAR = [0.0, 0.0, 0.0, 0.0]


def write_scene(bound_elements: Sequence[BoundElement], viewport: tuple[float, float], preset: VisualPreset) -> dict[str, Any]:
    """The true scene for these bound elements at this viewport size, in this visual preset."""
    width, height = viewport
    writer = _Writer(preset)
    parts = _Parts(bound_elements)
    toolbar, divider = preset.component("toolbar"), preset.component("divider")
    margin = preset.spacing["margin"]
    top = toolbar.height + margin
    sizes = preset.dimensions
    list_width = min(max(sizes["list-share"] * width, sizes["list-width-min"]), sizes["list-width-max"])

    elements = [
        writer.structural("s.root", "surface", None, "page", 0, 0, width, height),
        writer.structural("s.toolbar", "container", "s.root", "toolbar", 0, 0, width, toolbar.height),
        writer.structural("s.divider", "divider", "s.root", "divider", 0, toolbar.height, width, divider.height),
    ]
    elements += writer.toolbar(parts, width)
    elements += writer.list(parts, top, list_width)
    editor_x = 2 * margin + list_width
    elements += writer.editor(parts, editor_x, top, width - editor_x - margin, height - top - margin)
    elements += writer.notification(parts, width, height)
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
    """Writes the workspace's elements in one visual preset."""

    def __init__(self, preset: VisualPreset) -> None:
        self.preset = preset
        self.margin = preset.spacing["margin"]
        self.gap = preset.spacing["gap"]

    def toolbar(self, parts: _Parts, width: float) -> list[dict[str, Any]]:
        create = parts.one("toolbar", "button", "create")
        sort = parts.one("toolbar", "button", "sort")
        label = parts.one("toolbar", "label")
        field = parts.one("toolbar", "text-field", "filter")
        save = parts.one("toolbar", "button", "save")
        undo = parts.one("toolbar", "button", "undo")
        bar = self.preset.component("toolbar").height

        def button(element: BoundElement) -> Component:
            return self.preset.component("button-primary" if element.binding["command"] == "create" else "button-quiet")

        def button_width(element: BoundElement) -> float:
            return typography.measure(element.text, *button(element).type) + 2 * button(element).padding

        def place_button(element: BoundElement, x: float) -> dict[str, Any]:
            component = button(element)
            return self.bound(element, component, "s.toolbar", x, (bar - component.height) / 2, button_width(element), component.height)

        placed = []
        x = self.margin
        for element in (create, sort):
            placed.append(place_button(element, x))
            x += button_width(element) + self.gap

        text = self.preset.component("label")
        line = typography.line_height(*text.type)
        label_width = typography.measure(label.text, *text.type)
        placed.append(self.bound(label, text, "s.toolbar", x, (bar - line) / 2, label_width, line))
        x += label_width + self.gap

        # The filter field takes the room left before Save and Undo, within its
        # limits. Save and Undo sit at the right edge when there is room to spare.
        box = self.preset.component("field")
        sizes = self.preset.dimensions
        trailing = button_width(save) + self.gap + button_width(undo)
        field_width = min(max(width - self.margin - trailing - self.gap - x, sizes["filter-width-min"]), sizes["filter-width-max"])
        placed.append(self.bound(field, box, "s.toolbar", x, (bar - box.height) / 2, field_width, box.height))
        x = max(x + field_width + self.gap, width - self.margin - trailing)
        placed.append(place_button(save, x))
        placed.append(place_button(undo, x + button_width(save) + self.gap))
        return placed

    def list(self, parts: _Parts, top: float, list_width: float) -> list[dict[str, Any]]:
        heading = parts.one("list", "heading")
        rows = parts.take("list", "list-item", "open")
        empty = parts.take("list", "label")
        row, row_open = self.preset.component("row"), self.preset.component("row-open")
        inset, padding = self.preset.spacing["row-inset"], self.preset.spacing["panel-padding"]

        row_x = self.margin + inset
        # Headings and labels start where a row's text starts.
        text_x = row_x + (row.height - typography.line_height(*row.type)) / 2

        title = self.preset.component("heading")
        line = typography.line_height(*title.type)
        y = top + padding
        placed = [self.bound(heading, title, "s.list", text_x, y, typography.measure(heading.text, *title.type), line)]
        y += line + self.gap

        for element in rows:
            is_open = any(relationship["relation"] == "shown_in" for relationship in element.relationships)
            component = row_open if is_open else row
            placed.append(self.bound(element, component, "s.list", row_x, y, list_width - 2 * inset, component.height))
            y += component.height
        if rows:
            y += inset

        text = self.preset.component("label")
        for label in empty:
            line = typography.line_height(*text.type)
            placed.append(self.bound(label, text, "s.list", text_x, y, typography.measure(label.text, *text.type), line))
            y += line + padding

        panel = self.structural("s.list", "panel", "s.root", "panel", self.margin, top, list_width, y - top)
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
        padding = self.preset.spacing["editor-padding"]
        inner_x = x + padding
        inner_width = width - 2 * padding
        revision_y = y + padding + title_field.height + self.gap
        body_y = revision_y + line + self.gap
        return [
            panel,
            self.bound(title, title_field, "s.editor", inner_x, y + padding, inner_width, title_field.height),
            self.bound(revision, text, "s.editor", inner_x, revision_y, typography.measure(revision.text, *text.type), line),
            self.bound(
                body, self.preset.component("editor-body"), "s.editor", inner_x, body_y, inner_width, y + height - padding - body_y
            ),
        ]

    def notification(self, parts: _Parts, width: float, height: float) -> list[dict[str, Any]]:
        component = self.preset.component("notification")
        placed = []
        for status in parts.take("notification", "status"):
            # As wide as its text plus the inset the runtime renderer gives a
            # line of text: as far from the left edge as from the top.
            inset = (component.height - typography.line_height(*component.type)) / 2
            box_width = typography.measure(status.text, *component.type) + 2 * inset
            placed.append(
                self.bound(
                    status, component, "s.root",
                    width - 3 * self.margin - box_width, height - 3 * self.margin - component.height, box_width, component.height,
                )
            )
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
