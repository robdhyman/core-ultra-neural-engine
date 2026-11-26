"""Command-line tests for layout families, coherent variation, the validators
and the stress-test set (test seam 2).

`data generate` is run for real on the committed `configs/data/families-v1.json`
and the tests assert on the manifest, the records and the stress-test set it
writes.

The judges are independent of the generator. Which factor values a scene was
drawn in is read off its boxes here; whether text fits is measured by Qt's own
font metrics; whether a control can be reached is asked of the runtime
renderer's hit test; and each stress test is judged again from what its own
record holds.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from PySide6.QtGui import QFont, QFontMetricsF

from core_ultra import design, documents_adapter, generator, layout_family, reference_layout, runtime_renderer, typography, validators
from core_ultra import scene as scene_schema
from core_ultra.kernel import Kernel
from core_ultra.scene_session import Conditioning, RenderingMode, SceneSession

REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = REPO_ROOT / "configs" / "data" / "families-v1.json"
COMMITTED_MANIFEST = REPO_ROOT / "artifacts" / "datasets" / "families-v1" / "manifest.json"
LAYOUT_V2 = REPO_ROOT / "configs" / "layout" / "v2.json"
DESIGN_CONFIG = REPO_ROOT / "configs" / "design" / "v1.json"

FACTORS = ("navigation_position", "panel_arrangement", "density", "spacing", "notification_location")
DENSITY = {0.85: "compact", 1.0: "preset", 1.15: "roomy"}
SPACING = {0.75: "tight", 1.0: "preset", 1.25: "loose"}
STATES = {"default", "hover", "pressed", "focused", "disabled"}


def run_cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "core_ultra", *map(str, args)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=600
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_of(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def families_config(**changes) -> dict:
    config = {**json.loads(FAMILIES.read_text()), **changes}
    return {name: value for name, value in config.items() if value is not None}


def write_config(folder: Path, config: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    return path


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("layout-families")


@pytest.fixture(scope="module")
def run(folder) -> dict:
    """One real run of `data generate` on the families configuration."""
    out = folder / "families"
    result = run_cli("data", "generate", "--config", FAMILIES, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    records = [json.loads((out / entry["file"]).read_text()) for entry in manifest["records"]]
    stress = [json.loads((out / entry["file"]).read_text()) for entry in manifest["stress_tests"]["records"]]
    return {"result": result, "out": out, "manifest": manifest, "records": records, "stress": stress}


@pytest.fixture(scope="module")
def manifest(run) -> dict:
    return run["manifest"]


@pytest.fixture(scope="module")
def records(run) -> list[dict]:
    return run["records"]


@pytest.fixture(scope="module")
def stress(run) -> list[dict]:
    return run["stress"]


def bound_elements_of(holder: dict) -> tuple[documents_adapter.BoundElement, ...]:
    return tuple(
        documents_adapter.BoundElement(
            identity=item["identity"],
            role=item["role"],
            text=item["text"],
            binding=item["binding"],
            state=item["state"],
            relationships=tuple(item["relationships"]),
        )
        for item in holder["application"]["bound_elements"]
    )


def viewport_of(record: dict) -> tuple[float, float]:
    viewport = record["target"]["scene"]["viewport"]
    return (viewport["width"], viewport["height"])


def scene_of(record: dict) -> scene_schema.Scene:
    return scene_schema.validate(record["target"]["scene"], bound_elements_of(record), viewport_of(record))


def box(scene: dict, name: str) -> dict:
    """The box of a structural element by its id, or of a bound element by its identity."""
    for element in scene["elements"]:
        if element["id"] == name or element.get("bound", {}).get("identity") == name:
            return element["box"]
    raise KeyError(name)


def has(scene: dict, identity: str) -> bool:
    return any(element.get("bound", {}).get("identity") == identity for element in scene["elements"])


def nearest(value: float, names: dict[float, str]) -> str:
    factor = min(names, key=lambda known: abs(known - value))
    assert abs(factor - value) < 1e-6, (value, names)
    return names[factor]


def condition_read_off(record: dict) -> dict[str, str]:
    """The factor values a scene was drawn in, read off its boxes and the
    visual preset's token values, with no knowledge of the reference layout."""
    scene = record["target"]["scene"]
    tokens = record["inputs"]["visual_preset"]
    width, height = viewport_of(record)
    toolbar, listed, editor = box(scene, "s.toolbar"), box(scene, "s.list"), box(scene, "s.editor")
    create, sort = box(scene, "documents.create"), box(scene, "toolbar.sort")

    if toolbar["width"] == width and toolbar["y"] == 0:
        navigation = "top"
    elif toolbar["width"] == width and toolbar["y"] + toolbar["height"] == pytest.approx(height):
        navigation = "bottom"
    else:
        assert toolbar["x"] == 0 and toolbar["height"] == height and toolbar["width"] < width / 2
        navigation = "left"

    if listed["y"] == editor["y"]:
        arrangement = "list-left" if listed["x"] < editor["x"] else "list-right"
    else:
        assert listed["x"] == editor["x"] and listed["y"] + listed["height"] < editor["y"]
        arrangement = "list-top"

    if navigation == "left":
        gap = sort["y"] - create["y"] - create["height"]
    else:
        gap = sort["x"] - create["x"] - create["width"]
    found = {
        "navigation_position": navigation,
        "panel_arrangement": arrangement,
        "density": nearest(create["height"] / tokens["density"]["control-height"], DENSITY),
        "spacing": nearest(gap / tokens["spacing"]["gap"], SPACING),
    }
    if has(scene, "notification"):
        note = box(scene, "notification")
        left = toolbar["width"] if navigation == "left" else 0.0
        centre = note["x"] + note["width"] / 2
        middle = (left + width) / 2
        if centre == pytest.approx(middle):
            found["notification_location"] = "bottom-centre"
        else:
            found["notification_location"] = "bottom-left" if centre < middle else "bottom-right"
    return found


def a_workspace() -> Kernel:
    """Three documents, the second open and just saved, and so a notification."""
    kernel = Kernel()
    for title in ("Plan notes", "Résumé", "Budget garden"):
        kernel.execute({"command": "create"}, title)
    kernel.execute({"command": "open", "document": 2})
    kernel.execute({"command": "edit", "document": 2}, "Première ligne: déjà vu.\nZweite Zeile: Größe.")
    kernel.execute({"command": "save"})
    assert kernel.state().notification
    return kernel


# --- several structurally different layout families ------------------------------


def test_the_layout_configuration_declares_what_the_reference_layout_draws_and_no_more():
    raw = json.loads(LAYOUT_V2.read_text())
    assert set(raw["factors"]) == set(FACTORS)
    for factor, values in raw["factors"].items():
        assert set(values) == set(reference_layout.DRAWN[factor]), factor
        assert len(values) >= 3, factor


