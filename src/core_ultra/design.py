"""The design source: visual presets and element styling, and the check that
DESIGN.md and the generator configuration say the same.

Two files hold the design. `DESIGN.md` is the written one, in the Google Labs
DESIGN.md format (version alpha): tokens as YAML front matter, then prose. The
generator configuration (`configs/design/v1.json`) is the executable one, in
the generator's own vocabulary. The reference layout reads only the
configuration; `check` reads both and lists every disagreement.

    design = load()
    preset = design.preset("warm-paper")       # a VisualPreset
    button = preset.component("button-primary")
    button.height, button.padding, button.type  # sizes the layout uses
    button.style("hover")                       # scene style values for a state

What a visual preset is: one complete set of token values in nine groups
(`colours`, `type`, `spacing`, `dimensions`, `borders`, `radii`, `elevation`,
`density`, `opacity`). Every preset has the same token names. Components are
written once and name tokens in braces, as in `{colours.primary}`, so the same
component is a different set of style values in each preset.

A component's states are separate components named `<component>-<state>`, as
the DESIGN.md format has them. A state's entry lists only what it changes.

How the two files correspond:

| DESIGN.md | Generator configuration |
| --- | --- |
| top-level token groups | the preset named by `preset`, under `presets` |
| `presets.<name>` token groups | `presets.<name>` |
| `colors`, `typography`, `rounded` | `colours`, `type`, `radii` |
| `16px` | `16` (viewport units) |
| `fontFamily`, `fontSize`, `fontWeight` | `font.family`, `size`, `weight` |
| `backgroundColor`, `textColor`, `borderColor`, `borderWidth`, `rounded`, `typography` | `fill`, `text_colour`, `border_colour`, `border_width`, `corner_radius`, `type` |
| `elevation`, `opacity`, `height`, `padding` | the same names |

The DESIGN.md format has no token group for dimensions, borders, elevation,
density, opacity, states or presets, and no component property for a border,
an elevation or an opacity. Those are extension keys here, which the format
allows. Google's own linter (`@google/design.md`) is not run by this project;
`check` enforces the format rules this file relies on.

This module is part of the generator. D, Neural Scene must run without it.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "design" / "v1.json"
DEFAULT_DESIGN_MD = REPO_ROOT / "DESIGN.md"

STATES = ("default", "hover", "pressed", "focused", "disabled")
NUMBER_GROUPS = ("spacing", "dimensions", "borders", "radii", "elevation", "density", "opacity")
GROUPS = ("colours", "type", *NUMBER_GROUPS)
COLOUR_PROPERTIES = ("fill", "text_colour", "border_colour")
NUMBER_PROPERTIES = ("border_width", "corner_radius", "elevation", "opacity")
SIZE_PROPERTIES = ("height", "padding")
PROPERTIES = (*COLOUR_PROPERTIES, *NUMBER_PROPERTIES, "type", *SIZE_PROPERTIES)
FORMAT_VERSION = "alpha"

# The format's sections in the order it requires, each with its aliases.
SECTIONS = (
    ("Overview", "Brand & Style"),
    ("Colors",),
    ("Typography",),
    ("Layout", "Layout & Spacing"),
    ("Elevation & Depth", "Elevation"),
    ("Shapes",),
    ("Motion & Micro-interaction", "Motion & Micro-interactions", "Motion"),
    ("Voice & Content Strategy",),
    ("Components",),
    ("Do's and Don'ts",),
)

_GROUP_NAMES = {"colors": "colours", "typography": "type", "rounded": "radii"}
_WRITTEN_GROUPS = ("colors", "typography", "rounded", "spacing", "dimensions", "borders", "elevation", "density", "opacity")
_PROPERTY_NAMES = {
    "backgroundColor": "fill",
    "textColor": "text_colour",
    "borderColor": "border_colour",
    "borderWidth": "border_width",
    "rounded": "corner_radius",
    "typography": "type",
    "elevation": "elevation",
    "opacity": "opacity",
    "height": "height",
    "padding": "padding",
}
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_REFERENCE = re.compile(r"\{([a-z]+)\.([a-z0-9-]+)\}")
_PX = re.compile(r"(\d+(?:\.\d+)?)px")
_UNITLESS = {"dimensions": ("list-share",), "opacity": None}  # None: every token of the group


class DesignError(ValueError):
    """The generator configuration cannot be used. `problems` lists why."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Component:
    """One element's styling in one visual preset.

    `height` and `padding` are sizes the layout applies and `type` is the type
    size and weight, each None where the component states none.
    """

    name: str
    height: float | None
    padding: float | None
    type: tuple[float, float] | None
    _styles: Mapping[str, Mapping[str, Any]]

    def style(self, state: str = "default") -> dict[str, Any]:
        """The scene style values this component states, in this state. A
        value it does not state is absent; the scene writer supplies it."""
        if state not in STATES:
            raise ValueError(f"{state!r} is not a state; the states are {', '.join(STATES)}")
        return {name: list(value) if isinstance(value, tuple) else value for name, value in self._styles[state].items()}


