"""The scene schema and scene validation.

A scene is a tree of elements stored as JSON: a flat list in which every
element names its parent. Every element has a type, a box in viewport units and
the same set of style values. A bound element also carries what the documents
app adapter supplied (identity, role, text, binding, state, relationships),
unchanged. A structural element carries none of that.

    {
      "kind": "scene",
      "schema_version": 1,
      "viewport": {"width": 800, "height": 480},
      "elements": [
        {"id": "s.root", "type": "surface", "parent": null,
         "box": {"x": 0, "y": 0, "width": 800, "height": 480},
         "style": {"fill": [r, g, b, a], "text_colour": [...], "border_colour": [...],
                   "border_width": 0, "corner_radius": 0, "elevation": 0,
                   "opacity": 1, "type_size": 15, "type_weight": 400}},
        {"id": "b.documents.create", "type": "bound", "parent": "s.header",
         "box": {...}, "style": {...},
         "bound": {"identity": ..., "role": ..., "text": ..., "binding": ...,
                   "state": ..., "relationships": [...]}}
      ]
    }

`validate` is the only way to obtain a `Scene`, and the runtime renderer draws
and hit-tests nothing else. Validation never repairs: a candidate with any
problem is refused with every problem listed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from core_ultra.documents_adapter import BoundElement

SCHEMA_VERSION = 1
BOUND_TYPE = "bound"
STRUCTURAL_TYPES = ("surface", "panel", "container", "divider")
MAX_BOUND = 32
MAX_STRUCTURAL = 16

COLOUR_FIELDS = ("fill", "text_colour", "border_colour")
NUMBER_FIELDS = ("border_width", "corner_radius", "elevation", "opacity", "type_size", "type_weight")
STYLE_FIELDS = COLOUR_FIELDS + NUMBER_FIELDS
BOX_FIELDS = ("x", "y", "width", "height")
BOUND_FIELDS = ("identity", "role", "text", "binding", "state", "relationships")

# Slack for sums of 64-bit floats when a box is tested against the viewport.
_EDGE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Problem:
    """One reason a candidate scene is not valid.

    Codes: `malformed`, `non_finite`, `tree`, `out_of_range`, `outside_viewport`,
    `bound_missing`, `bound_duplicated`, `bound_unknown`, `bound_altered`,
    `structural_carries_bound`, `limit_exceeded`.
    """

    code: str
    element: str | None
    detail: str

    def __str__(self) -> str:
        where = f" ({self.element})" if self.element else ""
        return f"{self.code}{where}: {self.detail}"


class SceneInvalid(Exception):
    """A candidate scene failed validation. Nothing was drawn."""

    def __init__(self, problems: Sequence[Problem]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(str(problem) for problem in self.problems))

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(problem.code for problem in self.problems)


@dataclass(frozen=True)
class Style:
    fill: tuple[float, float, float, float]
    text_colour: tuple[float, float, float, float]
    border_colour: tuple[float, float, float, float]
    border_width: float
    corner_radius: float
    elevation: float
    opacity: float
    type_size: float
    type_weight: float


@dataclass(frozen=True)
class Element:
    id: str
    type: str
    parent: str | None
    x: float
    y: float
    width: float
    height: float
    style: Style
    bound: BoundElement | None


_PROOF = object()


class Scene:
    """A validated scene. Elements are held in drawing order: a parent before
    its children, siblings in the order the scene listed them."""

    __slots__ = ("viewport_width", "viewport_height", "elements")

    def __init__(self, proof: object, viewport_width: float, viewport_height: float, elements: tuple[Element, ...]) -> None:
        if proof is not _PROOF:
            raise TypeError("a Scene comes from core_ultra.scene.validate, never from its constructor")
        object.__setattr__(self, "viewport_width", viewport_width)
        object.__setattr__(self, "viewport_height", viewport_height)
        object.__setattr__(self, "elements", elements)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a validated scene is not edited; validate a new candidate instead")

    @property
    def bound_elements(self) -> tuple[Element, ...]:
        return tuple(element for element in self.elements if element.bound is not None)

    @property
    def structural_elements(self) -> tuple[Element, ...]:
        return tuple(element for element in self.elements if element.bound is None)

    def element_for(self, identity: str) -> Element:
        """The scene element that carries the bound element with this identity."""
        for element in self.elements:
            if element.bound is not None and element.bound.identity == identity:
                return element
        raise KeyError(identity)

    def to_json(self) -> dict[str, Any]:
        elements = []
        for element in self.elements:
            style = element.style
            item: dict[str, Any] = {
                "id": element.id,
                "type": element.type,
                "parent": element.parent,
                "box": {"x": element.x, "y": element.y, "width": element.width, "height": element.height},
                "style": {
                    **{name: list(getattr(style, name)) for name in COLOUR_FIELDS},
                    **{name: getattr(style, name) for name in NUMBER_FIELDS},
                },
            }
            if element.bound is not None:
                item["bound"] = element.bound.to_json()
            elements.append(item)
        return {
            "kind": "scene",
            "schema_version": SCHEMA_VERSION,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
            "elements": elements,
        }


def dumps(scene: Scene) -> str:
    """The scene as stored: JSON text."""
    return json.dumps(scene.to_json(), ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def loads(text: str) -> Any:
    """Read stored JSON as a candidate scene. It is not a scene until validated."""
    return json.loads(text)


def validate(candidate: Any, bound_elements: Sequence[BoundElement], viewport: tuple[float, float]) -> Scene:
    """Return the candidate as a `Scene`, or raise `SceneInvalid` listing every problem.

    `bound_elements` is what the adapter supplied for this state: each must
    appear in the scene exactly once, unchanged.
    """
    problems: list[Problem] = []

    def problem(code: str, element: str | None, detail: str) -> None:
        problems.append(Problem(code, element, detail))

    if not isinstance(candidate, dict):
        raise SceneInvalid([Problem("malformed", None, "a scene is a JSON object")])
    if candidate.get("kind") != "scene":
        problem("malformed", None, 'kind is not "scene"')
    if candidate.get("schema_version") != SCHEMA_VERSION:
        problem("malformed", None, f"schema_version is not {SCHEMA_VERSION}")

    width, height = viewport
    stated = candidate.get("viewport")
    if not isinstance(stated, dict) or set(stated) != {"width", "height"}:
        problem("malformed", None, "viewport is not {width, height}")
    elif not (_is_number(stated["width"]) and _is_number(stated["height"])):
        problem("malformed", None, "viewport width and height are numbers")
    elif (stated["width"], stated["height"]) != (width, height):
        problem(
            "malformed",
            None,
            f"viewport is {stated['width']} by {stated['height']}; the conditioning says {width} by {height}",
        )

    items = candidate.get("elements")
    if not isinstance(items, list):
        problem("malformed", None, "elements is not a list")
        raise SceneInvalid(problems)

    # Pass 1: each element on its own.
    parsed: dict[str, _Parsed] = {}
    order: list[str] = []
    tree_usable = True
    for index, item in enumerate(items):
        result = _parse_element(item, index, problems)
        if result is None:
            tree_usable = False
            continue
        if result.id in parsed:
            problem("tree", result.id, "two elements share this id")
            tree_usable = False
            continue
        parsed[result.id] = result
        order.append(result.id)

    # Pass 2: the tree.
    drawing_order: list[str] = []
    if tree_usable:
        drawing_order = _check_tree(parsed, order, problems)

    # Pass 3: numbers against the viewport and the allowed ranges.
    for element_id in order:
        _check_ranges(parsed[element_id], width, height, problems)

    # Pass 4: bound elements against what the adapter supplied.
    _check_bound(parsed, order, bound_elements, problems)

    bound_count = sum(1 for element_id in order if parsed[element_id].type == BOUND_TYPE)
    structural_count = len(order) - bound_count
    if bound_count > MAX_BOUND:
        problem("limit_exceeded", None, f"{bound_count} bound elements; the limit is {MAX_BOUND}")
    if structural_count > MAX_STRUCTURAL:
        problem("limit_exceeded", None, f"{structural_count} structural elements; the limit is {MAX_STRUCTURAL}")

    if problems:
        raise SceneInvalid(problems)

    supplied = {element.identity: element for element in bound_elements}
    elements = []
    for element_id in drawing_order:
        item = parsed[element_id]
        elements.append(
            Element(
                id=item.id,
                type=item.type,
                parent=item.parent,
                x=float(item.box["x"]),
                y=float(item.box["y"]),
                width=float(item.box["width"]),
                height=float(item.box["height"]),
                style=Style(
                    **{name: tuple(float(channel) for channel in item.style[name]) for name in COLOUR_FIELDS},
                    **{name: float(item.style[name]) for name in NUMBER_FIELDS},
                ),
                # The adapter's own object, so nothing read from the candidate
                # can stand in for what the application supplied.
                bound=supplied[item.bound["identity"]] if item.bound is not None else None,
            )
        )
    return Scene(_PROOF, float(width), float(height), tuple(elements))


@dataclass
class _Parsed:
    id: str
    type: str
    parent: str | None
    box: dict[str, float]
    style: dict[str, Any]
    bound: dict[str, Any] | None
    numbers_usable: bool


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_element(item: Any, index: int, problems: list[Problem]) -> _Parsed | None:
    """Check one element's shape. Returns None when it cannot be placed in the tree."""

    def problem(code: str, detail: str) -> None:
        problems.append(Problem(code, label, detail))

    label = f"element {index}"
    if not isinstance(item, dict):
        problem("malformed", "an element is a JSON object")
        return None
    element_id = item.get("id")
    if not isinstance(element_id, str) or not element_id:
        problem("malformed", "id is not a non-empty string")
        return None
    label = element_id

    usable = True
    element_type = item.get("type")
    if element_type != BOUND_TYPE and element_type not in STRUCTURAL_TYPES:
        problem("malformed", f"type {element_type!r} is not one of {', '.join((BOUND_TYPE, *STRUCTURAL_TYPES))}")
        usable = False

    if "parent" not in item or not (item["parent"] is None or isinstance(item["parent"], str)):
        problem("tree", "parent is neither an element id nor null")
        usable = False

    allowed = {"id", "type", "parent", "box", "style"} | ({"bound"} if element_type == BOUND_TYPE else set())
    carried = sorted((set(item) - allowed) & ({"bound"} | set(BOUND_FIELDS)))
    if carried and element_type in STRUCTURAL_TYPES:
        problem("structural_carries_bound", f"a structural element carries {', '.join(carried)}")
        usable = False
    unknown = sorted(set(item) - allowed - set(carried))
    if unknown or (carried and element_type not in STRUCTURAL_TYPES):
        problem("malformed", f"unexpected fields: {', '.join(unknown or carried)}")
        usable = False

    numbers_usable = True
    box = item.get("box")
    if not isinstance(box, dict) or set(box) != set(BOX_FIELDS):
        problem("malformed", f"box is not {{{', '.join(BOX_FIELDS)}}}")
        numbers_usable = False
    else:
        for name in BOX_FIELDS:
            numbers_usable &= _check_number(box[name], f"box.{name}", label, problems)

    style = item.get("style")
    if not isinstance(style, dict) or set(style) != set(STYLE_FIELDS):
        problem("malformed", f"style does not hold exactly: {', '.join(STYLE_FIELDS)}")
        numbers_usable = False
    else:
        for name in NUMBER_FIELDS:
            numbers_usable &= _check_number(style[name], f"style.{name}", label, problems)
        for name in COLOUR_FIELDS:
            colour = style[name]
            if not isinstance(colour, list) or len(colour) != 4:
                problem("malformed", f"style.{name} is not [red, green, blue, alpha]")
                numbers_usable = False
            else:
                for channel in colour:
                    numbers_usable &= _check_number(channel, f"style.{name}", label, problems)

    bound = None
    if element_type == BOUND_TYPE:
        bound = item.get("bound")
        if not isinstance(bound, dict) or set(bound) != set(BOUND_FIELDS) or not isinstance(bound.get("identity"), str):
            problem("malformed", f"bound does not hold exactly: {', '.join(BOUND_FIELDS)}")
            usable = False

    if not usable:
        return None
    return _Parsed(
        id=element_id,
        type=element_type,
        parent=item["parent"],
        box=box if numbers_usable else {},
        style=style if numbers_usable else {},
        bound=bound,
        numbers_usable=numbers_usable,
    )


