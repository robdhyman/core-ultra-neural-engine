"""The generator: scripted sessions in, traceable dataset records out.

`data generate` reads a dataset configuration, runs its scripted sessions
against the application kernel, has the reference layout engine write the true
scene of every state reached, puts each scene before the validators, draws
each one they pass with the runtime renderer and writes one dataset record and
one reference image per state, then the stress-test set and a manifest.

    dataset/
      manifest.json           hashes of everything below; the one file meant for git
      config.json             the dataset configuration, byte for byte
      records/<id>.json       one dataset record
      images/<id>.png         its reference image, A, Reference drawn by the runtime renderer
      stress/<name>.json      one stress-test record: never a dataset record, never a target
      stress/<name>.png       its candidate scene drawn, when the scene schema accepts it

A dataset record keeps five things apart:

| Field | Holds |
| --- | --- |
| `inputs` | The model inputs (`core_ultra.model_inputs`), and nothing else. |
| `target` | The true scene. |
| `reference_image` | The image file, its hash and size. |
| `application` | What the application supplied: the bound elements with their exact text, action bindings and states, and the application state. |
| `diagnostics` | Everything needed to trace and regenerate the record, and nothing the scene model may see: generator version, seed and configuration, layout family, visual preset, content length and scenario identifiers, asset provenance and validation results. |

Sessions. Each scenario of the configuration is a script
(`core_ultra.scripted_session`), run `sessions_per_scenario` times. A session
is one run of the application in one design, and a design is chosen whole
(`sessions`): one layout family, one visual preset, one viewport size and one
content length, never a factor value or a token on its own. A record's id is
`<scenario>-<run>.<moment>`.

Viewport sizes. `viewport_choice` is `dealt` (the sizes are dealt out in turn,
and a state that does not fit its size is rejected) or `fitting` (a session is
given the least used size in which every one of its states passes the
validators, so a roomy visual preset or a wide arrangement gets a size that
holds it). Under `fitting`, the sizes a session was refused are in the
manifest with the reason, and a session no size fits is not run and is listed
under `sessions_refused`.

Content lengths. `content_lengths` names ranges of title words and body lines
(`brief`, `long`); each session writes with one of them. Without it every
session uses the ranges of `content`.

Validators (`core_ultra.validators`). A state whose true scene any validator
rejects is not written as a record. It is listed in the manifest under
`rejected` with every finding: the validator, a code, the element and a
sentence. The coverage validator reads the accepted records and lists, under
`coverage.gaps`, every declared value that none of them shows.

The stress-test set. `stress_tests` lists deliberately difficult or broken
examples. Each is the last state of its own script in a design the case
names, written by the reference layout and then, for a broken one, given one
fault (`_break`). It is written apart, labelled `"set": "stress-test"` and
`"training_target": false`, holds a `candidate` scene and neither model inputs
nor a target, and must be rejected by the validators for exactly the codes the
case expects: if it is not, the configuration is refused and nothing is
written. What a case is rejected for depends on the content its seed writes,
so the expected codes belong to the configuration they are written in.

Nothing here depends on the clock, the machine's name or the order of a hash
table. The random choices come from `random.Random` seeded with text made of
the configuration's seed and the session's id. The same configuration
therefore gives the same bytes, and `check` proves it for a written dataset by
generating it again.

`record_problems` is the check that no model input holds the target or any
diagnostic metadata, and that the target passes the validators. The generator
runs it on every record before writing it, and `check` runs it on every record
of a written dataset; `stress_problems` is its counterpart for the stress-test
set.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import os
import random
import re
import shutil
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_ultra import design as design_source
from core_ultra import documents_adapter, layout_family, model_inputs, reference_layout, runtime_renderer
from core_ultra import scene as scene_schema, scripted_session, validators
from core_ultra.documents_adapter import BoundElement
from core_ultra.kernel import ApplicationState, Document
from core_ultra.scene_session import Conditioning, RenderingMode, SceneInvalid, SceneSession, TextNotDrawable
from core_ultra.scripted_session import Content, Moment, ScriptError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = Path("artifacts") / "datasets"

GENERATOR_NAME = "core-ultra data generate"
# Version 2 runs every validator, chooses fitting viewport sizes and writes
# the stress-test set. What it adds to a record and to the manifest is added
# beside what version 1 wrote, so the two schema versions stand.
GENERATOR_VERSION = 2
RECORD_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
STRESS_SCHEMA_VERSION = 1
STRESS_SET = "stress-test"
MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.json"

RECORD_FIELDS = ("kind", "schema_version", "id", "inputs", "target", "reference_image", "application", "diagnostics")
DIAGNOSTIC_FIELDS = ("generator", "layout_family", "visual_preset", "scenario", "related", "asset_provenance", "validation")
INPUT_RULE = "model inputs hold neither the target nor diagnostic metadata"
VALIDATORS = (*validators.SCENE_VALIDATORS, INPUT_RULE)
STRESS_FIELDS = (
    "kind", "schema_version", "id", "set", "training_target", "why", "application", "conditioning",
    "candidate", "broken_by", "image", "expected", "rejection", "diagnostics",
)  # fmt: skip
VIEWPORT_CHOICES = ("dealt", "fitting")
BREAKS = ("remove", "duplicate", "retext", "rebind", "resize", "move", "cover", "style", "reparent")

_CONFIG_FIELDS = (
    "kind", "name", "version", "note", "seed", "design", "layout", "layout_families", "visual_presets",
    "viewports", "viewport_choice", "pixels_per_viewport_unit", "sessions_per_scenario", "scenarios", "content",
    "content_lengths", "stress_tests",
)  # fmt: skip
_OPTIONAL_FIELDS = ("note", "viewport_choice", "content_lengths", "stress_tests")
_STRESS_CASE_FIELDS = ("name", "why", "script", "layout_family", "visual_preset", "viewport", "content", "break", "expect")
# Names the model inputs use. A diagnostic name must never be one of them.
_INPUT_WORDS = frozenset({*scripted_session.ACTIONS, *documents_adapter.ROLES, *documents_adapter.STATES, *documents_adapter.RELATIONS})
_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")


class ConfigError(ValueError):
    """The dataset configuration cannot be used. `problems` lists why."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


class DatasetDiffers(Exception):
    """The folder already holds a dataset that is not the one generated."""


@dataclass(frozen=True)
class Config:
    """A dataset configuration, with the design and layout it names loaded."""

    data: bytes
    sha256: str
    name: str
    version: int
    seed: int
    design_file: str
    layout_file: str
    design: design_source.Design
    layout: layout_family.Layout
    layout_families: tuple[str, ...]
    visual_presets: tuple[str, ...]
    viewports: tuple[tuple[float, float], ...]
    scale: float
    sessions_per_scenario: int
    scenarios: Mapping[str, tuple[str, ...]]
    content: Content
    viewport_choice: str = "dealt"
    content_lengths: Mapping[str, Content] = dataclasses.field(default_factory=dict)
    stress_tests: tuple[StressTest, ...] = ()