def test_the_families_are_different_structures_and_each_value_is_in_at_least_two():
    raw = json.loads(LAYOUT_V2.read_text())
    families = {name: entry["design_condition"] for name, entry in raw["families"].items()}
    assert len(families) >= 6
    # No two families share both where the navigation is and how the panels are arranged.
    structures = [(c["navigation_position"], c["panel_arrangement"]) for c in families.values()]
    assert len(set(structures)) == len(structures)
    # Holding one family out leaves every factor value in some other family.
    for factor in FACTORS:
        used = Counter(condition[factor] for condition in families.values())
        assert set(used) == set(raw["factors"][factor]), factor
        assert min(used.values()) >= 2, (factor, used)
    assert json.loads(FAMILIES.read_text())["layout_families"] == list(families)
    # The declared combinations are coherent: taller elements never come with
    # closer distances, nor shorter elements with wider ones.
    pairs = {(condition["density"], condition["spacing"]) for condition in families.values()}
    assert not pairs & {("roomy", "tight"), ("compact", "loose")}
    assert len(pairs) >= 5


def test_every_record_is_drawn_as_the_factor_values_of_its_family(records):
    raw = json.loads(LAYOUT_V2.read_text())["families"]
    located = Counter()
    for record in records:
        declared = raw[record["diagnostics"]["layout_family"]]["design_condition"]
        assert record["inputs"]["design_condition"] == declared
        found = condition_read_off(record)
        assert found == {factor: declared[factor] for factor in found}, record["id"]
        located[found.get("notification_location")] += 1
    assert {"bottom-right", "bottom-left", "bottom-centre"} <= set(located)


def test_one_state_is_a_different_arrangement_in_every_family():
    layout = layout_family.load(LAYOUT_V2)
    kernel = a_workspace()
    session = SceneSession(layout)
    drawn = {}
    for name, family in layout.families.items():
        frame = session.frame(
            kernel.state(), Conditioning(1280, 720, design_condition=family.design_condition.to_json()), RenderingMode.A_REFERENCE
        )
        scene = frame.scene.to_json()
        drawn[name] = (
            json.dumps([box(scene, part) for part in ("s.toolbar", "s.list", "s.editor", "notification")]),
            frame.image.tobytes(),
        )
        # The same bound elements, each still hit at its own centre.
        for element in frame.scene.bound_elements:
            assert frame.hit_test(element.x + element.width / 2, element.y + element.height / 2) is element.bound
    kernel.close()
    assert len({boxes for boxes, _ in drawn.values()}) == len(drawn) == 8
    assert len({image for _, image in drawn.values()}) == 8


def test_a_scene_session_without_the_layout_refuses_a_family_it_does_not_declare():
    family = layout_family.load(LAYOUT_V2).family("left-rail-list-top")
    kernel = Kernel()
    with pytest.raises(layout_family.LayoutError):
        SceneSession().frame(kernel.state(), Conditioning(1280, 720, design_condition=family.design_condition.to_json()), "A, Reference")
    kernel.close()


# --- validity is kept apart from preference ---------------------------------------


def test_every_combination_of_factor_values_is_drawn_and_passes_the_validators():
    """No navigation position, panel arrangement, density, spacing or
    notification location is rejected for what it is: all 243 combinations, in
    every visual preset, pass every validator when the viewport has room."""
    kernel = a_workspace()
    bound = documents_adapter.describe(kernel.state())
    kernel.close()
    presets = design.load().presets.values()
    combinations = list(itertools.product(*(reference_layout.DRAWN[factor] for factor in FACTORS)))
    assert len(combinations) == 243
    for values in combinations:
        condition = layout_family.DesignCondition(**dict(zip(FACTORS, values)))
        for preset in presets:
            candidate = reference_layout.write_scene(bound, (1440, 900), preset, condition)
            scene, found = validators.judge(candidate, bound, (1440, 900), preset)
            assert scene is not None and found == (), (values, preset.name, [str(finding) for finding in found])