def _check_number(value: Any, name: str, label: str, problems: list[Problem]) -> bool:
    if not _is_number(value):
        problems.append(Problem("malformed", label, f"{name} is not a number"))
        return False
    if not math.isfinite(value):
        problems.append(Problem("non_finite", label, f"{name} is {value}"))
        return False
    return True


def _check_tree(parsed: dict[str, _Parsed], order: list[str], problems: list[Problem]) -> list[str]:
    """Check that the elements form one tree. Returns them in drawing order."""
    roots = [element_id for element_id in order if parsed[element_id].parent is None]
    if len(roots) != 1:
        problems.append(Problem("tree", None, f"{len(roots)} elements have no parent; a scene has exactly one root"))
    children: dict[str, list[str]] = {element_id: [] for element_id in order}
    sound = len(roots) == 1
    for element_id in order:
        parent = parsed[element_id].parent
        if parent is None:
            continue
        if parent not in parsed:
            problems.append(Problem("tree", element_id, f"parent {parent!r} is not an element of this scene"))
            sound = False
        elif parsed[parent].type == BOUND_TYPE:
            problems.append(Problem("tree", element_id, f"parent {parent!r} is a bound element; only structural elements have children"))
            sound = False
        else:
            children[parent].append(element_id)
    if roots and len(roots) == 1 and parsed[roots[0]].type == BOUND_TYPE:
        problems.append(Problem("tree", roots[0], "the root is a bound element; the root is structural"))
        sound = False
    if not sound:
        return []

    drawing_order: list[str] = []
    pending = [roots[0]]
    while pending:
        element_id = pending.pop()
        drawing_order.append(element_id)
        pending.extend(reversed(children[element_id]))
    reached = set(drawing_order)
    for element_id in order:
        if element_id not in reached:
            problems.append(Problem("tree", element_id, "not reachable from the root; its parents form a cycle"))
    return drawing_order