@dataclass(frozen=True)
class Session:
    """One scripted session and the design it runs in. `viewport` is None
    until one is chosen, when the configuration's viewport choice is `fitting`."""

    id: str
    scenario: str
    script: tuple[str, ...]
    seed: str
    layout_family: str
    visual_preset: str
    viewport: tuple[float, float] | None
    content_length: str | None = None
    viewports_refused: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class StressTest:
    """One deliberately difficult or broken example of the stress-test set."""

    name: str
    why: str
    script: tuple[str, ...]
    layout_family: str
    visual_preset: str
    viewport: tuple[float, float]
    content: Content
    break_: Mapping[str, Any] | None
    expect: tuple[str, ...]


# --- the configuration ---------------------------------------------------------


def load_config(path: str | Path) -> Config:
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        raise ConfigError([f"{path} does not exist"]) from None
    return parse_config(data)


def parse_config(data: bytes) -> Config:
    """The configuration in these bytes. Raises `ConfigError` with every problem."""
    try:
        raw = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ConfigError([f"it is not valid JSON: {error}"]) from None
    if not isinstance(raw, dict) or raw.get("kind") != "dataset-config":
        raise ConfigError(['it is not an object of kind "dataset-config"'])
    problems = [f"{name!r} is not a field of a dataset configuration" for name in sorted(set(raw) - set(_CONFIG_FIELDS), key=str)]
    problems += [f"{name} is missing" for name in _CONFIG_FIELDS if name not in raw and name not in _OPTIONAL_FIELDS]
    if problems:
        raise ConfigError(problems)

    if not isinstance(raw["name"], str) or not _NAME.fullmatch(raw["name"]):
        problems.append("name is not lower-case words joined by hyphens")
    for field in ("version", "seed"):
        if not _is_whole(raw[field]) or raw[field] < 0:
            problems.append(f"{field} is not a whole number at or above zero")
    if not _is_whole(raw["sessions_per_scenario"]) or raw["sessions_per_scenario"] < 1:
        problems.append("sessions_per_scenario is not a whole number above zero")
    scale = raw["pixels_per_viewport_unit"]
    if not _is_number(scale) or scale <= 0:
        problems.append("pixels_per_viewport_unit is not a number above zero")

    design = layout = None
    try:
        design = design_source.load(_repository_file(raw["design"], "design"))
    except (ConfigError, design_source.DesignError) as error:
        problems += [f"design: {problem}" for problem in error.problems]
    try:
        layout = layout_family.load(_repository_file(raw["layout"], "layout"))
    except (ConfigError, layout_family.LayoutError) as error:
        problems += [f"layout: {problem}" for problem in error.problems]

    for field, known, what in (
        ("layout_families", layout.families if layout else None, "layout family"),
        ("visual_presets", design.presets if design else None, "visual preset"),
    ):
        names = raw[field]
        if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names) or len(set(names)) != len(names):
            problems.append(f"{field} is not a list of different names")
        elif known is not None:
            problems += [f"{field}: {name!r} is not a {what}; they are {', '.join(known)}" for name in names if name not in known]

    viewports = raw["viewports"]
    sound = isinstance(viewports, list) and viewports and all(
        isinstance(size, list) and len(size) == 2 and all(_is_number(side) and side > 0 for side in size) for size in viewports
    )
    if not sound:
        problems.append("viewports is not a list of [width, height] with both above zero")
    elif len({tuple(size) for size in viewports}) != len(viewports):
        problems.append("viewports repeats a size")

    scenarios = raw["scenarios"]
    if not isinstance(scenarios, dict) or not scenarios:
        problems.append("scenarios is missing or empty")
    else:
        for name, script in scenarios.items():
            if not _NAME.fullmatch(name):
                problems.append(f"scenarios.{name}: a scenario's name is lower-case words joined by hyphens")
            if name in scripted_session.ACTIONS:
                # A command's name is a model input (a binding's kind), and a
                # scenario's name must never be one.
                problems.append(f"scenarios.{name}: a scenario is not named after an action")
            if not isinstance(script, list) or not script:
                problems.append(f"scenarios.{name} is not a list of actions")
                continue
            for action in script:
                if action not in scripted_session.ACTIONS:
                    problems.append(
                        f"scenarios.{name}: {action!r} is not an action; the actions are {', '.join(scripted_session.ACTIONS)}"
                    )

    content = None
    try:
        content = Content.from_json(raw["content"])
    except ScriptError as error:
        problems.append(str(error))

    choice = raw.get("viewport_choice", "dealt")
    if choice not in VIEWPORT_CHOICES:
        problems.append(f"viewport_choice is {choice!r}; it is one of {', '.join(VIEWPORT_CHOICES)}")

    content_lengths: dict[str, Content] = {}
    lengths = raw.get("content_lengths", {})
    if not isinstance(lengths, dict) or ("content_lengths" in raw and not lengths):
        problems.append("content_lengths is not a set of named lengths")
    elif content is not None:
        for name, spans in lengths.items():
            where = f"content_lengths.{name}"
            if not _NAME.fullmatch(name) or name in _INPUT_WORDS:
                problems.append(f"{where}: a content length's name is lower-case words joined by hyphens, and no word the model inputs use")
            if not isinstance(spans, dict) or set(spans) != {"title_words", "body_lines"}:
                problems.append(f"{where} does not hold exactly: title_words, body_lines")
                continue
            try:
                content_lengths[name] = Content.from_json({**raw["content"], **spans})
            except ScriptError as error:
                problems.append(f"{where}: {error}")

    stress_tests: list[StressTest] = []
    cases = raw.get("stress_tests", [])
    if not isinstance(cases, list):
        problems.append("stress_tests is not a list of cases")
    elif content is not None and design is not None and layout is not None:
        for index, case in enumerate(cases):
            found, made = _stress_case(case, index, raw["content"], design, layout, scenarios if isinstance(scenarios, dict) else {})
            problems += found
            if made is not None:
                if made.name in {other.name for other in stress_tests}:
                    problems.append(f"stress_tests: two cases are named {made.name!r}")
                stress_tests.append(made)
    if problems:
        raise ConfigError(problems)

    return Config(
        data=data,
        sha256=_sha256(data),
        name=raw["name"],
        version=raw["version"],
        seed=raw["seed"],
        design_file=raw["design"],
        layout_file=raw["layout"],
        design=design,
        layout=layout,
        layout_families=tuple(raw["layout_families"]),
        visual_presets=tuple(raw["visual_presets"]),
        viewports=tuple((float(width), float(height)) for width, height in viewports),
        scale=float(scale),
        sessions_per_scenario=raw["sessions_per_scenario"],
        scenarios={name: tuple(script) for name, script in scenarios.items()},
        content=content,
        viewport_choice=choice,
        content_lengths=content_lengths,
        stress_tests=tuple(stress_tests),
    )