@dataclass(frozen=True)
class VisualPreset:
    """A named, coherent set of style values, and every component resolved in it.

    Colours are RGBA with channels from 0 to 1. A type token is (size, weight).
    Every length is in viewport units.
    """

    name: str
    title: str
    summary: str
    colours: Mapping[str, tuple[float, float, float, float]]
    type: Mapping[str, tuple[float, float]]
    spacing: Mapping[str, float]
    dimensions: Mapping[str, float]
    borders: Mapping[str, float]
    radii: Mapping[str, float]
    elevation: Mapping[str, float]
    density: Mapping[str, float]
    opacity: Mapping[str, float]
    components: Mapping[str, Component]

    def component(self, name: str) -> Component:
        try:
            return self.components[name]
        except KeyError:
            raise DesignError([f"the design has no component {name!r}"]) from None


@dataclass(frozen=True)
class Design:
    name: str
    version: int
    default_preset: str
    states: tuple[str, ...]
    font: Mapping[str, Any]
    presets: Mapping[str, VisualPreset]

    def preset(self, name: str | None = None) -> VisualPreset:
        """The visual preset of this name, or the default one."""
        name = self.default_preset if name is None else name
        try:
            return self.presets[name]
        except KeyError:
            raise DesignError([f"{name!r} is not a visual preset; the presets are {', '.join(self.presets)}"]) from None


def load(path: str | Path | None = None) -> Design:
    """The design in a generator configuration. Raises `DesignError` with
    every problem when the configuration cannot be used."""
    return _load(str(Path(path or DEFAULT_CONFIG).resolve()))


@lru_cache(maxsize=16)
def _load(path: str) -> Design:
    raw = _read_json(Path(path))
    problems = _config_problems(raw)
    if problems:
        raise DesignError(problems)
    presets = {name: _resolve(name, tokens, raw["components"]) for name, tokens in raw["presets"].items()}
    return Design(
        name=raw["name"],
        version=raw["version"],
        default_preset=raw["default_preset"],
        states=tuple(raw["states"]),
        font=MappingProxyType(dict(raw["font"])),
        presets=MappingProxyType(presets),
    )


def check(design_md: str | Path | None = None, config: str | Path | None = None) -> list[str]:
    """Every way DESIGN.md and the generator configuration disagree, and every
    way either is malformed. An empty list means they say the same."""
    design_md = Path(design_md or DEFAULT_DESIGN_MD)
    config = Path(config or DEFAULT_CONFIG)
    try:
        raw = _read_json(config)
    except DesignError as error:
        return list(error.problems)
    problems = [f"generator configuration: {problem}" for problem in _config_problems(raw)]
    try:
        text = design_md.read_text()
    except FileNotFoundError:
        return [*problems, f"{design_md} does not exist"]
    written, md_problems = _read_design_md(text)
    problems += [f"DESIGN.md: {problem}" for problem in md_problems]
    if problems:
        return problems
    _compare("", written, _canonical(raw), problems)
    return problems


