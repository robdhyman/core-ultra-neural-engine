"""Command-line tests for the `doctor` verb (test seam 2).

These run the real command in a subprocess on the machine at hand and assert
on what it reports. Nothing is mocked: the tested platform is macOS 27 on an
Apple M5 with 16 GB, and the platform test fails anywhere else on purpose.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "core_ultra", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=300,
    )


@pytest.fixture(scope="module")
def report() -> dict:
    result = run_cli("doctor", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_report_identifies_itself(report):
    assert report["kind"] == "doctor-report"
    assert report["schema_version"] == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", report["created_at"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", report["environment_id"])


def test_report_matches_the_tested_platform(report):
    assert report["os"]["name"] == "macOS"
    assert report["os"]["version"].split(".")[0] == "27"
    assert report["os"]["build"]
    assert report["hardware"]["machine"] == "arm64"
    assert "M5" in report["hardware"]["chip"]
    assert report["hardware"]["cpu_cores_logical"] >= report["hardware"]["cpu_cores_physical"] >= 1
    assert report["memory"]["total_bytes"] == 16 * GIB


def test_report_python_is_the_locked_version(report):
    assert report["python"]["implementation"] == "CPython"
    assert report["python"]["version"].startswith("3.12.")
    assert report["python"]["version"] == ".".join(map(str, sys.version_info[:3]))


def test_report_says_the_apple_gpu_path_is_usable(report):
    mps = report["accelerators"]["mps"]
    assert mps["built"] is True
    assert mps["available"] is True
    assert mps["forward_ok"] is True
    assert mps["backward_ok"] is True
    assert mps["agrees_with_cpu"] is True
    assert mps["usable"] is True
    assert mps["error"] is None
    assert report["accelerators"]["cuda"]["available"] is False
    assert report["accelerators"]["default_device"] == "mps"


def test_report_memory_and_disk(report):
    memory = report["memory"]
    assert 0 < memory["available_bytes"] <= memory["total_bytes"]
    disk = report["disk"]
    assert 0 < disk["free_bytes"] <= disk["total_bytes"]


def test_report_lists_usable_ml_dependencies_with_versions(report):
    dependencies = {entry["name"]: entry for entry in report["dependencies"]}
    assert {"torch", "numpy", "psutil"} <= set(dependencies)
    for entry in dependencies.values():
        assert entry["usable"] is True, entry
        assert re.match(r"\d+\.\d+", entry["version"]), entry
        assert entry["error"] is None
    assert report["problems"] == []


def test_report_carries_nothing_that_identifies_the_person(report):
    import getpass
    import socket

    text = json.dumps(report)
    # Whole words only: a short user name can sit inside a word like "problems".
    assert not re.search(rf"\b{re.escape(getpass.getuser())}\b", text)
    assert not re.search(rf"\b{re.escape(socket.gethostname())}\b", text)
    assert str(Path.home()) not in text


def test_environment_id_is_stable_between_runs(report):
    again = json.loads(run_cli("doctor", "--json").stdout)
    assert again["environment_id"] == report["environment_id"]


def test_plain_output_is_readable_text():
    result = run_cli("doctor")
    assert result.returncode == 0, result.stderr
    for label in ("OS", "Python", "Apple GPU", "Memory", "Disk", "torch", "numpy"):
        assert label in result.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


def test_save_writes_a_machine_readable_record(tmp_path):
    target = tmp_path / "nested" / "doctor.json"
    result = run_cli("doctor", "--save", str(target))
    assert result.returncode == 0, result.stderr
    record = json.loads(target.read_text())
    assert record["kind"] == "doctor-report"
    assert record["os"]["name"] == "macOS"
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert digest in result.stdout
    assert record["environment_id"] in result.stdout


def test_save_without_a_path_uses_the_committed_records_folder(tmp_path):
    result = run_cli("doctor", "--save", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    saved = list((tmp_path / "records" / "doctor").glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text())
    assert record["environment_id"].removeprefix("sha256:")[:12] in saved[0].name


def test_save_never_overwrites_an_existing_record(tmp_path):
    target = tmp_path / "doctor.json"
    target.write_text("{}")
    result = run_cli("doctor", "--save", str(target))
    assert result.returncode != 0
    assert target.read_text() == "{}"


def test_later_verbs_are_not_offered_yet():
    result = run_cli("train")
    assert result.returncode != 0


@pytest.mark.parametrize(
    "path",
    [
        "artifacts/weights/scene-model.safetensors",
        "artifacts/datasets/pilot/000001.json",
        "artifacts/datasets/pilot/000001.png",
        "artifacts/runs/structure-seed0/losses.jsonl",
        "artifacts/runs/structure-seed0/checkpoint.pt",
        "artifacts/use-log/2026-11-24.jsonl",
        "checkpoint.pt",
        "somewhere/else/model.safetensors",
        "somewhere/else/arrays.npz",
    ],
)
def test_weights_datasets_and_run_artifacts_are_ignored(path):
    assert _git_ignores(path)


@pytest.mark.parametrize(
    "path",
    [
        "artifacts/datasets/pilot/manifest.json",
        "artifacts/weights/scene-model.manifest.json",
        "artifacts/weights/scene-model.safetensors.sha256",
        "artifacts/datasets/pilot/SHA256SUMS",
        "records/doctor/20261124T000000Z-0123456789ab.json",
        "records/reports/comparison.md",
        "uv.lock",
    ],
)
def test_manifests_hashes_and_reports_are_not_ignored(path):
    assert not _git_ignores(path)


def _git_ignores(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=REPO_ROOT,
    )
    assert result.returncode in (0, 1), result
    return result.returncode == 0
