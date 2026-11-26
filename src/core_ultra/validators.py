"""Validators: what a scene must pass before the generator writes it as a target.

    scene, findings = judge(candidate, bound_elements, viewport, preset)

`judge` runs the validators below on a candidate scene and returns every
finding. A scene with any finding is rejected: the generator does not write it
as a dataset record, and records each finding with the validator that made it,
a code, the element and a sentence.

| Validator | Rejects | Codes |
| --- | --- | --- |
| scene validation | A scene the schema refuses: impossible geometry, a box outside the viewport, a bound element missing, repeated, unknown or altered (`core_ultra.scene`). | the scene schema's own |
| text fit | Text the font has no glyph for, text that runs past an edge of the box it is drawn in, and text that something drawn later lies over. | `text_not_drawable`, `text_overflows`, `text_too_tall`, `text_covered` |
| element completeness | An element outside its parent, an empty container, and elements or panels that overlap. | `outside_parent`, `empty_container`, `elements_overlap`, `panels_overlap` |
| state consistency | An element whose style values are not the ones its state has in the visual preset. Across records of one application state, `related_findings` rejects a state that moved a box or changed another element. | `state_style_mismatch`, `state_moves_box`, `state_changes_another` |
| hit targets | An element that is not what a pointer hits where it is drawn, because something lies over it. | `hit_target_covered`, `element_covered` |

`coverage` is the one validator of a whole dataset and not of a scene: it
lists every declared value that no accepted record shows.

These are validity constraints and nothing else. Each says that something
drawn would be clipped, hidden, outside what holds it, unreachable by the
pointer or at odds with the state the application supplied. None knows a
design factor, a layout family or a visual preset's name, and none prefers one
navigation position, panel arrangement, density or spacing to another. None
asks for padding around text, and none asks how elements are grouped into
containers. Design preferences live in the layout configuration, the design
source and the dataset configuration, and a design that passes these checks
is never rejected for what it is. `test_cli_layout_families.py` holds the
module to that.

Where text sits in its box is the runtime renderer's rule, and what a pointer
hits is the runtime renderer's answer, so text fit and hit targets ask the
runtime renderer for both. The visual preset is
passed in; this module loads neither the design source nor the reference
layout.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core_ultra import runtime_renderer, scene as scene_schema, typography
from core_ultra.documents_adapter import BoundElement
from core_ultra.scene import Element, Scene, SceneInvalid

SCENE_VALIDATION = "scene validation"
TEXT_FIT = "text fit"
COMPLETENESS = "element completeness"
STATE_CONSISTENCY = "state consistency"
HIT_TARGETS = "hit targets"
COVERAGE = "coverage"

# The validators of one scene, in the order they run.
SCENE_VALIDATORS = (SCENE_VALIDATION, TEXT_FIT, COMPLETENESS, STATE_CONSISTENCY, HIT_TARGETS)

# The components a role may be drawn as. Which of them an element is drawn as
# is the design's choice; that its style is that component's in the element's
# state is the constraint.
_COMPONENTS = {
    "button": ("button-primary", "button-quiet"),
    "text-field": ("field", "title-field"),
    "text-area": ("editor-body",),
    "list-item": ("row", "row-open"),
    "heading": ("heading",),
    "label": ("label",),
    "status": ("notification",),
}
_CONTAINERS = ("panel", "container")
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Finding:
    """One reason a scene is rejected."""

    validator: str
    code: str
    element: str | None
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"validator": self.validator, "code": self.code, "element": self.element, "detail": self.detail}

    def __str__(self) -> str:
        where = f" ({self.element})" if self.element else ""
        return f"{self.code}{where}: {self.detail}"


def judge(
    candidate: Any, bound_elements: Sequence[BoundElement], viewport: tuple[float, float], preset: Any
) -> tuple[Scene | None, tuple[Finding, ...]]:
    """The candidate as a validated scene (None when scene validation refuses
    it) and every finding of every validator. A scene that scene validation
    refuses is not read by the others, which read validated scenes only."""
    try:
        scene = scene_schema.validate(candidate, bound_elements, viewport)
    except SceneInvalid as refused:
        return None, tuple(Finding(SCENE_VALIDATION, problem.code, problem.element, problem.detail) for problem in refused.problems)
    return scene, findings(scene, preset)


def findings(scene: Scene, preset: Any) -> tuple[Finding, ...]:
    """Every finding of the validators that read a validated scene."""
    return (*text_fit(scene), *completeness(scene), *state_consistency(scene, preset), *hit_targets(scene))


# --- text fit ----------------------------------------------------------------------


def text_fit(scene: Scene) -> list[Finding]:
    """Text is never elided, wrapped or clipped, so it fits or the scene is
    rejected. The font must have a glyph for every character, every line must
    lie inside its element's box, where the runtime renderer puts it, and
    nothing drawn later may lie over it. How much room is left around the text
    is the design's affair and is not judged."""
    found = []
    for index, element in enumerate(scene.elements):
        if element.bound is None or not element.bound.text:
            continue
        style = element.style
        height = typography.line_height(style.type_size, style.type_weight)
        try:
            lines = [
                (text, x, y, typography.measure(text, style.type_size, style.type_weight))
                for text, x, y in runtime_renderer.text_lines(element)
                if text
            ]
        except typography.TextNotDrawable as refused:
            found.append(Finding(TEXT_FIT, "text_not_drawable", element.id, str(refused)))
            continue
        right = element.x + element.width
        for text, x, y, width in lines:
            if x < element.x - _TOLERANCE or x + width > right + _TOLERANCE:
                found.append(
                    Finding(TEXT_FIT, "text_overflows", element.id, f"{text!r} runs from x {_units(x)} to {_units(x + width)}; the box runs from {_units(element.x)} to {_units(right)}")
                )
        if lines:
            top, bottom = lines[0][2], lines[-1][2] + height
            if top < element.y - _TOLERANCE or bottom > element.y + element.height + _TOLERANCE:
                found.append(
                    Finding(TEXT_FIT, "text_too_tall", element.id, f"{len(lines)} lines of text run from y {_units(top)} to {_units(bottom)}; the box runs from {_units(element.y)} to {_units(element.y + element.height)}")
                )
        for other in scene.elements[index + 1 :]:
            if not _paints(other):
                continue
            covered = [text for text, x, y, width in lines if _overlap((x, y, width, height), _box(other))]
            if covered:
                found.append(Finding(TEXT_FIT, "text_covered", element.id, f"{other.id} is drawn over {covered[0]!r}"))
    return found