def summary(path: str | Path | None = None) -> str:
    """One line saying how much a generator configuration holds."""
    design = load(path)
    preset = design.preset()
    values = sum(len(getattr(preset, group)) for group in GROUPS)
    return f"{len(design.presets)} visual presets, {len(preset.components)} components, {values} token values in each preset"


# --- the generator configuration ---------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise DesignError([f"{path} does not exist"]) from None
    except json.JSONDecodeError as error:
        raise DesignError([f"{path} is not valid JSON: {error}"]) from None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _config_problems(raw: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(raw, dict) or raw.get("kind") != "design-config":
        return ['it is not an object of kind "design-config"']
    if not isinstance(raw.get("name"), str) or not raw.get("name"):
        problems.append("name is missing")
    if not isinstance(raw.get("version"), int) or isinstance(raw.get("version"), bool):
        problems.append("version is not a whole number")
    if raw.get("states") != list(STATES):
        problems.append(f"states is not {list(STATES)}")
    font = raw.get("font")
    if not isinstance(font, dict) or not isinstance(font.get("family"), str):
        problems.append("font.family is missing")
    presets = raw.get("presets")
    components = raw.get("components")
    if not isinstance(presets, dict) or not presets:
        return [*problems, "presets is missing or empty"]
    if not isinstance(components, dict) or not components:
        return [*problems, "components is missing or empty"]
    if raw.get("default_preset") not in presets:
        problems.append(f"default_preset {raw.get('default_preset')!r} is not one of the presets")

    first_name, first = next(iter(presets.items()))
    for name, tokens in presets.items():
        where = f"presets.{name}"
        if not _NAME.fullmatch(name):
            problems.append(f"{where}: a preset's name is lower-case words joined by hyphens")
        if not isinstance(tokens, dict):
            problems.append(f"{where} is not an object")
            continue
        for field in ("title", "summary"):
            if not isinstance(tokens.get(field), str) or not tokens.get(field):
                problems.append(f"{where}.{field} is missing")
        for group in GROUPS:
            values = tokens.get(group)
            if not isinstance(values, dict) or not values:
                problems.append(f"{where}.{group} is missing or empty")
                continue
            for token, value in values.items():
                problem = _token_problem(group, value)
                if not _NAME.fullmatch(token):
                    problem = "a token's name is lower-case words joined by hyphens"
                if problem:
                    problems.append(f"{where}.{group}.{token}: {problem}")
            reference = first.get(group) if isinstance(first, dict) else None
            if isinstance(reference, dict) and set(values) != set(reference):
                differing = ", ".join(sorted(set(values) ^ set(reference)))
                problems.append(f"{where}.{group} does not have the same tokens as presets.{first_name}.{group}: {differing}")
        for extra in sorted(set(tokens) - set(GROUPS) - {"title", "summary"}):
            problems.append(f"{where}.{extra} is not a token group")
    if problems:
        return problems

    for name, properties in components.items():
        where = f"components.{name}"
        if not _NAME.fullmatch(name):
            problems.append(f"{where}: a component's name is lower-case words joined by hyphens")
        if not isinstance(properties, dict) or not properties:
            problems.append(f"{where} is missing or empty")
            continue
        base, state = _base_and_state(name, components)
        for property_, value in properties.items():
            if property_ not in PROPERTIES:
                problems.append(f"{where}.{property_} is not a component property")
                continue
            if state != "default" and property_ in SIZE_PROPERTIES:
                problems.append(f"{where}.{property_}: a state changes style values, never a size")
                continue
            for preset_name, tokens in presets.items():
                problem = _value_problem(property_, value, tokens)
                if problem:
                    problems.append(f"{where}.{property_}: {problem} (in presets.{preset_name})")
                    break
    return problems


def _token_problem(group: str, value: Any) -> str | None:
    if group == "colours":
        return None if isinstance(value, str) and _HEX.fullmatch(value) else f"{value!r} is not a colour written #RRGGBB"
    if group == "type":
        if not isinstance(value, dict) or set(value) != {"size", "weight"}:
            return "a type token has exactly a size and a weight"
        if not _is_number(value["size"]) or value["size"] <= 0:
            return f"size {value['size']!r} is not a number above zero"
        if not _is_number(value["weight"]) or not 100 <= value["weight"] <= 900:
            return f"weight {value['weight']!r} is not a number from 100 to 900"
        return None
    if not _is_number(value) or value < 0:
        return f"{value!r} is not a number at or above zero"
    if group == "opacity" and value > 1:
        return f"{value!r} is not an opacity from 0 to 1"
    return None


def _value_problem(property_: str, value: Any, tokens: Mapping[str, Any]) -> str | None:
    """Why this component value cannot be used in a preset, or None."""
    reference = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if reference:
        group, token = reference.groups()
        if group not in GROUPS or token not in tokens[group]:
            return f"{value} names no token"
        if (property_ in COLOUR_PROPERTIES) != (group == "colours") or (property_ == "type") != (group == "type"):
            return f"{value} is not the kind of token this property takes"
        return None
    if property_ in COLOUR_PROPERTIES:
        return None if isinstance(value, str) and _HEX.fullmatch(value) else f"{value!r} is neither a token nor a colour written #RRGGBB"
    if property_ == "type":
        return f"{value!r} is not a type token"
    return None if _is_number(value) and value >= 0 else f"{value!r} is neither a token nor a number at or above zero"


def _base_and_state(name: str, components: Mapping[str, Any]) -> tuple[str, str]:
    """A component named `<base>-<state>`, where `<base>` is a component, is
    that component in that state."""
    for state in STATES[1:]:
        base = name.removesuffix(f"-{state}")
        if base != name and base in components:
            return base, state
    return name, "default"


def _rgba(colour: str) -> tuple[float, float, float, float]:
    return (int(colour[1:3], 16) / 255, int(colour[3:5], 16) / 255, int(colour[5:7], 16) / 255, 1.0)


def _resolve(name: str, tokens: Mapping[str, Any], components: Mapping[str, Mapping[str, Any]]) -> VisualPreset:
    colours = {token: _rgba(value) for token, value in tokens["colours"].items()}
    type_ = {token: (float(value["size"]), float(value["weight"])) for token, value in tokens["type"].items()}
    numbers = {group: {token: float(value) for token, value in tokens[group].items()} for group in NUMBER_GROUPS}
    groups: dict[str, Mapping[str, Any]] = {"colours": colours, "type": type_, **numbers}

    def value_of(property_: str, value: Any) -> Any:
        reference = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
        if reference:
            return groups[reference.group(1)][reference.group(2)]
        return _rgba(value) if property_ in COLOUR_PROPERTIES else float(value)

    def style_of(properties: Mapping[str, Any]) -> dict[str, Any]:
        style: dict[str, Any] = {}
        for property_, value in properties.items():
            if property_ in SIZE_PROPERTIES:
                continue
            if property_ == "type":
                style["type_size"], style["type_weight"] = value_of(property_, value)
            else:
                style[property_] = value_of(property_, value)
        return style

    resolved = {}
    for component, properties in components.items():
        if _base_and_state(component, components)[1] != "default":
            continue
        styles = {"default": style_of(properties)}
        for state in STATES[1:]:
            styles[state] = {**styles["default"], **style_of(components.get(f"{component}-{state}", {}))}
        resolved[component] = Component(
            name=component,
            height=value_of("height", properties["height"]) if "height" in properties else None,
            padding=value_of("padding", properties["padding"]) if "padding" in properties else None,
            type=value_of("type", properties["type"]) if "type" in properties else None,
            _styles=MappingProxyType({state: MappingProxyType(style) for state, style in styles.items()}),
        )
    return VisualPreset(
        name=name,
        title=tokens["title"],
        summary=tokens["summary"],
        components=MappingProxyType(resolved),
        **{group: MappingProxyType(values) for group, values in groups.items()},
    )


# --- the two files in one shape ------------------------------------------------


def _canonical(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The generator configuration in the shape both files are compared in."""
    family = raw["font"]["family"]
    presets = {}
    for name, tokens in raw["presets"].items():
        preset: dict[str, Any] = {"title": tokens["title"], "summary": tokens["summary"]}
        preset["colours"] = {token: value.upper() for token, value in tokens["colours"].items()}
        preset["type"] = {
            token: {"family": family, "size": float(value["size"]), "weight": float(value["weight"])}
            for token, value in tokens["type"].items()
        }
        for group in NUMBER_GROUPS:
            preset[group] = {token: float(value) for token, value in tokens[group].items()}
        presets[name] = preset
    components = {
        name: {
            property_: value.upper() if isinstance(value, str) and _HEX.fullmatch(value) else value if isinstance(value, str) else float(value)
            for property_, value in properties.items()
        }
        for name, properties in raw["components"].items()
    }
    return {"default_preset": raw["default_preset"], "states": list(raw["states"]), "components": components, "presets": presets}


def _compare(path: str, written: Any, configured: Any, problems: list[str]) -> None:
    if isinstance(written, dict) and isinstance(configured, dict):
        for key in sorted(written.keys() | configured.keys()):
            where = f"{path}.{key}" if path else key
            if key not in configured:
                problems.append(f"{where}: in DESIGN.md, missing from the generator configuration")
            elif key not in written:
                problems.append(f"{where}: in the generator configuration, missing from DESIGN.md")
            else:
                _compare(where, written[key], configured[key], problems)
    elif written != configured:
        problems.append(f"{path}: DESIGN.md says {written!r}, the generator configuration says {configured!r}")


# --- DESIGN.md -----------------------------------------------------------------


def _read_design_md(text: str) -> tuple[dict[str, Any], list[str]]:
    """DESIGN.md's tokens in the shape both files are compared in, and every
    way the file breaks the format rules this project relies on."""
    problems: list[str] = []
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return {}, ["it does not start with YAML front matter between two lines of ---"]
    end = lines.index("---", 1)
    try:
        tokens = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        return {}, [f"its front matter is not valid YAML: {error}"]
    if not isinstance(tokens, dict):
        return {}, ["its front matter is not a map of keys"]
    body = "\n".join(lines[end + 1 :])

    if tokens.get("version") != FORMAT_VERSION:
        problems.append(f"version is {tokens.get('version')!r}; this project writes format version {FORMAT_VERSION!r}")
    if not isinstance(tokens.get("name"), str) or not tokens.get("name"):
        problems.append("name is missing")
    problems += _section_problems(body, tokens.get("omitted", []))

    presets = tokens.get("presets")
    default = tokens.get("preset")
    if not isinstance(presets, dict) or default not in presets:
        return {}, [*problems, "preset does not name one of the entries under presets"]

    written_presets = {}
    for name, entry in presets.items():
        where = f"presets.{name}"
        if not isinstance(entry, dict):
            problems.append(f"{where} is not a map")
            continue
        # The default preset's tokens are the top-level groups of the format.
        source = tokens if name == default else entry
        preset: dict[str, Any] = {"title": entry.get("title"), "summary": entry.get("summary")}
        for key in _WRITTEN_GROUPS:
            group = _GROUP_NAMES.get(key, key)
            values = source.get(key)
            if not isinstance(values, dict):
                continue  # reported by the comparison as missing
            preset[group] = {token: _written_token(group, token, value, f"{where}.{key}.{token}", problems) for token, value in values.items()}
        if name == default and any(key in entry for key in _WRITTEN_GROUPS):
            problems.append(f"{where}: the default preset's tokens are the top-level groups, not repeated under presets")
        if isinstance(entry.get("title"), str) and entry["title"] not in body:
            problems.append(f"{where}: the preset's title {entry['title']!r} is not mentioned in the prose")
        written_presets[name] = preset

    if "primary" not in (tokens.get("colors") or {}):
        problems.append("colors.primary is missing; the format requires a primary colour")

    components = {}
    for name, properties in (tokens.get("components") or {}).items():
        if not isinstance(properties, dict):
            problems.append(f"components.{name} is not a map")
            continue
        translated = {}
        for property_, value in properties.items():
            where = f"components.{name}.{property_}"
            if property_ not in _PROPERTY_NAMES:
                problems.append(f"{where} is not a component property of the format or of this project's extensions")
                continue
            translated[_PROPERTY_NAMES[property_]] = _written_value(value, where, tokens, problems)
        components[name] = translated

    written = {"default_preset": default, "states": tokens.get("states"), "components": components, "presets": written_presets}
    return written, problems


def _section_problems(body: str, omitted: Any) -> list[str]:
    problems = []
    headings, fenced = [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            headings.append(line[3:].strip().replace("’", "'"))
    for heading in sorted({heading for heading in headings if headings.count(heading) > 1}):
        problems.append(f"the section {heading!r} appears more than once")

    index_of = {alias: index for index, aliases in enumerate(SECTIONS) for alias in aliases}
    known = [heading for heading in headings if heading in index_of]
    if [index_of[heading] for heading in known] != sorted(index_of[heading] for heading in known):
        problems.append(f"its sections are out of the format's order: {', '.join(known)}")

    left_out = set()
    for entry in omitted if isinstance(omitted, list) else []:
        section = entry.get("section") if isinstance(entry, dict) else entry
        if section not in index_of:
            problems.append(f"omitted names {section!r}, which is not a section of the format")
        else:
            left_out.add(index_of[section])
    present = {index_of[heading] for heading in known}
    for index, aliases in enumerate(SECTIONS):
        if index not in present and index not in left_out:
            problems.append(f"the section {aliases[0]!r} is neither written nor listed under omitted")
        if index in present and index in left_out:
            problems.append(f"the section {aliases[0]!r} is both written and listed under omitted")
    return problems


def _written_token(group: str, token: str, value: Any, where: str, problems: list[str]) -> Any:
    if group == "colours":
        if isinstance(value, str) and _HEX.fullmatch(value):
            return value.upper()
        problems.append(f"{where}: {value!r} is not a colour written #RRGGBB")
        return value
    if group == "type":
        if not isinstance(value, dict) or set(value) != {"fontFamily", "fontSize", "fontWeight"}:
            problems.append(f"{where}: a typography token has exactly fontFamily, fontSize and fontWeight")
            return value
        weight = value["fontWeight"]
        return {
            "family": value["fontFamily"],
            "size": _length(value["fontSize"], f"{where}.fontSize", problems),
            "weight": float(weight) if _is_number(weight) else weight,
        }
    unitless = _UNITLESS.get(group, ())
    if unitless is None or token in unitless:
        if _is_number(value):
            return float(value)
        problems.append(f"{where}: {value!r} is not a number")
        return value
    return _length(value, where, problems)


def _length(value: Any, where: str, problems: list[str]) -> Any:
    match = _PX.fullmatch(value) if isinstance(value, str) else None
    if match:
        return float(match.group(1))
    problems.append(f"{where}: {value!r} is not a length written in px")
    return value


def _written_value(value: Any, where: str, tokens: Mapping[str, Any], problems: list[str]) -> Any:
    """A component value in the configuration's vocabulary."""
    reference = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if reference:
        key, token = reference.groups()
        if not isinstance(tokens.get(key), dict) or token not in tokens[key]:
            problems.append(f"{where}: {value} names no token")
        return f"{{{_GROUP_NAMES.get(key, key)}.{token}}}"
    if isinstance(value, str) and _HEX.fullmatch(value):
        return value.upper()
    if isinstance(value, str) and _PX.fullmatch(value):
        return float(_PX.fullmatch(value).group(1))
    if _is_number(value):
        return float(value)
    problems.append(f"{where}: {value!r} is neither a token, a colour written #RRGGBB, a length in px nor a number")
    return value