def _stress_case(
    case: Any, index: int, content: Any, design: design_source.Design, layout: layout_family.Layout, scenarios: Mapping[str, Any]
) -> tuple[list[str], StressTest | None]:
    """One case of `stress_tests`, or every reason it cannot be used."""
    where = f"stress_tests[{index}]"
    required = [name for name in _STRESS_CASE_FIELDS if name not in ("content", "break")]
    if not isinstance(case, dict) or set(case) - set(_STRESS_CASE_FIELDS) or any(name not in case for name in required):
        return [f"{where} does not hold {', '.join(required)}, and at most content and break besides"], None
    name = case["name"]
    if not isinstance(name, str) or not _NAME.fullmatch(name) or name in _INPUT_WORDS or name in scenarios:
        return [f"{where}: a case's name is lower-case words joined by hyphens, and neither a scenario's name nor a word the model inputs use"], None
    where = f"stress_tests.{name}"
    problems = []
    if not isinstance(case["why"], str) or not case["why"]:
        problems.append(f"{where}.why does not say what makes the example difficult or broken")
    script = case["script"]
    if not isinstance(script, list) or not script or any(action not in scripted_session.ACTIONS for action in script):
        problems.append(f"{where}.script is not a list of actions; the actions are {', '.join(scripted_session.ACTIONS)}")
    if not isinstance(case["layout_family"], str) or case["layout_family"] not in layout.families:
        problems.append(f"{where}.layout_family: {case['layout_family']!r} is not a layout family; they are {', '.join(layout.families)}")
    if not isinstance(case["visual_preset"], str) or case["visual_preset"] not in design.presets:
        problems.append(f"{where}.visual_preset: {case['visual_preset']!r} is not a visual preset; they are {', '.join(design.presets)}")
    viewport = case["viewport"]
    if not (isinstance(viewport, list) and len(viewport) == 2 and all(_is_number(side) and side > 0 for side in viewport)):
        problems.append(f"{where}.viewport is not [width, height] with both above zero")
    expect = case["expect"]
    if not isinstance(expect, list) or not expect or not all(isinstance(code, str) and code for code in expect) or len(set(expect)) != len(expect):
        problems.append(f"{where}.expect is not a list of the different codes the validators must reject it for")
    made = None
    try:
        overrides = case.get("content", {})
        if not isinstance(overrides, dict):
            raise ScriptError("content is not a set of content fields")
        made = Content.from_json({**content, **overrides})
    except ScriptError as error:
        problems.append(f"{where}: {error}")
    broken = case.get("break")
    if broken is not None:
        if not isinstance(broken, dict) or broken.get("kind") not in BREAKS or not isinstance(broken.get("element"), str):
            problems.append(f"{where}.break does not name a kind ({', '.join(BREAKS)}) and the identity of an element")
    if problems:
        return problems, None
    return [], StressTest(
        name=name, why=case["why"], script=tuple(script), layout_family=case["layout_family"], visual_preset=case["visual_preset"],
        viewport=(float(viewport[0]), float(viewport[1])), content=made, break_=broken, expect=tuple(sorted(expect)),
    )  # fmt: skip


def _repository_file(stated: Any, field: str) -> Path:
    """A configuration names its design and layout by path from the repository root."""
    if not isinstance(stated, str) or not stated or Path(stated).is_absolute() or ".." in Path(stated).parts:
        raise ConfigError([f"{field} is not a path from the repository root"])
    return REPO_ROOT / stated


def default_out(config: Config) -> Path:
    return DEFAULT_OUT_ROOT / f"{config.name}-v{config.version}"


# --- sessions --------------------------------------------------------------------


def _dealt(config: Config) -> tuple[list[str], list[str], list[tuple[float, float]], list[str]]:
    """The layout families, visual presets, viewport sizes and content lengths,
    each in its seeded order."""
    dealer = random.Random(f"{config.seed}/designs")
    orders = []
    for values in (config.layout_families, config.visual_presets, config.viewports, tuple(config.content_lengths)):
        order = list(values)
        dealer.shuffle(order)
        orders.append(order)
    return tuple(orders)