# --- element completeness ----------------------------------------------------------


def completeness(scene: Scene) -> list[Finding]:
    """Every element is whole and in its place: inside its parent and not
    sharing its ground with a sibling, and no panel or container stands empty.
    Which container an element is put in is the design's affair and is not
    judged."""
    found = []
    by_id = {element.id: element for element in scene.elements}
    children: dict[str, list[Element]] = {element.id: [] for element in scene.elements}
    for element in scene.elements:
        if element.parent is not None:
            children[element.parent].append(element)
            parent = by_id[element.parent]
            if not _inside(_box(element), _box(parent)):
                found.append(Finding(COMPLETENESS, "outside_parent", element.id, f"its box leaves the box of {parent.id}"))

    for element in scene.structural_elements:
        if element.type in _CONTAINERS and not children[element.id]:
            found.append(Finding(COMPLETENESS, "empty_container", element.id, "a panel or container with nothing in it"))

    for parent, siblings in children.items():
        for index, first in enumerate(siblings):
            for second in siblings[index + 1 :]:
                if not _overlap(_box(first), _box(second)):
                    continue
                if first.bound is not None and second.bound is not None:
                    found.append(Finding(COMPLETENESS, "elements_overlap", first.id, f"its box overlaps the box of {second.id}"))
                elif first.type in _CONTAINERS and second.type in _CONTAINERS:
                    found.append(Finding(COMPLETENESS, "panels_overlap", first.id, f"its box overlaps the box of {second.id}"))
    return found


# --- state consistency ---------------------------------------------------------------


def state_consistency(scene: Scene, preset: Any) -> list[Finding]:
    """An element is drawn in the state the application supplied: its style
    values are those one of its role's components has in that state."""
    found = []
    for element in scene.bound_elements:
        bound = element.bound
        candidates = [preset.component(name).style(bound.state) for name in _COMPONENTS[bound.role]]
        if not any(_style_is(element, style) for style in candidates):
            found.append(
                Finding(
                    STATE_CONSISTENCY, "state_style_mismatch", element.id,
                    f"its style is not that of {' or '.join(_COMPONENTS[bound.role])} in the state {bound.state}",
                )
            )  # fmt: skip
    return found


