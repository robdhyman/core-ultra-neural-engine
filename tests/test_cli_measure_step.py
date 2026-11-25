"""Command-line tests for `measure step` (test seam 2).

The command is run for real on the machine at hand, on a configuration small
enough to finish in seconds. Its numbers are real but say nothing about the
planned model; the measurement that does is the committed record, checked at
the end of this file. The selection rule is tested with hand-written
measurements, because the cases it must handle (a size that does not fit, a
step that is too slow) cannot be produced on demand.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import math
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from core_ultra import step_measurement

REPO_ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3

TINY_CONFIG = {
    "name": "tiny",
    "version": 0,
    "planned_parameter_range": [10_000, 40_000],
    "sizes": [{"name": "d32-l1", "d_model": 32, "layers": 1, "heads": 4, "feedforward": 64}],
    "batch_sizes": [2, 4],
    "reference_batch_size": 2,
    "devices": ["mps", "cpu"],
    "dtype": "float32",
    "warmup_steps": 1,
    "measured_steps": 3,
    "phase_steps": 1,
    "seed": 0,
    "optimizer": {"name": "AdamW", "learning_rate": 0.0001, "weight_decay": 0.01},
    "selection": {
        "max_peak_footprint_fraction_of_memory": 0.5,
        "reference_epoch_examples": 20_000,
        "max_seconds_per_reference_epoch": 300,
    },
    "projection": {"pilot_examples": [200, 500], "full_examples": [5_000], "epochs": [10, 100]},
}


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "core_ultra", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=600,
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> dict:
    """One real run of the command on the tiny configuration."""
    folder = tmp_path_factory.mktemp("measure-step")
    config_path = folder / "tiny.json"
    config_path.write_text(json.dumps(TINY_CONFIG))
    records = folder / "records"
    result = run_cli("measure", "step", "--config", str(config_path), "--records", str(records))
    assert result.returncode == 0, result.stderr
    saved = list((records / "measurements" / "training-step").glob("*.json"))
    assert len(saved) == 1
    return {
        "result": result,
        "records": records,
        "path": saved[0],
        "record": json.loads(saved[0].read_text()),
    }


@pytest.fixture(scope="module")
def record(run) -> dict:
    return run["record"]


def test_record_identifies_itself(record):
    assert record["kind"] == "training-step-measurement"
    assert record["schema_version"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["created_at"])
    assert record["config"] == TINY_CONFIG


def test_every_measurement_is_tied_to_a_saved_doctor_record(run, record):
    doctor_path = run["records"] / record["doctor"]["record"]
    assert hashlib.sha256(doctor_path.read_bytes()).hexdigest() == record["doctor"]["sha256"]
    doctor_record = json.loads(doctor_path.read_text())
    assert doctor_record["kind"] == "doctor-report"
    assert doctor_record["environment_id"] == record["doctor"]["environment_id"]
    for entry in record["measurements"]:
        assert entry["environment_id"] == doctor_record["environment_id"]


def test_every_size_batch_and_device_is_measured(record):
    cases = {(e["size"], e["batch_size"], e["device"]) for e in record["measurements"]}
    assert cases == {
        ("d32-l1", batch, device) for batch in (2, 4) for device in ("mps", "cpu")
    }
    for entry in record["measurements"]:
        assert entry["ok"] is True, entry["error"]


def test_a_complete_step_is_timed_in_32_bit_floats_at_the_planned_positions(record):
    for entry in record["measurements"]:
        assert entry["dtype"] == "float32"
        assert entry["positions"] == {"bound": 32, "structural": 16, "conditioning": 3}
        assert entry["parameters"] > 0
        assert entry["torch_threads"] >= 1
        steps = entry["step_seconds"]
        assert len(steps["samples"]) == TINY_CONFIG["measured_steps"]
        assert 0 < steps["min"] <= steps["median"] <= steps["max"]
        assert entry["examples_per_second"] == pytest.approx(entry["batch_size"] / steps["median"])
        # Forward, loss, backward and update each took measurable time.
        assert set(entry["phase_seconds"]) == {"forward", "loss", "backward", "update"}
        assert all(seconds > 0 for seconds in entry["phase_seconds"].values())
        assert entry["losses_finite"] is True


def test_peak_memory_is_read_for_every_case(record):
    for entry in record["measurements"]:
        memory = entry["memory"]
        assert memory["process_peak_footprint_bytes"] >= memory["process_footprint_at_start_bytes"] > 0
        assert memory["process_peak_footprint_bytes"] < 16 * GIB
        if entry["device"] == "mps":
            assert memory["mps_peak_driver_allocated_bytes"] > 0
            assert memory["mps_peak_current_allocated_bytes"] > 0
        else:
            assert memory["mps_peak_driver_allocated_bytes"] is None


def test_the_state_of_the_machine_is_recorded_for_every_case(record):
    for entry in record["measurements"]:
        conditions = entry["conditions"]
        assert conditions["memory_available_bytes"] > 0
        assert conditions["swap_used_bytes"] >= 0
        assert conditions["power_source"] in ("AC Power", "Battery Power")
        assert conditions["low_power_mode"] in (True, False)
    summary = record["conditions"]
    throttled = summary["low_power_mode_seen"] or summary["power_sources"] != ["AC Power"]
    assert ("throttled" in summary["statement"]) is throttled


def test_apple_gpu_cases_run_without_the_cpu_fallback_switch(record):
    for entry in record["measurements"]:
        if entry["device"] == "mps":
            assert entry["mps_fallback_enabled"] is False
            assert entry["unsupported_operations"] == []
            assert entry["cpu_fallback_operations"] == []


def test_unsupported_operations_and_cpu_fallbacks_are_listed(record):
    gpu = record["apple_gpu_path"]
    assert gpu["unsupported_operations"] == []
    assert gpu["cpu_fallback_operations"] == []
    assert "No unsupported operation" in gpu["statement"]
    assert [audit["size"] for audit in gpu["audits"]] == ["d32-l1"]
    audit = gpu["audits"][0]
    assert audit["ok"] is True
    assert audit["profiler_output_seen"] is True
    assert audit["profiler_reported_no_fallbacks"] is True
    assert {copy["kind"] for copy in audit["copies"]} >= {"CPU to MPS"}


def test_the_apple_gpu_path_is_compared_with_the_cpu(record):
    for row in record["device_comparison"]:
        assert set(row["median_step_seconds"]) == {"mps", "cpu"}
        assert row["faster_device"] in ("mps", "cpu")
        assert row["cpu_step_divided_by_mps_step"] > 0


def test_a_starting_size_is_chosen_by_the_recorded_rule(record):
    selection = record["selection"]
    assert selection["chosen"] == "d32-l1"
    assert selection["limit"] == []
    assert selection["rule"]["memory_budget_bytes"] == 8 * GIB
    assert selection["candidates"][0]["eligible"] is True


def test_projections_are_labelled_and_derived_from_the_measured_step(record):
    projections = record["projections"]
    assert projections["label"] == "projection"
    assert "no figure from a paper" in projections["basis"]
    assert projections["size"] == record["selection"]["chosen"]
    medians = {
        entry["batch_size"]: entry["step_seconds"]["median"]
        for entry in record["measurements"]
        if entry["device"] == "mps"
    }
    assert [group["batch_size"] for group in projections["by_batch_size"]] == [2, 4]
    for group in projections["by_batch_size"]:
        assert group["median_step_seconds"] == medians[group["batch_size"]]
        runs = {(row["run"], row["examples"], row["epochs"]) for row in group["rows"]}
        assert runs == {
            ("pilot", 200, 10), ("pilot", 200, 100), ("pilot", 500, 10), ("pilot", 500, 100),
            ("full", 5_000, 10), ("full", 5_000, 100),
        }  # fmt: skip
        for row in group["rows"]:
            assert row["steps"] == math.ceil(row["examples"] / group["batch_size"]) * row["epochs"]
            assert row["seconds"] == pytest.approx(row["steps"] * group["median_step_seconds"])
    assert record["not_measured"]


def test_record_carries_nothing_that_identifies_the_person(run):
    text = run["path"].read_text()
    assert not re.search(rf"\b{re.escape(getpass.getuser())}\b", text)
    assert not re.search(rf"\b{re.escape(socket.gethostname())}\b", text)
    assert str(Path.home()) not in text


def test_plain_output_reports_the_measurement_and_where_it_was_saved(run):
    stdout = run["result"].stdout
    for label in ("Measured", "Apple GPU path", "Starting size", "Projections (not measurements)"):
        assert label in stdout
    assert str(run["path"]) in stdout
    assert hashlib.sha256(run["path"].read_bytes()).hexdigest() in stdout
    assert run["record"]["doctor"]["sha256"] in stdout


def test_records_are_never_overwritten(run, record, tmp_path):
    doctor_report = json.loads((run["records"] / record["doctor"]["record"]).read_text())
    step_measurement.save(record, doctor_report, tmp_path)
    with pytest.raises(FileExistsError):
        step_measurement.save(record, doctor_report, tmp_path)


def test_an_unusable_configuration_is_refused_before_anything_runs(tmp_path):
    config_path = tmp_path / "bad.json"
    config_path.write_text(json.dumps({**TINY_CONFIG, "dtype": "float64"}))
    result = run_cli("measure", "step", "--config", str(config_path), "--records", str(tmp_path / "records"))
    assert result.returncode == 2
    assert "float32" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "records").exists()


def test_a_second_measurement_is_refused_while_one_is_running(run, tmp_path):
    # Stands in for a running case: only its command line matters to the check.
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", "core_ultra.step_case"]
    )
    try:
        config_path = tmp_path / "tiny.json"
        config_path.write_text(json.dumps(TINY_CONFIG))
        result = run_cli("measure", "step", "--config", str(config_path), "--records", str(tmp_path / "records"))
    finally:
        other.kill()
        other.wait()
    assert result.returncode == 1
    assert "another measurement is running" in result.stderr
    assert str(other.pid) in result.stderr
    assert not (tmp_path / "records").exists()


def test_a_missing_configuration_is_reported_not_a_crash(tmp_path):
    result = run_cli("measure", "step", "--config", str(tmp_path / "absent.json"))
    assert result.returncode == 2
    assert "does not exist" in result.stderr
    assert "Traceback" not in result.stderr


# --- the selection rule, on hand-written measurements --------------------------

RULE_CONFIG = {
    "planned_parameter_range": [9_000_000, 13_000_000],
    "reference_batch_size": 64,
    "selection": {
        "max_peak_footprint_fraction_of_memory": 0.5,
        "reference_epoch_examples": 20_000,
        "max_seconds_per_reference_epoch": 300,
    },
}


def measured(size: str, parameters: int, *, step: float = 0.1, peak_gib: float = 2.0, **changes) -> dict:
    return {
        "size": size,
        "batch_size": 64,
        "device": "mps",
        "ok": True,
        "error": None,
        "parameters": parameters,
        "step_seconds": {"median": step},
        "memory": {"process_peak_footprint_bytes": int(peak_gib * GIB)},
        "cpu_fallback_operations": [],
        **changes,
    }


def select(*measurements: dict) -> dict:
    return step_measurement.select_starting_size(
        list(measurements), RULE_CONFIG, total_memory_bytes=16 * GIB
    )


def test_rule_chooses_the_eligible_size_nearest_the_middle_of_the_planned_range():
    selection = select(
        measured("below", 6_000_000),
        measured("low", 9_500_000),
        measured("middle", 10_700_000),
        measured("high", 12_600_000),
        measured("above", 17_000_000),
    )
    assert selection["chosen"] == "middle"
    assert selection["limit"] == []
    assert all(candidate["eligible"] for candidate in selection["candidates"])


def test_rule_drops_a_size_over_the_memory_budget():
    selection = select(
        measured("low", 9_500_000),
        measured("middle", 10_700_000, peak_gib=8.5),
    )
    assert selection["chosen"] == "low"
    middle = selection["candidates"][1]
    assert middle["eligible"] is False
    assert middle["limits"] == ["memory"]
    assert "8.50 GiB" in middle["reasons"][0]


def test_rule_drops_a_size_whose_epoch_is_over_the_time_budget():
    # 313 steps per epoch of 20,000 examples at batch 64; 1.0 s per step is 313 s.
    selection = select(
        measured("low", 9_500_000, step=0.5),
        measured("middle", 10_700_000, step=1.0),
    )
    assert selection["chosen"] == "low"
    assert selection["candidates"][1]["limits"] == ["time"]
    assert selection["candidates"][1]["reference_epoch_seconds"] == pytest.approx(313.0)


def test_rule_drops_a_size_that_needed_the_cpu_fallback():
    selection = select(
        measured("low", 9_500_000),
        measured("middle", 10_700_000, cpu_fallback_operations=["aten::example"]),
    )
    assert selection["chosen"] == "low"
    assert "aten::example" in selection["candidates"][1]["reasons"][0]


def test_rule_falls_below_the_range_and_states_memory_as_the_limit():
    selection = select(
        measured("small", 4_000_000),
        measured("below", 6_000_000),
        measured("low", 9_500_000, peak_gib=9.0),
        {
            "size": "middle",
            "batch_size": 64,
            "device": "mps",
            "ok": False,
            "error": {"type": "RuntimeError", "message": "MPS backend out of memory"},
        },
    )
    assert selection["chosen"] == "below"
    assert selection["limit"] == ["memory"]
    assert "limit is memory" in selection["statement"]


def test_rule_chooses_nothing_when_nothing_is_eligible():
    selection = select(measured("low", 9_500_000, step=5.0))
    assert selection["chosen"] is None
    assert selection["limit"] == ["time"]


def test_rule_reads_only_apple_gpu_cases_at_the_reference_batch_size():
    selection = select(
        measured("middle", 10_700_000),
        measured("middle", 10_700_000, device="cpu", step=50.0),
        measured("middle", 10_700_000, batch_size=256, peak_gib=12.0),
    )
    assert [candidate["size"] for candidate in selection["candidates"]] == ["middle"]
    assert selection["chosen"] == "middle"


# --- the committed S0 evidence --------------------------------------------------


def committed_record() -> tuple[Path, dict]:
    config = json.loads((REPO_ROOT / "configs" / "scene-model" / "v1.json").read_text())
    path = REPO_ROOT / config["chosen_from"]["measurement_record"]
    return path, json.loads(path.read_text())


def test_committed_measurement_covers_three_sizes_on_the_apple_gpu_and_the_cpu():
    _, record = committed_record()
    low, high = record["config"]["planned_parameter_range"]
    assert (low, high) == (9_000_000, 13_000_000)
    for device in ("mps", "cpu"):
        entries = [e for e in record["measurements"] if e["device"] == device and e["ok"]]
        assert all(e["dtype"] == "float32" for e in entries)
        assert all(e["positions"]["bound"] == 32 and e["positions"]["structural"] == 16 for e in entries)
        in_range = {e["size"] for e in entries if low <= e["parameters"] <= high}
        assert len(in_range) >= 3, (device, in_range)
        assert all(e["memory"]["process_peak_footprint_bytes"] > 0 for e in entries)


def test_committed_measurement_was_taken_on_ac_power_with_low_power_mode_off():
    _, record = committed_record()
    assert record["conditions"]["power_sources"] == ["AC Power"]
    assert record["conditions"]["low_power_mode_seen"] is False


def test_committed_measurement_is_tied_to_a_committed_doctor_record():
    _, record = committed_record()
    doctor_path = REPO_ROOT / "records" / record["doctor"]["record"]
    assert hashlib.sha256(doctor_path.read_bytes()).hexdigest() == record["doctor"]["sha256"]
    doctor_record = json.loads(doctor_path.read_text())
    assert doctor_record["environment_id"] == record["doctor"]["environment_id"]
    assert all(e["environment_id"] == doctor_record["environment_id"] for e in record["measurements"])


def test_scene_model_configuration_is_the_size_the_measurement_chose():
    config = json.loads((REPO_ROOT / "configs" / "scene-model" / "v1.json").read_text())
    path, record = committed_record()
    assert config["version"] == 1
    assert config["chosen_from"]["measurement_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert config["chosen_from"]["size"] == record["selection"]["chosen"]
    chosen = next(
        e for e in record["measurements"]
        if e["size"] == record["selection"]["chosen"] and e["device"] == "mps" and e["ok"]
    )
    model = config["model"]
    assert (model["d_model"], model["layers"], model["heads"], model["feedforward"]) == (
        chosen["d_model"], chosen["layers"], chosen["heads"], chosen["feedforward"],
    )  # fmt: skip
    assert config["placeholder_parameters"] == chosen["parameters"]
    assert config["positions"] == {"bound": 32, "structural": 16}
    assert config["dtype"] == "float32"
