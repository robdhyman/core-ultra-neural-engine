"""`measure generation`: what one example of a dataset costs to generate and to keep.

The full dataset is sized from this (issue #11). The measurement runs the real
command, `core-ultra data generate`, on a dataset configuration, each run as a
process of its own writing into a new folder that is deleted afterwards, and
reads:

- **Time.** Wall-clock seconds of the whole command: starting Python, loading
  Qt and the font, running the scripted sessions, the reference layout, the
  validators and viewport fitting, drawing every image, writing every file and
  writing the stress-test set and the manifest. Also the processor seconds
  the process used, and its peak resident memory.
- **Disk.** The bytes of the files written, by part, and the bytes the file
  system allocated for them, which is more because a file occupies whole
  blocks.

Per example means divided by the number of dataset records. The time and the
disk of the stress-test set are in the totals, so the per-example time of a
small dataset is higher than that of a large one with the same stress-test
set; `disk.per_example` leaves the stress-test set and the configuration out
and says so.

`projections` multiplies the per-example figures by the sizes the full dataset
may have. They are arithmetic on a measurement, not measurements: a larger
dataset has other scenarios and other content, and nothing here has generated
one.

Every run must write the same manifest, byte for byte, or the record says the
runs disagreed and no figure is given. The record is tied to a doctor record
saved beside it, as a training-step measurement is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core_ultra import doctor, generator, step_measurement

KIND = "generation-measurement"
SCHEMA_VERSION = 1
DEFAULT_RECORDS_ROOT = Path("records")
MEASUREMENTS_DIR = Path("measurements") / "generation"
DEFAULT_RUNS = 3
PROJECTED_EXAMPLES = (5_000, 10_000, 20_000)

TIME_DEFINITION = (
    "Wall-clock seconds from starting `core-ultra data generate` as a process of its own to its exit, "
    "writing a dataset that did not exist into a new folder: Python and Qt starting, the scripted sessions, "
    "the reference layout, the validators, viewport fitting, drawing and encoding every image, writing every "
    "file, the stress-test set and the manifest."
)
DISK_DEFINITION = (
    "`bytes` is the sum of the sizes of the files; `allocated_bytes` is the sum of the blocks the file system "
    "gave them. Per example is the records, the images and the manifest divided by the number of dataset "
    "records; the stress-test set and the configuration do not grow with the dataset and are left out."
)
NOT_MEASURED = [
    "A dataset of the projected sizes. The projections are the per-example figures multiplied out.",
    "Generation with other scenarios, content lengths or viewport sizes than the configuration's.",
    "The time `data check` and `data gallery` take, and the disk a gallery uses.",
    "Disk use on a file system with another block size, or with compression.",
]

Progress = Callable[[str], None]


def measure(config_path: str | Path, doctor_report: dict[str, Any], runs: int = DEFAULT_RUNS, progress: Progress | None = None) -> dict[str, Any]:
    """Generate the dataset of `config_path` `runs` times and return the
    measurement record. Raises `generator.ConfigError` when the configuration
    cannot be used, before anything is run, and `RuntimeError` when a run of
    the command fails."""
    say = progress or (lambda message: None)
    config_path = Path(config_path)
    config = generator.load_config(config_path)
    if runs < 1:
        raise ValueError("runs must be at least 1")

    scratch = Path(tempfile.mkdtemp(prefix="core-ultra-generation-"))
    conditions = []
    measured = []
    disk = None
    counts = None
    try:
        for index in range(1, runs + 1):
            out = scratch / f"run-{index}"
            conditions.append(step_measurement.conditions())
            say(f"[{index}/{runs}] data generate --config {config_path}")
            run = _run(config_path, out)
            manifest_bytes = (out / generator.MANIFEST_NAME).read_bytes()
            run["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
            measured.append(run)
            say(f"        {run['seconds']:.2f} s, peak resident memory {run['peak_resident_bytes'] / 1024**2:.0f} MiB")
            if disk is None:
                disk = _disk(out)
                counts = json.loads(manifest_bytes)["counts"]
            shutil.rmtree(out)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    records = counts["records"]
    same = len({run["manifest_sha256"] for run in measured}) == 1
    seconds = [run["seconds"] for run in measured]
    usable = same and records > 0
    time_summary = {
        "seconds": {"median": statistics.median(seconds), "least": min(seconds), "most": max(seconds)},
        "seconds_per_example": statistics.median(seconds) / records if usable else None,
        "examples_per_second": records / statistics.median(seconds) if usable else None,
    }
    per_example = None
    if usable:
        grows = ("records", "images", "manifest")
        per_example = {
            "record_bytes": disk["bytes"]["records"] / records,
            "image_bytes": disk["bytes"]["images"] / records,
            "manifest_bytes": disk["bytes"]["manifest"] / records,
            "bytes": sum(disk["bytes"][part] for part in grows) / records,
            "allocated_bytes": sum(disk["allocated_bytes"][part] for part in grows) / records,
        }
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": doctor_report["project"],
        "doctor": {
            "environment_id": doctor_report["environment_id"],
            "sha256": hashlib.sha256(doctor.to_json(doctor_report).encode()).hexdigest(),
            # Relative to the records folder.
            "record": _doctor_record_name(doctor_report),
        },
        "command": "core-ultra data generate --config <configuration> --out <a new folder>",
        "configuration": {"name": config.name, "version": config.version, "sha256": config.sha256, "seed": config.seed},
        "generator": {"name": generator.GENERATOR_NAME, "version": generator.GENERATOR_VERSION},
        "dataset": {
            "sessions": counts["sessions"],
            "records": records,
            "images": records,
            "application_states": counts["application_states"],
            "rejected": counts["rejected"],
            "stress_tests": counts.get("stress_tests", 0),
            "manifest_sha256": measured[0]["manifest_sha256"],
        },
        "definitions": {"time": TIME_DEFINITION, "disk": DISK_DEFINITION, "per_example": "divided by the number of dataset records"},
        "not_measured": NOT_MEASURED,
        "conditions": conditions,
        "runs": measured,
        "runs_wrote_the_same_manifest": same,
        "time": time_summary,
        "peak_resident_bytes": max(run["peak_resident_bytes"] for run in measured),
        "disk": {**disk, "per_example": per_example},
        "projections": _projections(time_summary, per_example, disk) if usable else None,
    }


def save(record: dict[str, Any], doctor_report: dict[str, Any], root: Path) -> dict[str, Any]:
    """Write the doctor record and the measurement record under `root` and
    return their paths and hashes. Records are evidence, so an existing file
    is never overwritten."""
    doctor_path = root / record["doctor"]["record"]
    doctor_digest = doctor.save_record(doctor_report, doctor_path)
    stamp = re.sub(r"[-:]", "", record["created_at"])
    short_id = record["doctor"]["environment_id"].removeprefix("sha256:")[:12]
    path = root / MEASUREMENTS_DIR / f"{stamp}-{record['configuration']['name']}-v{record['configuration']['version']}-{short_id}.json"
    data = to_json(record).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
    return {
        "measurement": {"path": path, "sha256": hashlib.sha256(data).hexdigest()},
        "doctor": {"path": doctor_path, "sha256": doctor_digest},
    }


def to_json(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2) + "\n"


def to_text(record: dict[str, Any]) -> str:
    configuration, dataset, timing, disk = record["configuration"], record["dataset"], record["time"], record["disk"]
    seconds = timing["seconds"]
    lines = [
        f"Core Ultra generation measurement  {record['created_at']}",
        f"Environment        {record['doctor']['environment_id']}",
        f"Doctor record      {record['doctor']['record']}",
        f"Configuration      {configuration['name']} version {configuration['version']}, seed {configuration['seed']}",
        f"Dataset            {dataset['records']} records and images from {dataset['sessions']} scripted sessions, "
        f"{dataset['rejected']} rejected, {dataset['stress_tests']} stress tests",
        f"Runs               {len(record['runs'])}, each the whole command as a process of its own: "
        + ", ".join(f"{run['seconds']:.2f} s" for run in record["runs"]),
        f"Time               median {seconds['median']:.2f} s (least {seconds['least']:.2f}, most {seconds['most']:.2f})",
    ]
    before = record["conditions"]
    free = [state["memory_available_bytes"] for state in before if state["memory_available_bytes"] is not None]
    swap = [state["swap_used_bytes"] for state in before if state["swap_used_bytes"] is not None]
    power = sorted({str(state["power_source"]) for state in before})
    low = sorted({{True: "on", False: "off", None: "unknown"}[state["low_power_mode"]] for state in before})
    # Before the runs, where the state of the machine belongs.
    lines.insert(
        5,
        f"Conditions         power {', '.join(power)}; Low Power Mode {', '.join(low)}; least free memory before a run "
        f"{_size(min(free)) if free else 'unknown'}; most swap in use {_size(max(swap)) if swap else 'unknown'}",
    )
    if not record["runs_wrote_the_same_manifest"]:
        lines.append("                   the runs did not write the same manifest, so no figure per example is given")
    if timing["seconds_per_example"] is not None:
        lines.append(f"  per example      {1000 * timing['seconds_per_example']:.1f} ms ({timing['examples_per_second']:.1f} examples a second)")
    lines.append(f"Peak memory        {record['peak_resident_bytes'] / 1024**2:.0f} MiB resident, the largest of the runs")
    lines.append(f"Disk               {_size(disk['bytes']['total'])} written, {_size(disk['allocated_bytes']['total'])} allocated")
    for part in ("records", "images", "stress", "manifest", "config"):
        lines.append(f"  {part:<16} {_size(disk['bytes'][part])} in {disk['files'][part]} files")
    per_example = disk["per_example"]
    if per_example is not None:
        lines.append(
            f"  per example      {_size(per_example['bytes'])} ({_size(per_example['record_bytes'])} record, {_size(per_example['image_bytes'])} image, "
            f"{_size(per_example['manifest_bytes'])} of manifest), {_size(per_example['allocated_bytes'])} allocated"
        )
    if record["projections"] is not None:
        lines.append("Projections        the per-example figures multiplied out; arithmetic, not measurements")
        for size, projected in record["projections"]["examples"].items():
            lines.append(
                f"  {int(size):>6} examples  {_duration(projected['seconds'])}, {_size(projected['bytes'])} written, {_size(projected['allocated_bytes'])} allocated"
            )
    return "\n".join(lines) + "\n"


def _run(config_path: Path, out: Path) -> dict[str, Any]:
    """One run of the real command in a process of its own."""
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-m", "core_ultra", "data", "generate", "--config", str(config_path), "--out", str(out)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # wait4 gives the processor time and the peak memory of this child alone.
    said = process.stderr.read()
    _, status, usage = os.wait4(process.pid, 0)
    seconds = time.perf_counter() - started
    process.returncode = os.waitstatus_to_exitcode(status)
    process.stderr.close()
    if process.returncode != 0:
        raise RuntimeError(f"`data generate` exited {process.returncode}: {said.decode(errors='replace').strip()}")
    return {
        "seconds": seconds,
        "processor_seconds": {"user": usage.ru_utime, "system": usage.ru_stime},
        # macOS reports the peak resident set size in bytes.
        "peak_resident_bytes": usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024,
    }


def _disk(folder: Path) -> dict[str, Any]:
    """The files of a written dataset by part: how many, their sizes and what
    the file system allocated for them."""
    parts = {"records": "records", "images": "images", "stress": "stress"}
    sizes = dict.fromkeys(("records", "images", "stress", "manifest", "config"), 0)
    allocated = dict(sizes)
    files = dict(sizes)
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(folder)
        if relative.parts[0] in parts:
            part = parts[relative.parts[0]]
        elif relative.as_posix() == generator.MANIFEST_NAME:
            part = "manifest"
        elif relative.as_posix() == generator.CONFIG_NAME:
            part = "config"
        else:
            raise RuntimeError(f"{relative} is not a file `data generate` writes")
        status = path.stat()
        sizes[part] += status.st_size
        allocated[part] += status.st_blocks * 512
        files[part] += 1
    return {
        "bytes": {**sizes, "total": sum(sizes.values())},
        "allocated_bytes": {**allocated, "total": sum(allocated.values())},
        "files": {**files, "total": sum(files.values())},
    }


def _projections(timing: dict[str, Any], per_example: dict[str, Any], disk: dict[str, Any]) -> dict[str, Any]:
    fixed = disk["bytes"]["stress"] + disk["bytes"]["config"]
    fixed_allocated = disk["allocated_bytes"]["stress"] + disk["allocated_bytes"]["config"]
    return {
        "basis": (
            "The measured seconds per example and bytes per example multiplied by the number of examples, plus the "
            "stress-test set and the configuration once. Arithmetic on this measurement, not a measurement: no dataset "
            "of these sizes was generated, and a larger one has other scenarios and content."
        ),
        "examples": {
            str(size): {
                "seconds": timing["seconds_per_example"] * size,
                "bytes": per_example["bytes"] * size + fixed,
                "allocated_bytes": per_example["allocated_bytes"] * size + fixed_allocated,
            }
            for size in PROJECTED_EXAMPLES
        },
    }


def _doctor_record_name(report: dict[str, Any]) -> str:
    return doctor.default_record_path(report).relative_to(DEFAULT_RECORDS_ROOT).as_posix()


def _size(count: float) -> str:
    if count >= 1024**3:
        return f"{count / 1024**3:.2f} GiB"
    if count >= 1024**2:
        return f"{count / 1024**2:.1f} MiB"
    return f"{count / 1024:.1f} KiB"


def _duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.1f} min"
