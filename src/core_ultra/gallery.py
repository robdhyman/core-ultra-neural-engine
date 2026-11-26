"""The review gallery: a written dataset as one local page a person can judge.

`data gallery` reads a dataset folder that `data generate` wrote and builds a
folder beside it:

    gallery/
      index.html              the page; it opens from disk and loads nothing from a network
      manifest.json           what the page shows, the coverage summary and the hash of every file
      images/<id>.png         the reference image of every dataset record, byte for byte
      rejected/<id>.png       every rejected state that can be drawn, drawn again
      stress/<name>.png       the pictures of the stress-test set, byte for byte

The page has three parts.

The coverage summary counts the records by layout family, visual preset,
density, content length, element state and viewport size, and by each pair of
layout family and visual preset. A value the dataset configuration declares
and no record shows is listed as not shown, with a count of zero.

The dataset records are grouped by layout family, then visual preset, then
scripted session. Each reference image is labelled with its layout family,
its visual preset, its design condition and its state: the element pointed at
and how, and every element state the frame shows.

What the validators rejected is shown apart, after the records and never
among them, each with every reason: the states the manifest lists under
`rejected`; the viewport sizes a session was refused, with the first state
rejected there; the sessions no viewport size fits; and the stress-test set,
labelled as never a training target. A rejected state is not in the dataset,
so it has no image there. The gallery makes its scene again from the
dataset's own configuration (`generator.rejected_scene`) and draws it with
the runtime renderer; a state scene validation refuses cannot be drawn, and
the page says so in place of a picture.

A dataset whose files are not the ones its manifest lists is refused: a
gallery is only ever built from a dataset that is what it says. The same
dataset always gives the same gallery, byte for byte, and a gallery is never
overwritten by a different one.

Every label and every count is read from the dataset's records and manifest.
Nothing here judges a scene, and nothing is measured with the page.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_ultra import documents_adapter, generator, runtime_renderer

DEFAULT_OUT_ROOT = Path("artifacts") / "galleries"
KIND = "dataset-gallery"
SCHEMA_VERSION = 1
PAGE_NAME = "index.html"
MANIFEST_NAME = "manifest.json"

# The dimensions of the coverage summary, in the order they are shown.
DIMENSIONS = ("layout family", "visual preset", "density", "content length", "element state", "viewport")
# What a record's content length is called when its configuration names none.
ONE_LENGTH = "unnamed"


class SourceError(Exception):
    """The folder is not a dataset a gallery can be built from. `problems` lists why."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


class GalleryDiffers(Exception):
    """The folder already holds a gallery that is not the one built."""


@dataclass(frozen=True)
class Dataset:
    """A written dataset, read whole: its manifest, its configuration, its
    records in the manifest's order and the bytes of every picture."""

    folder: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    config: generator.Config
    records: tuple[Mapping[str, Any], ...]
    images: Mapping[str, bytes]
    stress: tuple[Mapping[str, Any], ...]
    stress_images: Mapping[str, bytes]


def default_out(dataset: Dataset) -> Path:
    return DEFAULT_OUT_ROOT / f"{dataset.config.name}-v{dataset.config.version}"


# --- reading the dataset ---------------------------------------------------------


