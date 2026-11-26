"""Model inputs: everything the scene model is given, and nothing else.

    {
      "bound_elements": [
        {"identity": "toolbar.save", "role": "button", "binding_kind": "save",
         "state": "disabled", "text_length": 4, "text_width": 37.6,
         "relationships": [{"relation": "part_of", "target": "workspace.toolbar"}]}
      ],
      "viewport": {"width": 960, "height": 540},
      "design_condition": {"navigation_position": "top", ...},
      "visual_preset": {"colours": {"primary": [r, g, b, a]}, "type": {"body": [size, weight]},
                        "spacing": {...}, ...}
    }

- A bound element is given by its identity, role, the kind of its action
  binding (the command it names, or null), its current state, the length of
  its text in characters, the measured width of its text and its semantic
  relationships. The text itself is not an input.
- `text_width` is the advance width of the widest line of the text at
  `REFERENCE_TYPE_SIZE` and `REFERENCE_TYPE_WEIGHT`, in viewport units.
- The design condition is its factor values. The visual preset is its token
  values; its name is not an input.

The true scene, a drawn image, validation results, a layout family's name, a
visual preset's name, seeds and diagnostic metadata are never inputs. `build`
cannot put them there, because it is not given them, and `problems` refuses
any inputs that hold a key or a value outside the shape above.

The same `build` serves the generator and D, Neural Scene, so the scene model
is asked at run time exactly what it was trained on. This module does not load
the reference layout or the design source.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from core_ultra import typography
from core_ultra.documents_adapter import RELATIONS, ROLES, STATES, BoundElement
from core_ultra.layout_family import FACTORS

REFERENCE_TYPE_SIZE = 16.0
REFERENCE_TYPE_WEIGHT = 400.0

FIELDS = ("bound_elements", "viewport", "design_condition", "visual_preset")
ELEMENT_FIELDS = ("identity", "role", "binding_kind", "state", "text_length", "text_width", "relationships")
TOKEN_GROUPS = ("colours", "type", "spacing", "dimensions", "borders", "radii", "elevation", "density", "opacity")
_TOKEN_LENGTHS = {"colours": 4, "type": 2}


def text_width(text: str) -> float:
    """The advance width of the text's widest line at the reference type size and weight."""
    return max(typography.measure(line, REFERENCE_TYPE_SIZE, REFERENCE_TYPE_WEIGHT) for line in text.split("\n"))


def preset_tokens(preset: Any) -> dict[str, dict[str, Any]]:
    """A visual preset's token values: every token group, without the preset's
    name, title or summary. A colour is [red, green, blue, alpha] and a type
    token is [size, weight]."""
    return {
        group: {token: list(value) if isinstance(value, tuple) else value for token, value in getattr(preset, group).items()}
        for group in TOKEN_GROUPS
    }


def build(
    bound_elements: Sequence[BoundElement],
    viewport: tuple[float, float],
    design_condition: Mapping[str, str],
    visual_preset: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The model inputs for these bound elements under this conditioning.

    `design_condition` is the factor values and `visual_preset` the token
    values, as `preset_tokens` returns them.
    """
    inputs = {
        "bound_elements": [
            {
                "identity": element.identity,
                "role": element.role,
                "binding_kind": None if element.binding is None else element.binding["command"],
                "state": element.state,
                "text_length": len(element.text),
                "text_width": text_width(element.text),
                "relationships": [dict(relationship) for relationship in element.relationships],
            }
            for element in bound_elements
        ],
        "viewport": {"width": float(viewport[0]), "height": float(viewport[1])},
        "design_condition": {factor: design_condition[factor] for factor in FACTORS},
        "visual_preset": {
            group: {token: list(value) if isinstance(value, (list, tuple)) else value for token, value in visual_preset[group].items()}
            for group in TOKEN_GROUPS
        },
    }
    found = problems(inputs)
    if found:
        raise ValueError("these are not model inputs: " + "; ".join(found))
    return inputs


def problems(inputs: Any) -> list[str]:
    """Every way this is not model inputs: a field that is missing, a field
    that is not one of the listed ones, or a value of the wrong kind. An empty
    list means it holds exactly what the scene model is given."""
    found: list[str] = []
    if not _exactly(inputs, FIELDS, "the inputs", found):
        return found

    elements = inputs["bound_elements"]
    if not isinstance(elements, list):
        found.append("bound_elements is not a list")
        elements = []
    for index, element in enumerate(elements):
        where = f"bound_elements[{index}]"
        if not _exactly(element, ELEMENT_FIELDS, where, found):
            continue
        if not isinstance(element["identity"], str) or not element["identity"]:
            found.append(f"{where}.identity is not a name")
        if element["role"] not in ROLES:
            found.append(f"{where}.role is not one of {', '.join(ROLES)}")
        if not (element["binding_kind"] is None or isinstance(element["binding_kind"], str)):
            found.append(f"{where}.binding_kind is neither a command's name nor null")
        if element["state"] not in STATES:
            found.append(f"{where}.state is not one of {', '.join(STATES)}")
        if not isinstance(element["text_length"], int) or isinstance(element["text_length"], bool) or element["text_length"] < 0:
            found.append(f"{where}.text_length is not a whole number at or above zero")
        if not _is_number(element["text_width"]) or element["text_width"] < 0:
            found.append(f"{where}.text_width is not a number at or above zero")
        relationships = element["relationships"]
        if not isinstance(relationships, list):
            found.append(f"{where}.relationships is not a list")
            continue
        for position, relationship in enumerate(relationships):
            inner = f"{where}.relationships[{position}]"
            if not _exactly(relationship, ("relation", "target"), inner, found):
                continue
            if relationship["relation"] not in RELATIONS:
                found.append(f"{inner}.relation is not one of {', '.join(RELATIONS)}")
            if not isinstance(relationship["target"], str) or not relationship["target"]:
                found.append(f"{inner}.target is not a name")

    viewport = inputs["viewport"]
    if _exactly(viewport, ("width", "height"), "viewport", found):
        for name in ("width", "height"):
            if not _is_number(viewport[name]) or viewport[name] <= 0:
                found.append(f"viewport.{name} is not a number above zero")

    condition = inputs["design_condition"]
    if _exactly(condition, FACTORS, "design_condition", found):
        for factor in FACTORS:
            if not isinstance(condition[factor], str) or not condition[factor]:
                found.append(f"design_condition.{factor} is not a factor value")

    preset = inputs["visual_preset"]
    if _exactly(preset, TOKEN_GROUPS, "visual_preset", found):
        for group in TOKEN_GROUPS:
            tokens = preset[group]
            if not isinstance(tokens, dict) or not tokens:
                found.append(f"visual_preset.{group} is not a set of tokens")
                continue
            length = _TOKEN_LENGTHS.get(group)
            for token, value in tokens.items():
                if length is None:
                    sound = _is_number(value)
                else:
                    sound = isinstance(value, list) and len(value) == length and all(_is_number(part) for part in value)
                if not sound:
                    kind = "a number" if length is None else f"{length} numbers"
                    found.append(f"visual_preset.{group}.{token} is not {kind}")
    return found


def _exactly(value: Any, fields: Sequence[str], where: str, found: list[str]) -> bool:
    """Whether `value` is an object with exactly these fields; says so if not."""
    if not isinstance(value, dict):
        found.append(f"{where} is not an object")
        return False
    sound = True
    for extra in sorted(set(value) - set(fields), key=str):
        found.append(f"{where} holds {extra!r}, which is not a model input")
        sound = False
    for missing in (field for field in fields if field not in value):
        found.append(f"{where} has no {missing}")
        sound = False
    return sound


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