def test_the_validators_are_given_no_design_condition_and_load_no_design_preference():
    code = (
        "import sys, core_ultra.validators\n"
        "loaded = [name for name in ('core_ultra.reference_layout', 'core_ultra.layout_family', 'core_ultra.design', 'core_ultra.generator') if name in sys.modules]\n"
        "sys.exit(', '.join(loaded) or 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    # Nothing in the module names a layout family, and no validator is told
    # which factor values a scene was drawn in.
    source = (REPO_ROOT / "src" / "core_ultra" / "validators.py").read_text()
    for name in json.loads(LAYOUT_V2.read_text())["families"]:
        assert name not in source
    for preset in json.loads(DESIGN_CONFIG.read_text())["presets"]:
        assert preset not in source
    assert "design_condition" not in source and "DesignCondition" not in source


def test_text_that_reaches_the_edge_of_its_box_without_crossing_it_is_not_rejected(sound):
    """How much room is left around text is a preference. Only text that
    runs past its box is clipped."""
    preset = design.load().preset(sound["diagnostics"]["visual_preset"])
    bound, viewport = bound_elements_of(sound), viewport_of(sound)
    title = the(sound["target"]["scene"], "editor.title")
    wide = width_by_qt(title["bound"]["text"], title["style"]["type_size"], title["style"]["type_weight"])
    start = (title["box"]["height"] - typography.line_height(title["style"]["type_size"], title["style"]["type_weight"])) / 2

    def findings_at_width(width: float) -> list[str]:
        scene = copy.deepcopy(sound["target"]["scene"])
        the(scene, "editor.title")["box"]["width"] = width
        return [finding.code for finding in validators.judge(scene, bound, viewport, preset)[1]]

    assert start > 2
    # The text ends half a unit inside the box: closer to the right edge than to the left.
    assert findings_at_width(start + wide + 0.5) == []
    assert findings_at_width(start + wide - 0.5) == ["text_overflows"]


def test_how_elements_are_grouped_into_containers_is_not_judged(sound):
    """Save and Undo in a container of their own, inside the toolbar's place:
    another grouping of the same part of the workspace, and still valid."""
    preset = design.load().preset(sound["diagnostics"]["visual_preset"])
    scene = copy.deepcopy(sound["target"]["scene"])
    save, undo, toolbar = the(scene, "toolbar.save"), the(scene, "toolbar.undo"), the(scene, "s.toolbar")
    group = {
        **copy.deepcopy(toolbar),
        "id": "s.toolbar.trailing",
        "parent": "s.root",
        "box": {
            "x": save["box"]["x"], "y": toolbar["box"]["y"],
            "width": undo["box"]["x"] + undo["box"]["width"] - save["box"]["x"], "height": toolbar["box"]["height"],
        },
    }  # fmt: skip
    toolbar["box"]["width"] = save["box"]["x"] - toolbar["box"]["x"]
    scene["elements"].insert(scene["elements"].index(the(scene, "s.divider")), group)
    save["parent"] = undo["parent"] = "s.toolbar.trailing"
    validated, found = validators.judge(scene, bound_elements_of(sound), viewport_of(sound), preset)
    assert validated is not None and found == (), [str(finding) for finding in found]
    assert {element.parent for element in validated.bound_elements if element.bound.identity.startswith("toolbar.")} == {"s.toolbar", "s.toolbar.trailing"}


# --- variation -----------------------------------------------------------------------


def test_the_records_vary_in_structure_content_and_appearance(records, manifest):
    conditions = [record["inputs"]["design_condition"] for record in records]
    scenes = [record["target"]["scene"] for record in records]

    def rows(scene: dict) -> list[dict]:
        return [e for e in scene["elements"] if e.get("bound", {}).get("role") == "list-item"]

    # Composition, grouping, navigation placement, panel arrangement, density, spacing.
    for factor in FACTORS:
        assert len({condition[factor] for condition in conditions}) == 3, factor
    # Grouping and alignment: in a rail the controls are stretched to one width
    # and stacked; in a bar each is as wide as its text and they sit in a row.
    stretched = {box(s, "documents.create")["width"] == box(s, "toolbar.sort")["width"] for s in scenes}
    assert stretched == {True, False}
    stacked = {box(s, "toolbar.save")["x"] == box(s, "toolbar.undo")["x"] for s in scenes}
    assert stacked == {True, False}
    for scene in scenes:
        if box(scene, "toolbar.save")["x"] == box(scene, "toolbar.undo")["x"]:
            rail, margin = box(scene, "s.toolbar")["width"], box(scene, "documents.create")["x"]
            for control in ("documents.create", "toolbar.sort", "toolbar.filter", "toolbar.save", "toolbar.undo"):
                assert box(scene, control)["width"] == pytest.approx(rail - 2 * margin), control
    # A list is one column, or a grid with several rows side by side.
    assert any(len({row["box"]["y"] for row in rows(s)}) < len(rows(s)) for s in scenes)
    assert any(len({row["box"]["y"] for row in rows(s)}) == len(rows(s)) > 1 for s in scenes)

    # Element count and content length.
    assert {len(rows(scene)) for scene in scenes} >= set(range(0, 10))
    titles = [row["bound"]["text"] for scene in scenes for row in rows(scene)]
    assert {len(title.split()) for title in titles} >= {1, 2, 3, 4}
    bodies = [e["bound"]["text"] for s in scenes for e in s["elements"] if e.get("bound", {}).get("identity") == "editor.body"]
    assert min(len(body.split("\n")) for body in bodies if body) == 1 and max(len(body.split("\n")) for body in bodies) >= 6
    assert {session["content_length"] for session in manifest["sessions"]} == {"brief", "medium", "long"}

    # Viewport size, in more than one proportion.
    sizes = {(scene["viewport"]["width"], scene["viewport"]["height"]) for scene in scenes}
    assert len(sizes) == 5 and len({round(width / height, 2) for width, height in sizes}) >= 2

    # Element state.
    assert {e["bound"]["state"] for s in scenes for e in s["elements"] if "bound" in e} == STATES

    # Type, colour, radius and elevation: each visual preset is another set.
    looks = defaultdict(set)
    for record in records:
        scene = record["target"]["scene"]
        button = next(e for e in scene["elements"] if e.get("bound", {}).get("identity") == "documents.create")
        if button["bound"]["state"] != "default":
            continue
        create = button["style"]
        panel = next(e for e in scene["elements"] if e["id"] == "s.list")["style"]
        looks[record["diagnostics"]["visual_preset"]].add(
            json.dumps([create["fill"], create["type_size"], create["type_weight"], create["corner_radius"], panel["elevation"]])
        )
    assert len(looks) == 4 and len(set.union(*looks.values())) == 4
    for field in (1, 2, 3, 4):
        assert len({json.loads(next(iter(look)))[field] for look in looks.values()}) >= 2, field


def test_the_coverage_validator_finds_every_declared_value_in_the_records(run, manifest, records):
    coverage = manifest["coverage"]
    assert coverage["gaps"] == [] and manifest["counts"]["coverage_gaps"] == 0
    config = json.loads(FAMILIES.read_text())
    dimensions = coverage["dimensions"]
    assert set(dimensions["layout family"]) == set(config["layout_families"])
    assert set(dimensions["visual preset"]) == set(config["visual_presets"])
    assert set(dimensions["viewport"]) == {f"{width} by {height}" for width, height in config["viewports"]}
    assert set(dimensions["scenario"]) == set(config["scenarios"])
    assert set(dimensions["content length"]) == set(config["content_lengths"])
    assert set(dimensions["element state"]) == STATES and set(dimensions["role"]) == set(documents_adapter.ROLES)
    for factor in FACTORS:
        assert len(dimensions[factor.replace("_", " ")]) == 3
    assert all(count > 0 for values in dimensions.values() for count in values.values())
    # Counted here from the records themselves.
    assert dimensions["layout family"] == dict(Counter(r["diagnostics"]["layout_family"] for r in records))
    assert dimensions["visual preset"] == dict(Counter(r["diagnostics"]["visual_preset"] for r in records))
    assert "Coverage gaps      0" in run["result"].stdout


def test_what_the_records_do_not_cover_is_recorded_as_a_gap(folder):
    # One session cannot show four visual presets or eight families.
    config = write_config(folder / "gaps", families_config(scenarios={"one-document": ["create"]}, sessions_per_scenario=1, stress_tests=None))
    out = folder / "gaps" / "out"
    result = run_cli("data", "generate", "--config", config, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    gaps = manifest["coverage"]["gaps"]
    assert all(gap["validator"] == "coverage" and gap["code"] == "not_covered" and gap["detail"] for gap in gaps)
    missing = defaultdict(set)
    for gap in gaps:
        missing[gap["dimension"]].add(gap["value"])
    (session,) = manifest["sessions"]
    assert missing["visual preset"] == set(families_config()["visual_presets"]) - {session["visual_preset"]}
    assert missing["layout family"] == set(families_config()["layout_families"]) - {session["layout_family"]}
    assert missing["editor"] == {"document open"} and missing["element state"] == {"focused"}
    assert manifest["counts"]["coverage_gaps"] == len(gaps) > 10
    assert f"Coverage gaps      {len(gaps)}" in result.stdout
    assert f"no accepted record shows visual preset {sorted(missing['visual preset'])[0]}" in result.stdout


# --- coherent combinations -------------------------------------------------------------


def test_a_design_is_sampled_whole_and_never_token_by_token(records, manifest):
    raw_layout = json.loads(LAYOUT_V2.read_text())
    declared_conditions = {json.dumps(f["design_condition"], sort_keys=True) for f in raw_layout["families"].values()}
    raw_design = json.loads(DESIGN_CONFIG.read_text())["presets"]

    # Of 243 possible combinations of factor values, only the declared families are sampled.
    sampled = {json.dumps(record["inputs"]["design_condition"], sort_keys=True) for record in records}
    assert sampled == declared_conditions and len(sampled) == 8

    # Every record's style tokens are one declared visual preset, whole.
    token_sets = {json.dumps(record["inputs"]["visual_preset"], sort_keys=True) for record in records}
    assert len(token_sets) == len(raw_design) == 4
    for record in records:
        tokens, declared = record["inputs"]["visual_preset"], raw_design[record["diagnostics"]["visual_preset"]]
        for group in ("spacing", "dimensions", "borders", "radii", "elevation", "density", "opacity"):
            assert tokens[group] == {name: float(value) for name, value in declared[group].items()}, (record["id"], group)
        assert tokens["type"] == {name: [float(v["size"]), float(v["weight"])] for name, v in declared["type"].items()}

    # A session is one application in one design.
    by_session = defaultdict(list)
    for record in records:
        by_session[record["diagnostics"]["related"]["session"]].append(record)
    for session in by_session.values():
        assert len({json.dumps([r["inputs"]["design_condition"], r["inputs"]["visual_preset"], r["inputs"]["viewport"]], sort_keys=True) for r in session}) == 1


def test_density_and_spacing_each_scale_their_whole_group_of_tokens_by_one_factor(records):
    seen = set()
    for record in records:
        scene, tokens = record["target"]["scene"], record["inputs"]["visual_preset"]
        if not (has(scene, "editor.title") and has(scene, "notification") and has(scene, "document:1")):
            continue
        heights = tokens["density"]
        ratios = {
            box(scene, "documents.create")["height"] / heights["control-height"],
            box(scene, "toolbar.filter")["height"] / heights["control-height"],
            box(scene, "document:1")["height"] / heights["row-height"],
            box(scene, "editor.title")["height"] / heights["title-height"],
            box(scene, "notification")["height"] / heights["notification-height"],
        }
        (density,) = {nearest(ratio, DENSITY) for ratio in ratios}
        assert density == record["inputs"]["design_condition"]["density"]

        # Two distances: the editor's padding and the gap under the title field.
        editor, title, revision = box(scene, "s.editor"), box(scene, "editor.title"), box(scene, "editor.revision")
        distances = {
            (title["x"] - editor["x"]) / tokens["spacing"]["editor-padding"],
            (revision["y"] - title["y"] - title["height"]) / tokens["spacing"]["gap"],
        }
        (spacing,) = {nearest(ratio, SPACING) for ratio in distances}
        assert spacing == record["inputs"]["design_condition"]["spacing"]
        seen.add((density, spacing))
    assert {density for density, _ in seen} == set(DENSITY.values()) and {spacing for _, spacing in seen} == set(SPACING.values())


def test_the_sessions_cover_families_presets_sizes_and_lengths_evenly(manifest):
    sessions = manifest["sessions"]
    assert len(sessions) == 16 and manifest["counts"]["sessions_refused"] == 0 and manifest["sessions_refused"] == []
    assert set(Counter(s["layout_family"] for s in sessions).values()) == {2}
    assert set(Counter(s["visual_preset"] for s in sessions).values()) == {4}
    assert set(Counter(s["content_length"] for s in sessions).values()) <= {5, 6}
    sizes = Counter((s["viewport"]["width"], s["viewport"]["height"]) for s in sessions)
    assert len(sizes) == 5 and max(sizes.values()) - min(sizes.values()) <= 1
    # A family meets a different visual preset each time it comes round.
    met = defaultdict(set)
    for session in sessions:
        met[session["layout_family"]].add(session["visual_preset"])
    assert all(len(presets) == 2 for presets in met.values())


def test_a_viewport_size_is_given_only_where_every_state_of_the_session_fits(manifest, records):
    """The sizes a session was refused are recorded with the reason, and the
    reason is found again here: the state named, laid out at that size, is
    rejected for those codes; at the size the session was given, it passes."""
    assert manifest["viewport_choice"] == "fitting"
    by_id = {record["id"]: record for record in records}
    layout, presets = layout_family.load(LAYOUT_V2), design.load().presets
    refusals = 0
    for session in manifest["sessions"]:
        for refusal in session["viewports_refused"]:
            refusals += 1
            record = by_id[f"{session['id']}.{refusal['moment']:03d}"]
            bound, preset = bound_elements_of(record), presets[session["visual_preset"]]
            condition = layout.family(session["layout_family"]).design_condition
            size = (refusal["viewport"]["width"], refusal["viewport"]["height"])
            assert size != viewport_of(record)
            _, found = validators.judge(reference_layout.write_scene(bound, size, preset, condition), bound, size, preset)
            assert sorted({finding.code for finding in found}) == refusal["codes"] != []
            # The refusal says which element and why, as a rejection does.
            assert refusal["problems"] == [finding.to_json() for finding in found]
            given = reference_layout.write_scene(bound, viewport_of(record), preset, condition)
            assert validators.judge(given, bound, viewport_of(record), preset)[1] == ()
    assert refusals >= 1


def test_sessions_whose_design_fits_no_viewport_size_are_not_run_and_say_why(folder):
    config = write_config(folder / "no-fit", families_config(viewports=[[320, 200]], stress_tests=None))
    out = folder / "no-fit" / "out"
    result = run_cli("data", "generate", "--config", config, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["counts"]["sessions"] == 0 and manifest["counts"]["records"] == 0 and manifest["records"] == []
    assert manifest["counts"]["sessions_refused"] == len(manifest["sessions_refused"]) == 16
    for session in manifest["sessions_refused"]:
        assert session["reason"] == "no_viewport_fits" and session["viewport"] is None
        (refusal,) = session["viewports_refused"]
        assert refusal["viewport"] == {"width": 320.0, "height": 200.0} and refusal["codes"]
        assert all(set(problem) == {"validator", "code", "element", "detail"} and problem["detail"] for problem in refusal["problems"])
        assert sorted({problem["code"] for problem in refusal["problems"]}) == refusal["codes"]
    assert "Sessions not run   16 (no viewport size fits)" in result.stdout
    assert manifest["counts"]["coverage_gaps"] > 0
    assert not (out / "records").exists()


# --- the validators, one finding at a time --------------------------------------------


@pytest.fixture(scope="module")
def sound(records) -> dict:
    """A record with a top bar, an open document, a row, a notification and a disabled button."""
    for record in records:
        scene = record["target"]["scene"]
        states = {e["bound"]["identity"]: e["bound"]["state"] for e in scene["elements"] if "bound" in e}
        if (
            record["inputs"]["design_condition"]["navigation_position"] == "top"
            and has(scene, "editor.body") and has(scene, "notification") and has(scene, "document:1")
            and states["toolbar.save"] == "disabled"
        ):  # fmt: skip
            return record
    raise AssertionError("no such record")


def the(scene: dict, name: str) -> dict:
    return next(e for e in scene["elements"] if e["id"] == name or e.get("bound", {}).get("identity") == name)


def cover(scene: dict, name: str) -> None:
    root = next(e for e in scene["elements"] if e["parent"] is None)
    scene["elements"].append({"id": "s.lid", "type": "divider", "parent": root["id"], "box": dict(the(scene, name)["box"]), "style": copy.deepcopy(root["style"])})


def narrow(scene: dict, name: str) -> None:
    the(scene, name)["box"]["width"] /= 2


def flatten(scene: dict, name: str) -> None:
    the(scene, name)["box"]["height"] = 12.0


def out_of_its_panel(scene: dict, name: str) -> None:
    the(scene, name)["box"]["y"] = the(scene, "s.list")["box"]["y"] - the(scene, name)["box"]["height"] / 2


def into_the_editor(scene: dict, name: str) -> None:
    the(scene, name)["parent"] = "s.editor"


def onto_save(scene: dict, name: str) -> None:
    the(scene, name)["box"]["x"] = the(scene, "toolbar.save")["box"]["x"]


def an_empty_panel(scene: dict, name: str) -> None:
    scene["elements"].append({**copy.deepcopy(the(scene, "s.list")), "id": "s.spare", "box": {"x": 0.0, "y": 0.0, "width": 4.0, "height": 4.0}})


def editor_over_the_list(scene: dict, name: str) -> None:
    the(scene, "s.editor")["box"] = dict(the(scene, "s.list")["box"])


def full_opacity(scene: dict, name: str) -> None:
    the(scene, name)["style"]["opacity"] = 1.0


def another_fill(scene: dict, name: str) -> None:
    the(scene, name)["style"]["fill"] = [1.0, 0.0, 0.0, 1.0]


FAULTS = [
    (narrow, "documents.create", "text fit", "text_overflows"),
    (flatten, "editor.body", "text fit", "text_too_tall"),
    (cover, "documents.heading", "text fit", "text_covered"),
    (cover, "documents.heading", "hit targets", "element_covered"),
    (cover, "toolbar.sort", "hit targets", "hit_target_covered"),
    (out_of_its_panel, "document:1", "element completeness", "outside_parent"),
    (into_the_editor, "document:1", "element completeness", "outside_parent"),
    (onto_save, "toolbar.undo", "element completeness", "elements_overlap"),
    (an_empty_panel, "", "element completeness", "empty_container"),
    (editor_over_the_list, "", "element completeness", "panels_overlap"),
    (full_opacity, "toolbar.save", "state consistency", "state_style_mismatch"),
    (another_fill, "documents.create", "state consistency", "state_style_mismatch"),
]


@pytest.mark.parametrize("fault, element, validator, code", FAULTS, ids=[f"{fault.__name__}-{code}" for fault, _, _, code in FAULTS])
def test_each_validator_rejects_its_fault_and_says_which_element_and_why(sound, fault, element, validator, code):
    preset = design.load().preset(sound["diagnostics"]["visual_preset"])
    bound, viewport = bound_elements_of(sound), viewport_of(sound)
    scene, found = validators.judge(sound["target"]["scene"], bound, viewport, preset)
    assert scene is not None and found == ()

    broken = copy.deepcopy(sound["target"]["scene"])
    fault(broken, element)
    scene, found = validators.judge(broken, bound, viewport, preset)
    assert scene is not None, "the fault is one scene validation does not see"
    matching = [finding for finding in found if (finding.validator, finding.code) == (validator, code)]
    assert matching, [str(finding) for finding in found]
    assert all(finding.detail for finding in found)
    if element:
        # The finding names the element, in its `element` or in its sentence.
        named = (f"b.{element}", the(broken, element)["parent"], element.split(":")[0].split(".")[0])
        assert any(any(name in f"{finding.element} {finding.detail}" for name in named) for finding in matching), [str(f) for f in matching]
    assert set(matching[0].to_json()) == {"validator", "code", "element", "detail"}


def test_scene_validation_is_the_first_validator_and_its_findings_carry_its_name(sound):
    preset = design.load().preset(sound["diagnostics"]["visual_preset"])
    broken = copy.deepcopy(sound["target"]["scene"])
    the(broken, "toolbar.save")["bound"]["binding"] = {"command": "create"}
    the(broken, "editor.title")["box"]["width"] = 0
    scene, found = validators.judge(broken, bound_elements_of(sound), viewport_of(sound), preset)
    assert scene is None
    assert {(finding.validator, finding.code) for finding in found} == {("scene validation", "bound_altered"), ("scene validation", "out_of_range")}


def test_a_notification_may_lie_over_one_corner_of_an_element_and_no_more(sound):
    """The notification is laid over the workspace. Over one of the four outer
    points the hit test is asked at, it is accepted; over two, or over the
    centre, the element is covered."""
    preset = design.load().preset(sound["diagnostics"]["visual_preset"])
    bound, viewport = bound_elements_of(sound), viewport_of(sound)

    def findings_with_the_notification_at(x: float, y: float) -> list[tuple[str, str]]:
        scene = copy.deepcopy(sound["target"]["scene"])
        note = the(scene, "notification")["box"]
        note["x"], note["y"] = x, y
        validated = scene_schema.validate(scene, bound, viewport)
        return [(finding.code, finding.element) for finding in validators.hit_targets(validated)]

    body = the(sound["target"]["scene"], "editor.body")["box"]
    note = the(sound["target"]["scene"], "notification")["box"]
    assert note["width"] < body["width"] / 2 and note["height"] < body["height"] / 2
    low, right = body["y"] + 0.75 * body["height"] - note["height"] / 2, body["x"] + 0.75 * body["width"] - note["width"] / 2
    # Over the lower right outer point only.
    assert findings_with_the_notification_at(right, low) == []
    # Over the centre.
    centre = (body["x"] + (body["width"] - note["width"]) / 2, body["y"] + (body["height"] - note["height"]) / 2)
    assert findings_with_the_notification_at(*centre) == [("hit_target_covered", "b.editor.body")]
    # Over both right-hand outer points of the title field, and not its centre.
    title = the(sound["target"]["scene"], "editor.title")["box"]
    assert note["height"] >= title["height"] / 2 + 2
    over_two = (title["x"] + 0.75 * title["width"] - 4, title["y"] + title["height"] / 4 - 1)
    assert over_two[0] > title["x"] + title["width"] / 2 and over_two[0] + note["width"] <= viewport[0]
    assert ("hit_target_covered", "b.editor.title") in findings_with_the_notification_at(*over_two)


def test_a_state_may_change_style_values_and_nothing_else(records):
    """Records of one application state under different pointer states."""
    groups = defaultdict(list)
    for record in records:
        groups[record["diagnostics"]["related"]["application_state"]].append(record)
    first, second = next(group for group in groups.values() if len(group) == 3)[:2]
    one, other = scene_of(first), scene_of(second)
    assert validators.related_findings(one, other) == []

    moved = copy.deepcopy(second)
    the(moved["target"]["scene"], "toolbar.sort")["box"]["x"] += 3
    assert {f.code for f in validators.related_findings(one, scene_of(moved))} == {"state_moves_box"}

    restyled = copy.deepcopy(second)
    bystander = next(
        e for e in restyled["target"]["scene"]["elements"]
        if "bound" in e and e["bound"]["identity"] not in {*first["application"]["state"]["interaction"], *second["application"]["state"]["interaction"]}
    )  # fmt: skip
    bystander["style"]["opacity"] = 0.5
    found = validators.related_findings(one, scene_of(restyled))
    assert [(f.validator, f.code, f.element) for f in found] == [("state consistency", "state_changes_another", bystander["id"])]


def test_the_generator_rejects_a_state_whose_scene_moves_a_box(monkeypatch):
    """The reference layout never moves a box with a state, so this one is
    made to: a hovered element is written one unit to the right. The generator
    must reject every such record as a state that moves a box, and write the
    rest."""
    written = reference_layout.write_scene

    def moving(bound_elements, viewport, preset, condition):
        scene = written(bound_elements, viewport, preset, condition)
        for element in scene["elements"]:
            if element.get("bound", {}).get("state") == "hover":
                element["box"]["x"] += 1.0
        return scene

    monkeypatch.setattr(reference_layout, "write_scene", moving)
    config = generator.load_config(REPO_ROOT / "configs" / "data" / "tiny-v1.json")
    files = dict(generator.generate(config))
    manifest = json.loads(files["manifest.json"])
    # One hover moment for each action of the four scripts.
    hovers = sum(len(script) for script in config.scenarios.values())
    assert manifest["counts"]["rejected"] == hovers and manifest["counts"]["records"] == 82 - hovers
    for rejection in manifest["rejected"]:
        assert rejection["reason"] == "rejected_by_validators"
        assert [(p["validator"], p["code"]) for p in rejection["problems"]] == [("state consistency", "state_moves_box")]
        assert f"records/{rejection['id']}.json" not in files


# --- rejections are recorded with their reasons ------------------------------------------


def test_a_scene_a_validator_rejects_is_not_written_and_its_reasons_are_recorded(folder):
    """With viewport sizes dealt and not fitted, a long list in a short
    viewport gives scenes that the schema refuses and scenes that only the
    other validators refuse."""
    config = write_config(
        folder / "short",
        families_config(
            viewport_choice="dealt", viewports=[[960, 400]], layout_families=["left-rail-list-left"], visual_presets=["calm-blue"],
            scenarios={"long-list": ["create"] * 12 + ["open", "edit"]}, sessions_per_scenario=1, content_lengths=None, stress_tests=None,
        ),
    )  # fmt: skip
    out = folder / "short" / "out"
    result = run_cli("data", "generate", "--config", config, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    rejected = manifest["rejected"]
    assert manifest["counts"]["rejected"] == len(rejected) and manifest["counts"]["records"] + len(rejected) == 1 + 3 * 14
    assert {rejection["reason"] for rejection in rejected} == {"scene_invalid", "rejected_by_validators"}
    written = {path.stem for path in (out / "records").glob("*.json")}
    assert written == {entry["id"] for entry in manifest["records"]}
    names = set()
    for rejection in rejected:
        assert rejection["id"] not in written and not (out / "images" / f"{rejection['id']}.png").exists()
        assert rejection["problems"]
        for problem in rejection["problems"]:
            assert set(problem) == {"validator", "code", "element", "detail"} and problem["detail"]
            assert problem["validator"] in manifest["validators"]
            names.add(problem["validator"])
        if rejection["reason"] == "scene_invalid":
            assert {problem["validator"] for problem in rejection["problems"]} == {"scene validation"}
        else:
            assert "scene validation" not in {problem["validator"] for problem in rejection["problems"]}
        codes = ", ".join(sorted({problem["code"] for problem in rejection["problems"]}))
        assert f"  {rejection['id']:<16} {codes}" in result.stdout
    assert {"scene validation", "hit targets", "text fit"} <= names
    assert f"Rejected           {len(rejected)}" in result.stdout
    assert run_cli("data", "check", out).returncode == 0


def test_every_record_names_the_validators_it_passed(records, manifest):
    names = ["scene validation", "text fit", "element completeness", "state consistency", "hit targets"]
    assert manifest["validators"][:5] == names and manifest["validators"][-1] == "coverage"
    assert manifest["counts"]["rejected"] == 0 and manifest["rejected"] == []
    for record in records:
        validation = record["diagnostics"]["validation"]
        assert validation["validators"] == manifest["validators"][:-1]
        assert validation["scene"] == {"valid": True, "problems": []}
        for name in ("text_fit", "element_completeness", "state_consistency", "hit_targets", "inputs"):
            assert validation[name] == {"problems": []}


# --- property: every generated scene is valid ---------------------------------------------


def width_by_qt(text: str, size: float, weight: float) -> float:
    typography.ensure_gui()
    font = QFont("Inter")
    font.setVariableAxis(QFont.Tag("wght"), weight)
    font.setVariableAxis(QFont.Tag("opsz"), 16)
    font.setPixelSize(100)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return QFontMetricsF(font).horizontalAdvance(text) * size / 100


def assert_valid(record: dict, presets) -> None:
    """A record's target, judged four ways: by scene validation, by the
    validators, by the runtime renderer's hit test and by Qt's font metrics."""
    scene = scene_of(record)
    found = validators.findings(scene, presets[record["diagnostics"]["visual_preset"]])
    assert found == (), (record["id"], [str(finding) for finding in found])
    for element in scene.bound_elements:
        # What is drawn at its centre is what is hit there.
        assert runtime_renderer.hit_test(scene, element.x + element.width / 2, element.y + element.height / 2) is element.bound, (record["id"], element.id)
        # No line of its text is wider than its box.
        for line in element.bound.text.split("\n"):
            wide = width_by_qt(line, element.style.type_size, element.style.type_weight)
            assert wide <= element.width + 1e-6, (record["id"], element.id, line)
        # It lies inside its parent.
        parent = next(other for other in scene.elements if other.id == element.parent)
        assert parent.x - 1e-6 <= element.x and element.x + element.width <= parent.x + parent.width + 1e-6, (record["id"], element.id)
        assert parent.y - 1e-6 <= element.y and element.y + element.height <= parent.y + parent.height + 1e-6, (record["id"], element.id)


def test_every_generated_scene_is_valid(records):
    presets = design.load().presets
    for record in records:
        assert_valid(record, presets)
        assert generator.record_problems(record, design.load()) == [], record["id"]


def test_a_record_whose_target_a_validator_rejects_breaks_the_record_rules(sound):
    """`data check` runs this rule on every record of a written dataset."""
    record = copy.deepcopy(sound)
    assert generator.record_problems(record, design.load()) == []
    the(record["target"]["scene"], "documents.create")["box"]["width"] /= 2
    problems = generator.record_problems(record, design.load())
    assert any(problem.startswith("target.scene is rejected by text fit: text_overflows (b.documents.create)") for problem in problems), problems


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_generated_scene_is_valid_whatever_the_seed(seed):
    """Other seeds deal other designs to the scenarios and write other
    content. The stress tests are left out: what each is rejected for is
    stated for the committed seed's content."""
    raw = families_config(seed=seed, sessions_per_scenario=1, stress_tests=None)
    config = generator.parse_config(json.dumps(raw, ensure_ascii=False).encode())
    files = dict(generator.generate(config))
    manifest = json.loads(files["manifest.json"])
    presets = design.load().presets
    moments = {s["id"]: 1 + 3 * len(raw["scenarios"][s["scenario"]]) for s in manifest["sessions"]}
    assert manifest["counts"]["records"] + manifest["counts"]["rejected"] == sum(moments.values())
    assert manifest["counts"]["sessions"] + manifest["counts"]["sessions_refused"] == len(raw["scenarios"])
    assert manifest["counts"]["records"] > 100
    for entry in manifest["records"]:
        assert_valid(json.loads(files[entry["file"]]), presets)
    # Whatever was not written says why.
    for rejection in manifest["rejected"]:
        assert rejection["problems"] and rejection["id"] not in {entry["id"] for entry in manifest["records"]}
    for session in manifest["sessions_refused"]:
        assert session["viewports_refused"] and all(refusal["codes"] for refusal in session["viewports_refused"])


# --- property: identical seeds give identical records ---------------------------------------


def test_the_same_seed_and_configuration_give_the_same_bytes(run, folder):
    again = folder / "again"
    result = run_cli("data", "generate", "--config", FAMILIES, "--out", again)
    assert result.returncode == 0, result.stderr
    first, second = files_of(run["out"]), files_of(again)
    assert first == second
    assert sum(name.startswith("records/") for name in first) == 358 and sum(name.startswith("stress/") for name in first) >= 20


def test_another_seed_deals_other_designs_and_writes_other_records(manifest):
    raw = families_config(seed=5, stress_tests=None)
    other = generator.sessions(generator.parse_config(json.dumps(raw, ensure_ascii=False).encode()))
    ours = {session["id"]: (session["layout_family"], session["visual_preset"]) for session in manifest["sessions"]}
    assert {session.id: (session.layout_family, session.visual_preset) for session in other} != ours
    assert {session.id for session in other} == set(ours)


def test_data_check_passes_the_dataset_as_written(run):
    result = run_cli("data", "check", run["out"])
    assert result.returncode == 0, result.stderr
    assert "generating it again gives the same bytes" in result.stdout


def test_the_committed_manifest_is_the_families_configuration_generated(manifest):
    """Compared by the hashes of the inputs and the targets, which depend on
    this machine's text measurement but not on its rasteriser."""
    committed = json.loads(COMMITTED_MANIFEST.read_text())
    assert committed["configuration"]["sha256"] == sha256(FAMILIES.read_bytes())
    assert committed["generator"] == manifest["generator"] and committed["seed"] == manifest["seed"]
    assert committed["counts"] == manifest["counts"]
    assert committed["sessions"] == manifest["sessions"] and committed["coverage"] == manifest["coverage"]
    fields = ("id", "file", "session", "application_state", "layout_family", "visual_preset", "viewport", "inputs_sha256", "target_sha256")
    assert [[entry[f] for f in fields] for entry in committed["records"]] == [[entry[f] for f in fields] for entry in manifest["records"]]
    fields = ("id", "file", "sha256", "layout_family", "visual_preset", "viewport", "broken", "reason", "codes")
    assert [[e[f] for f in fields] for e in committed["stress_tests"]["records"]] == [[e[f] for f in fields] for e in manifest["stress_tests"]["records"]]

    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 0

    dataset = generator.default_out(generator.load_config(FAMILIES)).as_posix()
    assert dataset == "artifacts/datasets/families-v1"
    assert not ignored(f"{dataset}/manifest.json")
    assert ignored(f"{dataset}/records/long-list-0.000.json") and ignored(f"{dataset}/stress/missing-button.json")


# --- the stress-test set ----------------------------------------------------------------------


def test_the_stress_test_set_is_written_apart_and_labelled(run, manifest, records, stress):
    out, listed = run["out"], manifest["stress_tests"]
    assert listed["set"] == "stress-test" and listed["training_target"] is False
    cases = json.loads(FAMILIES.read_text())["stress_tests"]
    assert manifest["counts"]["stress_tests"] == len(listed["records"]) == len(cases) == len(stress) >= 20
    assert manifest["counts"]["records"] == len(records) == 358

    record_ids = {record["id"] for record in records}
    for case, entry, record in zip(cases, listed["records"], stress, strict=True):
        assert entry["id"] == record["id"] == f"stress.{case['name']}" and entry["id"] not in record_ids
        assert entry["file"] == f"stress/{case['name']}.json" and sha256((out / entry["file"]).read_bytes()) == entry["sha256"]
        assert record["kind"] == "stress-test-record" and record["set"] == "stress-test" and record["training_target"] is False
        assert record["why"] == case["why"] and record["why"].split(":")[0] in ("Difficult", "Broken")
        # It has no model inputs and no target, so nothing that reads records can train on it.
        assert "inputs" not in record and "target" not in record and "reference_image" not in record
        assert generator.record_problems(record) == ['it is not an object of kind "dataset-record"']
        assert entry["broken"] == (record["broken_by"] is not None) == ("break" in case)
        assert record["diagnostics"]["generator"]["configuration"]["sha256"] == sha256(FAMILIES.read_bytes())
    # Nothing of the stress-test set is among the records or their images.
    assert {path.parent.name for path in out.rglob("*") if path.name.startswith("stress") or "stress" in path.parent.name} == {"stress", out.name}
    assert not [name for name in files_of(out) if name.startswith(("records/", "images/")) and "stress" in name]
    assert {entry["broken"] for entry in listed["records"]} == {True, False}
    for entry in listed["records"]:
        assert f"  {entry['id']:<34} {', '.join(entry['codes'])}" in run["result"].stdout


def test_the_validators_reject_every_stress_test_for_the_recorded_reasons(run, stress):
    """Judged again here from what each record holds: its candidate scene, the
    bound elements the application supplied, its viewport and its visual preset."""
    presets = design.load().presets
    cases = {f"stress.{case['name']}": case for case in json.loads(FAMILIES.read_text())["stress_tests"]}
    rejected_for = set()
    for record in stress:
        bound = bound_elements_of(record)
        conditioning = record["conditioning"]
        viewport = (conditioning["viewport"]["width"], conditioning["viewport"]["height"])
        scene, found = validators.judge(record["candidate"]["scene"], bound, viewport, presets[conditioning["visual_preset"]])
        codes = sorted({finding.code for finding in found})
        assert codes, record["id"]
        assert codes == sorted(cases[record["id"]]["expect"]) == record["expected"]["codes"], record["id"]
        assert [finding.to_json() for finding in found] == record["rejection"]["problems"], record["id"]
        assert record["rejection"]["reason"] == ("scene_invalid" if scene is None else "rejected_by_validators")
        # One that the schema accepts was drawn, so that a person can see it.
        drawable = scene is not None and "text_not_drawable" not in codes
        assert (record["image"] is not None) == drawable
        if drawable:
            assert sha256((run["out"] / record["image"]["file"]).read_bytes()) == record["image"]["sha256"]
        rejected_for |= set(codes)
    # Clipping, a broken binding, impossible geometry, and every validator of a scene.
    assert rejected_for >= {
        "outside_viewport", "text_overflows", "text_too_tall", "text_covered", "text_not_drawable", "bound_altered", "bound_missing",
        "bound_duplicated", "out_of_range", "limit_exceeded", "tree", "elements_overlap", "outside_parent",
        "state_style_mismatch", "hit_target_covered", "element_covered",
    }  # fmt: skip
    assert {problem["validator"] for record in stress for problem in record["rejection"]["problems"]} == set(validators.SCENE_VALIDATORS)


def test_a_difficult_stress_test_is_what_the_reference_layout_writes_for_a_reachable_state(stress):
    """Nothing was broken by hand: the candidate is the reference layout's own
    scene for a state the kernel reaches, and it is the content or the
    viewport that makes it invalid."""
    layout, presets = layout_family.load(LAYOUT_V2), design.load().presets
    difficult = [record for record in stress if record["broken_by"] is None]
    assert len(difficult) >= 6
    for record in difficult:
        kernel = Kernel()
        for command in record["diagnostics"]["scenario"]["trace"]:
            kernel.execute(command["binding"], command["text"])
        described = documents_adapter.describe(kernel.state())
        kernel.close()
        assert [element.to_json() for element in described] == record["application"]["bound_elements"], record["id"]
        conditioning = record["conditioning"]
        assert layout.family(conditioning["layout_family"]).design_condition.to_json() == conditioning["design_condition"]
        written = reference_layout.write_scene(
            described, (conditioning["viewport"]["width"], conditioning["viewport"]["height"]),
            presets[conditioning["visual_preset"]], layout.condition(conditioning["design_condition"]),
        )  # fmt: skip
        assert written == record["candidate"]["scene"], record["id"]


def test_data_check_fails_a_stress_test_that_is_relabelled_or_no_longer_rejected(run, folder, manifest):
    changed = folder / "stress-changed"
    shutil.copytree(run["out"], changed)
    relabelled, mended, moved = (entry for entry in manifest["stress_tests"]["records"] if entry["id"] in ("stress.missing-button", "stress.button-narrower-than-its-text", "stress.covered-label"))

    record = json.loads((changed / relabelled["file"]).read_text())
    record["training_target"] = True
    (changed / relabelled["file"]).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    record = json.loads((changed / mended["file"]).read_text())
    the(record["candidate"]["scene"], "documents.create")["box"]["width"] *= 2
    (changed / mended["file"]).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    shutil.copy(changed / moved["file"], changed / "records" / "covered-label.json")

    result = run_cli("data", "check", changed)
    assert result.returncode == 1
    assert f'stress test {relabelled["id"]}: it is not labelled set "stress-test" and training_target false' in result.stderr
    assert f"stress test {mended['id']}: the validators do not reject it" in result.stderr
    assert "records/covered-label.json is not listed in the manifest" in result.stderr


@pytest.mark.parametrize(
    "change, said",
    [
        ({"expect": ["text_overflows"]}, "stress_tests.missing-button: it is expected to be rejected for text_overflows; the validators rejected it for bound_missing"),
        ({"break": None}, "stress_tests.missing-button: it is expected to be rejected for bound_missing; the validators did not reject it"),
        ({"break": {"kind": "remove", "element": "toolbar.print"}}, "stress_tests.missing-button.break: 'toolbar.print' is not an element of the script's last state"),
        ({"break": {"kind": "melt", "element": "toolbar.save"}}, "stress_tests.missing-button.break does not name a kind"),
        ({"layout_family": "sidebar-right"}, "stress_tests.missing-button.layout_family: 'sidebar-right' is not a layout family"),
        ({"layout_family": ["sidebar-right"]}, "stress_tests.missing-button.layout_family: ['sidebar-right'] is not a layout family"),
        ({"visual_preset": {"name": "neon"}}, "stress_tests.missing-button.visual_preset: {'name': 'neon'} is not a visual preset"),
        ({"script": ["create", "save"]}, "stress_tests.missing-button: step 1 (save): toolbar.save is disabled in this state"),
        ({"name": "save"}, "a case's name is lower-case words joined by hyphens, and neither a scenario's name nor a word the model inputs use"),
        ({"target": {}}, "stress_tests[0] does not hold name, why, script, layout_family, visual_preset, viewport, expect"),
    ],
)
def test_a_stress_test_that_is_not_rejected_for_what_it_states_stops_the_run(folder, change, said):
    case = next(case for case in families_config()["stress_tests"] if case["name"] == "missing-button")
    case = {name: value for name, value in {**case, **change}.items() if value is not None}
    where = folder / f"stress-refused-{abs(hash(json.dumps(change, sort_keys=True)))}"
    config = write_config(where, families_config(scenarios={"one-document": ["create"]}, sessions_per_scenario=1, stress_tests=[case]))
    result = run_cli("data", "generate", "--config", config, "--out", where / "out")
    assert result.returncode == 2, result.stdout
    assert said in result.stderr
    assert not (where / "out").exists()


# --- configurations that cannot be used ---------------------------------------------------------


@pytest.mark.parametrize(
    "change, said",
    [
        ({"viewport_choice": "random"}, "viewport_choice is 'random'; it is one of dealt, fitting"),
        ({"content_lengths": {"hover": {"title_words": [1, 1], "body_lines": [1, 1]}}}, "content_lengths.hover: a content length's name"),
        ({"content_lengths": {"long": {"title_words": [1, 99], "body_lines": [1, 1]}}}, "content_lengths.long: content.title_words is not [fewest, most]"),
        ({"content_lengths": {"long": {"title_words": [1, 2]}}}, "content_lengths.long does not hold exactly: title_words, body_lines"),
        ({"content_lengths": {}}, "content_lengths is not a set of named lengths"),
        ({"stress_tests": {"a": 1}}, "stress_tests is not a list of cases"),
        ({"layout": "configs/layout/v1.json"}, "layout_families: 'top-bar-list-right' is not a layout family"),
    ],
)
def test_a_configuration_that_cannot_be_used_is_refused_with_the_reason(folder, change, said):
    where = folder / f"refused-{abs(hash(json.dumps(change, sort_keys=True)))}"
    config = write_config(where, families_config(**change))
    result = run_cli("data", "generate", "--config", config, "--out", where / "out")
    assert result.returncode == 2
    assert said in result.stderr
    assert not (where / "out").exists()


def test_a_content_length_is_diagnostic_metadata_and_never_a_model_input(records):
    record = copy.deepcopy(next(r for r in records if r["diagnostics"]["scenario"]["content_length"] == "long"))
    assert generator.record_problems(record) == []
    record["inputs"]["bound_elements"][0]["identity"] = "long"
    assert any("is the content length's name: an input contains diagnostic metadata" in problem for problem in generator.record_problems(record))
    for other in records:
        assert other["diagnostics"]["scenario"]["content_length"] not in json.dumps(other["inputs"])


# --- what the generator does not do -----------------------------------------------------------------


def test_the_variation_the_generator_does_not_support_is_listed(manifest):
    stated = json.loads(LAYOUT_V2.read_text())["out_of_scope"]
    assert len(stated) >= 10 and all(isinstance(item, str) and item.endswith(".") for item in stated)
    assert manifest["out_of_scope"] == stated
    record = (REPO_ROOT / "records" / "milestones" / "S2.md").read_text()
    for item in stated:
        assert item.split(".")[0] in record, item