def related_findings(first: Scene, other: Scene) -> list[Finding]:
    """Two scenes of one application state under different pointer states
    differ only in the style of the elements whose state differs: a state
    changes style values, never a box and never another element."""
    found = []
    ours = {element.id: element for element in first.elements}
    for element in other.elements:
        before = ours.pop(element.id, None)
        if before is None:
            found.append(Finding(STATE_CONSISTENCY, "state_changes_another", element.id, "it is not in the related scene"))
            continue
        if _box(before) != _box(element) or (before.type, before.parent) != (element.type, element.parent):
            found.append(Finding(STATE_CONSISTENCY, "state_moves_box", element.id, "its box or its place in the tree differs from the related scene's"))
        if (before.bound is None) != (element.bound is None):
            continue
        same_state = before.bound is None or before.bound.state == element.bound.state
        if same_state and before.style != element.style:
            found.append(Finding(STATE_CONSISTENCY, "state_changes_another", element.id, "its style differs from the related scene's and its state does not"))
    for missing in ours:
        found.append(Finding(STATE_CONSISTENCY, "state_changes_another", missing, "it is in the related scene only"))
    return found


# --- hit targets -----------------------------------------------------------------------


def hit_targets(scene: Scene) -> list[Finding]:
    """What is drawn at an element's place is what a pointer hits there.

    The runtime renderer is asked what it hits at five points of each bound
    element: the centre and the four points halfway from the centre to each
    corner. The answer must be the element itself. A status drawn over it (the
    notification, which has no action and is laid over the workspace) may
    take one of the four outer points and never the centre.
    """
    found = []
    for element in scene.bound_elements:
        code = "hit_target_covered" if element.bound.binding is not None else "element_covered"
        centre = (element.x + element.width / 2, element.y + element.height / 2)
        outer = [(element.x + element.width * across, element.y + element.height * down) for down in (0.25, 0.75) for across in (0.25, 0.75)]
        lost_to_status = 0
        for point in (centre, *outer):
            hit = runtime_renderer.hit_test(scene, *point)
            if hit is not None and hit.identity == element.bound.identity:
                continue
            is_status = hit is not None and hit.role == "status" and hit.binding is None
            if is_status and point != centre:
                lost_to_status += 1
                if lost_to_status == 1:
                    continue
            what = "nothing" if hit is None else hit.identity
            found.append(Finding(HIT_TARGETS, code, element.id, f"at x {_units(point[0])}, y {_units(point[1])} a pointer hits {what}"))
            break
    return found


# --- coverage ------------------------------------------------------------------------


def coverage(declared: Mapping[str, Sequence[str]], seen: Mapping[str, Iterable[str]]) -> dict[str, Any]:
    """What the accepted records show of what was declared.

    `declared` names, for each dimension, the values the dataset was meant to
    show; `seen` gives, for each dimension, the value of every accepted record
    (or of every element of every record). A declared value that is never seen
    is a gap, with its dimension.
    """
    dimensions = {}
    gaps = []
    for dimension, values in declared.items():
        counts = Counter(seen.get(dimension, ()))
        dimensions[dimension] = {value: counts.get(value, 0) for value in values}
        gaps += [
            {"validator": COVERAGE, "code": "not_covered", "dimension": dimension, "value": value, "detail": f"no accepted record shows {dimension} {value}"}
            for value in values
            if not counts.get(value)
        ]
    return {"dimensions": dimensions, "gaps": gaps}


# --- small things ----------------------------------------------------------------------


def _box(element: Element) -> tuple[float, float, float, float]:
    return (element.x, element.y, element.width, element.height)


def _inside(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> bool:
    return (
        inner[0] >= outer[0] - _TOLERANCE
        and inner[1] >= outer[1] - _TOLERANCE
        and inner[0] + inner[2] <= outer[0] + outer[2] + _TOLERANCE
        and inner[1] + inner[3] <= outer[1] + outer[3] + _TOLERANCE
    )


def _overlap(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
    """Whether two boxes share ground. Boxes that only touch do not."""
    across = min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0])
    down = min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1])
    return across > _TOLERANCE and down > _TOLERANCE


def _paints(element: Element) -> bool:
    """Whether drawing this element can hide what is under it."""
    return element.bound is not None or element.style.fill[3] * element.style.opacity > 0


def _style_is(element: Element, stated: Mapping[str, Any]) -> bool:
    """Whether the element has every style value a component states."""
    for name, value in stated.items():
        ours = getattr(element.style, name)
        if isinstance(value, list):
            if any(abs(a - b) > 1e-9 for a, b in zip(ours, value, strict=True)):
                return False
        elif abs(ours - value) > 1e-9:
            return False
    return True


def _units(value: float) -> str:
    """A length or a coordinate in viewport units, as a finding's sentence writes it."""
    return f"{value:.1f}"
