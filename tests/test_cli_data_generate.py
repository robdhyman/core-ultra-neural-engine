"""Command-line tests for `data generate` and `data check` (test seam 2).

`data generate` is run for real on the tiny configuration, the committed
`configs/data/tiny-v1.json`, and the tests assert on the manifest, the records
and the images it writes.

The judges are independent of the generator. A record's application state is
reached again here with a kernel of the test's own, from the commands the
record lists; its true scene is asked of the scene session; its image is drawn
again by the runtime renderer; its text width is measured by Qt's own font
metrics; and its visual preset is read from DESIGN.md's YAML.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
import yaml
from PySide6.QtGui import QFont, QFontMetricsF, QImage

from core_ultra import documents_adapter, generator, layout_family, reference_layout, runtime_renderer, typography
from core_ultra import scene as scene_schema
from core_ultra.kernel import Kernel
from core_ultra.scene_session import Conditioning, RenderingMode, SceneSession
from core_ultra.scripted_session import ACTIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY = REPO_ROOT / "configs" / "data" / "tiny-v1.json"
COMMITTED_MANIFEST = REPO_ROOT / "artifacts" / "datasets" / "tiny-v1" / "manifest.json"
DESIGN_MD = REPO_ROOT / "DESIGN.md"
LAYOUT_CONFIG = REPO_ROOT / "configs" / "layout" / "v1.json"
FONT = REPO_ROOT / "src" / "core_ultra" / "assets" / "fonts" / "inter" / "Inter[opsz,wght].ttf"

FACTORS = {"navigation_position", "panel_arrangement", "density", "spacing", "notification_location"}
TOKEN_GROUPS = {"colours", "type", "spacing", "dimensions", "borders", "radii", "elevation", "density", "opacity"}
INPUT_ELEMENT_FIELDS = {"identity", "role", "binding_kind", "state", "text_length", "text_width", "relationships"}
STATES = {"default", "hover", "pressed", "focused", "disabled"}
COMMANDS = {"create", "open", "rename", "edit", "save", "sort", "filter", "undo"}


def run_cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "core_ultra", *map(str, args)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=600
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_of(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def tiny_config(**changes) -> dict:
    return {**json.loads(TINY.read_text()), **changes}


def write_config(folder: Path, config: dict, name: str = "config.json") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    return path


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("data-generate")


@pytest.fixture(scope="module")
def run(folder) -> dict:
    """One real run of `data generate` on the tiny configuration."""
    out = folder / "tiny"
    result = run_cli("data", "generate", "--config", TINY, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    records = [json.loads((out / entry["file"]).read_text()) for entry in manifest["records"]]
    return {"result": result, "out": out, "manifest": manifest, "records": records}


@pytest.fixture(scope="module")
def manifest(run) -> dict:
    return run["manifest"]


@pytest.fixture(scope="module")
def records(run) -> list[dict]:
    return run["records"]


def interaction_of(record: dict) -> dict:
    return record["application"]["state"]["interaction"]


def replay(record: dict):
    """The record's application state, reached again from an empty kernel by
    giving it the commands the record lists. Returns the state and, for each
    command, the bound element the record says was activated, as the adapter
    described it just before."""
    kernel = Kernel()
    activated = []
    try:
        for command in record["diagnostics"]["scenario"]["trace"]:
            elements = {element.identity: element for element in documents_adapter.describe(kernel.state())}
            activated.append(elements[command["element"]])
            kernel.execute(command["binding"], command["text"])
        return kernel.state().with_interaction(interaction_of(record)), activated
    finally:
        kernel.close()


def bound_elements_of(record: dict) -> tuple[documents_adapter.BoundElement, ...]:
    return tuple(
        documents_adapter.BoundElement(
            identity=item["identity"],
            role=item["role"],
            text=item["text"],
            binding=item["binding"],
            state=item["state"],
            relationships=tuple(item["relationships"]),
        )
        for item in record["application"]["bound_elements"]
    )


def conditioning_of(record: dict) -> Conditioning:
    viewport = record["inputs"]["viewport"]
    return Conditioning(
        viewport["width"],
        viewport["height"],
        visual_preset=record["diagnostics"]["visual_preset"],
        design_condition=record["inputs"]["design_condition"],
    )


# --- what the command writes ---------------------------------------------------


def test_the_command_writes_a_manifest_the_configuration_and_every_record_with_its_image(run, manifest):
    out = run["out"]
    config = json.loads(TINY.read_text())
    # One moment before the first action, and three for each action.
    moments = sum(1 + 3 * len(script) for script in config["scenarios"].values()) * config["sessions_per_scenario"]

    assert manifest["kind"] == "dataset-manifest"
    assert manifest["dataset"] == {"name": "tiny", "version": 1}
    assert manifest["seed"] == config["seed"]
    assert manifest["rendering_mode"] == "A, Reference"
    assert manifest["counts"]["sessions"] == len(config["scenarios"]) == len(manifest["sessions"])
    assert manifest["counts"]["records"] == len(manifest["records"]) == moments
    assert manifest["counts"]["rejected"] == 0 and manifest["rejected"] == []
    assert sum(manifest["counts"]["by_visual_preset"].values()) == moments
    assert set(manifest["counts"]["by_visual_preset"]) == set(config["visual_presets"])
    assert manifest["counts"]["by_layout_family"] == {"top-bar-list-left": moments}

    written = files_of(out)
    assert written["config.json"] == TINY.read_bytes()
    assert manifest["configuration"] == {"file": "config.json", "sha256": sha256(TINY.read_bytes())}
    listed = {"manifest.json", "config.json"}
    for entry in manifest["records"]:
        assert sha256(written[entry["file"]]) == entry["sha256"]
        assert sha256(written[entry["image"]["file"]]) == entry["image"]["sha256"]
        listed |= {entry["file"], entry["image"]["file"]}
    assert set(written) == listed
    assert len({entry["id"] for entry in manifest["records"]}) == moments

    stdout = run["result"].stdout
    assert f"Records            {moments}" in stdout
    assert "Rejected           0" in stdout
    assert sha256(written["manifest.json"]) in stdout


def test_the_tiny_set_shows_every_state_command_and_role(records):
    states = {element["state"] for record in records for element in record["inputs"]["bound_elements"]}
    commands = {command["binding"]["command"] for record in records for command in record["diagnostics"]["scenario"]["trace"]}
    roles = {element["role"] for record in records for element in record["inputs"]["bound_elements"]}
    identities = {element["identity"] for record in records for element in record["inputs"]["bound_elements"]}
    assert states == STATES
    assert commands == COMMANDS
    assert roles == set(documents_adapter.ROLES)
    assert {"documents.empty", "editor.empty", "notification", "editor.body", "document:1"} <= identities


# --- scripted sessions drive the kernel ----------------------------------------


def test_every_record_is_a_state_the_kernel_reaches_through_action_bindings(records):
    for record in records:
        state, activated = replay(record)
        described = [element.to_json() for element in documents_adapter.describe(state)]
        assert described == record["application"]["bound_elements"], record["id"]
        assert [document.title for document in state.documents] == [d["title"] for d in record["application"]["state"]["documents"]]
        assert state.notification == record["application"]["state"]["notification"]
        # Each command was the action binding of an element that was there to
        # be activated, and was not disabled.
        for command, element in zip(record["diagnostics"]["scenario"]["trace"], activated):
            assert dict(element.binding) == command["binding"], record["id"]
            assert element.state != "disabled", record["id"]


def test_a_session_moves_by_one_command_at_a_time(records):
    by_session = defaultdict(list)
    for record in records:
        by_session[record["diagnostics"]["scenario"]["session"]].append(record)
    for session in by_session.values():
        assert [record["diagnostics"]["scenario"]["moment"] for record in session] == list(range(len(session)))
        assert session[0]["diagnostics"]["scenario"]["trace"] == []
        assert session[0]["application"]["state"]["total_documents"] == 0
        for before, after in zip(session, session[1:]):
            earlier, later = (r["diagnostics"]["scenario"]["trace"] for r in (before, after))
            assert later[: len(earlier)] == earlier and len(later) - len(earlier) in (0, 1)
            if after["diagnostics"]["scenario"]["phase"] == "result":
                assert len(later) == len(earlier) + 1
                # The command given is the binding of the element that was just pressed or focused.
                (identity, pointer_state), = interaction_of(before).items()
                assert pointer_state in ("pressed", "focused")
                assert later[-1]["element"] == identity
            else:
                assert len(later) == len(earlier)


def test_a_script_that_cannot_be_carried_out_is_refused_and_nothing_is_written(folder):
    # Save is disabled while nothing is open.
    config = write_config(folder / "impossible", tiny_config(scenarios={"save-nothing": ["create", "save"]}))
    out = folder / "impossible" / "out"
    result = run_cli("data", "generate", "--config", config, "--out", out)
    assert result.returncode == 2
    assert "scenarios.save-nothing" in result.stderr and "step 1 (save)" in result.stderr and "toolbar.save is disabled" in result.stderr
    assert not out.exists() and files_of(folder / "impossible") == {"config.json": config.read_bytes()}


# --- one true scene for each state, design condition, preset and family ----------


def test_the_target_is_the_one_scene_the_reference_layout_writes_for_the_state_and_its_conditioning(records):
    """The state comes from the test's own kernel and the scene from a fresh
    scene session. Neither is given a seed, a scenario or the record's target,
    so a target that depended on anything else would not be reproduced."""
    session = SceneSession()
    layout = layout_family.load(LAYOUT_CONFIG)
    for record in records:
        state, _ = replay(record)
        frame = session.frame(state, conditioning_of(record), RenderingMode.A_REFERENCE)
        assert frame.scene.to_json() == record["target"]["scene"], record["id"]
        condition = layout.condition(record["inputs"]["design_condition"])
        assert layout.family_of(condition).name == record["diagnostics"]["layout_family"]


def test_equal_states_under_equal_conditioning_have_equal_targets_whatever_the_seed(folder, records):
    # With seed 4 the sessions are dealt the same presets and viewports as in
    # the tiny configuration, so both datasets start from the same empty
    # workspaces before their content parts ways.
    config = write_config(folder / "other-seed", tiny_config(seed=4))
    out = folder / "other-seed" / "out"
    assert run_cli("data", "generate", "--config", config, "--out", out).returncode == 0
    others = [json.loads(path.read_text()) for path in sorted((out / "records").glob("*.json"))]

    def given(record: dict) -> str:
        return json.dumps(
            [record["application"]["bound_elements"], record["inputs"]["viewport"], record["inputs"]["design_condition"], record["diagnostics"]["visual_preset"]],
            sort_keys=True,
        )

    targets = {given(record): record["target"] for record in records}
    met = [record for record in others if given(record) in targets]
    assert len(met) >= 12
    for record in met:
        assert record["target"] == targets[given(record)]
    # The other seed did write other sessions.
    assert {r["diagnostics"]["scenario"]["session_seed"] for r in others}.isdisjoint(r["diagnostics"]["scenario"]["session_seed"] for r in records)
    assert [r["application"]["state"] for r in others] != [r["application"]["state"] for r in records]


def test_the_layout_configuration_declares_only_what_the_reference_layout_draws():
    raw = json.loads(LAYOUT_CONFIG.read_text())
    assert set(raw["factors"]) == FACTORS
    for factor, values in raw["factors"].items():
        assert set(values) <= set(reference_layout.DRAWN[factor]), factor
    for family in raw["families"].values():
        assert set(family["design_condition"]) == FACTORS


@pytest.mark.parametrize(
    "change, said",
    [
        ({"navigation_position": "left"}, "navigation_position is 'left'"),
        ({"density": 2}, "density is 2"),
        ({"brand": "acme"}, "'brand' is not a design factor"),
        ({"spacing": None}, "spacing is None"),
    ],
)
def test_a_design_condition_that_is_not_declared_is_refused_and_never_drawn_as_another(change, said):
    kernel = Kernel()
    kernel.create_document("Plan")
    condition = {**layout_family.load(LAYOUT_CONFIG).family().design_condition.to_json(), **change}
    with pytest.raises(layout_family.LayoutError, match=said):
        SceneSession().frame(kernel.state(), Conditioning(960, 540, design_condition=condition), RenderingMode.A_REFERENCE)
    kernel.close()


def test_a_design_condition_without_one_of_its_factors_is_refused():
    kernel = Kernel()
    drawn = layout_family.load(LAYOUT_CONFIG).family().design_condition.to_json()
    for factor in FACTORS:
        missing = {name: value for name, value in drawn.items() if name != factor}
        with pytest.raises(layout_family.LayoutError, match=f"the design condition has no {factor}"):
            SceneSession().frame(kernel.state(), Conditioning(960, 540, design_condition=missing), RenderingMode.A_REFERENCE)
    kernel.close()


def test_the_reference_layout_itself_refuses_a_factor_value_it_does_not_draw():
    from core_ultra import design

    drawn = layout_family.load(LAYOUT_CONFIG).family().design_condition
    kernel = Kernel()
    bound = documents_adapter.describe(kernel.state())
    for factor in FACTORS:
        condition = layout_family.DesignCondition(**{**drawn.to_json(), factor: "elsewhere"})
        with pytest.raises(ValueError, match=f"does not draw {factor} 'elsewhere'"):
            reference_layout.write_scene(bound, (960, 540), design.load().preset(), condition)


# --- what a record holds ---------------------------------------------------------


def test_each_record_keeps_inputs_target_image_application_and_diagnostics_apart(records, manifest):
    config = json.loads(TINY.read_text())
    for record in records:
        assert list(record) == ["kind", "schema_version", "id", "inputs", "target", "reference_image", "application", "diagnostics"]
        assert record["kind"] == "dataset-record" and record["schema_version"] == 1
        assert list(record["target"]) == ["scene"] and record["target"]["scene"]["kind"] == "scene"
        assert set(record["application"]) == {"bound_elements", "state"}

        diagnostics = record["diagnostics"]
        assert set(diagnostics) == {"generator", "layout_family", "visual_preset", "scenario", "related", "asset_provenance", "validation"}
        assert diagnostics["generator"] == {
            "name": "core-ultra data generate",
            "version": generator.GENERATOR_VERSION,
            "seed": config["seed"],
            "configuration": {"name": "tiny", "version": 1, "sha256": sha256(TINY.read_bytes())},
        }
        assert diagnostics["layout_family"] in config["layout_families"]
        assert diagnostics["visual_preset"] in config["visual_presets"]
        scenario = diagnostics["scenario"]
        assert scenario["name"] in config["scenarios"]
        assert record["id"] == f"{scenario['session']}.{scenario['moment']:03d}"
        assert scenario["session_seed"] == f"{config['seed']}/{scenario['session']}"
        if scenario["step"] is not None:
            assert scenario["action"] == config["scenarios"][scenario["name"]][scenario["step"]]
        assert diagnostics["validation"]["scene"] == {"valid": True, "problems": []}
        assert diagnostics["validation"]["inputs"] == {"problems": []}

        provenance = diagnostics["asset_provenance"]
        assert provenance == manifest["asset_provenance"]
        assert provenance["font"]["family"] == "Inter" and provenance["font"]["sha256"] == sha256(FONT.read_bytes())
        assert "Open Font License" in provenance["font"]["licence"] and provenance["font"]["source"].startswith("https://")
        for name in ("design", "layout"):
            assert provenance[name]["sha256"] == sha256((REPO_ROOT / provenance[name]["file"]).read_bytes())


def test_stable_element_identities_and_states_are_in_every_record(records):
    for record in records:
        supplied = record["application"]["bound_elements"]
        identities = [element["identity"] for element in supplied]
        assert len(set(identities)) == len(identities)
        carried = [element["bound"] for element in record["target"]["scene"]["elements"] if element["type"] == "bound"]
        # The scene carries each supplied element once, unchanged; the inputs name the same ones in the same order.
        assert sorted(carried, key=lambda e: e["identity"]) == sorted(supplied, key=lambda e: e["identity"])
        assert [element["identity"] for element in record["inputs"]["bound_elements"]] == identities
        for identity, state in interaction_of(record).items():
            assert next(e for e in supplied if e["identity"] == identity)["state"] == state
        for document in record["application"]["state"]["documents"]:
            row = next(e for e in supplied if e["identity"] == f"document:{document['id']}")
            assert row["text"] == document["title"] and row["binding"] == {"command": "open", "document": document["id"]}


def test_the_reference_image_is_the_target_scene_drawn_by_the_runtime_renderer(run, records):
    typography.ensure_gui()
    for record in records:
        image = record["reference_image"]
        assert image["rendering_mode"] == "A, Reference" and image["drawn_by"] == "runtime renderer"
        data = (run["out"] / image["file"]).read_bytes()
        assert sha256(data) == image["sha256"]
        picture = QImage.fromData(data, "PNG").convertToFormat(QImage.Format.Format_RGBA8888)
        assert (picture.width(), picture.height()) == (image["width"], image["height"])
        pixels = np.frombuffer(picture.constBits(), dtype=np.uint8).reshape(picture.height(), picture.bytesPerLine() // 4, 4)[:, : picture.width()]

        viewport = record["inputs"]["viewport"]
        scene = scene_schema.validate(record["target"]["scene"], bound_elements_of(record), (viewport["width"], viewport["height"]))
        assert np.array_equal(pixels, runtime_renderer.draw(scene, image["pixels_per_viewport_unit"])), record["id"]


# --- model inputs ------------------------------------------------------------------


def width_by_qt(text: str) -> float:
    """The width of the widest line at 16 units and weight 400, by Qt's own font metrics."""
    typography.ensure_gui()
    font = QFont("Inter")
    font.setVariableAxis(QFont.Tag("wght"), 400)
    font.setVariableAxis(QFont.Tag("opsz"), 16)
    font.setPixelSize(100)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    metrics = QFontMetricsF(font)
    return max(metrics.horizontalAdvance(line) for line in text.split("\n")) * 16 / 100


