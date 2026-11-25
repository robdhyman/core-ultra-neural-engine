"""The documents app adapter: application state described as bound elements.

A bound element says what a piece of the interface means: its stable identity,
role, exact text, action binding, current state and semantic relationships. It
holds no coordinate and no style value; where and how an element is drawn is
the scene writer's work, and nothing here may be changed by it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core_ultra.kernel import ApplicationState

ROLES = ("heading", "button", "list-item")
STATES = ("default", "hover", "pressed", "focused", "disabled")

HEADING = "documents.heading"
CREATE = "documents.create"


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


def describe(state: ApplicationState) -> tuple[BoundElement, ...]:
    """The bound elements of the document list, in reading order.

    Identities are stable: a document keeps `document:<id>` for as long as it
    exists, whatever else is created around it. Each row is an item of the list
    that the heading names.
    """
    elements = [
        (HEADING, "heading", "Documents", None, ()),
        (CREATE, "button", "New document", {"command": "create"}, ()),
    ]
    for document in state.documents:
        elements.append(
            (
                document_identity(document.id),
                "list-item",
                document.title,
                {"command": "open", "document": document.id},
                ({"relation": "item_of", "target": HEADING},),
            )
        )

    known = {identity for identity, *_ in elements}
    for identity, element_state in state.interaction.items():
        if identity not in known:
            raise ValueError(f"interaction names {identity!r}, which is not an element of this state")
        if element_state not in STATES:
            raise ValueError(f"{element_state!r} is not an element state; the states are {', '.join(STATES)}")

    return tuple(
        BoundElement(
            identity=identity,
            role=role,
            text=text,
            binding=binding,
            state=state.interaction.get(identity, "default"),
            relationships=relationships,
        )
        for identity, role, text, binding, relationships in elements
    )
