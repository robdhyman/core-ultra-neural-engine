"""Scene export: a validated scene written as an editable SVG.

The SVG is an export for opening in a design tool. It is not a renderer of
record: visual results are measured with the runtime renderer and nothing
else, and `scene_export_comparison` measures how far a rasterised SVG is from
it. Nothing here reads anything but the file it is given and the bundled
font, by which text is placed, and nothing calls a network.

What is written, from the scene and nothing else:

    <svg width height viewBox>                 the viewport, in viewport units
      <defs> <filter id="elevation-4"> ...     one shadow for each elevation in the scene
      <g id="s.root" data-type="surface">      one group for each element, named by its id
        <rect .../>                            the element's own shape
        <g id="b.toolbar.save" data-type="bound" data-role="button">
          <rect .../>
          <text ...>Save</text>                text as text, never as outlines
        </g>
      </g>
    </svg>

- **Tree and order.** An element's group holds its own shape, then its text,
  then the groups of the elements whose parent it is, in the scene's order.
  Document order is therefore the scene's drawing order.
- **Fill** is `fill` as #RRGGBB, with `fill-opacity` when its alpha is below 1
  and `fill="none"` when it is 0.
- **Border.** SVG strokes along the middle of an outline; the scene's border
  lies inside it. A bordered rectangle is therefore written half a border in
  from the element's box, with its corner radius smaller by the same amount, so
  the stroke's outer edge is the element's outline.
- **Corner radius** is `rx`.
- **Opacity** is on the element's own shape and text, never on its group,
  because the scene's opacity is the element's own and a group also holds the
  elements inside it.
- **Elevation** is a filter on the shape: the shape's alpha blurred with a
  standard deviation of half the elevation, moved down by half the elevation,
  in black at the runtime renderer's shadow alpha. A blur is not the runtime
  renderer's smoothstep; it is the editable shadow nearest to it.
- **Text** is one `<text>` in Inter at the scene's type size, in
  `text_colour`, on the baseline the runtime renderer draws it on. Its weight
  is the scene's type weight at the nearest hundred, which is the weight the
  runtime renderer draws. A button's is anchored at the middle of its box.
  Text on several lines (a text-area) is one `<tspan>` for each line that says
  anything. Text the font has no glyph for is refused with `TextNotDrawable`,
  as the runtime renderer refuses it.

A scene comes from a dataset record (its `target.scene`, validated against the
bound elements and viewport the record holds) or from a scene file (stored
scene JSON). A scene file names no application state, so it is validated
against the bound elements it carries itself: every problem of shape, tree,
range, viewport and limit is found, and a bound element that is missing,
invented or altered from what an application supplied cannot be.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from core_ultra import scene as scene_schema
from core_ultra.documents_adapter import BoundElement
from core_ultra.scene import Element, Problem, Scene, SceneInvalid

RECORD_KIND = "dataset-record"
SCENE_KIND = "scene"


class SourceError(Exception):
    """The file given holds no scene that could be read."""


class NotExportable(Exception):
    """A valid scene that cannot be written as XML."""


def load(path: str | Path) -> tuple[Scene, str]:
    """The validated scene a file holds, and what kind of file it was.

    Raises `SceneInvalid`, listing every problem, when the scene is not valid,
    and `SourceError` when the file holds no scene at all.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_bytes())
    except OSError as error:
        raise SourceError(f"{path} cannot be read: {error.strerror or error}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SourceError(f"{path} is not JSON: {error}") from None
    kind = data.get("kind") if isinstance(data, dict) else None
    try:
        if kind == RECORD_KIND:
            return from_record(data, path), "dataset record"
        if kind == SCENE_KIND:
            return _from_scene_file(data), "scene file"
    except OverflowError:
        raise SourceError(f"{path} holds a whole number too large to be a scene's value") from None
    raise SourceError(f"{path} is neither a dataset record nor a scene")


def from_record(record: dict[str, Any], path: Path) -> Scene:
    """A dataset record's true scene, validated against what the record says the application supplied."""
    target = record.get("target")
    candidate = target.get("scene") if isinstance(target, dict) else None
    if candidate is None:
        raise SourceError(f"{path} has no target scene")
    try:
        supplied = tuple(_bound_element(item) for item in record["application"]["bound_elements"])
        stated = record["inputs"]["viewport"]
        viewport = (stated["width"], stated["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise SourceError(f"{path} does not say what the application supplied or its viewport: {error!r}") from None
    if not _usable_viewport(viewport):
        raise SourceError(f"{path} has a viewport of {viewport[0]!r} by {viewport[1]!r}; it is two finite numbers above zero")
    return scene_schema.validate(candidate, supplied, viewport)


def _from_scene_file(candidate: dict[str, Any]) -> Scene:
    problems: list[Problem] = []
    stated = candidate.get("viewport")
    viewport = (stated.get("width"), stated.get("height")) if isinstance(stated, dict) else (None, None)
    viewport_usable = _usable_viewport(viewport)
    if not viewport_usable:
        problems.append(Problem("malformed", None, "viewport is not a width and a height, both finite numbers above zero"))

    # The bound elements the scene carries stand in for what an application supplied.
    carried: list[BoundElement] = []
    unusable: set[str] = set()
    items = candidate.get("elements")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("type") != scene_schema.BOUND_TYPE:
            continue
        bound, element_id = item.get("bound"), item.get("id")
        if not isinstance(bound, dict) or set(bound) != set(scene_schema.BOUND_FIELDS) or not isinstance(element_id, str):
            continue  # scene validation says what is wrong with it
        try:
            carried.append(_bound_element(bound))
        except TypeError as error:
            unusable.add(element_id)
            problems.append(Problem("malformed", element_id, f"bound is not a bound element: {error}"))

    try:
        scene = scene_schema.validate(candidate, carried, viewport if viewport_usable else (math.inf, math.inf))
    except SceneInvalid as refused:
        for problem in refused.problems:
            repeats_viewport = not viewport_usable and problem.element is None and problem.detail.startswith("viewport")
            repeats_bound = problem.code == "bound_unknown" and problem.element in unusable
            if not (repeats_viewport or repeats_bound):
                problems.append(problem)
    if problems:
        raise SceneInvalid(problems)
    return scene


def _usable_viewport(viewport: tuple[Any, Any]) -> bool:
    try:
        return all(scene_schema._is_finite_number(value) and value > 0 for value in viewport)
    except OverflowError:  # a whole number too large for a float
        return False


def _bound_element(item: Any) -> BoundElement:
    """A bound element from its stored JSON, or TypeError when it is not one."""
    if not isinstance(item, dict):
        raise TypeError("it is not a JSON object")
    for name in ("identity", "role", "text", "state"):
        if not isinstance(item[name], str):
            raise TypeError(f"{name} is not text")
    binding, relationships = item["binding"], item["relationships"]
    if not (binding is None or isinstance(binding, dict)):
        raise TypeError("binding is neither an object nor null")
    if not isinstance(relationships, list) or not all(isinstance(relationship, dict) for relationship in relationships):
        raise TypeError("relationships is not a list of objects")
    return BoundElement(
        identity=item["identity"], role=item["role"], text=item["text"], binding=binding,
        state=item["state"], relationships=tuple(relationships),
    )  # fmt: skip


# --- writing -------------------------------------------------------------------------


def to_svg(scene: Scene) -> str:
    """The scene as SVG text. The same scene always gives the same text."""
    if not isinstance(scene, Scene):
        raise TypeError("scene export reads a validated Scene; pass the candidate through scene.validate")
    # Imported here: the shadow's constants and the place of text are the runtime renderer's.
    from core_ultra import runtime_renderer

    width, height = _number(scene.viewport_width), _number(scene.viewport_height)
    children: dict[str | None, list[Element]] = {}
    for element in scene.elements:
        children.setdefault(element.parent, []).append(element)

    # Filter names must not be an element's id; ids are unique in a document.
    prefix = "elevation-"
    while any(element.id.startswith(prefix) for element in scene.elements):
        prefix = "_" + prefix
    elevations = sorted({_elevation(element) for element in scene.elements} - {0.0})

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
    ]
    if elevations:
        lines.append("  <defs>")
        for elevation in elevations:
            half = _number(elevation / 2)
            lines += [
                f'    <filter id={_attribute(prefix + _number(elevation))} filterUnits="userSpaceOnUse" x="0" y="0" '
                f'width="{width}" height="{height}" color-interpolation-filters="sRGB">',
                f'      <feGaussianBlur in="SourceAlpha" stdDeviation="{half}"/>',
                f'      <feOffset dy="{half}" result="shadow"/>',
                f'      <feFlood flood-color="#000000" flood-opacity="{_number(runtime_renderer.SHADOW_ALPHA)}"/>',
                '      <feComposite in2="shadow" operator="in"/>',
                '      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>',
                "    </filter>",
            ]
        lines.append("  </defs>")

    def write(element: Element, depth: int) -> None:
        indent = "  " * depth
        role = f" data-role={_attribute(element.bound.role)}" if element.bound is not None else ""
        lines.append(f'{indent}<g id={_attribute(element.id)} data-type="{element.type}"{role}>')
        lines.append(f"{indent}  {_shape(element, prefix)}")
        if element.bound is not None and element.bound.text:
            lines.append(f"{indent}  {_text(element, runtime_renderer.text_lines(element))}")
        for child in children.get(element.id, []):
            write(child, depth + 1)
        lines.append(f"{indent}</g>")

    for root in children.get(None, []):
        write(root, 1)
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _shape(element: Element, filter_prefix: str) -> str:
    style = element.style
    bordered = style.border_width > 0 and style.border_colour[3] > 0
    half = style.border_width / 2 if bordered else 0.0
    parts = [
        f'x="{_number(element.x + half)}"',
        f'y="{_number(element.y + half)}"',
        f'width="{_number(element.width - 2 * half)}"',
        f'height="{_number(element.height - 2 * half)}"',
    ]
    radius = max(style.corner_radius - half, 0.0)
    if radius > 0:
        parts.append(f'rx="{_number(radius)}"')
    parts += _paint("fill", style.fill)
    if bordered:
        parts += _paint("stroke", style.border_colour)
        parts.append(f'stroke-width="{_number(style.border_width)}"')
    if style.opacity < 1:
        parts.append(f'opacity="{_number(style.opacity)}"')
    if _elevation(element) > 0:
        parts.append(f"filter={_attribute(f'url(#{filter_prefix}{_number(_elevation(element))})')}")
    return f"<rect {' '.join(parts)}/>"


def _elevation(element: Element) -> float:
    """The element's elevation as it is written: two that are written alike share one filter."""
    return round(element.style.elevation, 6)


def _text(element: Element, placed: tuple[tuple[str, float, float], ...]) -> str:
    from core_ultra import typography

    style = element.style
    for text, _, _ in placed:
        # Raises TextNotDrawable for a character the font lacks, whatever the element's role.
        typography.shape(text, style.type_weight)
    ascent = typography.shape("", style.type_weight).ascent * typography.reference_scale(style.type_size)
    parts = [
        'xml:space="preserve"',
        f'font-family="{typography.FONT_FAMILY}"',
        f'font-size="{_number(style.type_size)}"',
        f'font-weight="{_number(typography.font_weight(style.type_weight))}"',
        *_paint("fill", style.text_colour),
    ]
    if style.opacity < 1:
        parts.append(f'opacity="{_number(style.opacity)}"')
    if element.bound.role == "button":
        # Anchored at the middle, so it stays centred whatever the tool measures the text to be.
        placed = tuple((text, element.x + element.width / 2, top) for text, _, top in placed)
        parts.append('text-anchor="middle"')

    def position(x: float, top: float) -> str:
        return f'x="{_number(x)}" y="{_number(top + ascent)}"'

    if len(placed) == 1:
        text, x, top = placed[0]
        return f"<text {position(x, top)} {' '.join(parts)}>{_characters(text)}</text>"
    spans = "".join(f"<tspan {position(x, top)}>{_characters(text)}</tspan>" for text, x, top in placed if text)
    return f"<text {' '.join(parts)}>{spans}</text>"


def _paint(name: str, colour: tuple[float, float, float, float]) -> list[str]:
    red, green, blue, alpha = colour
    if alpha <= 0:
        return [f'{name}="none"']
    parts = [f'{name}="#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"']
    if alpha < 1:
        parts.append(f'{name}-opacity="{_number(alpha)}"')
    return parts


def _number(value: float) -> str:
    """A number as SVG writes it: at most six decimals, no trailing zeros, never -0."""
    rounded = round(float(value), 6)
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return str(int(rounded))
    return repr(rounded)


def _writable(text: str) -> str:
    for character in text:
        code = ord(character)
        if not (code in (0x9, 0xA, 0xD) or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or code >= 0x10000):
            raise NotExportable(f"{text!r} holds the character U+{code:04X}, which XML cannot hold")
    return text


def _attribute(value: str) -> str:
    return quoteattr(_writable(value), {"\n": "&#10;", "\r": "&#13;", "\t": "&#9;"})


def _characters(value: str) -> str:
    return escape(_writable(value), {"\r": "&#13;"})