def test_model_inputs_hold_only_what_the_scene_model_is_given(records, manifest):
    family = json.loads(LAYOUT_CONFIG.read_text())["families"]
    viewports = {session["id"]: session["viewport"] for session in manifest["sessions"]}
    for record in records:
        inputs = record["inputs"]
        assert set(inputs) == {"bound_elements", "viewport", "design_condition", "visual_preset"}
        assert inputs["viewport"] == viewports[record["diagnostics"]["scenario"]["session"]] == record["target"]["scene"]["viewport"]
        assert inputs["design_condition"] == family[record["diagnostics"]["layout_family"]]["design_condition"]
        assert set(inputs["design_condition"]) == FACTORS
        assert set(inputs["visual_preset"]) == TOKEN_GROUPS

        for given, supplied in zip(inputs["bound_elements"], record["application"]["bound_elements"], strict=True):
            assert set(given) == INPUT_ELEMENT_FIELDS
            assert (given["identity"], given["role"], given["state"]) == (supplied["identity"], supplied["role"], supplied["state"])
            assert given["binding_kind"] == (supplied["binding"] or {}).get("command")
            assert given["relationships"] == supplied["relationships"]
            assert given["text_length"] == len(supplied["text"])
            assert given["text_width"] == pytest.approx(width_by_qt(supplied["text"]), abs=1e-6)