def load(folder: str | Path) -> Dataset:
    """The dataset in `folder`. Raises `SourceError` with every reason when it
    is not one, or when a file is not the one its manifest lists."""
    folder = Path(folder)
    try:
        manifest_bytes = (folder / generator.MANIFEST_NAME).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        raise SourceError([f"{folder / generator.MANIFEST_NAME} does not exist; a dataset folder is one `data generate` wrote"]) from None
    except OSError as error:
        raise SourceError([f"{folder / generator.MANIFEST_NAME} cannot be read: {error.strerror or error}"]) from None
    try:
        manifest = json.loads(manifest_bytes)
        if manifest.get("kind") != "dataset-manifest":
            raise KeyError("kind")
        entries = [(entry["id"], entry["file"], entry["sha256"], entry["image"]["file"], entry["image"]["sha256"]) for entry in manifest["records"]]
        stress_entries = [
            (entry["id"], entry["file"], entry["sha256"], *((entry["image"]["file"], entry["image"]["sha256"]) if entry["image"] else (None, None)))
            for entry in manifest.get("stress_tests", {}).get("records", [])
        ]
        config_sha256 = manifest["configuration"]["sha256"]
        names = [name for entry in (*entries, *stress_entries) for name in (entry[0], entry[1], entry[3]) if name is not None]
        if not all(isinstance(name, str) and name for name in names):
            raise TypeError("an id or a file name is not text")
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError, ValueError) as error:
        raise SourceError([f"{folder / generator.MANIFEST_NAME} is not a dataset manifest: {error!r}"]) from None

    problems: list[str] = []
    config = None
    try:
        config_bytes = (folder / generator.CONFIG_NAME).read_bytes()
        if _sha256(config_bytes) != config_sha256:
            problems.append(f"{generator.CONFIG_NAME} does not have the hash the manifest gives")
        else:
            config = generator.parse_config(config_bytes)
    except FileNotFoundError:
        problems.append(f"{generator.CONFIG_NAME} does not exist")
    except OSError as error:
        problems.append(f"{generator.CONFIG_NAME} cannot be read: {error.strerror or error}")
    except generator.ConfigError as error:
        problems.append(f"{generator.CONFIG_NAME} cannot be used: {error}")

    def listed(name: str, sha256: str) -> bytes | None:
        try:
            data = (folder / name).read_bytes()
        except FileNotFoundError:
            problems.append(f"{name} is listed in the manifest and does not exist")
            return None
        except OSError as error:
            problems.append(f"{name} is listed in the manifest and cannot be read: {error.strerror or error}")
            return None
        if _sha256(data) != sha256:
            problems.append(f"{name} does not have the hash the manifest gives")
            return None
        return data

    def parsed(name: str, data: bytes | None, kind: str, record_id: str) -> Mapping[str, Any] | None:
        if data is None:
            return None
        try:
            record = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            record = None
        if not isinstance(record, dict) or record.get("kind") != kind:
            problems.append(f'{name} is not an object of kind "{kind}"')
            return None
        if record.get("id") != record_id:
            problems.append(f"{name} is listed in the manifest as {record_id!r} and says it is {record.get('id')!r}")
            return None
        return record

    records, images = [], {}
    for record_id, record_file, record_sha256, image_file, image_sha256 in entries:
        record = parsed(record_file, listed(record_file, record_sha256), "dataset-record", record_id)
        image = listed(image_file, image_sha256)
        if record is not None and image is not None:
            records.append(record)
            images[record_id] = image
    stress, stress_images = [], {}
    for record_id, record_file, record_sha256, image_file, image_sha256 in stress_entries:
        record = parsed(record_file, listed(record_file, record_sha256), "stress-test-record", record_id)
        image = listed(image_file, image_sha256) if image_file else None
        if record is not None:
            stress.append(record)
            if image is not None:
                stress_images[record_id] = image
    if problems or config is None:
        raise SourceError(problems)
    return Dataset(
        folder=folder, manifest=manifest, manifest_sha256=_sha256(manifest_bytes), config=config,
        records=tuple(records), images=images, stress=tuple(stress), stress_images=stress_images,
    )  # fmt: skip


@dataclass(frozen=True)
class Shown:
    """What the gallery reads from one dataset record, and nothing else."""

    id: str
    layout_family: str
    visual_preset: str
    design_condition: Mapping[str, str]
    viewport: str
    content_length: str
    session: str
    scenario: str
    moment: str
    pointed: Mapping[str, str]
    states: Mapping[str, int]
    width: int
    height: int

    @property
    def state(self) -> str:
        """The frame's state as its label says it: what is pointed at and how,
        then every element state the frame shows."""
        pointed = ", ".join(f"{state} on {identity}" for identity, state in sorted(self.pointed.items())) or "nothing pointed at"
        return f"{pointed}; shows {', '.join(state for state in documents_adapter.STATES if self.states.get(state))}"


def shown(record: Mapping[str, Any]) -> Shown:
    try:
        diagnostics, scenario = record["diagnostics"], record["diagnostics"]["scenario"]
        viewport = record["inputs"]["viewport"]
        action = "before the first action" if scenario["action"] is None else f"{scenario['action']}, {scenario['phase']}"
        return Shown(
            id=record["id"],
            layout_family=diagnostics["layout_family"],
            visual_preset=diagnostics["visual_preset"],
            design_condition=dict(record["inputs"]["design_condition"]),
            viewport=_viewport_name(viewport),
            content_length=scenario.get("content_length") or ONE_LENGTH,
            session=scenario["session"],
            scenario=scenario["name"],
            moment=action,
            pointed=dict(record["application"]["state"]["interaction"]),
            states=Counter(element["state"] for element in record["application"]["bound_elements"]),
            width=int(record["reference_image"]["width"]),
            height=int(record["reference_image"]["height"]),
        )
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise SourceError([f"record {record.get('id')!r} cannot be read: {error!r}"]) from None


# --- the coverage summary --------------------------------------------------------


def coverage_summary(dataset: Dataset) -> dict[str, Any]:
    """How many records, and how many scripted sessions, show each value of
    each dimension, with every value the configuration declares and no record
    shows listed under `not_shown`. A record counts under every element state
    it shows; `elements` is the number of bound elements in that state."""
    config = dataset.config
    views = [shown(record) for record in dataset.records]
    conditions = [config.layout.family(name).design_condition.to_json() for name in config.layout_families]
    declared = {
        "layout family": list(config.layout_families),
        "visual preset": list(config.visual_presets),
        "density": [value for value in config.layout.factors["density"] if value in {condition["density"] for condition in conditions}],
        "content length": list(config.content_lengths) or [ONE_LENGTH],
        "element state": list(documents_adapter.STATES),
        "viewport": [_viewport_name({"width": width, "height": height}) for width, height in config.viewports],
    }
    of = {
        "layout family": lambda view: [view.layout_family],
        "visual preset": lambda view: [view.visual_preset],
        "density": lambda view: [view.design_condition.get("density")],
        "content length": lambda view: [view.content_length],
        "element state": lambda view: [state for state, count in view.states.items() if count],
        "viewport": lambda view: [view.viewport],
    }

    by: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        records: Counter = Counter()
        sessions: dict[str, set[str]] = {}
        for view in views:
            for value in of[dimension](view):
                records[value] += 1
                sessions.setdefault(value, set()).add(view.session)
        values = [*declared[dimension], *sorted(value for value in records if value not in declared[dimension])]
        by[dimension] = {
            "values": {
                value: {
                    "records": records[value],
                    "sessions": len(sessions.get(value, ())),
                    **({"elements": sum(view.states.get(value, 0) for view in views)} if dimension == "element state" else {}),
                }
                for value in values
            },
            "not_shown": [value for value in declared[dimension] if not records[value]],
        }

    pairs: Counter = Counter((view.layout_family, view.visual_preset) for view in views)
    pair_sessions: dict[tuple[str, str], set[str]] = {}
    for view in views:
        pair_sessions.setdefault((view.layout_family, view.visual_preset), set()).add(view.session)
    return {
        "records": len(views),
        "sessions": len({view.session for view in views}),
        "by": by,
        "layout_family_by_visual_preset": {
            family: {
                preset: {"records": pairs[family, preset], "sessions": len(pair_sessions.get((family, preset), ()))}
                for preset in config.visual_presets
            }
            for family in config.layout_families
        },
        "pairs_not_shown": [[family, preset] for family in config.layout_families for preset in config.visual_presets if not pairs[family, preset]],
    }