def sessions(config: Config) -> tuple[Session, ...]:
    """Every scripted session of the configuration, each with its design.

    A design is chosen whole: one layout family (a declared combination of
    factor values), one visual preset (a declared set of token values), one
    viewport size and one content length. No factor value and no token is
    drawn on its own. The families, presets, sizes and lengths are each put in
    a seeded order and dealt out in turn, so the sessions cover each list
    evenly; each time the pairing of families and presets would repeat, the
    presets move on by one, so a family meets every preset in turn.

    With the viewport choice `fitting` the viewport size is not dealt here: it
    is chosen when the session has run (`generate`), and is None until then.
    """
    families, presets, viewports, lengths = _dealt(config)
    repeat = math.lcm(len(families), len(presets))

    planned = []
    for scenario, script in config.scenarios.items():
        for run in range(config.sessions_per_scenario):
            number = len(planned)
            session_id = f"{scenario}-{run}"
            planned.append(
                Session(
                    id=session_id,
                    scenario=scenario,
                    script=script,
                    seed=f"{config.seed}/{session_id}",
                    layout_family=families[number % len(families)],
                    visual_preset=presets[(number + number // repeat) % len(presets)],
                    viewport=viewports[number % len(viewports)] if config.viewport_choice == "dealt" else None,
                    content_length=lengths[number % len(lengths)] if lengths else None,
                )
            )
    return tuple(planned)


def _fit(
    moments: Sequence[Moment],
    family: layout_family.LayoutFamily,
    preset: design_source.VisualPreset,
    order: Sequence[tuple[float, float]],
    used: Counter,
    least_text_inset: float = 0.0,
) -> tuple[tuple[float, float] | None, list[dict[str, Any]]]:
    """The viewport size a session is given under the viewport choice
    `fitting`: the least used size, earliest in the seeded order among equals,
    in which every state of the session passes the validators. Returns it (None
    when no size fits) and every size that was tried before it and refused,
    with the first state the validators rejected there and why."""
    refused = []
    for viewport in sorted(order, key=lambda size: (used[size], order.index(size))):
        rejection = None
        related: dict[int, scene_schema.Scene] = {}
        for moment in moments:
            _, scene, found = _judged(moment.bound_elements, viewport, preset, family, least_text_inset=least_text_inset)
            if scene is not None and moment.application_state in related:
                found = (*found, *validators.related_findings(related[moment.application_state], scene))
            if found:
                rejection = {
                    "viewport": _viewport_json(viewport),
                    "moment": moment.index,
                    "codes": sorted({finding.code for finding in found}),
                    "problems": [finding.to_json() for finding in found],
                }
                break
            related.setdefault(moment.application_state, scene)
        if rejection is None:
            return viewport, refused
        refused.append(rejection)
    return None, refused


def _judged(
    bound_elements: Sequence[BoundElement],
    viewport: tuple[float, float],
    preset: design_source.VisualPreset,
    family: layout_family.LayoutFamily,
    broken: Mapping[str, Any] | None = None,
    where: str = "",
    least_text_inset: float = 0.0,
) -> tuple[Any, scene_schema.Scene | None, tuple[validators.Finding, ...]]:
    """The candidate scene the reference layout writes, changed by `broken`
    if given; the same as a validated scene, or None when scene validation
    refuses it; and what the validators find in it. The candidate too is None
    when the font cannot draw a text the reference layout measures."""
    try:
        candidate = reference_layout.write_scene(bound_elements, viewport, preset, family.design_condition, least_text_inset)
    except TextNotDrawable as refused:
        return None, None, (validators.Finding(validators.TEXT_FIT, "text_not_drawable", None, str(refused)),)
    if broken is not None:
        candidate = _break(candidate, broken, where)
    return (candidate, *validators.judge(candidate, bound_elements, viewport, preset))


def rejected_scene(config: Config, session_id: str, moment: int, viewport: tuple[float, float]) -> scene_schema.Scene | None:
    """The scene the reference layout writes for one state of one scripted
    session in one viewport size, made again so that a person can be shown a
    state the validators rejected: one the manifest lists under `rejected`, or
    the first state a refused viewport size was refused for.

    None when scene validation refuses the scene or the font cannot draw a
    text, because such a state cannot be drawn. The reasons a state was
    rejected for are the manifest's; this gives the picture only.
    `ConfigError` when the configuration has no such session or the session
    no such moment.
    """
    session = next((session for session in sessions(config) if session.id == session_id), None)
    if session is None:
        raise ConfigError([f"{session_id!r} is not a scripted session of the configuration"])
    content = config.content_lengths.get(session.content_length, config.content)
    moments = list(scripted_session.run(session.script, content, random.Random(session.seed)))
    if not 0 <= moment < len(moments):
        raise ConfigError([f"session {session_id} has no moment {moment}"])
    family = config.layout.family(session.layout_family)
    preset = config.design.preset(session.visual_preset)
    return _judged(moments[moment].bound_elements, viewport, preset, family, least_text_inset=config.layout.least_text_inset)[1]


# --- generating ------------------------------------------------------------------


def generate(config: Config) -> Iterator[tuple[str, bytes]]:
    """Every file of the dataset as (path inside the dataset folder, bytes):
    the configuration, each record with its image, the stress-test set, then
    the manifest."""
    yield CONFIG_NAME, config.data

    scene_session = SceneSession(config.layout)
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    ran: list[Session] = []
    refused: list[Session] = []
    seen: dict[str, list[str]] = {}
    _, _, order, _ = _dealt(config)
    used: Counter = Counter()
    for session in sessions(config):
        family = config.layout.family(session.layout_family)
        preset = config.design.preset(session.visual_preset)
        content = config.content_lengths.get(session.content_length, config.content)
        try:
            moments = list(scripted_session.run(session.script, content, random.Random(session.seed)))
        except ScriptError as error:
            raise ConfigError([f"scenarios.{session.scenario}, session {session.id}: {error}"]) from None

        if session.viewport is None:
            viewport, tried = _fit(moments, family, preset, order, used, config.layout.least_text_inset)
            session = dataclasses.replace(session, viewport=viewport, viewports_refused=tuple(tried))
            if viewport is None:
                refused.append(session)
                continue
            used[viewport] += 1
        ran.append(session)
        conditioning = Conditioning(
            *session.viewport, visual_preset=preset.name, design_condition=family.design_condition.to_json()
        )
        tokens = model_inputs.preset_tokens(preset)
        # The first accepted scene of each application state, which the
        # others of that state are held against.
        related: dict[int, scene_schema.Scene] = {}

        for moment in moments:
            record_id = f"{session.id}.{moment.index:03d}"
            try:
                frame = scene_session.frame(moment.state, conditioning, RenderingMode.A_REFERENCE, scale=config.scale)
            except SceneInvalid as refusal:
                found = [validators.Finding(validators.SCENE_VALIDATION, p.code, p.element, p.detail) for p in refusal.problems]
                rejected.append(_rejection(record_id, session, "scene_invalid", found))
                continue
            except TextNotDrawable as refusal:
                found = [validators.Finding(validators.TEXT_FIT, "text_not_drawable", None, str(refusal))]
                rejected.append(_rejection(record_id, session, "text_not_drawable", found))
                continue
            found = list(validators.findings(frame.scene, preset))
            if moment.application_state in related:
                found += validators.related_findings(related[moment.application_state], frame.scene)
            if found:
                rejected.append(_rejection(record_id, session, "rejected_by_validators", found))
                continue
            related.setdefault(moment.application_state, frame.scene)

            image = runtime_renderer.png_bytes(frame.image)
            image_file = f"images/{record_id}.png"
            record = {
                "kind": "dataset-record",
                "schema_version": RECORD_SCHEMA_VERSION,
                "id": record_id,
                "inputs": model_inputs.build(moment.bound_elements, session.viewport, family.design_condition.to_json(), tokens),
                "target": {"scene": frame.scene.to_json()},
                "reference_image": {
                    "file": image_file,
                    "sha256": _sha256(image),
                    "width": int(frame.image.shape[1]),
                    "height": int(frame.image.shape[0]),
                    "pixels_per_viewport_unit": config.scale,
                    "rendering_mode": RenderingMode.A_REFERENCE.value,
                    "drawn_by": "runtime renderer",
                },
                "application": {
                    "bound_elements": [element.to_json() for element in moment.bound_elements],
                    "state": _state_json(moment.state),
                },
                "diagnostics": _diagnostics(config, session, moment),
            }
            problems = record_problems(record, config.design, config.layout)
            if problems:
                raise RuntimeError(f"record {record_id} was not written, because it broke the record rules: " + "; ".join(problems))
            record_file = f"records/{record_id}.json"
            record_bytes = _json_bytes(record)
            yield record_file, record_bytes
            yield image_file, image
            entries.append(
                {
                    "id": record_id,
                    "file": record_file,
                    "sha256": _sha256(record_bytes),
                    "image": {"file": image_file, "sha256": _sha256(image)},
                    "inputs_sha256": _canonical_sha256(record["inputs"]),
                    "target_sha256": _canonical_sha256(record["target"]),
                    "session": session.id,
                    "application_state": record["diagnostics"]["related"]["application_state"],
                    "layout_family": session.layout_family,
                    "visual_preset": session.visual_preset,
                    "viewport": _viewport_json(session.viewport),
                }
            )
            _see(seen, session, family, moment)

    stress = []
    for case in config.stress_tests:
        entry, files = _stress_record(config, case)
        stress.append(entry)
        yield from files

    yield MANIFEST_NAME, _json_bytes(_manifest(config, ran, refused, entries, rejected, stress, seen))


def _see(seen: dict[str, list[str]], session: Session, family: layout_family.LayoutFamily, moment: Moment) -> None:
    """Note what one accepted record shows, for the coverage validator."""

    def note(dimension: str, *values: str) -> None:
        seen.setdefault(dimension, []).extend(values)

    note("layout family", session.layout_family)
    note("visual preset", session.visual_preset)
    note("viewport", _viewport_name(session.viewport))
    note("scenario", session.scenario)
    if session.content_length is not None:
        note("content length", session.content_length)
    for factor, value in family.design_condition.to_json().items():
        note(factor.replace("_", " "), value)
    elements = moment.bound_elements
    note("element state", *{element.state for element in elements})
    note("role", *{element.role for element in elements})
    note("command", *{element.binding["command"] for element in elements if element.binding is not None})
    identities = {element.identity for element in elements}
    note("document list", "empty" if documents_adapter.EMPTY_LIST in identities else "with rows")
    note("editor", "empty" if documents_adapter.EMPTY_EDITOR in identities else "document open")
    note("notification", "shown" if documents_adapter.NOTIFICATION in identities else "absent")


def _declared(config: Config) -> dict[str, list[str]]:
    """What the configuration means the accepted records to show."""
    conditions = [config.layout.family(name).design_condition.to_json() for name in config.layout_families]
    commands = ("create", "sort", "filter", "save", "undo", "open", "rename", "edit")
    return {
        "layout family": list(config.layout_families),
        "visual preset": list(config.visual_presets),
        "viewport": [_viewport_name(viewport) for viewport in config.viewports],
        "scenario": list(config.scenarios),
        **({"content length": list(config.content_lengths)} if config.content_lengths else {}),
        **{factor.replace("_", " "): sorted({condition[factor] for condition in conditions}) for factor in config.layout.factors},
        "element state": list(documents_adapter.STATES),
        "role": list(documents_adapter.ROLES),
        "command": list(commands),
        "document list": ["empty", "with rows"],
        "editor": ["empty", "document open"],
        "notification": ["absent", "shown"],
    }


def _diagnostics(config: Config, session: Session, moment: Moment) -> dict[str, Any]:
    return {
        "generator": _generator_json(config),
        "layout_family": session.layout_family,
        "visual_preset": session.visual_preset,
        "scenario": {
            "name": session.scenario,
            "session": session.id,
            "session_seed": session.seed,
            "content_length": session.content_length,
            "moment": moment.index,
            "step": moment.step,
            "action": moment.action,
            "phase": moment.phase,
            "trace": [dict(command) for command in moment.trace],
        },
        # Records that share `application_state` are one application state
        # under different pointer states; records that share `session` are one
        # run of the application.
        "related": {"session": session.id, "application_state": f"{session.id}/{moment.application_state}"},
        "asset_provenance": _provenance(config),
        "validation": {
            "validators": list(VALIDATORS),
            "scene": {"valid": True, "problems": []},
            "text_fit": {"problems": []},
            "element_completeness": {"problems": []},
            "state_consistency": {"problems": []},
            "hit_targets": {"problems": []},
            "inputs": {"problems": []},
        },
    }


def _generator_json(config: Config) -> dict[str, Any]:
    return {
        "name": GENERATOR_NAME,
        "version": GENERATOR_VERSION,
        "seed": config.seed,
        "configuration": {"name": config.name, "version": config.version, "sha256": config.sha256},
    }


def _provenance(config: Config) -> dict[str, Any]:
    font = config.design.font
    return {
        "design": {
            "name": config.design.name,
            "version": config.design.version,
            "file": config.design_file,
            "sha256": _sha256((REPO_ROOT / config.design_file).read_bytes()),
            "origin": "original; written for this project",
        },
        "layout": {
            "name": config.layout.name,
            "version": config.layout.version,
            "file": config.layout_file,
            "sha256": config.layout.sha256,
            "origin": "original; written for this project",
        },
        "font": {
            name: font[name]
            for name in ("family", "version", "file", "sha256", "licence", "licence_file", "copyright", "source")
        },
        "content": {"origin": "original; the words and lines of the dataset configuration"},
    }


def _rejection(record_id: str, session: Session, reason: str, found: Sequence[validators.Finding]) -> dict[str, Any]:
    return {
        "id": record_id,
        "session": session.id,
        "layout_family": session.layout_family,
        "visual_preset": session.visual_preset,
        "viewport": _viewport_json(session.viewport),
        "reason": reason,
        "problems": [finding.to_json() for finding in found],
    }


# --- the stress-test set ---------------------------------------------------------


def _stress_record(config: Config, case: StressTest) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    """One stress-test record: the last state of the case's script, in the
    case's design, as the reference layout writes it and the case then breaks
    it. Returns its manifest entry and its files. Raises `ConfigError` unless
    the validators reject it for exactly the codes the case expects."""
    where = f"stress_tests.{case.name}"
    family = config.layout.family(case.layout_family)
    preset = config.design.preset(case.visual_preset)
    seed = f"{config.seed}/stress/{case.name}"
    try:
        moment = list(scripted_session.run(case.script, case.content, random.Random(seed)))[-1]
    except ScriptError as error:
        raise ConfigError([f"{where}: {error}"]) from None
    candidate, scene, found = _judged(moment.bound_elements, case.viewport, preset, family, case.break_, where, config.layout.least_text_inset)
    codes = tuple(sorted({finding.code for finding in found}))
    if codes != case.expect:
        got = f"rejected it for {', '.join(codes)}" if codes else "did not reject it"
        raise ConfigError([f"{where}: it is expected to be rejected for {', '.join(case.expect)}; the validators {got}"])

    record_id = f"stress.{case.name}"
    files: list[tuple[str, bytes]] = []
    image_json = None
    if scene is not None and "text_not_drawable" not in codes:
        # A scene the schema accepts can be drawn, so that a person can see
        # what the validators rejected.
        pixels = runtime_renderer.draw(scene, config.scale)
        image = runtime_renderer.png_bytes(pixels)
        image_json = {
            "file": f"stress/{case.name}.png",
            "sha256": _sha256(image),
            "width": int(pixels.shape[1]),
            "height": int(pixels.shape[0]),
            "pixels_per_viewport_unit": config.scale,
            "drawn_by": "runtime renderer",
        }
        files.append((image_json["file"], image))
    reason = "text_not_drawable" if candidate is None else "scene_invalid" if scene is None else "rejected_by_validators"
    record = {
        "kind": "stress-test-record",
        "schema_version": STRESS_SCHEMA_VERSION,
        "id": record_id,
        "set": STRESS_SET,
        "training_target": False,
        "why": case.why,
        "application": {
            "bound_elements": [element.to_json() for element in moment.bound_elements],
            "state": _state_json(moment.state),
        },
        "conditioning": {
            "viewport": _viewport_json(case.viewport),
            "design_condition": family.design_condition.to_json(),
            "layout_family": family.name,
            "visual_preset": preset.name,
        },
        # The scene that was rejected. It is a candidate and never a target.
        "candidate": None if candidate is None else {"scene": candidate},
        "broken_by": None if case.break_ is None else dict(case.break_),
        "image": image_json,
        "expected": {"codes": list(case.expect)},
        "rejection": {"reason": reason, "problems": [finding.to_json() for finding in found]},
        "diagnostics": {
            "generator": _generator_json(config),
            "scenario": {
                "script": list(case.script),
                "session_seed": seed,
                "moment": moment.index,
                "trace": [dict(command) for command in moment.trace],
            },
            "asset_provenance": _provenance(config),
            "validation": {"validators": list(validators.SCENE_VALIDATORS)},
        },
    }
    record_file = f"stress/{case.name}.json"
    record_bytes = _json_bytes(record)
    files.insert(0, (record_file, record_bytes))
    entry = {
        "id": record_id,
        "file": record_file,
        "sha256": _sha256(record_bytes),
        "image": None if image_json is None else {"file": image_json["file"], "sha256": image_json["sha256"]},
        "layout_family": family.name,
        "visual_preset": preset.name,
        "viewport": _viewport_json(case.viewport),
        "broken": case.break_ is not None,
        "reason": reason,
        "codes": list(codes),
    }
    return entry, files


def _break(candidate: dict[str, Any], broken: Mapping[str, Any], where: str) -> dict[str, Any]:
    """A copy of a scene with one deliberate fault.

    `element` is the identity of a bound element. `remove` takes it out;
    `duplicate` writes it twice; `retext` and `rebind` change the text or the
    binding the application supplied; `resize` multiplies its box's `width`
    and `height`; `move` shifts it by `dx` and `dy` or puts it `onto` another
    element; `cover` draws an opaque structural element over it; `style` sets
    the style value `field` to `value`; `reparent` gives it the `parent` named.
    """
    scene = copy.deepcopy(candidate)
    elements = scene["elements"]

    def find(identity: Any) -> dict[str, Any]:
        for element in elements:
            if element.get("bound", {}).get("identity") == identity:
                return element
        raise ConfigError([f"{where}.break: {identity!r} is not an element of the script's last state"])

    element = find(broken["element"])
    kind = broken["kind"]
    try:
        if kind == "remove":
            elements.remove(element)
        elif kind == "duplicate":
            elements.append({**copy.deepcopy(element), "id": element["id"] + ".copy"})
        elif kind == "retext":
            element["bound"]["text"] = broken.get("text", element["bound"]["text"] + " (changed)")
        elif kind == "rebind":
            element["bound"]["binding"] = broken.get("binding", {"command": "create"})
        elif kind == "resize":
            element["box"]["width"] *= broken.get("width", 1.0)
            element["box"]["height"] *= broken.get("height", 1.0)
        elif kind == "move":
            if "onto" in broken:
                other = find(broken["onto"])["box"]
                element["box"]["x"], element["box"]["y"] = other["x"], other["y"]
            else:
                element["box"]["x"] += broken.get("dx", 0.0)
                element["box"]["y"] += broken.get("dy", 0.0)
        elif kind == "cover":
            root = next(item for item in elements if item["parent"] is None)
            elements.append({"id": "s.cover", "type": "divider", "parent": root["id"], "box": dict(element["box"]), "style": copy.deepcopy(root["style"])})
        elif kind == "style":
            if broken["field"] not in element["style"]:
                raise KeyError(broken["field"])
            element["style"][broken["field"]] = broken["value"]
        elif kind == "reparent":
            element["parent"] = broken["parent"]
    except (KeyError, TypeError) as error:
        raise ConfigError([f"{where}.break: the {kind} it describes cannot be made ({error!r})"]) from None
    return scene


def stress_problems(record: Any, config: Config) -> list[str]:
    """Every way a stress-test record is not one: it is labelled as the
    stress-test set and as no training target, it holds neither model inputs
    nor a target, and the validators still reject its candidate scene for
    exactly the codes it records."""
    if not isinstance(record, dict) or record.get("kind") != "stress-test-record":
        return ['it is not an object of kind "stress-test-record"']
    problems = [f"it has no {name}" for name in STRESS_FIELDS if name not in record]
    problems += [f"{name!r} is not a field of a stress-test record" for name in sorted(set(record) - set(STRESS_FIELDS), key=str)]
    if problems:
        return problems
    if record["set"] != STRESS_SET or record["training_target"] is not False:
        problems.append(f'it is not labelled set "{STRESS_SET}" and training_target false')
    try:
        supplied = _bound_elements(record["application"]["bound_elements"])
        conditioning = record["conditioning"]
        viewport = (conditioning["viewport"]["width"], conditioning["viewport"]["height"])
        preset = config.design.preset(conditioning["visual_preset"])
        family = config.layout.family_of(config.layout.condition(conditioning["design_condition"]))
        expected = sorted(record["expected"]["codes"])
        recorded = sorted({problem["code"] for problem in record["rejection"]["problems"]})
        candidate = record["candidate"]
        if candidate is None:
            found = _judged(supplied, viewport, preset, family, least_text_inset=config.layout.least_text_inset)[2]
        else:
            found = validators.judge(candidate["scene"], supplied, viewport, preset)[1]
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return [*problems, f"it cannot be judged again: {error!r}"]
    codes = sorted({finding.code for finding in found})
    if not codes:
        problems.append("the validators do not reject it")
    if codes != recorded:
        problems.append(f"the validators reject it for {', '.join(codes) or 'nothing'}; it records {', '.join(recorded) or 'nothing'}")
    if recorded != expected:
        problems.append(f"it records {', '.join(recorded) or 'nothing'} and was expected to be rejected for {', '.join(expected)}")
    return problems


def _manifest(
    config: Config,
    ran: Sequence[Session],
    refused: Sequence[Session],
    entries: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    stress: list[dict[str, Any]],
    seen: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    import PySide6
    from PySide6.QtCore import qVersion

    def count(field: str) -> dict[str, int]:
        return dict(sorted(Counter(entry[field] for entry in entries).items()))

    def session_json(session: Session) -> dict[str, Any]:
        return {
            "id": session.id,
            "scenario": session.scenario,
            "seed": session.seed,
            "layout_family": session.layout_family,
            "visual_preset": session.visual_preset,
            "viewport": None if session.viewport is None else _viewport_json(session.viewport),
            "content_length": session.content_length,
            # The sizes tried before this one and refused, under the viewport choice `fitting`.
            "viewports_refused": [dict(refusal) for refusal in session.viewports_refused],
        }

    coverage = validators.coverage(_declared(config), seen)
    return {
        "kind": "dataset-manifest",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset": {"name": config.name, "version": config.version},
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "seed": config.seed,
        "configuration": {"file": CONFIG_NAME, "sha256": config.sha256},
        "asset_provenance": _provenance(config),
        # The text measurements in the records and the pixels of the images
        # come from this Qt; another version may give other bytes.
        "drawn_with": {"pyside6": PySide6.__version__, "qt": qVersion()},
        "rendering_mode": RenderingMode.A_REFERENCE.value,
        "pixels_per_viewport_unit": config.scale,
        "validators": [*VALIDATORS, validators.COVERAGE],
        "viewport_choice": config.viewport_choice,
        "counts": {
            "sessions": len(ran),
            "sessions_refused": len(refused),
            "records": len(entries),
            "rejected": len(rejected),
            "application_states": len({entry["application_state"] for entry in entries}),
            "by_layout_family": count("layout_family"),
            "by_visual_preset": count("visual_preset"),
            "by_viewport": dict(sorted(Counter(_viewport_name((e["viewport"]["width"], e["viewport"]["height"])) for e in entries).items())),
            "coverage_gaps": len(coverage["gaps"]),
            "stress_tests": len(stress),
        },
        "sessions": [session_json(session) for session in ran],
        # Sessions that were not run, because their design fits none of the viewport sizes.
        "sessions_refused": [{**session_json(session), "reason": "no_viewport_fits"} for session in refused],
        "records": entries,
        "rejected": rejected,
        "coverage": coverage,
        # Deliberately difficult or broken examples. None is a record, and none is a training target.
        "stress_tests": {"set": STRESS_SET, "training_target": False, "records": stress},
        "out_of_scope": list(config.layout.out_of_scope),
        # One hash over every record and image hash, in order.
        "records_sha256": _sha256("".join(entry["sha256"] + entry["image"]["sha256"] for entry in entries).encode()),
    }


# --- writing and checking --------------------------------------------------------


def write(config: Config, out: str | Path) -> dict[str, Any]:
    """Generate the dataset into `out` and return its manifest.

    The dataset is generated beside `out` and moved into place whole, so `out`
    never holds half a dataset. If `out` already holds this very dataset, byte
    for byte, nothing changes. If it holds anything else, `DatasetDiffers` is
    raised and nothing changes: a dataset is never overwritten.
    """
    try:
        return json.loads(write_folder(generate(config), out)[MANIFEST_NAME])
    except FolderDiffers as differs:
        raise DatasetDiffers(f"{out} already holds a different dataset ({differs})") from None


class FolderDiffers(Exception):
    """The folder already holds files that are not the ones made. Says the first difference."""


class UnsafeName(ValueError):
    """A file was named with a path that leaves the folder it is written into."""


def write_folder(files: Iterable[tuple[str, bytes]], out: str | Path, keep: Sequence[str] = (MANIFEST_NAME,)) -> dict[str, bytes]:
    """Write files given as (path inside the folder, bytes) into `out`, whole
    or not at all, and return the bytes of those named in `keep`.

    The files are written beside `out` and moved into place together. If `out`
    already holds these very files, byte for byte, nothing changes. If it
    holds anything else, `FolderDiffers` is raised and nothing changes. A name
    that is absolute or steps out of the folder raises `UnsafeName`, and
    nothing is written anywhere.
    """
    out = Path(out)
    partial = out.with_name(f".{out.name}.partial-{os.getpid()}")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        kept: dict[str, bytes] = {}
        for name, data in files:
            inside = Path(name)
            if not name or inside.is_absolute() or ".." in inside.parts:
                raise UnsafeName(f"{name!r} is not a path inside the folder")
            path = partial / inside
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if name in keep:
                kept[name] = data
        if out.exists():
            difference = _first_difference(partial, out)
            if difference:
                raise FolderDiffers(difference)
        else:
            partial.rename(out)
        return kept
    finally:
        if partial.exists():
            shutil.rmtree(partial)


def _first_difference(made: Path, existing: Path) -> str | None:
    def files(root: Path) -> set[str]:
        return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}

    ours, theirs = files(made), files(existing)
    for name in sorted(ours | theirs):
        if name not in theirs:
            return f"{name} is missing from it"
        if name not in ours:
            return f"{name} is not part of what was generated"
        if (made / name).read_bytes() != (existing / name).read_bytes():
            return f"{name} has other contents"
    return None


def check(folder: str | Path) -> list[str]:
    """Every way a written dataset is not what its manifest and its own
    configuration say. An empty list means: every file has the hash the
    manifest gives, every record keeps the record rules, and generating the
    dataset again from its configuration gives the same bytes."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_bytes())
        entries = [(entry["id"], entry["file"], entry["sha256"], entry["image"]["file"], entry["image"]["sha256"]) for entry in manifest["records"]]
        stress = [
            (entry["id"], entry["file"], entry["sha256"], *((entry["image"]["file"], entry["image"]["sha256"]) if entry["image"] else (None, None)))
            for entry in manifest.get("stress_tests", {}).get("records", [])
        ]
        config_sha256 = manifest["configuration"]["sha256"]
    except FileNotFoundError:
        return [f"{folder / MANIFEST_NAME} does not exist"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
        return [f"{MANIFEST_NAME} is not a dataset manifest: {error!r}"]

    # The configuration the dataset was generated from, if it is still the one
    # the manifest names: the validators need its design and its layout.
    config, unusable = None, None
    try:
        config_bytes = (folder / CONFIG_NAME).read_bytes()
        if _sha256(config_bytes) != config_sha256:
            unusable = f"{CONFIG_NAME} does not have the hash the manifest gives"
        else:
            config = parse_config(config_bytes)
    except FileNotFoundError:
        unusable = f"{CONFIG_NAME} does not exist"
    except ConfigError as error:
        unusable = f"{CONFIG_NAME} cannot be used: {error}"

    problems: list[str] = []
    listed = {MANIFEST_NAME, CONFIG_NAME}
    for kind, items in (("record", entries), ("stress test", stress)):
        for record_id, record_file, record_sha256, image_file, image_sha256 in items:
            for name, sha256 in ((record_file, record_sha256), (image_file, image_sha256)):
                if name is None:
                    continue
                listed.add(name)
                path = folder / name
                if not path.is_file():
                    problems.append(f"{name} is listed in the manifest and does not exist")
                elif _sha256(path.read_bytes()) != sha256:
                    problems.append(f"{name} does not have the hash the manifest gives")
            try:
                record = json.loads((folder / record_file).read_bytes())
            except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if kind == "record":
                found = record_problems(record, config.design if config else None, config.layout if config else None)
                image = record.get("reference_image") if isinstance(record, dict) else None
            else:
                found = stress_problems(record, config) if config else []
                image = record.get("image") if isinstance(record, dict) else None
            problems += [f"{kind} {record_id}: {problem}" for problem in found]
            if isinstance(image, dict) and image.get("sha256") != image_sha256:
                problems.append(f"{kind} {record_id}: its image is not the one the manifest lists")
    if {record_id for record_id, *_ in entries} & {record_id for record_id, *_ in stress}:
        problems.append("a stress test is listed among the records")
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and name not in listed:
            problems.append(f"{name} is not listed in the manifest")

    if config is None:
        return [*problems, f"{unusable}, so no target was put before the validators, no stress test was judged again and the dataset cannot be generated again"]
    try:
        for name, data in generate(config):
            path = folder / name
            if path.is_file() and path.read_bytes() != data:
                problems.append(f"{name} is not what generating the dataset again gives")
            elif not path.is_file() and name not in listed:
                problems.append(f"{name} is generated again and is not in the dataset")
    except ConfigError as error:
        problems.append(f"the dataset cannot be generated again: {error}")
    return problems


# --- the record rules --------------------------------------------------------------


def record_problems(record: Any, design: design_source.Design | None = None, layout: layout_family.Layout | None = None) -> list[str]:
    """Every way a dataset record breaks the record rules. Chief among them:
    its model inputs hold only model inputs, and so neither the target, nor an
    image, nor any diagnostic metadata. Given the design the dataset was
    generated in, the target must also pass every validator of a scene, which
    need the visual preset. Given the layout, the design condition in the
    inputs must be the whole condition of the record's layout family: a
    factor left out of the inputs would leave the target undetermined by
    them."""
    if not isinstance(record, dict) or record.get("kind") != "dataset-record":
        return ['it is not an object of kind "dataset-record"']
    problems = [f"it has no {name}" for name in RECORD_FIELDS if name not in record]
    problems += [f"{name!r} is not a field of a dataset record" for name in sorted(set(record) - set(RECORD_FIELDS), key=str)]
    if problems:
        return problems
    inputs, target, application, diagnostics = (record[name] for name in ("inputs", "target", "application", "diagnostics"))

    # 1. The inputs are exactly the listed model inputs.
    problems += [f"inputs: {problem}" for problem in model_inputs.problems(inputs)]

    # 2. No part of the inputs is the target, or a part of it.
    scene = target.get("scene") if isinstance(target, dict) else None
    if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
        return [*problems, "target.scene is not a scene"]
    parts: list[tuple[str, Any]] = [("the target scene", scene), ("the target scene's elements", scene["elements"])]
    for element in scene["elements"]:
        if isinstance(element, dict):
            label = element.get("id")
            parts.append((f"the target element {label}", element))
            parts += [(f"the {name} of the target element {label}", element[name]) for name in ("box", "style") if name in element]
    for where, value in _walk(inputs, "inputs"):
        for what, part in parts:
            if isinstance(value, (dict, list)) and scene_schema._same(value, part):
                problems.append(f"{where} is {what}: an input contains the target")

    # 3. No name or number that identifies how the record was made is in the inputs.
    if not isinstance(diagnostics, dict) or set(diagnostics) != set(DIAGNOSTIC_FIELDS):
        return [*problems, f"diagnostics does not hold exactly: {', '.join(DIAGNOSTIC_FIELDS)}"]
    try:
        scenario, generator = diagnostics["scenario"], diagnostics["generator"]
        forbidden = {
            "the record's id": record["id"],
            "the layout family's name": diagnostics["layout_family"],
            "the visual preset's name": diagnostics["visual_preset"],
            "the scenario's name": scenario["name"],
            "the session's id": scenario["session"],
            "the session's seed": scenario["session_seed"],
            "the content length's name": scenario.get("content_length"),
            "the configuration's hash": generator["configuration"]["sha256"],
            "the reference image's hash": record["reference_image"]["sha256"],
            "the reference image's file": record["reference_image"]["file"],
        }
    except (KeyError, TypeError) as error:
        return [*problems, f"diagnostics is incomplete: {error!r}"]
    for where, value in _walk(inputs, "inputs", keys=True):
        for what, name in forbidden.items():
            if isinstance(value, str) and value == name:
                problems.append(f"{where} is {what}: an input contains diagnostic metadata")

    # 4. The inputs describe the bound elements the application supplied.
    try:
        supplied = _bound_elements(application["bound_elements"])
        viewport = (inputs["viewport"]["width"], inputs["viewport"]["height"])
        rebuilt = model_inputs.build(supplied, viewport, inputs["design_condition"], inputs["visual_preset"])
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return [*problems, f"the inputs cannot be rebuilt from application.bound_elements: {error!r}"]
    if not scene_schema._same(rebuilt, inputs):
        problems.append("inputs are not what application.bound_elements, the viewport and the conditioning give")

    # 5. The target is a valid scene that carries those bound elements unchanged.
    try:
        valid = scene_schema.validate(scene, supplied, viewport)
    except SceneInvalid as refused:
        return [*problems, *(f"target.scene is invalid: {problem}" for problem in refused.problems)]

    # 6. The inputs give every factor value of the record's layout family.
    if layout is not None:
        try:
            declared = layout.family(diagnostics["layout_family"]).design_condition.to_json()
        except layout_family.LayoutError as error:
            return [*problems, f"diagnostics.layout_family: {error}"]
        if not scene_schema._same(inputs["design_condition"], declared):
            problems.append("inputs.design_condition is not the design condition of the record's layout family")

    # 7. The target passes the other validators, in the record's visual preset.
    if design is not None:
        try:
            preset = design.preset(diagnostics["visual_preset"])
        except design_source.DesignError as error:
            return [*problems, f"diagnostics.visual_preset: {error}"]
        problems += [f"target.scene is rejected by {finding.validator}: {finding}" for finding in validators.findings(valid, preset)]
    return problems


def _bound_elements(items: Any) -> tuple[BoundElement, ...]:
    """Bound elements as a record stores them, as the adapter's objects."""
    return tuple(
        BoundElement(
            identity=item["identity"], role=item["role"], text=item["text"], binding=item["binding"],
            state=item["state"], relationships=tuple(item["relationships"]),
        )
        for item in items
    )  # fmt: skip


def _walk(value: Any, where: str, keys: bool = False) -> Iterator[tuple[str, Any]]:
    """Every value inside `value` with its place, and every key too if asked."""
    yield where, value
    if isinstance(value, dict):
        for key, inner in value.items():
            if keys:
                yield f"a key of {where}", key
            yield from _walk(inner, f"{where}.{key}", keys)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _walk(inner, f"{where}[{index}]", keys)


# --- small things ----------------------------------------------------------------


def _document_json(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "body": document.body,
        "revision": document.revision,
        "draft": document.draft,
        "modified": document.modified,
    }


def _state_json(state: ApplicationState) -> dict[str, Any]:
    return {
        "documents": [_document_json(document) for document in state.documents],
        "total_documents": state.total_documents,
        "sort": {"key": state.sort.key, "descending": state.sort.descending},
        "filter": state.filter,
        "open_document": None if state.open_document is None else _document_json(state.open_document),
        "undoable": state.undoable,
        "notification": state.notification,
        "interaction": dict(sorted(state.interaction.items())),
    }


def _viewport_json(viewport: tuple[float, float]) -> dict[str, float]:
    return {"width": viewport[0], "height": viewport[1]}


def _viewport_name(viewport: tuple[float, float]) -> str:
    return f"{viewport[0]:g} by {viewport[1]:g}"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _canonical_sha256(value: Any) -> str:
    """The hash of a JSON value whatever order its keys were written in."""
    return _sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
