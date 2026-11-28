"""Command-line tests for `renderer check` (test seam 2).

The real command is run on the committed check configuration, in a records
folder of the test's own, and the tests assert on what it wrote: the record,
its support matrix and the doctor record it is tied to. Refusals and failures
are provoked with configurations written here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "configs" / "renderer" / "check-v1.json"
ATTRIBUTES = ["x", "y", "width", "height", "corner_radius", "fill", "opacity"]
needs_apple_gpu = pytest.mark.skipif(not torch.backends.mps.is_available(), reason="PyTorch reports no usable Apple GPU")


def run_cli(*args: str | Path, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "core_ultra", *map(str, args)], capture_output=True, text=True, cwd=cwd, timeout=600)


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("renderer-check")


@pytest.fixture(scope="module")
def run(folder) -> subprocess.CompletedProcess[str]:
    """`renderer check` on the committed configuration, run once."""
    return run_cli("renderer", "check", "--records", folder / "records")


@pytest.fixture(scope="module")
def record(run, folder) -> dict:
    (path,) = (folder / "records" / "renderer").glob("*.json")
    return json.loads(path.read_text())


def small_config() -> dict:
    """The committed configuration cut down to one scene at one scale."""
    config = json.loads(CONFIG.read_text())
    config["scales"] = [1]
    config["scenes"] = [entry for entry in config["scenes"] if entry["name"] == "one-rounded"]
    config["moves"] = config["moves"][:1]
    config["zero_gradients"] = config["zero_gradients"][:1]
    return config


def write(folder: Path, name: str, config: object) -> Path:
    path = folder / name
    path.write_text(json.dumps(config))
    return path


# --- the record ------------------------------------------------------------------


@needs_apple_gpu
def test_the_check_passes_and_says_where_it_saved_its_record(run, folder):
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Check              PASSED" in run.stdout
    (path,) = (folder / "records" / "renderer").glob("*-stage-1-*.json")
    assert f"Saved record       {path}" in run.stdout
    assert f"Record SHA-256     {hashlib.sha256(path.read_bytes()).hexdigest()}" in run.stdout


def test_the_record_is_tied_to_a_doctor_record_saved_beside_it(run, record, folder):
    doctor_path = folder / "records" / record["doctor"]["record"]
    assert hashlib.sha256(doctor_path.read_bytes()).hexdigest() == record["doctor"]["sha256"]
    assert json.loads(doctor_path.read_text())["environment_id"] == record["doctor"]["environment_id"]
    assert f"Doctor record      {doctor_path}" in run.stdout
    assert record["kind"] == "renderer-check" and record["training_renderer_stage"] == 1
    assert record["config"] == json.loads(CONFIG.read_text())


def test_the_support_matrix_lists_each_primitive_whether_it_is_drawn_and_its_gradients(record):
    matrix = {row["primitive"]: row for row in record["support_matrix"]}
    assert list(matrix) == ["rounded rectangle with fill and opacity", "border", "text", "shadow"]

    drawn = matrix["rounded rectangle with fill and opacity"]
    assert drawn["drawn"] is True and drawn["stage"] == 1
    assert [cell["attribute"] for cell in drawn["attributes"]] == ATTRIBUTES
    assert all(cell["gradient"] is True for cell in drawn["attributes"])
    assert drawn["not_differentiable"] == ["drawing order"]

    for name, stage in (("border", 2), ("text", 2), ("shadow", 3)):
        row = matrix[name]
        assert row["drawn"] is False and row["stage"] == stage
        assert row["attributes"] == [] and row["drawn_verified"] is None
    assert matrix["text"]["not_differentiable"] == ["font choice", "shaping", "line wrapping"]
    assert record["not_drawn"] == ["border", "text", "shadow"]
    assert any("past half the box's shorter side" in limit for limit in record["limits"])


@needs_apple_gpu
def test_every_cell_of_the_drawn_primitive_is_verified_on_the_cpu_and_on_the_apple_gpu_path(record):
    drawn = record["support_matrix"][0]
    assert drawn["drawn_verified"] is True
    for cell in drawn["attributes"]:
        assert cell == {"attribute": cell["attribute"], "gradient": True, "finite_differences_on_cpu": True, "apple_gpu_path": True, "verified": True}
    assert record["passed"] is True
    assert record["sections_passed"] == {"finite_differences": True, "apple_gpu_path": True, "moves": True, "zero_gradients": True}


def test_finite_differences_cover_every_attribute_of_every_scene_not_on_kinks(record):
    section = record["finite_differences"]
    assert section["device"] == "cpu" and section["dtype"] == "float64"
    assert section["scenes_left_out"] == ["square-corners", "whole-numbers"]
    scenes = [entry["name"] for entry in record["config"]["scenes"] if not entry.get("on_kinks")]
    seen = {(row["scene"], row["scale"], row["scalar"], row["attribute"]) for row in section["rows"]}
    assert seen == {
        (scene, scale, scalar, attribute)
        for scene in scenes
        for scale in record["config"]["scales"]
        for scalar in ("squared_difference_from_target", "weighted_sum")
        for attribute in ATTRIBUTES
    }
    for row in section["rows"]:
        assert row["passed"] is True
        # A gradient of zero everywhere would agree with anything.
        assert row["largest_gradient"] > 1e-3, row
        assert row["largest_error"] <= section["absolute_tolerance"] + section["relative_tolerance"] * row["largest_gradient"]


@needs_apple_gpu
def test_the_apple_gpu_path_is_run_forward_and_backward_and_its_fallbacks_are_listed(record):
    gpu = record["apple_gpu_path"]
    assert gpu["available"] is True and gpu["dtype"] == "float32"
    assert gpu["ran_without_cpu_fallback"] is True and gpu["error"] is None
    assert gpu["unsupported_operations"] == [] and gpu["cpu_fallback_operations"] == []
    assert gpu["profile"]["ok"] is True and gpu["profile"]["profiler_output_seen"] is True
    assert gpu["profile"]["profiler_reported_no_fallbacks"] is True

    scenes = [entry["name"] for entry in record["config"]["scenes"]]
    assert {(row["scene"], row["scale"]) for row in gpu["forward"]} == {(scene, scale) for scene in scenes for scale in record["config"]["scales"]}
    assert all(row["passed"] and row["largest_difference"] <= gpu["tolerances"]["image_tolerance"] for row in gpu["forward"])
    # Backward is compared wherever finite differences were taken.
    assert {row["scene"] for row in gpu["backward"]} == set(scenes) - {"square-corners", "whole-numbers"}
    assert {row["attribute"] for row in gpu["backward"]} == set(ATTRIBUTES)
    assert all(row["passed"] for row in gpu["backward"])


def test_every_move_lowers_the_render_loss_at_every_step_and_ends_at_zero(record):
    moves = record["moves"]
    assert {row["name"] for row in moves} == {entry["name"] for entry in record["config"]["moves"]}
    for row in moves:
        losses = row["render_loss"]
        assert len(losses) == 9 and losses[-1] == 0.0
        assert all(later < earlier for earlier, later in zip(losses, losses[1:]))
        assert all(slope < 0 for slope in row["slope_along_the_move"])
        assert row["passed"] is True


def test_zero_gradients_are_told_apart_from_a_disconnected_computation(record):
    cases = {(row["name"], row["scale"]): row for row in record["zero_gradients"]}
    apart = {cell["attribute"]: cell for cell in cases[("no-overlap-with-the-target", 1)]["attributes"]}
    assert [apart[name]["state"] for name in ATTRIBUTES] == ["zero", "zero", "non-zero", "non-zero", "zero", "non-zero", "non-zero"]
    # Position is part of the computation and the image depends on it; only the loss does not.
    assert apart["x"]["largest_gradient"] is not None and apart["x"]["image_depends_on_it"] is True
    hidden = cases[("under-an-opaque-element", 1)]["attributes"]
    assert [cell["state"] for cell in hidden] == ["zero"] * 7
    assert not any(cell["image_depends_on_it"] for cell in hidden)
    for row in cases.values():
        assert row["passed"] is True
        assert [cell["state_when_cut_out"] for cell in row["attributes"]] == ["disconnected"] * 7


def test_agreement_with_the_runtime_renderer_is_reported_for_every_valid_scene(record):
    agreement = record["agreement"]
    assert agreement["scenes_left_out"] == ["past-the-viewport"]
    valid = [entry["name"] for entry in record["config"]["scenes"] if not entry.get("leaves_viewport")]
    assert [(row["scene"], row["scale"]) for row in agreement["rows"]] == [(scene, scale) for scene in valid for scale in record["config"]["scales"]]
    for row in agreement["rows"]:
        for comparison in ("training_against_runtime", "training_against_exact_cover", "runtime_against_exact_cover"):
            numbers = row[comparison]
            assert set(numbers) == {"mean_absolute_difference", "share_of_pixels_over_16", "largest_difference"}
            assert 0 <= numbers["mean_absolute_difference"] <= numbers["largest_difference"] <= 255
        # The two renderers differ on a few pixels of a corner and nowhere else.
        assert row["training_against_runtime"]["mean_absolute_difference"] < 1
        assert row["training_against_runtime"]["share_of_pixels_over_16"] < 0.02
        assert row["training_against_exact_cover"]["mean_absolute_difference"] < 0.25
    assert agreement["overall"]["scenes_drawn"] == len(agreement["rows"])


def test_the_text_report_shows_the_matrix_the_checks_and_what_is_not_drawn(run):
    out = run.stdout
    assert "Support matrix" in out
    assert "rounded rectangle with fill and opacity" in out
    for name in ("border", "text", "shadow"):
        assert any(line.strip().startswith(name) and "not drawn" in line for line in out.splitlines())
    for heading in ("Finite differences", "Apple GPU path", "Moves", "Zero gradients", "Agreement"):
        assert heading in out
    assert "Not drawn by this stage, so not compared: border, text, shadow" in out


# --- other outputs, refusals and failures ----------------------------------------------


def test_json_prints_the_record_and_nothing_else_on_stdout(folder):
    result = run_cli("renderer", "check", "--json", "--config", write(folder, "small.json", small_config()), "--records", folder / "json-records")
    printed = json.loads(result.stdout)
    (path,) = (folder / "json-records" / "renderer").glob("*.json")
    assert printed == json.loads(path.read_text())
    assert "Saved record" in result.stderr


def test_a_check_that_fails_exits_1_and_still_writes_the_record(folder):
    """The configuration states that position has a gradient where it has none."""
    config = small_config()
    case = config["zero_gradients"][0]
    case["zero"], case["non_zero"] = ["y", "corner_radius"], ["x", "width", "height", "fill", "opacity"]
    result = run_cli("renderer", "check", "--config", write(folder, "wrong.json", config), "--records", folder / "wrong-records")
    assert result.returncode == 1
    assert "Zero gradients     FAILED" in result.stdout and "Check              FAILED" in result.stdout
    (path,) = (folder / "wrong-records" / "renderer").glob("*.json")
    written = json.loads(path.read_text())
    assert written["passed"] is False and written["sections_passed"]["zero_gradients"] is False
    failed = [cell for cell in written["zero_gradients"][0]["attributes"] if not cell["passed"]]
    assert [(cell["attribute"], cell["expected"], cell["state"]) for cell in failed] == [("x", "non-zero", "zero")]


def test_a_tolerance_nothing_can_meet_leaves_the_cell_not_verified(folder):
    config = small_config()
    config["finite_differences"].update({"absolute_tolerance": 1e-300, "relative_tolerance": 1e-300})
    result = run_cli("renderer", "check", "--config", write(folder, "strict.json", config), "--records", folder / "strict-records")
    assert result.returncode == 1
    assert "NOT VERIFIED" in result.stdout and "Finite differences FAILED" in result.stdout
    (path,) = (folder / "strict-records" / "renderer").glob("*.json")
    cells = json.loads(path.read_text())["support_matrix"][0]["attributes"]
    assert not any(cell["verified"] for cell in cells if cell["finite_differences_on_cpu"] is False)
    assert any(cell["finite_differences_on_cpu"] is False for cell in cells)


def test_a_configuration_that_cannot_be_used_exits_2_with_every_problem_and_writes_nothing(folder):
    config = small_config()
    config["stage"] = 2
    config["scales"] = [0]
    config["scenes"][0]["elements"][0]["box"] = [5, 4, 400, 26]
    config["zero_gradients"][0]["zero"] = ["x"]
    result = run_cli("renderer", "check", "--config", write(folder, "bad.json", config), "--records", folder / "bad-records")
    assert result.returncode == 2
    assert "the check configuration cannot be used (3)" in result.stderr
    assert "stage is 2; the training renderer is at stage 1" in result.stderr
    assert "scales is not a list of numbers above zero" in result.stderr
    assert "zero and non_zero together do not name each of" in result.stderr
    assert not (folder / "bad-records").exists()

    # A scene that is not valid is refused for scene validation's own reasons.
    config = small_config()
    config["scenes"][0]["elements"][0]["box"] = [5, 4, 400, 26]
    result = run_cli("renderer", "check", "--config", write(folder, "invalid.json", config), "--records", folder / "bad-records")
    assert result.returncode == 2 and "outside_viewport" in result.stderr

    result = run_cli("renderer", "check", "--config", folder / "missing.json", "--records", folder / "bad-records")
    assert result.returncode == 2 and "cannot be read" in result.stderr
    result = run_cli("renderer", "check", "--config", write(folder, "list.json", []), "--records", folder / "bad-records")
    assert result.returncode == 2 and "is not a JSON object" in result.stderr
    assert not (folder / "bad-records").exists()


def test_the_caller_cannot_hide_a_cpu_fallback_by_allowing_it_in_the_environment(folder, monkeypatch):
    """The first run on the Apple GPU path is made with the fallback not
    allowed, whatever the environment the command was started in says."""
    if not torch.backends.mps.is_available():
        pytest.skip("PyTorch reports no usable Apple GPU")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    result = run_cli("renderer", "check", "--json", "--config", write(folder, "small-again.json", small_config()), "--records", folder / "environment-records")
    gpu = json.loads(result.stdout)["apple_gpu_path"]
    assert gpu["ran_without_cpu_fallback"] is True and gpu["cpu_fallback_operations"] == []