# --- what is shown apart ---------------------------------------------------------


_NOT_DRAWABLE = "scene validation refuses this scene, or the font cannot draw a text in it, so the runtime renderer cannot draw it"
_OTHER_GENERATOR = (
    "the dataset was written by another version of the generator, or from a design or layout file that has changed since, "
    "so the scene the validators judged cannot be made again"
)


def _apart(dataset: Dataset) -> tuple[dict[str, list[dict[str, Any]]], dict[str, bytes]]:
    """Everything the validators rejected, in the four groups the page shows
    apart, and the pictures of those that can be drawn."""
    manifest, config = dataset.manifest, dataset.config
    pictures: dict[str, bytes] = {}
    # A rejected state is made again by this code, from the design and layout
    # files as they are now. That is the scene the validators judged only if
    # the dataset was written by the same generator from the same files.
    provenance = manifest.get("asset_provenance", {})
    same_generator = (
        manifest.get("generator", {}).get("version") == generator.GENERATOR_VERSION
        and provenance.get("layout", {}).get("sha256") == config.layout.sha256
        and provenance.get("design", {}).get("sha256") == _sha256((generator.REPO_ROOT / config.design_file).read_bytes())
    )

    def drawn(file: str, session: str, moment: int, viewport: Mapping[str, float]) -> dict[str, Any] | None:
        if not same_generator:
            return None
        try:
            scene = generator.rejected_scene(config, session, moment, (viewport["width"], viewport["height"]))
        except generator.ConfigError as error:
            raise SourceError([f"a rejected state of session {session} cannot be made again: {error}"]) from None
        if scene is None:
            return None
        pixels = runtime_renderer.draw(scene, config.scale)
        pictures[file] = runtime_renderer.png_bytes(pixels)
        return {"file": file, "sha256": _sha256(pictures[file]), "width": int(pixels.shape[1]), "height": int(pixels.shape[0])}

    rejected = []
    for rejection in manifest.get("rejected", []):
        moment = int(rejection["id"].rsplit(".", 1)[1])
        rejected.append(
            {
                "id": rejection["id"],
                "session": rejection["session"],
                "layout_family": rejection["layout_family"],
                "visual_preset": rejection["visual_preset"],
                "viewport": _viewport_name(rejection["viewport"]),
                "reason": rejection["reason"],
                "problems": rejection["problems"],
                "image": drawn(f"rejected/{rejection['id']}.png", rejection["session"], moment, rejection["viewport"]),
                "not_drawn": None,
            }
        )

    refused_sizes = []
    for session in [*manifest.get("sessions", []), *manifest.get("sessions_refused", [])]:
        for refusal in session.get("viewports_refused", []):
            size = refusal["viewport"]
            state = f"{session['id']}.{refusal['moment']:03d}"
            refused_sizes.append(
                {
                    "id": f"{state} at {_viewport_name(size)}",
                    "session": session["id"],
                    "layout_family": session["layout_family"],
                    "visual_preset": session["visual_preset"],
                    "viewport": _viewport_name(size),
                    "given": None if session.get("viewport") is None else _viewport_name(session["viewport"]),
                    "reason": "viewport_refused",
                    "problems": refusal["problems"],
                    "image": drawn(f"rejected/{state}-{size['width']:g}x{size['height']:g}.png", session["id"], refusal["moment"], size),
                    "not_drawn": None,
                }
            )

    refused_sessions = [
        {
            "id": session["id"],
            "layout_family": session["layout_family"],
            "visual_preset": session["visual_preset"],
            "content_length": session.get("content_length"),
            "reason": session.get("reason", "no_viewport_fits"),
        }
        for session in manifest.get("sessions_refused", [])
    ]

    stress = []
    for record in dataset.stress:
        image = record.get("image")
        if image is not None and record["id"] in dataset.stress_images:
            pictures[image["file"]] = dataset.stress_images[record["id"]]
        stress.append(
            {
                "id": record["id"],
                "set": record["set"],
                "training_target": record["training_target"],
                "why": record["why"],
                "layout_family": record["conditioning"]["layout_family"],
                "visual_preset": record["conditioning"]["visual_preset"],
                "viewport": _viewport_name(record["conditioning"]["viewport"]),
                "broken_by": record["broken_by"],
                "reason": record["rejection"]["reason"],
                "problems": record["rejection"]["problems"],
                "image": None if image is None else {"file": image["file"], "sha256": image["sha256"], "width": int(image["width"]), "height": int(image["height"])},
                "not_drawn": None if image is not None else _NOT_DRAWABLE,
            }
        )
    for item in (*rejected, *refused_sizes):
        if item["image"] is None:
            item["not_drawn"] = _NOT_DRAWABLE if same_generator else _OTHER_GENERATOR
    groups = {"rejected": rejected, "viewports_refused": refused_sizes, "sessions_refused": refused_sessions, "stress_tests": stress}
    return groups, pictures