def _check_ranges(item: _Parsed, width: float, height: float, problems: list[Problem]) -> None:
    if not item.numbers_usable:
        return

    def problem(code: str, detail: str) -> None:
        problems.append(Problem(code, item.id, detail))

    box, style = item.box, item.style
    if box["width"] <= 0 or box["height"] <= 0:
        problem("out_of_range", f"box is {box['width']} by {box['height']}; width and height are above zero")
        return
    if (
        box["x"] < -_EDGE_TOLERANCE
        or box["y"] < -_EDGE_TOLERANCE
        or box["x"] + box["width"] > width + _EDGE_TOLERANCE
        or box["y"] + box["height"] > height + _EDGE_TOLERANCE
    ):
        problem(
            "outside_viewport",
            f"box x {box['x']}, y {box['y']}, {box['width']} by {box['height']} leaves the {width} by {height} viewport",
        )
    for name in COLOUR_FIELDS:
        if any(not 0 <= channel <= 1 for channel in style[name]):
            problem("out_of_range", f"style.{name} has a channel outside 0 to 1")
    if not 0 <= style["opacity"] <= 1:
        problem("out_of_range", f"style.opacity is {style['opacity']}; it lies in 0 to 1")
    half = min(box["width"], box["height"]) / 2
    for name in ("border_width", "corner_radius"):
        if not 0 <= style[name] <= half + _EDGE_TOLERANCE:
            problem("out_of_range", f"style.{name} is {style[name]}; it lies in 0 to half the box's shorter side ({half})")
    if style["elevation"] < 0:
        problem("out_of_range", f"style.elevation is {style['elevation']}; it is zero or more")
    if style["type_size"] <= 0:
        problem("out_of_range", f"style.type_size is {style['type_size']}; it is above zero")
    if not 100 <= style["type_weight"] <= 900:
        problem("out_of_range", f"style.type_weight is {style['type_weight']}; it lies in 100 to 900")


