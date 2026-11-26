"""Command-line tests for `measure generation` (test seam 2).

The command is run for real on the tiny dataset configuration, which
generates in under two seconds. Its times are real and say nothing about the
pilot; the measurement that does is the committed record, checked at the end
of this file.

The judge of the disk figures is a dataset generated here by `data generate`
and measured with `os.stat`, without the measurement's code.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TINY = REPO_ROOT / "configs" / "data" / "tiny-v1.json"
PILOT = REPO_ROOT / "configs" / "data" / "pilot-v1.json"
COMMITTED = REPO_ROOT / "records" / "measurements" / "generation"
COMMITTED_PILOT_MANIFEST = REPO_ROOT / "artifacts" / "datasets" / "pilot-v1" / "manifest.json"
RUNS = 2


def run_cli(*args: str | Path, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "core_ultra", *map(str, args)], capture_output=True, text=True, cwd=cwd, timeout=600)


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> dict:
    """One real run of `measure generation` on the tiny configuration."""
    root = tmp_path_factory.mktemp("measure-generation")
    result = run_cli("measure", "generation", "--config", TINY, "--runs", RUNS, "--records", root / "records")
    assert result.returncode == 0, result.stderr
    saved = sorted((root / "records" / "measurements" / "generation").glob("*.json"))
    assert len(saved) == 1
    return {"result": result, "root": root, "path": saved[0], "record": json.loads(saved[0].read_text())}


@pytest.fixture(scope="module")
def record(run) -> dict:
    return run["record"]


@pytest.fixture(scope="module")
def dataset(run) -> Path:
    """The tiny dataset, generated here to measure the files by hand."""
    out = run["root"] / "dataset"
    assert run_cli("data", "generate", "--config", TINY, "--out", out).returncode == 0
    return out


def sizes(folder: Path, allocated: bool = False) -> int:
    return sum((path.stat().st_blocks * 512 if allocated else path.stat().st_size) for path in folder.rglob("*") if path.is_file())


def test_the_record_identifies_itself_the_configuration_and_the_dataset(record, dataset):
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert record["kind"] == "generation-measurement" and record["schema_version"] == 1
    assert record["configuration"] == {"name": "tiny", "version": 1, "sha256": hashlib.sha256(TINY.read_bytes()).hexdigest(), "seed": 20261126}
    assert record["dataset"]["records"] == record["dataset"]["images"] == manifest["counts"]["records"] == 82
    assert record["dataset"]["sessions"] == manifest["counts"]["sessions"]
    assert record["dataset"]["manifest_sha256"] == hashlib.sha256((dataset / "manifest.json").read_bytes()).hexdigest()
    assert record["generator"]["name"] == manifest["generator"]["name"] and record["generator"]["version"] == manifest["generator"]["version"]


def test_the_measurement_is_tied_to_a_saved_doctor_record(run, record):
    doctor_path = run["root"] / "records" / record["doctor"]["record"]
    assert doctor_path.is_file()
    assert hashlib.sha256(doctor_path.read_bytes()).hexdigest() == record["doctor"]["sha256"]
    assert json.loads(doctor_path.read_text())["environment_id"] == record["doctor"]["environment_id"]
    assert run["path"].name.endswith(f"-tiny-v1-{record['doctor']['environment_id'].removeprefix('sha256:')[:12]}.json")


def test_every_run_is_the_whole_command_timed_with_its_memory_and_the_state_of_the_machine(record):
    assert len(record["runs"]) == len(record["conditions"]) == RUNS
    for measured in record["runs"]:
        assert measured["seconds"] > 0
        # A process cannot use more processor time than its cores allow, nor run without any.
        used = measured["processor_seconds"]["user"] + measured["processor_seconds"]["system"]
        assert 0 < used < 64 * measured["seconds"]
        assert 32 * 1024**2 < measured["peak_resident_bytes"] < 64 * 1024**3
        assert measured["manifest_sha256"] == record["dataset"]["manifest_sha256"]
    assert record["runs_wrote_the_same_manifest"] is True
    assert record["peak_resident_bytes"] == max(measured["peak_resident_bytes"] for measured in record["runs"])
    for conditions in record["conditions"]:
        assert set(conditions) == {"memory_available_bytes", "swap_used_bytes", "power_source", "low_power_mode"}
    assert "data generate" in record["command"] and record["definitions"]["time"] and record["definitions"]["disk"]


def test_the_time_per_example_is_the_median_run_divided_by_the_records(record):
    seconds = sorted(measured["seconds"] for measured in record["runs"])
    median = (seconds[0] + seconds[1]) / 2
    timing = record["time"]
    assert timing["seconds"] == {"median": pytest.approx(median), "least": seconds[0], "most": seconds[-1]}
    assert timing["seconds_per_example"] == pytest.approx(median / 82)
    assert timing["examples_per_second"] == pytest.approx(82 / median)


def test_the_disk_figures_are_the_files_data_generate_writes(record, dataset):
    disk = record["disk"]
    by_hand = {
        "records": sizes(dataset / "records"),
        "images": sizes(dataset / "images"),
        "stress": 0,
        "manifest": (dataset / "manifest.json").stat().st_size,
        "config": (dataset / "config.json").stat().st_size,
    }
    assert disk["bytes"] == {**by_hand, "total": sizes(dataset)}
    assert disk["files"] == {"records": 82, "images": 82, "stress": 0, "manifest": 1, "config": 1, "total": 166}
    assert disk["allocated_bytes"]["total"] == sizes(dataset, allocated=True) >= disk["bytes"]["total"]
    per_example = disk["per_example"]
    assert per_example["record_bytes"] == pytest.approx(by_hand["records"] / 82)
    assert per_example["image_bytes"] == pytest.approx(by_hand["images"] / 82)
    assert per_example["manifest_bytes"] == pytest.approx(by_hand["manifest"] / 82)
    # What grows with the dataset: the records, the images and the manifest. Not the configuration.
    assert per_example["bytes"] == pytest.approx((by_hand["records"] + by_hand["images"] + by_hand["manifest"]) / 82)
    assert per_example["allocated_bytes"] >= per_example["bytes"]


def test_projections_are_labelled_as_arithmetic_and_follow_from_the_measurement(record):
    projections = record["projections"]
    assert "not a measurement" in projections["basis"]
    assert list(projections["examples"]) == ["5000", "10000", "20000"]
    fixed = record["disk"]["bytes"]["stress"] + record["disk"]["bytes"]["config"]
    for size, projected in projections["examples"].items():
        assert projected["seconds"] == pytest.approx(record["time"]["seconds_per_example"] * int(size))
        assert projected["bytes"] == pytest.approx(record["disk"]["per_example"]["bytes"] * int(size) + fixed)
        assert projected["allocated_bytes"] >= projected["bytes"]
    assert any("projected sizes" in line for line in record["not_measured"])


def test_the_plain_output_reports_the_measurement_and_where_it_was_saved(run, record):
    stdout = run["result"].stdout
    assert "Configuration      tiny version 1" in stdout
    assert "82 records and images from 4 scripted sessions" in stdout
    assert f"Runs               {RUNS}," in stdout and "per example" in stdout
    assert "arithmetic, not measurements" in stdout
    assert f"Saved record       {run['path']}" in stdout
    assert f"Record SHA-256     {hashlib.sha256(run['path'].read_bytes()).hexdigest()}" in stdout
    # Progress goes to stderr, one line for each run.
    assert run["result"].stderr.count("data generate --config") == RUNS


def test_the_record_carries_nothing_that_identifies_the_person_and_leaves_no_dataset_behind(run):
    text = run["path"].read_text()
    for private in (getpass.getuser(), socket.gethostname().split(".")[0], str(Path.home()), str(run["root"])):
        assert private not in text
    assert not list(run["root"].rglob("run-*"))


def test_json_output_is_the_saved_record(tmp_path):
    result = run_cli("measure", "generation", "--config", TINY, "--runs", 1, "--records", tmp_path, "--json")
    assert result.returncode == 0, result.stderr
    saved = next((tmp_path / "measurements" / "generation").glob("*.json"))
    assert json.loads(result.stdout) == json.loads(saved.read_text())
    assert len(json.loads(result.stdout)["runs"]) == 1


def test_a_configuration_that_cannot_be_used_is_refused_before_anything_runs(tmp_path):
    missing = run_cli("measure", "generation", "--config", tmp_path / "none.json", "--records", tmp_path / "records")
    assert missing.returncode == 2 and "does not exist" in missing.stderr
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**json.loads(TINY.read_text()), "viewports": []}))
    refused = run_cli("measure", "generation", "--config", bad, "--records", tmp_path / "records")
    assert refused.returncode == 2 and "viewports" in refused.stderr
    none = run_cli("measure", "generation", "--config", TINY, "--runs", 0, "--records", tmp_path / "records")
    assert none.returncode == 2 and "--runs" in none.stderr
    assert not (tmp_path / "records").exists()


def test_a_measurement_is_refused_while_another_is_running(tmp_path):
    # Stands in for a running `measure generation`: only its command line matters to the check.
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "core_ultra", "measure", "generation"])
    try:
        result = run_cli("measure", "generation", "--config", TINY, "--records", tmp_path / "records")
    finally:
        other.kill()
        other.wait()
    assert result.returncode == 1
    assert "another measurement is running" in result.stderr and str(other.pid) in result.stderr
    assert not (tmp_path / "records").exists()


def test_the_plain_output_states_the_conditions_the_runs_were_made_in(run, record):
    line = next(line for line in run["result"].stdout.splitlines() if line.startswith("Conditions"))
    assert str(record["conditions"][0]["power_source"]) in line and "Low Power Mode" in line and "swap" in line


# --- the committed measurement of the pilot ------------------------------------------------


def committed() -> dict:
    pilot_sha256 = hashlib.sha256(PILOT.read_bytes()).hexdigest()
    records = [json.loads(path.read_text()) for path in sorted(COMMITTED.glob("*.json"))]
    matching = [record for record in records if record["configuration"]["sha256"] == pilot_sha256]
    assert matching, "no committed generation measurement is of configs/data/pilot-v1.json as it stands"
    return matching[-1]


def test_the_committed_measurement_is_of_the_pilot_dataset_as_committed():
    record = committed()
    manifest = json.loads(COMMITTED_PILOT_MANIFEST.read_text())
    assert record["dataset"]["manifest_sha256"] == hashlib.sha256(COMMITTED_PILOT_MANIFEST.read_bytes()).hexdigest()
    assert record["dataset"]["records"] == manifest["counts"]["records"]
    assert record["dataset"]["stress_tests"] == manifest["counts"]["stress_tests"]
    assert len(record["runs"]) >= 3 and record["runs_wrote_the_same_manifest"] is True
    assert record["disk"]["files"]["records"] == record["disk"]["files"]["images"] == manifest["counts"]["records"]
    assert record["disk"]["bytes"]["manifest"] == COMMITTED_PILOT_MANIFEST.stat().st_size
    assert record["time"]["seconds_per_example"] > 0 and record["disk"]["per_example"]["bytes"] > 0


def test_the_committed_measurement_is_tied_to_a_committed_doctor_record():
    record = committed()
    doctor_path = REPO_ROOT / "records" / record["doctor"]["record"]
    assert doctor_path.is_file()
    assert hashlib.sha256(doctor_path.read_bytes()).hexdigest() == record["doctor"]["sha256"]
    assert json.loads(doctor_path.read_text())["problems"] == []