def test_the_visual_preset_is_given_as_its_token_values_from_design_md(records):
    written = yaml.safe_load(DESIGN_MD.read_text().split("\n---\n")[0].removeprefix("---\n"))

    def px(value: str) -> float:
        return float(value.removesuffix("px"))

    seen = set()
    for record in records:
        name = record["diagnostics"]["visual_preset"]
        if name in seen:
            continue
        seen.add(name)
        tokens = record["inputs"]["visual_preset"]
        source = written if name == written["preset"] else written["presets"][name]
        assert tokens["colours"] == {
            token: [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0] for token, colour in source["colors"].items()
        }
        assert tokens["type"] == {token: [px(value["fontSize"]), float(value["fontWeight"])] for token, value in source["typography"].items()}
        assert tokens["radii"] == {token: px(value) for token, value in source["rounded"].items()}
        for group in ("spacing", "borders", "elevation", "density"):
            assert tokens[group] == {token: px(value) for token, value in source[group].items()}, group
        assert tokens["opacity"] == {token: float(value) for token, value in source["opacity"].items()}
        assert set(tokens["dimensions"]) == set(source["dimensions"])
    assert seen == set(written["presets"])


def test_no_model_input_holds_the_target_an_image_or_diagnostic_metadata(records):
    for record in records:
        assert generator.record_problems(record) == [], record["id"]

        # The same, judged without the generator's own rule: by reading the inputs as text.
        text = json.dumps(record["inputs"], ensure_ascii=False)
        diagnostics = record["diagnostics"]
        for name in (
            diagnostics["layout_family"],
            diagnostics["visual_preset"],
            diagnostics["scenario"]["session"],
            diagnostics["scenario"]["session_seed"],
            str(diagnostics["generator"]["seed"]),
            record["reference_image"]["sha256"],
            ".png",
        ):
            assert name not in text, (record["id"], name)
        for key in ('"box"', '"style"', '"scene"', '"parent"', '"text"', '"seed"', '"sha256"', '"binding"', '"name"', '"summary"', '"validation"'):
            assert key not in text, (record["id"], key)
        for element in record["target"]["scene"]["elements"]:
            assert json.dumps(element["box"]) not in text and json.dumps(element["style"]) not in text