# --- building and writing --------------------------------------------------------


def build(dataset: Dataset) -> Iterator[tuple[str, bytes]]:
    """Every file of the gallery as (path inside the gallery folder, bytes):
    the pictures, the page, then the manifest."""
    views = [shown(record) for record in dataset.records]
    summary = coverage_summary(dataset)
    # The manifest's and the stress-test records' own shape is read from here on.
    try:
        apart, pictures = _apart(dataset)
        page = _page(dataset, views, summary, apart)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise SourceError([f"the manifest or a stress-test record is not as `data generate` writes it: {error!r}"]) from None
    hashes: dict[str, str] = {}

    def file(name: str, data: bytes) -> tuple[str, bytes]:
        hashes[name] = _sha256(data)
        return name, data

    for view in views:
        yield file(f"images/{view.id}.png", dataset.images[view.id])
    for name, data in pictures.items():
        yield file(name, data)
    yield file(PAGE_NAME, page.encode("utf-8"))

    drawable = [item for group in ("rejected", "viewports_refused") for item in apart[group]]
    manifest = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "dataset": {
            "name": dataset.config.name,
            "version": dataset.config.version,
            "manifest_sha256": dataset.manifest_sha256,
            "generator": dataset.manifest.get("generator"),
            "rendering_mode": dataset.manifest.get("rendering_mode"),
        },
        "page": PAGE_NAME,
        "counts": {
            "records": len(views),
            "rejected": len(apart["rejected"]),
            "viewports_refused": len(apart["viewports_refused"]),
            "sessions_refused": len(apart["sessions_refused"]),
            "stress_tests": len(apart["stress_tests"]),
            # Rejected states the runtime renderer could draw, of those listed.
            "rejected_states_drawn": sum(1 for item in drawable if item["image"]),
            "rejected_states_not_drawn": sum(1 for item in drawable if not item["image"]),
        },
        "labels": ["layout family", "visual preset", "design condition", "state"],
        "coverage_summary": summary,
        # Never among the records, and never a training target.
        "shown_apart": apart,
        "files": dict(sorted(hashes.items())),
    }
    yield MANIFEST_NAME, _json_bytes(manifest)


def write(dataset: Dataset, out: str | Path) -> dict[str, Any]:
    """Build the gallery into `out` and return its manifest. `out` never holds
    half a gallery; the same gallery again changes nothing; a different one
    raises `GalleryDiffers` and changes nothing."""
    try:
        return json.loads(generator.write_folder(build(dataset), out, keep=(MANIFEST_NAME,))[MANIFEST_NAME])
    except generator.FolderDiffers as differs:
        raise GalleryDiffers(f"{out} already holds a different gallery ({differs})") from None
    except generator.UnsafeName as unsafe:
        raise SourceError([f"an id or a file name in the dataset would be written outside the gallery: {unsafe}"]) from None


def to_text(manifest: Mapping[str, Any]) -> str:
    """The gallery's counts and its coverage summary, as the command prints them."""
    counts, summary = manifest["counts"], manifest["coverage_summary"]
    dataset = manifest["dataset"]
    lines = [
        f"Gallery of         {dataset['name']} version {dataset['version']}",
        f"Records shown      {counts['records']}, each labelled with {', '.join(manifest['labels'])}",
        f"Shown apart        {counts['rejected']} rejected, {counts['viewports_refused']} viewport sizes refused, "
        f"{counts['sessions_refused']} sessions not run, {counts['stress_tests']} stress tests",
        f"                   {counts['rejected_states_drawn']} rejected states drawn again, {counts['rejected_states_not_drawn']} without a picture",
        "Coverage summary   records (scripted sessions)",
    ]
    for dimension in DIMENSIONS:
        entry = summary["by"][dimension]
        lines.append(f"  {dimension}")
        for value, count in entry["values"].items():
            extra = f", {count['elements']} elements" if "elements" in count else ""
            lines.append(f"    {value:<24} {count['records']:>5} ({count['sessions']}{extra})")
        if entry["not_shown"]:
            lines.append(f"    not shown: {', '.join(entry['not_shown'])}")
    presets = list(next(iter(summary["layout_family_by_visual_preset"].values()), {}))
    lines.append("  layout family by visual preset")
    lines.append(f"    {'':<24} " + " ".join(f"{preset:>12}" for preset in presets))
    for family, row in summary["layout_family_by_visual_preset"].items():
        lines.append(f"    {family:<24} " + " ".join(f"{row[preset]['records']:>12}" for preset in presets))
    missing = summary["pairs_not_shown"]
    lines.append(f"  pairs not shown: {', '.join(f'{family} in {preset}' for family, preset in missing) if missing else 'none'}")
    return "\n".join(lines) + "\n"