def _check_bound(
    parsed: dict[str, _Parsed],
    order: list[str],
    bound_elements: Sequence[BoundElement],
    problems: list[Problem],
) -> None:
    supplied = {element.identity: element.to_json() for element in bound_elements}
    seen: dict[str, int] = {}
    for element_id in order:
        item = parsed[element_id]
        if item.bound is None:
            continue
        identity = item.bound["identity"]
        seen[identity] = seen.get(identity, 0) + 1
        if identity not in supplied:
            problems.append(Problem("bound_unknown", element_id, f"{identity!r} was not supplied by the application"))
            continue
        for name in BOUND_FIELDS:
            if not _same(item.bound[name], supplied[identity][name]):
                problems.append(
                    Problem(
                        "bound_altered",
                        element_id,
                        f"{name} of {identity!r} is {item.bound[name]!r}; the application supplied {supplied[identity][name]!r}",
                    )
                )
    for identity in supplied:
        count = seen.get(identity, 0)
        if count == 0:
            problems.append(Problem("bound_missing", None, f"{identity!r} is not in the scene"))
        elif count > 1:
            problems.append(Problem("bound_duplicated", None, f"{identity!r} is in the scene {count} times"))


def _same(left: Any, right: Any) -> bool:
    """Equality that does not let 1 pass for True or 1.0, which JSON keeps apart."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right