def test_model_inputs_are_built_without_the_reference_layout_or_the_design_source():
    code = (
        "import sys, core_ultra.model_inputs\n"
        "loaded = [name for name in ('core_ultra.reference_layout', 'core_ultra.design', 'core_ultra.generator') if name in sys.modules]\n"
        "sys.exit(', '.join(loaded) or 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr


# --- `data check`: an input that contains the target fails -----------------------


def put_target_in_inputs(record):
    record["inputs"]["target"] = copy.deepcopy(record["target"])


def put_scene_in_place_of_the_viewport(record):
    record["inputs"]["viewport"] = copy.deepcopy(record["target"]["scene"])


def put_a_box_on_an_input_element(record):
    record["inputs"]["bound_elements"][0]["box"] = copy.deepcopy(record["target"]["scene"]["elements"][3]["box"])


def put_a_style_among_the_tokens(record):
    record["inputs"]["visual_preset"]["spacing"] = copy.deepcopy(record["target"]["scene"]["elements"][3]["style"])


def put_the_text_on_an_input_element(record):
    record["inputs"]["bound_elements"][0]["text"] = record["application"]["bound_elements"][0]["text"]


def put_the_preset_name_in_inputs(record):
    record["inputs"]["visual_preset"]["name"] = record["diagnostics"]["visual_preset"]


def put_the_layout_family_in_the_design_condition(record):
    record["inputs"]["design_condition"]["panel_arrangement"] = record["diagnostics"]["layout_family"]


def put_the_seed_in_inputs(record):
    record["inputs"]["seed"] = record["diagnostics"]["generator"]["seed"]


def put_the_image_in_inputs(record):
    record["inputs"]["bound_elements"][0]["identity"] = record["reference_image"]["file"]


def put_validation_in_inputs(record):
    record["inputs"]["design_condition"]["validation"] = record["diagnostics"]["validation"]


LEAKS = [
    (put_target_in_inputs, "inputs: the inputs holds 'target', which is not a model input"),
    (put_scene_in_place_of_the_viewport, "inputs.viewport is the target scene: an input contains the target"),
    (put_a_box_on_an_input_element, "inputs.bound_elements[0].box is the box of the target element"),
    (put_a_style_among_the_tokens, "inputs.visual_preset.spacing is the style of the target element"),
    (put_the_text_on_an_input_element, "inputs: bound_elements[0] holds 'text', which is not a model input"),
    (put_the_preset_name_in_inputs, "inputs: visual_preset holds 'name', which is not a model input"),
    (put_the_layout_family_in_the_design_condition, "inputs.design_condition.panel_arrangement is the layout family's name: an input contains diagnostic metadata"),
    (put_the_seed_in_inputs, "inputs: the inputs holds 'seed', which is not a model input"),
    (put_the_image_in_inputs, "inputs.bound_elements[0].identity is the reference image's file: an input contains diagnostic metadata"),
    (put_validation_in_inputs, "inputs: design_condition holds 'validation', which is not a model input"),
]


def test_data_check_passes_the_dataset_as_written(run):
    result = run_cli("data", "check", run["out"])
    assert result.returncode == 0, result.stderr
    assert "generating it again gives the same bytes" in result.stdout


def test_data_check_fails_each_record_whose_inputs_contain_the_target_or_diagnostic_metadata(run, folder, manifest):
    leaky = folder / "leaky"
    shutil.copytree(run["out"], leaky)
    # A record with an open document and several elements, a different one for each leak.
    entries = [entry for entry in manifest["records"] if entry["session"] == "first-documents-0"][6 : 6 + len(LEAKS)]
    assert len(entries) == len(LEAKS)
    for (leak, _), entry in zip(LEAKS, entries):
        record = json.loads((leaky / entry["file"]).read_text())
        leak(record)
        (leaky / entry["file"]).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    result = run_cli("data", "check", leaky)
    assert result.returncode == 1
    for (leak, said), entry in zip(LEAKS, entries):
        lines = [line for line in result.stderr.splitlines() if f"record {entry['id']}: " in line]
        assert any(said in line for line in lines), (leak.__name__, lines)
    # Only the records that were changed are reported.
    reported = {line.split("record ")[1].split(":")[0] for line in result.stderr.splitlines() if "- record " in line}
    assert reported == {entry["id"] for entry in entries}


@pytest.mark.parametrize("leak, said", LEAKS, ids=[leak.__name__ for leak, _ in LEAKS])
def test_the_record_rule_names_each_leak(records, leak, said):
    record = copy.deepcopy(next(r for r in records if r["id"] == "first-documents-0.012"))
    assert generator.record_problems(record) == []
    leak(record)
    assert any(said in f"record: {problem}" for problem in generator.record_problems(record)), generator.record_problems(record)


def test_data_check_fails_a_dataset_that_is_not_what_its_manifest_says(run, folder, manifest):
    changed = folder / "changed"
    shutil.copytree(run["out"], changed)
    first, second, third = (entry for entry in manifest["records"][:3])
    # A target moved by one unit, a deleted image, a file nobody listed.
    record = json.loads((changed / first["file"]).read_text())
    record["target"]["scene"]["elements"][1]["box"]["x"] += 1
    (changed / first["file"]).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    (changed / second["image"]["file"]).unlink()
    (changed / "records" / "extra.json").write_text("{}")

    result = run_cli("data", "check", changed)
    assert result.returncode == 1
    assert f"{first['file']} does not have the hash the manifest gives" in result.stderr
    assert f"{first['file']} is not what generating the dataset again gives" in result.stderr
    assert f"{second['image']['file']} is listed in the manifest and does not exist" in result.stderr
    assert "records/extra.json is not listed in the manifest" in result.stderr
    assert third["file"] not in result.stderr

    assert run_cli("data", "check", folder / "nothing-here").returncode == 1


# --- identical seeds and configuration give identical records ----------------------


def test_the_same_seed_and_configuration_give_the_same_bytes(run, folder):
    again = folder / "again"
    result = run_cli("data", "generate", "--config", TINY, "--out", again)
    assert result.returncode == 0, result.stderr
    assert files_of(again) == files_of(run["out"])


def test_another_seed_or_version_gives_another_dataset(run, folder):
    before = files_of(run["out"])
    for change in ({"seed": 6}, {"version": 2}):
        out = folder / f"changed-{next(iter(change))}"
        config = write_config(out.with_suffix(".config"), tiny_config(**change))
        assert run_cli("data", "generate", "--config", config, "--out", out).returncode == 0
        after = files_of(out)
        assert after["manifest.json"] != before["manifest.json"]
        records_before = {name: data for name, data in before.items() if name.startswith("records/")}
        assert all(after.get(name) != data for name, data in records_before.items())


def test_a_dataset_is_never_overwritten(run, folder):
    before = files_of(run["out"])
    # The same dataset again: nothing to do.
    same = run_cli("data", "generate", "--config", TINY, "--out", run["out"])
    assert same.returncode == 0, same.stderr
    assert files_of(run["out"]) == before
    # Another dataset into the same folder: refused.
    config = write_config(folder / "other", tiny_config(seed=7))
    other = run_cli("data", "generate", "--config", config, "--out", run["out"])
    assert other.returncode == 2
    assert "already holds a different dataset" in other.stderr and "nothing was written" in other.stderr
    assert files_of(run["out"]) == before
    assert [path.name for path in run["out"].parent.iterdir() if "partial" in path.name] == []


# --- related examples ----------------------------------------------------------------


def test_related_examples_keep_text_identities_application_state_and_bindings(records):
    """Records that share `related.application_state` are one application
    state under different pointer states."""
    groups = defaultdict(list)
    for record in records:
        groups[record["diagnostics"]["related"]["application_state"]].append(record)
    assert any(len(group) == 3 for group in groups.values())

    def without(items: list[dict], *fields: str) -> list[dict]:
        return [{name: value for name, value in item.items() if name not in fields} for item in items]

    for group in groups.values():
        first = group[0]
        states = set()
        for record in group:
            assert record["diagnostics"]["related"]["session"] == first["diagnostics"]["related"]["session"]
            assert record["diagnostics"]["scenario"]["trace"] == first["diagnostics"]["scenario"]["trace"]
            # The application: everything but the pointer state.
            assert without([record["application"]["state"]], "interaction") == without([first["application"]["state"]], "interaction")
            # The bound elements: identity, role, text, binding and relationships.
            assert without(record["application"]["bound_elements"], "state") == without(first["application"]["bound_elements"], "state")
            assert without(record["inputs"]["bound_elements"], "state") == without(first["inputs"]["bound_elements"], "state")
            # The scene: the same elements in the same boxes. A state changes style values only.
            ours, theirs = record["target"]["scene"]["elements"], first["target"]["scene"]["elements"]
            assert [(e["id"], e["type"], e["parent"], e["box"]) for e in ours] == [(e["id"], e["type"], e["parent"], e["box"]) for e in theirs]
            changed = {e["id"] for e, f in zip(ours, theirs) if e["style"] != f["style"]}
            moved = {f"b.{identity}" for identity in set(interaction_of(record)) | set(interaction_of(first))}
            assert changed <= moved
            states.add(json.dumps(interaction_of(record), sort_keys=True))
        assert len(states) == len(group)


def test_an_element_keeps_its_identity_and_binding_through_a_session(records):
    by_session = defaultdict(list)
    for record in records:
        by_session[record["diagnostics"]["related"]["session"]].append(record)
    for session in by_session.values():
        seen: dict[str, tuple] = {}
        for record in session:
            for element in record["application"]["bound_elements"]:
                if element["identity"] == "toolbar.sort":
                    continue  # its binding is the next order, which changes with each sort
                kept = (element["role"], json.dumps(element["binding"], sort_keys=True))
                assert seen.setdefault(element["identity"], kept) == kept, (record["id"], element["identity"])


# --- the manifest is for git; the data is not ------------------------------------------


def test_git_ignores_the_data_and_keeps_the_manifest():
    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 0

    dataset = "artifacts/datasets/tiny-v1"
    assert ignored(f"{dataset}/records/first-documents-0.000.json")
    assert ignored(f"{dataset}/images/first-documents-0.000.png")
    assert ignored(f"{dataset}/config.json")
    assert not ignored(f"{dataset}/manifest.json")
    assert generator.default_out(generator.load_config(TINY)).as_posix() == dataset


def test_the_committed_manifest_is_the_tiny_configuration_generated(manifest):
    """Compared by the hashes of the inputs and the targets, which depend on
    this machine's text measurement but not on its rasteriser."""
    committed = json.loads(COMMITTED_MANIFEST.read_text())
    assert committed["configuration"]["sha256"] == sha256(TINY.read_bytes())
    assert committed["generator"] == manifest["generator"] and committed["seed"] == manifest["seed"]
    assert committed["counts"] == manifest["counts"]
    assert committed["asset_provenance"] == manifest["asset_provenance"]
    fields = ("id", "file", "session", "application_state", "layout_family", "visual_preset", "viewport", "inputs_sha256", "target_sha256")
    assert [[entry[f] for f in fields] for entry in committed["records"]] == [[entry[f] for f in fields] for entry in manifest["records"]]


# --- rejected states -------------------------------------------------------------------


def test_a_state_whose_true_scene_is_invalid_is_rejected_with_its_reasons_and_not_written(folder):
    # The warm-paper workspace does not fit a viewport this small.
    config = write_config(folder / "small", tiny_config(viewports=[[480, 300]], visual_presets=["warm-paper"]))
    out = folder / "small" / "out"
    result = run_cli("data", "generate", "--config", config, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    moments = sum(1 + 3 * len(script) for script in tiny_config()["scenarios"].values())
    assert manifest["counts"]["rejected"] == len(manifest["rejected"]) > 0
    assert manifest["counts"]["records"] + manifest["counts"]["rejected"] == moments
    written = {path.stem for path in (out / "records").glob("*.json")} if (out / "records").exists() else set()
    for rejection in manifest["rejected"]:
        assert rejection["reason"] == "scene_invalid"
        assert rejection["problems"] and {problem["code"] for problem in rejection["problems"]} == {"outside_viewport"}
        assert all(problem["element"] and problem["detail"] for problem in rejection["problems"])
        assert rejection["id"] not in written
        assert f"  {rejection['id']}" in result.stdout
    assert written == {entry["id"] for entry in manifest["records"]}
    assert f"Rejected           {len(manifest['rejected'])}" in result.stdout
    assert run_cli("data", "check", out).returncode == 0


# --- configurations that cannot be used --------------------------------------------------


@pytest.mark.parametrize(
    "change, said",
    [
        ({"visual_presets": ["calm-blue", "neon"]}, "visual_presets: 'neon' is not a visual preset"),
        ({"layout_families": ["sidebar-right"]}, "layout_families: 'sidebar-right' is not a layout family"),
        ({"scenarios": {"wander": ["create", "delete"]}}, "scenarios.wander: 'delete' is not an action"),
        ({"scenarios": {"rename": ["create"]}}, "scenarios.rename: a scenario is not named after an action"),
        ({"viewports": [[960, 0]]}, "viewports is not a list of [width, height]"),
        ({"seed": "seven"}, "seed is not a whole number"),
        ({"design": "../elsewhere.json"}, "design is not a path from the repository root"),
        ({"layout": "configs/layout/v0.json"}, "layout: "),
        ({"preset": "calm-blue"}, "'preset' is not a field of a dataset configuration"),
        ({"content": {"words": ["one"]}}, "content does not hold exactly"),
        ({"kind": "design-config"}, 'it is not an object of kind "dataset-config"'),
    ],
)
def test_a_configuration_that_cannot_be_used_is_refused_with_every_reason(folder, change, said):
    where = folder / f"refused-{abs(hash(json.dumps(change, sort_keys=True)))}"
    config = write_config(where, tiny_config(**change))
    result = run_cli("data", "generate", "--config", config, "--out", where / "out")
    assert result.returncode == 2
    assert said in result.stderr
    assert not (where / "out").exists()


def test_a_missing_configuration_is_refused(folder):
    result = run_cli("data", "generate", "--config", folder / "no-such.json", "--out", folder / "no-such-out")
    assert result.returncode == 2 and "does not exist" in result.stderr


def test_every_action_is_one_the_tiny_configuration_or_this_test_runs(folder):
    """The three filter actions and the rest, in one script, so that no action exists untested."""
    config = write_config(
        folder / "all-actions",
        tiny_config(scenarios={"everything": ["create", "create", "open", "edit", "save", "rename", "sort", "filter", "filter-none", "filter-clear", "undo"]}),
    )
    out = folder / "all-actions" / "out"
    assert set(tiny_config(scenarios=json.loads(config.read_text())["scenarios"])["scenarios"]["everything"]) == set(ACTIONS)
    assert run_cli("data", "generate", "--config", config, "--out", out).returncode == 0
    records = [json.loads(path.read_text()) for path in sorted((out / "records").glob("*.json"))]
    after = {record["diagnostics"]["scenario"]["action"]: record for record in records if record["diagnostics"]["scenario"]["phase"] == "result"}
    assert after["filter"]["application"]["state"]["documents"] and after["filter"]["application"]["state"]["filter"]
    assert after["filter-none"]["application"]["state"]["documents"] == []
    assert after["filter-clear"]["application"]["state"]["filter"] == ""
    assert len(after["filter-clear"]["application"]["state"]["documents"]) == 2