# --- the page --------------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark; --page: #f2f2ef; --card: #ffffff; --ink: #1b1c1f; --soft: #5d6068; --line: #d5d6d2; --mark: #8a5a00; --bar: #c9cdd6; }
@media (prefers-color-scheme: dark) { :root { --page: #16171a; --card: #202226; --ink: #e8e8e4; --soft: #a3a6ad; --line: #383b41; --mark: #e0b25a; --bar: #454a55; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 14px/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 1680px; margin: 0 auto; padding: 24px 16px 96px; }
h1 { font-size: 26px; margin: 0 0 6px; } h2 { font-size: 22px; margin: 48px 0 6px; } h3 { font-size: 18px; margin: 40px 0 6px; } h4 { font-size: 15px; margin: 24px 0 4px; }
h5 { font-size: 13px; margin: 14px 0 8px; color: var(--soft); font-weight: 600; } [id] { scroll-margin-top: 64px; }
p { margin: 6px 0; max-width: 100ch; } code { font: 12px/1.4 ui-monospace, Menlo, monospace; } a { color: inherit; }
.soft, figcaption, .facts dt, th { color: var(--soft); }
nav { position: sticky; top: 0; z-index: 2; background: var(--page); border-bottom: 1px solid var(--line); padding: 8px 0; margin: 16px 0 0; display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; }
nav a { text-decoration: none; border-bottom: 1px solid var(--line); } nav select { font: inherit; max-width: 100%; } nav label { white-space: nowrap; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 2px 16px; margin: 12px 0; } .facts dd { margin: 0; overflow-wrap: anywhere; }
.tables { display: flex; flex-wrap: wrap; gap: 20px 32px; align-items: flex-start; } .scroll { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; } caption { text-align: left; font-weight: 600; padding-bottom: 4px; }
th, td { text-align: left; padding: 3px 12px 3px 0; border-bottom: 1px solid var(--line); vertical-align: top; } td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
td.bar { min-width: 120px; padding-right: 0; } td.bar i { display: block; height: 10px; margin-top: 5px; background: var(--bar); }
.none td, .warn { color: var(--mark); font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 4px 6px; margin: 6px 0; padding: 0; list-style: none; } .chips li { border: 1px solid var(--line); border-radius: 4px; padding: 0 6px; background: var(--card); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap: 14px; }
figure { margin: 0; background: var(--card); border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
figure img { display: block; width: 100%; height: auto; border-bottom: 1px solid var(--line); } figure a { display: block; }
figcaption { padding: 8px 10px 10px; font-size: 12px; overflow-wrap: anywhere; } figcaption b { color: var(--ink); font-weight: 600; }
figcaption dl { display: grid; grid-template-columns: max-content 1fr; gap: 1px 8px; margin: 4px 0 0; } figcaption dd { margin: 0; color: var(--ink); }
figcaption ul { margin: 4px 0 0; padding-left: 16px; color: var(--ink); }
.nopicture { aspect-ratio: 16 / 9; display: grid; place-items: center; padding: 16px; text-align: center; border-bottom: 1px solid var(--line); color: var(--soft); background: repeating-linear-gradient(45deg, transparent 0 10px, var(--line) 10px 11px); }
.apart figure { border-color: var(--mark); } .tag { display: inline-block; border: 1px solid var(--mark); color: var(--mark); border-radius: 4px; padding: 0 6px; font-size: 12px; font-weight: 600; }
[hidden] { display: none !important; }
#view { width: 100vw; height: 100vh; max-width: none; max-height: none; margin: 0; border: 0; padding: 0; background: #0d0d10; color: #eee; }
#view[open] { display: grid; grid-template-rows: 1fr auto; }
#view img { max-width: 100%; max-height: 100%; margin: auto; display: block; min-height: 0; } #view .pic { min-height: 0; display: grid; padding: 12px; }
#view p { margin: 0; padding: 10px 16px 14px; max-width: none; font-size: 13px; overflow-wrap: anywhere; } #view button { font: inherit; margin-right: 8px; }
"""

# The page works without this script: every picture is on it and every link
# opens its image. The script adds the three filters and a larger view.
_SCRIPT = """
(function () {
  var shots = Array.prototype.slice.call(document.querySelectorAll('#records figure'));
  var picks = Array.prototype.slice.call(document.querySelectorAll('nav select'));
  var tally = document.getElementById('tally');
  function apply() {
    var count = 0;
    shots.forEach(function (shot) {
      var keep = picks.every(function (pick) {
        if (!pick.value) return true;
        var have = shot.getAttribute('data-' + pick.name);
        return pick.name === 'states' ? (' ' + have + ' ').indexOf(' ' + pick.value + ' ') >= 0 : have === pick.value;
      });
      shot.hidden = !keep;
      if (keep) count += 1;
    });
    ['.session', '.preset', '.family'].forEach(function (group) {
      Array.prototype.forEach.call(document.querySelectorAll('#records ' + group), function (part) {
        part.hidden = !part.querySelector('figure:not([hidden])');
      });
    });
    tally.textContent = count + ' of ' + shots.length + ' records shown';
  }
  picks.forEach(function (pick) { pick.addEventListener('change', apply); });
  document.getElementById('filters').hidden = false;
  apply();

  var view = document.getElementById('view'), picture = view.querySelector('img'), words = view.querySelector('span'), at = null;
  if (!view.showModal) return;
  function all() { return Array.prototype.slice.call(document.querySelectorAll('figure:not([hidden])')).filter(function (f) { return f.querySelector('img'); }); }
  function show(figure) {
    at = figure;
    picture.src = figure.querySelector('img').getAttribute('src');
    picture.alt = figure.querySelector('img').alt;
    words.textContent = figure.querySelector('figcaption').innerText.replace(/\\s*\\n\\s*/g, '  ·  ');
    if (!view.open) view.showModal();
  }
  function move(by) { var list = all(), i = list.indexOf(at); if (i >= 0) show(list[(i + by + list.length) % list.length]); }
  document.addEventListener('click', function (event) {
    var link = event.target.closest ? event.target.closest('figure a') : null;
    if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey) { event.preventDefault(); show(link.closest('figure')); }
  });
  view.addEventListener('click', function (event) {
    var name = event.target.getAttribute('data-do');
    if (name === 'back') move(-1); else if (name === 'on') move(1); else view.close();
  });
  view.addEventListener('close', function () {
    var link = at && at.querySelector('a');
    picture.removeAttribute('src'); at = null;
    if (link) link.focus();
  });
  view.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowLeft') move(-1); else if (event.key === 'ArrowRight') move(1);
  });
})();
"""


def _page(dataset: Dataset, views: Sequence[Shown], summary: Mapping[str, Any], apart: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    config, manifest = dataset.config, dataset.manifest
    title = f"{config.name.capitalize()} dataset, version {config.version}: review gallery"
    counts = manifest.get("counts", {})
    generated = manifest.get("generator", {})
    facts = [
        ("Dataset", f"{config.name} version {config.version}, seed {config.seed}"),
        ("Records", f"{len(views)} from {summary['sessions']} scripted sessions, {counts.get('application_states', 'an unrecorded number of')} application states"),
        ("Drawn in", f"{manifest.get('rendering_mode', 'unrecorded')}, by the runtime renderer, at {config.scale:g} pixels per viewport unit"),
        ("Generator", f"{generated.get('name', 'unrecorded')}, version {generated.get('version', 'unrecorded')}"),
        ("Dataset manifest", f"SHA-256 {dataset.manifest_sha256}"),
        (
            "Shown apart",
            f"{len(apart['rejected'])} rejected states, {len(apart['viewports_refused'])} viewport sizes refused, "
            f"{len(apart['sessions_refused'])} sessions not run, {len(apart['stress_tests'])} stress tests",
        ),
    ]
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(title)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>{_e(title)}</h1>",
        "<p>Every dataset record of the dataset as its reference image, to be judged for visual coherence before anything is scaled. "
        "Each picture is labelled with its layout family, its visual preset, its design condition and its state. "
        "What the validators rejected is at the end, apart from the records. A picture opens larger when it is chosen.</p>",
        '<dl class="facts">' + "".join(f"<dt>{_e(name)}</dt><dd>{_e(value)}</dd>" for name, value in facts) + "</dl>",
        _navigation(config, summary),
        _coverage(summary),
        _records(config, views),
        _shown_apart(apart),
        '<dialog id="view" aria-label="A picture, larger"><div class="pic"><img alt=""></div>'
        '<p><button type="button" data-do="back">Previous</button><button type="button" data-do="on">Next</button>'
        '<button type="button" data-do="close">Close</button><span></span></p></dialog>',
        f"<script>{_SCRIPT}</script>",
        "</main></body></html>",
    ]
    return "\n".join(parts) + "\n"


def _navigation(config: generator.Config, summary: Mapping[str, Any]) -> str:
    def pick(name: str, label: str, values: Sequence[str]) -> str:
        options = "".join(f'<option value="{_e(value)}">{_e(value)}</option>' for value in values)
        return f'<label>{_e(label)} <select name="{name}"><option value="">every one</option>{options}</select></label>'

    links = '<a href="#coverage">Coverage summary</a> <a href="#records">Dataset records</a> <a href="#apart">Shown apart</a>'
    filters = (
        '<span id="filters" hidden>'
        + pick("family", "Layout family", list(summary["by"]["layout family"]["values"]))
        + " "
        + pick("preset", "Visual preset", list(summary["by"]["visual preset"]["values"]))
        + " "
        + pick("states", "Shows state", list(summary["by"]["element state"]["values"]))
        + ' <span id="tally" class="soft"></span></span>'
    )
    return f"<nav>{links} {filters}</nav>"


def _coverage(summary: Mapping[str, Any]) -> str:
    total = max(summary["records"], 1)
    tables = []
    for dimension in DIMENSIONS:
        entry = summary["by"][dimension]
        elements = dimension == "element state"
        rows = []
        for value, count in entry["values"].items():
            cells = f'<td>{_e(value)}</td><td class="n">{count["records"]}</td><td class="n">{count["sessions"]}</td>'
            if elements:
                cells += f'<td class="n">{count["elements"]}</td>'
            cells += f'<td class="bar"><i style="width:{100 * count["records"] / total:.1f}%"></i></td>'
            rows.append(f"<tr{'' if count['records'] else ' class=\"none\"'}>{cells}</tr>")
        head = '<th scope="col">Value</th><th scope="col" class="n">Records</th><th scope="col" class="n">Sessions</th>' + ('<th scope="col" class="n">Elements</th>' if elements else "") + '<th scope="col"></th>'
        missing = f'<p class="warn">Not shown: {_e(", ".join(entry["not_shown"]))}</p>' if entry["not_shown"] else ""
        tables.append(
            f'<div class="scroll"><table><caption>{_e(dimension.capitalize())}</caption><tr>{head}</tr>{"".join(rows)}</table>{missing}</div>'
        )

    cross = summary["layout_family_by_visual_preset"]
    presets = list(next(iter(cross.values()), {}))
    head = '<th scope="col">Layout family</th>' + "".join(f'<th scope="col" class="n">{_e(preset)}</th>' for preset in presets)
    rows = "".join(
        f"<tr><td>{_e(family)}</td>"
        + "".join(f'<td class="n{"" if row[preset]["records"] else " warn"}">{row[preset]["records"]}</td>' for preset in presets)
        + "</tr>"
        for family, row in cross.items()
    )
    missing = summary["pairs_not_shown"]
    pairs = (
        f'<p class="warn">Pairs not shown: {_e(", ".join(f"{family} in {preset}" for family, preset in missing))}</p>'
        if missing
        else "<p>Every layout family is shown in every visual preset.</p>"
    )
    return (
        '<section id="coverage"><h2>Coverage summary</h2>'
        f"<p>{summary['records']} records from {summary['sessions']} scripted sessions. A record counts once under each value it shows, "
        "so under every element state one of its bound elements is in; Elements is the number of bound elements in that state. "
        "A value the dataset configuration declares and no record shows has a count of zero and is named under its table.</p>"
        f'<div class="tables">{"".join(tables)}</div>'
        f'<h3>Records by layout family and visual preset</h3><div class="scroll"><table><tr>{head}</tr>{rows}</table></div>{pairs}</section>'
    )


def _records(config: generator.Config, views: Sequence[Shown]) -> str:
    families = [*config.layout_families, *sorted({view.layout_family for view in views} - set(config.layout_families))]
    presets = [*config.visual_presets, *sorted({view.visual_preset for view in views} - set(config.visual_presets))]
    out = ['<section id="records"><h2>Dataset records</h2>']
    for name in families:
        mine = [view for view in views if view.layout_family == name]
        if not mine:
            continue
        family = config.layout.families.get(name)
        condition = "".join(f"<li>{_e(_factor(factor))} <b>{_e(value)}</b></li>" for factor, value in mine[0].design_condition.items())
        out.append(f'<section class="family"><h3 id="family-{_e(name)}">{_e(family.title if family else name)} <code>{_e(name)}</code></h3>')
        if family:
            out.append(f"<p>{_e(family.summary)}</p>")
        out.append(f'<ul class="chips">{condition}</ul>')
        for preset in presets:
            in_preset = [view for view in mine if view.visual_preset == preset]
            if not in_preset:
                continue
            out.append(f'<section class="preset"><h4>{_e(name)} in {_e(preset)}</h4>')
            for session in dict.fromkeys(view.session for view in in_preset):
                frames = [view for view in in_preset if view.session == session]
                first = frames[0]
                out.append(
                    f'<section class="session"><h5>Scripted session {_e(session)}: scenario {_e(first.scenario)}, viewport {_e(first.viewport)}, '
                    f"content length {_e(first.content_length)}, {len(frames)} records</h5><div class=\"grid\">"
                )
                out += [_figure(view) for view in frames]
                out.append("</div></section>")
            out.append("</section>")
        out.append("</section>")
    out.append("</section>")
    return "\n".join(out)


def _figure(view: Shown) -> str:
    condition = ", ".join(f"{_SHORT.get(factor, _factor(factor))} {value}" for factor, value in view.design_condition.items())
    states = " ".join(state for state in documents_adapter.STATES if view.states.get(state))
    alt = f"{view.id}: {view.layout_family} in {view.visual_preset}, {view.state}"
    return (
        f'<figure id="record-{_e(view.id)}" data-family="{_e(view.layout_family)}" data-preset="{_e(view.visual_preset)}" data-states="{_e(states)}">'
        f'<a href="images/{_e(view.id)}.png"><img loading="lazy" src="images/{_e(view.id)}.png" width="{view.width}" height="{view.height}" alt="{_e(alt)}"></a>'
        f"<figcaption><b>{_e(view.id)}</b> {_e(view.moment)}<dl>"
        f'<dt>Layout family</dt><dd data-label="layout family">{_e(view.layout_family)}</dd>'
        f'<dt>Visual preset</dt><dd data-label="visual preset">{_e(view.visual_preset)}</dd>'
        f'<dt>Design condition</dt><dd data-label="design condition">{_e(condition)}</dd>'
        f'<dt>State</dt><dd data-label="state">{_e(view.state)}</dd>'
        "</dl></figcaption></figure>"
    )


def _shown_apart(apart: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    out = [
        '<section id="apart" class="apart"><h2>Shown apart: what the validators rejected</h2>',
        "<p>Nothing in this part is a dataset record, and nothing in it is a training target. "
        "A rejected state is not in the dataset: its picture is the scene made again from the dataset's configuration and drawn by the runtime renderer. "
        "A state scene validation refuses cannot be drawn, and has its reasons without a picture.</p>",
    ]

    def group(anchor: str, heading: str, said: str, items: Sequence[Mapping[str, Any]], empty: str) -> None:
        out.append(f'<section id="{anchor}"><h3>{_e(heading)} ({len(items)})</h3><p>{_e(said)}</p>')
        if items:
            out.append('<div class="grid">' + "\n".join(_apart_figure(item, anchor) for item in items) + "</div>")
        else:
            out.append(f'<p class="soft">{_e(empty)}</p>')
        out.append("</section>")

    group(
        "rejected", "Rejected states",
        "States a scripted session reached whose true scene a validator rejected. None was written as a dataset record.",
        apart["rejected"], "No state was rejected.",
    )  # fmt: skip
    group(
        "viewports-refused", "Viewport sizes refused",
        "Viewport sizes a scripted session was offered and not given, each with the first state the validators rejected there. "
        "The session ran in another size, in which every one of its states passes.",
        apart["viewports_refused"], "No session was refused a viewport size.",
    )  # fmt: skip
    out.append(f'<section id="sessions-refused"><h3>Scripted sessions not run ({len(apart["sessions_refused"])})</h3>')
    if apart["sessions_refused"]:
        rows = "".join(
            f"<tr><td>{_e(item['id'])}</td><td>{_e(item['layout_family'])}</td><td>{_e(item['visual_preset'])}</td><td>{_e(item['reason'])}</td></tr>"
            for item in apart["sessions_refused"]
        )
        out.append(
            "<p>Sessions whose design fits none of the viewport sizes. Each size it was refused is among the viewport sizes refused.</p>"
            f'<div class="scroll"><table><tr><th scope="col">Session</th><th scope="col">Layout family</th><th scope="col">Visual preset</th><th scope="col">Reason</th></tr>{rows}</table></div>'
        )
    else:
        out.append('<p class="soft">Every session was given a viewport size.</p>')
    out.append("</section>")
    group(
        "stress-tests", "Stress-test set",
        "Deliberately difficult or broken examples, each rejected for the reasons it states. Never a training target.",
        apart["stress_tests"], "The dataset has no stress-test set.",
    )  # fmt: skip
    out.append("</section>")
    return "\n".join(out)


def _apart_figure(item: Mapping[str, Any], group: str) -> str:
    image = item["image"]
    if image is None:
        picture = f'<div class="nopicture">No picture: {_e(item["not_drawn"])}.</div>'
    else:
        alt = f"{item['id']}: rejected, {item['layout_family']} in {item['visual_preset']}"
        picture = (
            f'<a href="{_e(image["file"])}"><img loading="lazy" src="{_e(image["file"])}" width="{image["width"]}" height="{image["height"]}" alt="{_e(alt)}"></a>'
        )
    codes = ", ".join(sorted({problem["code"] for problem in item["problems"]}))
    reasons = "".join(
        f"<li><code>{_e(problem['code'])}</code> ({_e(problem['validator'])}{', ' + _e(problem['element']) if problem.get('element') else ''}): {_e(problem['detail'])}</li>"
        for problem in item["problems"]
    )
    rows = [
        ("Layout family", item["layout_family"]),
        ("Visual preset", item["visual_preset"]),
        ("Viewport", item["viewport"] + (f"; the session was given {item['given']}" if item.get("given") else "")),
        ("Rejected for", codes),
    ]
    if group == "stress-tests":
        broken = item["broken_by"]
        rows.insert(0, ("Why", item["why"]))
        rows.insert(1, ("Kind", "difficult: the reference layout's own scene" if broken is None else f"broken: {broken['kind']} of {broken['element']}"))
        tag = '<span class="tag">stress test: never a training target</span>'
    else:
        tag = '<span class="tag">rejected: not a dataset record</span>'
    facts = "".join(f"<dt>{_e(name)}</dt><dd>{_e(value)}</dd>" for name, value in rows)
    return (
        f'<figure data-apart="{group}" data-id="{_e(item["id"])}" data-codes="{_e(codes)}">{picture}'
        f"<figcaption><b>{_e(item['id'])}</b> {tag}<dl>{facts}</dl><ul>{reasons}</ul></figcaption></figure>"
    )


# --- small things ----------------------------------------------------------------


# A design factor as a caption names it, where its full name is long.
_SHORT = {"navigation_position": "navigation", "panel_arrangement": "panels", "notification_location": "notification"}


def _factor(name: str) -> str:
    return name.replace("_", " ")


def _viewport_name(viewport: Mapping[str, float]) -> str:
    return f"{viewport['width']:g} by {viewport['height']:g}"


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
