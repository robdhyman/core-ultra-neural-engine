"""The documents app adapter: application state described as bound elements.

A bound element says what a piece of the interface means: its stable identity,
role, exact text, action binding, current state and semantic relationships. It
holds no coordinate and no style value; where and how an element is drawn is
the scene writer's work, and nothing here may be changed by it.

The document workspace has four parts: the document list, the editor, the
toolbar and the notification. `describe` returns the elements of all four, in
reading order:

| Identity | Role | Text | Binding |
| --- | --- | --- | --- |
| `documents.create` | button | New document | create |
| `toolbar.sort` | button | the current order | sort, to the next order |
| `toolbar.filter.label` | label | Filter | none |
| `toolbar.filter` | text-field | the filter text | filter |
| `toolbar.save` | button | Save | save |
| `toolbar.undo` | button | Undo | undo |
| `documents.heading` | heading | Documents | none |
| `document:<id>` | list-item | the title | open that document |
| `documents.empty` | label | why the list is empty | none |
| `editor.title` | text-field | the open document's title | rename it |
| `editor.revision` | label | its revision, and whether it has unsaved changes | none |
| `editor.body` | text-area | its draft, or its body when nothing is unsaved | edit it |
| `editor.empty` | label | No document is open | none |
| `notification` | status | the kernel's notification | none |

`documents.empty` stands in for the rows when there are none, `editor.empty`
for the three editor elements when no document is open, and `notification` is
present only while the kernel has one.

Relationships name either another bound element or a part of the workspace:

- `part_of`: every element, to `workspace.toolbar`, `workspace.list`,
  `workspace.editor` or `workspace.notification`.
- `item_of`: a row, to the heading that names its list.
- `controls`: sort and filter, to the list's heading; save, to the editor body.
- `labels`: a label, to the element it names.
- `shown_in`: the open document's row, to the editor body.

States. The application decides `disabled`: Save while the open document has
nothing unsaved (or none is open), Undo while there is nothing to undo. The
caller's interaction supplies the rest, and only for elements that have a
binding; an element the application disabled stays disabled.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core_ultra.kernel import ApplicationState, Sort

ROLES = ("heading", "button", "list-item", "text-field", "text-area", "label", "status")
STATES = ("default", "hover", "pressed", "focused", "disabled")
RELATIONS = ("part_of", "item_of", "controls", "labels", "shown_in")

TOOLBAR = "workspace.toolbar"
LIST = "workspace.list"
EDITOR = "workspace.editor"
NOTIFICATION_PART = "workspace.notification"
PARTS = (TOOLBAR, LIST, EDITOR, NOTIFICATION_PART)

CREATE = "documents.create"
SORT = "toolbar.sort"
FILTER_LABEL = "toolbar.filter.label"
FILTER = "toolbar.filter"
SAVE = "toolbar.save"
UNDO = "toolbar.undo"
HEADING = "documents.heading"
EMPTY_LIST = "documents.empty"
EDITOR_TITLE = "editor.title"
EDITOR_REVISION = "editor.revision"
EDITOR_BODY = "editor.body"
EMPTY_EDITOR = "editor.empty"
NOTIFICATION = "notification"

# The orders the sort button steps through, with the text it shows for each.
SORT_ORDERS = (
    (Sort("created", False), "Sort: oldest first"),
    (Sort("created", True), "Sort: newest first"),
    (Sort("title", False), "Sort: title A to Z"),
    (Sort("title", True), "Sort: title Z to A"),
    (Sort("modified", True), "Sort: last changed first"),
    (Sort("modified", False), "Sort: last changed last"),
)


@dataclass(frozen=True)
class BoundElement:
    identity: str
    role: str
    text: str
    binding: Mapping[str, Any] | None
    state: str
    relationships: tuple[Mapping[str, str], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "role": self.role,
            "text": self.text,
            "binding": None if self.binding is None else dict(self.binding),
            "state": self.state,
            "relationships": [dict(relationship) for relationship in self.relationships],
        }


def document_identity(document_id: int) -> str:
    return f"document:{document_id}"


def _relation(relation: str, target: str) -> dict[str, str]:
    return {"relation": relation, "target": target}


def describe(state: ApplicationState) -> tuple[BoundElement, ...]:
    """The bound elements of the document workspace, in reading order.

    Identities are stable: a document keeps `document:<id>` for as long as it
    exists, whatever is created, renamed, sorted or filtered around it.
    """
    orders = [order for order, _ in SORT_ORDERS]
    current = orders.index(state.sort)
    following = orders[(current + 1) % len(orders)]
    opened = state.open_document

    # identity, role, text, binding, relationships, disabled by the application
    elements: list[tuple[str, str, str, dict[str, Any] | None, tuple[dict[str, str], ...], bool]] = [
        (CREATE, "button", "New document", {"command": "create"}, (_relation("part_of", TOOLBAR),), False),
        (
            SORT,
            "button",
            SORT_ORDERS[current][1],
            {"command": "sort", "key": following.key, "descending": following.descending},
            (_relation("part_of", TOOLBAR), _relation("controls", HEADING)),
            False,
        ),
        (FILTER_LABEL, "label", "Filter", None, (_relation("part_of", TOOLBAR), _relation("labels", FILTER)), False),
        (
            FILTER,
            "text-field",
            state.filter,
            {"command": "filter"},
            (_relation("part_of", TOOLBAR), _relation("controls", HEADING)),
            False,
        ),
        (
            SAVE,
            "button",
            "Save",
            {"command": "save"},
            (_relation("part_of", TOOLBAR), *((_relation("controls", EDITOR_BODY),) if opened else ())),
            opened is None or not opened.unsaved,
        ),
        (UNDO, "button", "Undo", {"command": "undo"}, (_relation("part_of", TOOLBAR),), state.undoable is None),
        (HEADING, "heading", "Documents", None, (_relation("part_of", LIST),), False),
    ]

    for document in state.documents:
        relationships = [_relation("part_of", LIST), _relation("item_of", HEADING)]
        if opened is not None and document.id == opened.id:
            relationships.append(_relation("shown_in", EDITOR_BODY))
        elements.append(
            (
                document_identity(document.id),
                "list-item",
                document.title,
                {"command": "open", "document": document.id},
                tuple(relationships),
                False,
            )
        )
    if not state.documents:
        if state.total_documents:
            text = f"No title contains “{state.filter}”"
        else:
            text = "No documents yet"
        elements.append((EMPTY_LIST, "label", text, None, (_relation("part_of", LIST), _relation("item_of", HEADING)), False))

    if opened is None:
        elements.append((EMPTY_EDITOR, "label", "No document is open", None, (_relation("part_of", EDITOR),), False))
    else:
        revision = f"Revision {opened.revision}" + (", unsaved changes" if opened.unsaved else "")
        elements += [
            (
                EDITOR_TITLE,
                "text-field",
                opened.title,
                {"command": "rename", "document": opened.id},
                (_relation("part_of", EDITOR), _relation("labels", EDITOR_BODY)),
                False,
            ),
            (EDITOR_REVISION, "label", revision, None, (_relation("part_of", EDITOR), _relation("labels", EDITOR_BODY)), False),
            (
                EDITOR_BODY,
                "text-area",
                opened.text,
                {"command": "edit", "document": opened.id},
                (_relation("part_of", EDITOR),),
                False,
            ),
        ]

    if state.notification is not None:
        elements.append(
            (NOTIFICATION, "status", state.notification, None, (_relation("part_of", NOTIFICATION_PART),), False)
        )

    bindings = {identity: binding for identity, _, _, binding, _, _ in elements}
    for identity, element_state in state.interaction.items():
        if identity not in bindings:
            raise ValueError(f"interaction names {identity!r}, which is not an element of this state")
        if element_state not in STATES:
            raise ValueError(f"{element_state!r} is not an element state; the states are {', '.join(STATES)}")
        if bindings[identity] is None and element_state != "default":
            raise ValueError(f"{identity!r} has no binding; only an element with an action leaves the default state")

    return tuple(
        BoundElement(
            identity=identity,
            role=role,
            text=text,
            binding=binding,
            state="disabled" if disabled else state.interaction.get(identity, "default"),
            relationships=relationships,
        )
        for identity, role, text, binding, relationships, disabled in elements
    )
