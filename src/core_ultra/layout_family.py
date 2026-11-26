"""Design conditions and layout families.

A design condition is one value for each declared design factor: navigation
position, panel arrangement, density, spacing and notification location. A
layout family is a named combination of those values. The two say the same
thing in two vocabularies: the scene model is given the factor values, and the
family's name is diagnostic metadata that it never sees, so a held-out family
is a combination it has not met and not an unknown identifier.

A layout configuration (`configs/layout/v1.json`, `configs/layout/v2.json`)
declares the factors, the values each may take and the families. Version 1
has one family. Version 2 has eight, and lists under `out_of_scope` the
variation the generator does not produce. `load()` without a path reads
version 1, which is what a scene session draws A, Reference in unless it is
given another layout.

    layout = load()
    family = layout.family("top-bar-list-left")
    family.design_condition.to_json()   # the five factor values
    layout.condition({...})             # a checked DesignCondition
    layout.family_of(condition).name    # the family a combination is

A design condition is only ever one of the declared families' combinations.
Anything else is refused with `LayoutError`; nothing is defaulted or ignored.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "layout" / "v1.json"

FACTORS = ("navigation_position", "panel_arrangement", "density", "spacing", "notification_location")

_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")


class LayoutError(ValueError):
    """The layout configuration cannot be used, or a design condition is not
    one it declares. `problems` lists why."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class DesignCondition:
    """One value for each design factor."""

    navigation_position: str
    panel_arrangement: str
    density: str
    spacing: str
    notification_location: str

    def to_json(self) -> dict[str, str]:
        return {factor: getattr(self, factor) for factor in FACTORS}


@dataclass(frozen=True)
class LayoutFamily:
    name: str
    title: str
    summary: str
    design_condition: DesignCondition


@dataclass(frozen=True)
class Layout:
    name: str
    version: int
    sha256: str
    factors: Mapping[str, tuple[str, ...]]
    default_family: str
    families: Mapping[str, LayoutFamily]
    out_of_scope: tuple[str, ...] = ()

    def family(self, name: str | None = None) -> LayoutFamily:
        """The layout family of this name, or the default one."""
        name = self.default_family if name is None else name
        try:
            return self.families[name]
        except (KeyError, TypeError):
            raise LayoutError([f"{name!r} is not a layout family; the families are {', '.join(self.families)}"]) from None

    def condition(self, values: Mapping[str, str] | DesignCondition | None = None) -> DesignCondition:
        """These factor values as a design condition, or the default family's
        when none are given. Refused unless they are a declared family's."""
        if values is None:
            return self.family().design_condition
        if isinstance(values, DesignCondition):
            values = values.to_json()
        problems = _condition_problems(values, self.factors)
        if problems:
            raise LayoutError(problems)
        condition = DesignCondition(**values)
        self.family_of(condition)
        return condition

    def family_of(self, condition: DesignCondition) -> LayoutFamily:
        """The layout family this combination of factor values is."""
        for family in self.families.values():
            if family.design_condition == condition:
                return family
        stated = ", ".join(f"{factor} {value}" for factor, value in condition.to_json().items())
        raise LayoutError([f"no layout family is the combination {stated}"])


def load(path: str | Path | None = None) -> Layout:
    """The layout in a layout configuration. Raises `LayoutError` with every
    problem when the configuration cannot be used."""
    return _load(str(Path(path or DEFAULT_CONFIG).resolve()))


@lru_cache(maxsize=16)
def _load(path: str) -> Layout:
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        raise LayoutError([f"{path} does not exist"]) from None
    try:
        raw = json.loads(data)
    except json.JSONDecodeError as error:
        raise LayoutError([f"{path} is not valid JSON: {error}"]) from None
    problems = _config_problems(raw)
    if problems:
        raise LayoutError(problems)
    factors = MappingProxyType({factor: tuple(raw["factors"][factor]) for factor in FACTORS})
    families = {
        name: LayoutFamily(name, entry["title"], entry["summary"], DesignCondition(**entry["design_condition"]))
        for name, entry in raw["families"].items()
    }
    return Layout(
        name=raw["name"],
        version=raw["version"],
        sha256=hashlib.sha256(data).hexdigest(),
        factors=factors,
        default_family=raw["default_family"],
        families=MappingProxyType(families),
        out_of_scope=tuple(raw.get("out_of_scope", ())),
    )


def _condition_problems(values: Any, factors: Mapping[str, Any]) -> list[str]:
    if not isinstance(values, Mapping):
        return ["a design condition is a value for each design factor"]
    problems = []
    for factor in FACTORS:
        if factor not in values:
            problems.append(f"the design condition has no {factor}")
        elif not isinstance(values[factor], str) or values[factor] not in factors[factor]:
            problems.append(f"{factor} is {values[factor]!r}; its values are {', '.join(factors[factor])}")
    for extra in sorted(set(values) - set(FACTORS), key=str):
        problems.append(f"{extra!r} is not a design factor; the factors are {', '.join(FACTORS)}")
    return problems


def _config_problems(raw: Any) -> list[str]:
    if not isinstance(raw, dict) or raw.get("kind") != "layout-config":
        return ['it is not an object of kind "layout-config"']
    problems: list[str] = []
    if not isinstance(raw.get("name"), str) or not raw.get("name"):
        problems.append("name is missing")
    if not isinstance(raw.get("version"), int) or isinstance(raw.get("version"), bool):
        problems.append("version is not a whole number")

    stated = raw.get("out_of_scope", [])
    if not isinstance(stated, list) or not all(isinstance(item, str) and item for item in stated):
        problems.append("out_of_scope is not a list of sentences")

    factors = raw.get("factors")
    if not isinstance(factors, dict) or set(factors) != set(FACTORS):
        return [*problems, f"factors does not hold exactly: {', '.join(FACTORS)}"]
    for factor, values in factors.items():
        if not isinstance(values, list) or not values or len(set(map(str, values))) != len(values):
            problems.append(f"factors.{factor} is not a list of different values")
        elif not all(isinstance(value, str) and _NAME.fullmatch(value) for value in values):
            problems.append(f"factors.{factor}: a value is lower-case words joined by hyphens")
    if problems:
        return problems

    families = raw.get("families")
    if not isinstance(families, dict) or not families:
        return ["families is missing or empty"]
    if raw.get("default_family") not in families:
        problems.append(f"default_family {raw.get('default_family')!r} is not one of the families")
    seen: dict[tuple[str, ...], str] = {}
    for name, entry in families.items():
        where = f"families.{name}"
        if not _NAME.fullmatch(name):
            problems.append(f"{where}: a family's name is lower-case words joined by hyphens")
        if not isinstance(entry, dict) or set(entry) != {"title", "summary", "design_condition"}:
            problems.append(f"{where} does not hold exactly: title, summary, design_condition")
            continue
        for field in ("title", "summary"):
            if not isinstance(entry[field], str) or not entry[field]:
                problems.append(f"{where}.{field} is missing")
        inner = _condition_problems(entry["design_condition"], factors)
        problems += [f"{where}.design_condition: {problem}" for problem in inner]
        if not inner:
            combination = tuple(entry["design_condition"][factor] for factor in FACTORS)
            if combination in seen:
                problems.append(f"{where} is the same combination as families.{seen[combination]}")
            seen[combination] = name
    return problems
