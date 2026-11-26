"""Scripted sessions: synthetic runs of the documents app, with no person involved.

A scripted session starts an empty application kernel and works through a
script, a list of actions. Each action is carried out the way a person would:
the pointer moves onto a bound element, the element is pressed (or, for a
field, focused), and the command its action binding names is given to the
kernel. Nothing else changes the kernel, so every application state a session
passes through is one the application can really reach.

    for moment in run(["create", "open", "edit", "save"], content, random.Random("7/first")):
        moment.state            # the application state, pointer state included
        moment.trace            # every command executed so far, as the kernel was given it

Each action gives three moments: the element hovered, the element pressed or
focused, and the application after the command with the pointer state cleared.
Before the first action there is one moment for the empty application.
Moments that differ only in the pointer state share `application_state`, the
number of commands executed so far.

Actions and the bound element each one activates:

| Action | Element | Text given to the command |
| --- | --- | --- |
| `create` | `documents.create` | a new title |
| `open` | a row of the list, one that is not open if there is one | |
| `rename` | `editor.title` | a new title |
| `edit` | `editor.body` | a new body |
| `save` | `toolbar.save` | |
| `undo` | `toolbar.undo` | |
| `sort` | `toolbar.sort` | |
| `filter` | `toolbar.filter` | a word of a listed title |
| `filter-none` | `toolbar.filter` | text no title contains |
| `filter-clear` | `toolbar.filter` | empty text |

Which row, which title and which body are chosen with the random source the
session is given and with nothing else, so the same script, content and seed
always give the same session. An action that cannot be carried out (its
element is absent or disabled, or the kernel refuses the command) stops the
session with `ScriptError`; an action is never skipped.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core_ultra import documents_adapter
from core_ultra.documents_adapter import BoundElement
from core_ultra.kernel import ApplicationState, Kernel, KernelError

ACTIONS = ("create", "open", "rename", "edit", "save", "undo", "sort", "filter", "filter-none", "filter-clear")
PHASES = ("start", "hover", "pressed", "focused", "result")

_ELEMENT = {
    "create": documents_adapter.CREATE,
    "rename": documents_adapter.EDITOR_TITLE,
    "edit": documents_adapter.EDITOR_BODY,
    "save": documents_adapter.SAVE,
    "undo": documents_adapter.UNDO,
    "sort": documents_adapter.SORT,
    "filter": documents_adapter.FILTER,
    "filter-none": documents_adapter.FILTER,
    "filter-clear": documents_adapter.FILTER,
}
# The pointer state an element is in at the moment its command is given.
_ACTIVE = {"button": "pressed", "list-item": "pressed", "text-field": "focused", "text-area": "focused"}
_ATTEMPTS = 32


class ScriptError(ValueError):
    """A script that cannot be carried out, or content a script cannot use."""


@dataclass(frozen=True)
class Content:
    """What a session writes with.

    A title is `title_words[0]` to `title_words[1]` different words of
    `words`, the first one capitalised. A body is `body_lines[0]` to
    `body_lines[1]` different lines of `lines`. `filter_misses` are texts
    meant to match no title.
    """

    words: tuple[str, ...]
    title_words: tuple[int, int]
    lines: tuple[str, ...]
    body_lines: tuple[int, int]
    filter_misses: tuple[str, ...]

    @classmethod
    def from_json(cls, raw: Any) -> Content:
        fields = ("words", "title_words", "lines", "body_lines", "filter_misses")
        if not isinstance(raw, Mapping) or set(raw) != set(fields):
            raise ScriptError(f"content does not hold exactly: {', '.join(fields)}")
        for name in ("words", "lines", "filter_misses"):
            if not isinstance(raw[name], list) or not raw[name] or not all(isinstance(item, str) and item for item in raw[name]):
                raise ScriptError(f"content.{name} is not a list of texts")
            if len(set(raw[name])) != len(raw[name]):
                raise ScriptError(f"content.{name} repeats a text")
        for name, pool in (("title_words", "words"), ("body_lines", "lines")):
            span = raw[name]
            whole = isinstance(span, list) and len(span) == 2 and all(isinstance(n, int) and not isinstance(n, bool) for n in span)
            if not whole or not 1 <= span[0] <= span[1] <= len(raw[pool]):
                raise ScriptError(f"content.{name} is not [fewest, most] with 1 <= fewest <= most <= the number of {pool}")
        if len(raw["words"]) < 2 or len(raw["lines"]) < 2:
            raise ScriptError("content needs at least two words and two lines, so that a rename and an edit can change something")
        return cls(
            words=tuple(raw["words"]),
            title_words=tuple(raw["title_words"]),
            lines=tuple(raw["lines"]),
            body_lines=tuple(raw["body_lines"]),
            filter_misses=tuple(raw["filter_misses"]),
        )


@dataclass(frozen=True)
class Moment:
    """One reached state of a scripted session.

    `step` is the position in the script of the action this moment belongs to
    and `action` its name; both are None for the first moment. `trace` holds
    every command executed before this moment: the element activated, its
    action binding and the text given, exactly as the kernel received them.
    """

    index: int
    step: int | None
    action: str | None
    phase: str
    state: ApplicationState
    bound_elements: tuple[BoundElement, ...]
    application_state: int
    trace: tuple[Mapping[str, Any], ...]


def run(script: Sequence[str], content: Content, rng: random.Random) -> Iterator[Moment]:
    """Carry the script out on an empty kernel and give each moment in turn."""
    for action in script:
        if action not in ACTIONS:
            raise ScriptError(f"{action!r} is not an action; the actions are {', '.join(ACTIONS)}")

    kernel = Kernel()
    try:
        trace: list[Mapping[str, Any]] = []
        index = 0

        def moment(step: int | None, action: str | None, phase: str, interaction: Mapping[str, str]) -> Moment:
            nonlocal index
            state = kernel.state().with_interaction(interaction)
            made = Moment(index, step, action, phase, state, documents_adapter.describe(state), len(trace), tuple(trace))
            index += 1
            return made

        yield moment(None, None, "start", {})
        for step, action in enumerate(script):
            where = f"step {step} ({action})"
            state = kernel.state()
            element = _target(action, state, rng, where)
            if element.state == "disabled":
                raise ScriptError(f"{where}: {element.identity} is disabled in this state")
            text = _text(action, state, content, rng, where)

            yield moment(step, action, "hover", {element.identity: "hover"})
            active = _ACTIVE[element.role]
            yield moment(step, action, active, {element.identity: active})
            try:
                kernel.execute(element.binding, text)
            except KernelError as refused:
                raise ScriptError(f"{where}: the kernel refused the command: {refused}") from None
            trace.append({"element": element.identity, "binding": dict(element.binding), "text": text})
            # The kernel is the judge of what a filter matches.
            listed = len(kernel.state().documents)
            if action == "filter-none" and listed:
                raise ScriptError(f"{where}: the filter {text!r} was meant to match no title and matches {listed}")
            if action == "filter" and not listed:
                raise ScriptError(f"{where}: the filter {text!r} was meant to match a title and matches none")
            yield moment(step, action, "result", {})
    finally:
        kernel.close()


def _target(action: str, state: ApplicationState, rng: random.Random, where: str) -> BoundElement:
    elements = {element.identity: element for element in documents_adapter.describe(state)}
    if action == "open":
        rows = [document.id for document in state.documents]
        if not rows:
            raise ScriptError(f"{where}: the list has no row to open")
        opened = state.open_document.id if state.open_document else None
        others = [document_id for document_id in rows if document_id != opened]
        return elements[documents_adapter.document_identity(rng.choice(others or rows))]
    try:
        return elements[_ELEMENT[action]]
    except KeyError:
        raise ScriptError(f"{where}: {_ELEMENT[action]} is not an element of this state") from None


def _text(action: str, state: ApplicationState, content: Content, rng: random.Random, where: str) -> str | None:
    """What is typed for this action, or None for an action that takes no text."""
    if action == "create":
        return _title(content, rng)
    if action == "rename":
        return _different(lambda: _title(content, rng), state.open_document.title, where)
    if action == "edit":
        return _different(lambda: _body(content, rng), state.open_document.text, where)
    if action == "filter":
        titles = [document.title for document in state.documents]
        if not titles:
            raise ScriptError(f"{where}: the list has no title to filter by")
        return rng.choice(rng.choice(titles).split()).lower()
    if action == "filter-none":
        for miss in content.filter_misses:
            if not any(miss.casefold() in document.title.casefold() for document in state.documents):
                return miss
        raise ScriptError(f"{where}: every text in content.filter_misses is in a listed title")
    if action == "filter-clear":
        return ""
    return None


def _title(content: Content, rng: random.Random) -> str:
    words = rng.sample(content.words, rng.randint(*content.title_words))
    title = " ".join(words)
    return title[0].upper() + title[1:]


def _body(content: Content, rng: random.Random) -> str:
    return "\n".join(rng.sample(content.lines, rng.randint(*content.body_lines)))


def _different(make: Any, current: str, where: str) -> str:
    for _ in range(_ATTEMPTS):
        text = make()
        if text != current:
            return text
    raise ScriptError(f"{where}: the content gave the same text {_ATTEMPTS} times")
