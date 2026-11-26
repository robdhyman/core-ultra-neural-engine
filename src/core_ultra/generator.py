"""The generator: scripted sessions in, traceable dataset records out.

`data generate` reads a dataset configuration, runs its scripted sessions
against the application kernel, has the reference layout engine write the true
scene of every state reached, draws that scene with the runtime renderer and
writes one dataset record and one reference image per state, then a manifest.

    dataset/
      manifest.json           hashes of everything below; the one file meant for git
      config.json             the dataset configuration, byte for byte
      records/<id>.json       one dataset record
      images/<id>.png         its reference image, A, Reference drawn by the runtime renderer

A dataset record keeps five things apart:

| Field | Holds |
| --- | --- |
| `inputs` | The model inputs (`core_ultra.model_inputs`), and nothing else. |
| `target` | The true scene. |
| `reference_image` | The image file, its hash and size. |
| `application` | What the application supplied: the bound elements with their exact text, action bindings and states, and the application state. |
| `diagnostics` | Everything needed to trace and regenerate the record, and nothing the scene model may see: generator version, seed and configuration, layout family, visual preset and scenario identifiers, asset provenance and validation results. |

Sessions. Each scenario of the configuration is a script
(`core_ultra.scripted_session`), run `sessions_per_scenario` times. A session
is one run of the application in one design: it is given one layout family,
one visual preset and one viewport size, dealt out in turn from seeded orders
so that the sessions cover each list evenly. A record's id is
`<scenario>-<run>.<moment>`.

Nothing here depends on the clock, the machine's name or the order of a hash
table. The random choices come from `random.Random` seeded with text made of
the configuration's seed and the session's id. The same configuration
therefore gives the same bytes, and `check` proves it for a written dataset by
generating it again.

A state whose true scene fails scene validation is not written as a record. It
is listed in the manifest under `rejected` with every problem, and counted.

`record_problems` is the check that no model input holds the target or any
diagnostic metadata. The generator runs it on every record before writing it,
and `check` runs it on every record of a written dataset.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_ultra import design as design_source
from core_ultra import layout_family, model_inputs, runtime_renderer, scene as scene_schema, scripted_session
from core_ultra.documents_adapter import BoundElement
from core_ultra.kernel import ApplicationState, Document
from core_ultra.scene_session import Conditioning, RenderingMode, SceneInvalid, SceneSession, TextNotDrawable
from core_ultra.scripted_session import Content, Moment, ScriptError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = Path("artifacts") / "datasets"

GENERATOR_NAME = "core-ultra data generate"
GENERATOR_VERSION = 1
RECORD_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.json"

RECORD_FIELDS = ("kind", "schema_version", "id", "inputs", "target", "reference_image", "application", "diagnostics")
DIAGNOSTIC_FIELDS = ("generator", "layout_family", "visual_preset", "scenario", "related", "asset_provenance", "validation")
VALIDATORS = ("scene validation", "model inputs hold neither the target nor diagnostic metadata")

_CONFIG_FIELDS = (
    "kind", "name", "version", "note", "seed", "design", "layout", "layout_families", "visual_presets",
    "viewports", "pixels_per_viewport_unit", "sessions_per_scenario", "scenarios", "content",
)  # fmt: skip
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


@dataclass(frozen=True)
class Session:
    """One scripted session and the design it runs in."""

    id: str
    scenario: str
    script: tuple[str, ...]
    seed: str
    layout_family: str
    visual_preset: str
    viewport: tuple[float, float]


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
    problems += [f"{name} is missing" for name in _CONFIG_FIELDS if name not in raw and name != "note"]
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
    )


def _repository_file(stated: Any, field: str) -> Path:
    """A configuration names its design and layout by path from the repository root."""
    if not isinstance(stated, str) or not stated or Path(stated).is_absolute() or ".." in Path(stated).parts:
        raise ConfigError([f"{field} is not a path from the repository root"])
    return REPO_ROOT / stated


def default_out(config: Config) -> Path:
    return DEFAULT_OUT_ROOT / f"{config.name}-v{config.version}"


# --- sessions --------------------------------------------------------------------


def sessions(config: Config) -> tuple[Session, ...]:
    """Every scripted session of the configuration, each with its design.

    The layout families, visual presets and viewport sizes are each put in a
    seeded order and dealt out in turn, so session n has the nth of each.
    """
    dealer = random.Random(f"{config.seed}/designs")
    orders = []
    for values in (config.layout_families, config.visual_presets, config.viewports):
        order = list(values)
        dealer.shuffle(order)
        orders.append(order)
    families, presets, viewports = orders

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
                    visual_preset=presets[number % len(presets)],
                    viewport=viewports[number % len(viewports)],
                )
            )
    return tuple(planned)


# --- generating ------------------------------------------------------------------


def generate(config: Config) -> Iterator[tuple[str, bytes]]:
    """Every file of the dataset as (path inside the dataset folder, bytes):
    the configuration, then each record with its image, then the manifest."""
    yield CONFIG_NAME, config.data

    scene_session = SceneSession()
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    planned = sessions(config)
    for session in planned:
        family = config.layout.family(session.layout_family)
        preset = config.design.preset(session.visual_preset)
        conditioning = Conditioning(
            *session.viewport, visual_preset=preset.name, design_condition=family.design_condition.to_json()
        )
        tokens = model_inputs.preset_tokens(preset)
        try:
            moments = list(scripted_session.run(session.script, config.content, random.Random(session.seed)))
        except ScriptError as error:
            raise ConfigError([f"scenarios.{session.scenario}, session {session.id}: {error}"]) from None

        for moment in moments:
            record_id = f"{session.id}.{moment.index:03d}"
            try:
                frame = scene_session.frame(moment.state, conditioning, RenderingMode.A_REFERENCE, scale=config.scale)
            except SceneInvalid as refused:
                rejected.append(
                    _rejection(record_id, session, "scene_invalid", [_problem_json(problem) for problem in refused.problems])
                )
                continue
            except TextNotDrawable as refused:
                rejected.append(
                    _rejection(record_id, session, "text_not_drawable", [{"code": "text_not_drawable", "element": None, "detail": str(refused)}])
                )
                continue

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
            found = record_problems(record)
            if found:
                raise RuntimeError(f"record {record_id} was not written, because it broke the record rules: " + "; ".join(found))
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
                    "viewport": {"width": session.viewport[0], "height": session.viewport[1]},
                }
            )

    yield MANIFEST_NAME, _json_bytes(_manifest(config, planned, entries, rejected))


def _diagnostics(config: Config, session: Session, moment: Moment) -> dict[str, Any]:
    return {
        "generator": {
            "name": GENERATOR_NAME,
            "version": GENERATOR_VERSION,
            "seed": config.seed,
            "configuration": {"name": config.name, "version": config.version, "sha256": config.sha256},
        },
        "layout_family": session.layout_family,
        "visual_preset": session.visual_preset,
        "scenario": {
            "name": session.scenario,
            "session": session.id,
            "session_seed": session.seed,
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
            "inputs": {"problems": []},
        },
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


def _rejection(record_id: str, session: Session, reason: str, problems: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": record_id,
        "session": session.id,
        "layout_family": session.layout_family,
        "visual_preset": session.visual_preset,
        "viewport": {"width": session.viewport[0], "height": session.viewport[1]},
        "reason": reason,
        "problems": problems,
    }


def _manifest(config: Config, planned: tuple[Session, ...], entries: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    import PySide6
    from PySide6.QtCore import qVersion

    def count(field: str) -> dict[str, int]:
        return dict(sorted(Counter(entry[field] for entry in entries).items()))

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
        "counts": {
            "sessions": len(planned),
            "records": len(entries),
            "rejected": len(rejected),
            "application_states": len({entry["application_state"] for entry in entries}),
            "by_layout_family": count("layout_family"),
            "by_visual_preset": count("visual_preset"),
        },
        "sessions": [
            {
                "id": session.id,
                "scenario": session.scenario,
                "seed": session.seed,
                "layout_family": session.layout_family,
                "visual_preset": session.visual_preset,
                "viewport": {"width": session.viewport[0], "height": session.viewport[1]},
            }
            for session in planned
        ],
        "records": entries,
        "rejected": rejected,
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
    out = Path(out)
    partial = out.with_name(f".{out.name}.partial-{os.getpid()}")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        manifest_bytes = b""
        for name, data in generate(config):
            path = partial / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if name == MANIFEST_NAME:
                manifest_bytes = data
        if out.exists():
            difference = _first_difference(partial, out)
            if difference:
                raise DatasetDiffers(f"{out} already holds a different dataset ({difference})")
        else:
            partial.rename(out)
        return json.loads(manifest_bytes)
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
            return f"{name} is not part of the generated dataset"
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
        config_sha256 = manifest["configuration"]["sha256"]
    except FileNotFoundError:
        return [f"{folder / MANIFEST_NAME} does not exist"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
        return [f"{MANIFEST_NAME} is not a dataset manifest: {error!r}"]

    problems: list[str] = []
    listed = {MANIFEST_NAME, CONFIG_NAME}
    for record_id, record_file, record_sha256, image_file, image_sha256 in entries:
        for name, sha256 in ((record_file, record_sha256), (image_file, image_sha256)):
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
        problems += [f"record {record_id}: {problem}" for problem in record_problems(record)]
        if isinstance(record, dict) and isinstance(record.get("reference_image"), dict):
            if record["reference_image"].get("sha256") != image_sha256:
                problems.append(f"record {record_id}: its reference image is not the one the manifest lists")
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and name not in listed:
            problems.append(f"{name} is not listed in the manifest")

    try:
        config_bytes = (folder / CONFIG_NAME).read_bytes()
    except FileNotFoundError:
        return [*problems, f"{CONFIG_NAME} does not exist, so the dataset cannot be generated again"]
    if _sha256(config_bytes) != config_sha256:
        return [*problems, f"{CONFIG_NAME} does not have the hash the manifest gives, so the dataset cannot be generated again"]
    try:
        config = parse_config(config_bytes)
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


def record_problems(record: Any) -> list[str]:
    """Every way a dataset record breaks the record rules. Chief among them:
    its model inputs hold only model inputs, and so neither the target, nor an
    image, nor any diagnostic metadata."""
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
        supplied = tuple(
            BoundElement(
                identity=item["identity"], role=item["role"], text=item["text"], binding=item["binding"],
                state=item["state"], relationships=tuple(item["relationships"]),
            )
            for item in application["bound_elements"]
        )  # fmt: skip
        viewport = (inputs["viewport"]["width"], inputs["viewport"]["height"])
        rebuilt = model_inputs.build(supplied, viewport, inputs["design_condition"], inputs["visual_preset"])
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        return [*problems, f"the inputs cannot be rebuilt from application.bound_elements: {error!r}"]
    if not scene_schema._same(rebuilt, inputs):
        problems.append("inputs are not what application.bound_elements, the viewport and the conditioning give")

    # 5. The target is a valid scene that carries those bound elements unchanged.
    try:
        scene_schema.validate(scene, supplied, viewport)
    except SceneInvalid as refused:
        problems += [f"target.scene is invalid: {problem}" for problem in refused.problems]
    return problems


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


def _problem_json(problem: scene_schema.Problem) -> dict[str, Any]:
    return {"code": problem.code, "element": problem.element, "detail": problem.detail}


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
