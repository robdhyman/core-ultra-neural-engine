"""Measure a complete training step on this machine (spec milestone S0).

`measure` runs every case of a configuration in its own interpreter, ties the
results to a doctor report, lists what the Apple GPU path could not run,
chooses a starting model size by the configuration's rule and projects run
durations from the measured step. The result is plain JSON-compatible data
with no host name, user name or absolute path, because records are committed
to a public repository.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core_ultra import apple_gpu_path, doctor

SCHEMA_VERSION = 1
DEFAULT_CONFIG = Path("configs") / "measure" / "training-step-v1.json"
DEFAULT_RECORDS_ROOT = Path("records")
MEASUREMENTS_DIR = Path("measurements") / "training-step"

STEP_DEFINITION = (
    "One step is zeroing gradients, the forward pass, the loss, the backward pass and the "
    "optimiser update, on a batch already on the device. On the Apple GPU path the clock "
    "stops only after the device has finished its queued work."
)
PEAK_MEMORY_DEFINITION = (
    "process_peak_footprint_bytes is the lifetime peak of the process's physical footprint as "
    "macOS accounts it (proc_pid_rusage), read after the timed steps. It includes the Python "
    "interpreter, PyTorch and, on Apple silicon, memory held for the GPU. Each case runs in "
    "its own process."
)
NOT_MEASURED = [
    "the render loss and the training renderer (S3)",
    "the minimum-cost assignment of structural slots inside the structure loss",
    "loading and batching real dataset records",
    "validation, checkpointing and logging",
    "whether the model learns anything: inputs and targets are random numbers",
]

_POWER_SOURCE = re.compile(r"Now drawing from '([^']+)'")
_LOW_POWER_MODE = re.compile(r"^\s*lowpowermode\s+(\d)", re.MULTILINE)
_REQUIRED_KEYS = (
    "name",
    "version",
    "planned_parameter_range",
    "sizes",
    "batch_sizes",
    "reference_batch_size",
    "devices",
    "dtype",
    "warmup_steps",
    "measured_steps",
    "seed",
    "optimizer",
    "selection",
    "projection",
)

Progress = Callable[[str], None]


class ConfigError(ValueError):
    """The measurement configuration cannot be used."""


def other_measurements() -> list[int]:
    """Process ids of training-step measurements already running on this machine.

    Two measurements that overlap share the GPU and the CPU, and neither
    reports an error: the steps are only slower. So a second one is refused.
    """
    try:
        import psutil
    except ImportError:
        return []
    try:
        own = {os.getpid(), *(parent.pid for parent in psutil.Process().parents())}
    except psutil.Error:
        own = {os.getpid()}
    found = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        arguments = process.info["cmdline"] or []
        if process.info["pid"] in own:
            continue
        is_case = "core_ultra.step_case" in arguments
        is_command = any(
            Path(argument).name in ("core-ultra", "core_ultra") for argument in arguments
        ) and any(pair == ("measure", "step") for pair in zip(arguments, arguments[1:]))
        if is_case or is_command:
            found.append(process.info["pid"])
    return sorted(found)


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist") from None
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from None
    missing = [key for key in _REQUIRED_KEYS if key not in config]
    if missing:
        raise ConfigError(f"{path} is missing {', '.join(missing)}")
    if config["dtype"] != "float32":
        raise ConfigError("only float32 is measured: the Apple GPU path has no 64-bit floats")
    if config["reference_batch_size"] not in config["batch_sizes"]:
        raise ConfigError("reference_batch_size must be one of batch_sizes")
    if not config["sizes"] or not config["devices"]:
        raise ConfigError("at least one size and one device are needed")
    return config


def measure(
    config: dict[str, Any],
    doctor_report: dict[str, Any],
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Run every case of `config` on this machine and return the measurement record."""
    say = progress or (lambda message: None)
    environment_id = doctor_report["environment_id"]
    cases = [
        (size, batch_size, device)
        for size in config["sizes"]
        for batch_size in config["batch_sizes"]
        for device in config["devices"]
    ]
    measurements = []
    for index, (size, batch_size, device) in enumerate(cases, start=1):
        say(f"[{index}/{len(cases)}] {size['name']} batch {batch_size} on {device}")
        entry = _measure_case(config, size, batch_size, device)
        entry["environment_id"] = environment_id
        measurements.append(entry)
        say(f"        {_one_line(entry)}")

    audits = []
    if "mps" in config["devices"]:
        for size in config["sizes"]:
            say(f"[audit] {size['name']} batch {config['reference_batch_size']} on mps")
            audits.append(_audit_apple_gpu_path(config, size))

    selection = select_starting_size(
        measurements, config, total_memory_bytes=doctor_report["memory"]["total_bytes"]
    )
    return {
        "kind": "training-step-measurement",
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": doctor_report["project"],
        "doctor": {
            "environment_id": environment_id,
            "sha256": hashlib.sha256(doctor.to_json(doctor_report).encode()).hexdigest(),
            # Relative to the records folder.
            "record": _doctor_record_name(doctor_report),
        },
        "config": config,
        "config_sha256": _canonical_sha256(config),
        "definitions": {"step": STEP_DEFINITION, "peak_memory": PEAK_MEMORY_DEFINITION},
        "not_measured": NOT_MEASURED,
        "conditions": _conditions_summary(measurements),
        "measurements": measurements,
        "device_comparison": _device_comparison(measurements),
        "apple_gpu_path": _apple_gpu_path_summary(measurements, audits),
        "selection": selection,
        "projections": _projections(measurements, config, selection["chosen"]),
    }


def select_starting_size(
    measurements: list[dict[str, Any]],
    config: dict[str, Any],
    total_memory_bytes: int | None,
) -> dict[str, Any]:
    """Apply the configuration's rule to the Apple GPU measurements.

    A size is eligible when its step at the reference batch size ran on the
    Apple GPU path without a CPU fallback, its peak footprint stayed inside
    the memory budget and one reference epoch stayed inside the time budget.
    Among eligible sizes inside the planned range the one nearest the middle
    of the range is chosen. If none is eligible there, the largest eligible
    size below the range is chosen and the limit is named.
    """
    rule = config["selection"]
    low, high = config["planned_parameter_range"]
    reference_batch = config["reference_batch_size"]
    memory_budget = (
        None
        if total_memory_bytes is None
        else int(total_memory_bytes * rule["max_peak_footprint_fraction_of_memory"])
    )
    epoch_steps = math.ceil(rule["reference_epoch_examples"] / reference_batch)

    candidates = []
    for entry in measurements:
        if entry["device"] != "mps" or entry["batch_size"] != reference_batch:
            continue
        reasons: list[str] = []
        limits: set[str] = set()
        epoch_seconds = None
        if not entry["ok"]:
            reasons.append(f"the step did not run: {entry['error']['type']}")
            message = entry["error"]["message"].lower()
            # macOS kills a process that exhausts memory with signal 9.
            if "out of memory" in message or "exit status -9" in message:
                limits.add("memory")
            elif entry["error"]["type"] == "Timeout":
                limits.add("time")
        else:
            if entry["cpu_fallback_operations"]:
                reasons.append(
                    "operations fell back to the CPU: " + ", ".join(entry["cpu_fallback_operations"])
                )
            peak = entry["memory"]["process_peak_footprint_bytes"]
            if peak is None or memory_budget is None:
                reasons.append("peak memory could not be read")
            elif peak > memory_budget:
                reasons.append(
                    f"peak footprint {_gib(peak)} is over the budget of {_gib(memory_budget)}"
                )
                limits.add("memory")
            epoch_seconds = epoch_steps * entry["step_seconds"]["median"]
            if epoch_seconds > rule["max_seconds_per_reference_epoch"]:
                reasons.append(
                    f"one epoch of {rule['reference_epoch_examples']} examples takes "
                    f"{_duration(epoch_seconds)}, over the budget of "
                    f"{_duration(rule['max_seconds_per_reference_epoch'])}"
                )
                limits.add("time")
        parameters = entry.get("parameters")
        candidates.append(
            {
                "size": entry["size"],
                "parameters": parameters,
                "in_planned_range": parameters is not None and low <= parameters <= high,
                "below_planned_range": parameters is not None and parameters < low,
                "reference_epoch_seconds": epoch_seconds,
                "eligible": not reasons,
                "reasons": reasons,
                "limits": sorted(limits),
            }
        )

    middle = (low + high) / 2
    in_range = [c for c in candidates if c["eligible"] and c["in_planned_range"]]
    below = [c for c in candidates if c["eligible"] and c["below_planned_range"]]
    limit: list[str] = []
    if in_range:
        chosen = min(in_range, key=lambda c: (abs(c["parameters"] - middle), c["parameters"]))
        statement = (
            f"{chosen['size']} ({_millions(chosen['parameters'])} parameters) is the eligible "
            f"size nearest the middle of the planned range. Neither memory nor time was the "
            f"limit for it at batch {reference_batch}."
        )
    else:
        limit = sorted(
            {name for c in candidates if not c["eligible"] and not c["below_planned_range"] for name in c["limits"]}
        )
        named = " and ".join(limit) if limit else "an unnamed cause (see the reasons)"
        if below:
            chosen = max(below, key=lambda c: c["parameters"])
            statement = (
                f"No size inside the planned range is eligible on this machine; the measured "
                f"limit is {named}. {chosen['size']} ({_millions(chosen['parameters'])} "
                f"parameters) is the largest eligible size below the range."
            )
        else:
            chosen = None
            statement = (
                f"No measured size is eligible on this machine; the measured limit is {named}. "
                f"No starting size is chosen."
            )
    return {
        "rule": {
            **rule,
            "planned_parameter_range": [low, high],
            "reference_batch_size": reference_batch,
            "memory_budget_bytes": memory_budget,
            "text": (
                "Eligible: ran on the Apple GPU path at the reference batch size with no CPU "
                "fallback, peak footprint inside the memory budget, one reference epoch inside "
                "the time budget. Chosen: the eligible size inside the planned range nearest "
                "its middle; failing that, the largest eligible size below the range."
            ),
        },
        "candidates": candidates,
        "chosen": chosen["size"] if chosen else None,
        "chosen_parameters": chosen["parameters"] if chosen else None,
        "limit": limit,
        "statement": statement,
    }


def save(record: dict[str, Any], doctor_report: dict[str, Any], root: Path) -> dict[str, Any]:
    """Write the doctor record and the measurement record under `root`.

    Returns their paths and SHA-256 hashes. Records are evidence, so an
    existing file is never overwritten.
    """
    doctor_path = root / record["doctor"]["record"]
    doctor_digest = doctor.save_record(doctor_report, doctor_path)
    stamp = re.sub(r"[-:]", "", record["created_at"])
    short_id = record["doctor"]["environment_id"].removeprefix("sha256:")[:12]
    path = root / MEASUREMENTS_DIR / f"{stamp}-{short_id}.json"
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
    config = record["config"]
    lines = [
        f"Core Ultra training-step measurement  {record['created_at']}",
        f"Environment        {record['doctor']['environment_id']}",
        f"Doctor record      {record['doctor']['record']}",
        f"Configuration      {config['name']} (version {config['version']})",
        f"Steps per case     {config['warmup_steps']} warm-up, {config['measured_steps']} timed",
        f"Conditions         {record['conditions']['statement']} Least free memory before a case: "
        f"{_gib(record['conditions']['min_memory_available_bytes'])}.",
        "",
        "Measured (median step, peak process footprint)",
        f"  {'size':<12}{'parameters':>11}{'batch':>7}{'device':>8}{'step':>11}"
        f"{'examples/s':>12}{'peak':>11}",
    ]
    for entry in record["measurements"]:
        prefix = f"  {entry['size']:<12}"
        if not entry["ok"]:
            lines.append(
                f"{prefix}{'':>11}{entry['batch_size']:>7}{entry['device']:>8}  "
                f"FAILED {entry['error']['type']}: {entry['error']['message']}"
            )
            continue
        lines.append(
            f"{prefix}{_millions(entry['parameters']):>11}{entry['batch_size']:>7}"
            f"{entry['device']:>8}{entry['step_seconds']['median'] * 1000:>8.1f} ms"
            f"{entry['examples_per_second']:>12.0f}"
            f"{_gib(entry['memory']['process_peak_footprint_bytes']):>11}"
        )

    gpu = record["apple_gpu_path"]
    lines += ["", "Apple GPU path", f"  {gpu['statement']}"]
    for audit in gpu["audits"]:
        copies = ", ".join(f"{c['count']} {c['kind']} ({c['size']})" for c in audit["copies"])
        lines.append(f"  {audit['size']:<12}copies in {audit['steps']} steps: {copies or 'not reported'}")

    selection = record["selection"]
    lines += ["", "Starting size", f"  {selection['statement']}"]
    for candidate in selection["candidates"]:
        if candidate["reasons"]:
            lines.append(f"  {candidate['size']:<12}not eligible: {'; '.join(candidate['reasons'])}")

    projections = record["projections"]
    lines += ["", "Projections (not measurements)"]
    if not projections["by_batch_size"]:
        lines.append("  None: no starting size was chosen.")
    else:
        lines.append(f"  {projections['basis']}")
        lines.append(f"  Not included: {'; '.join(record['not_measured'])}.")
        for group in projections["by_batch_size"]:
            lines.append(
                f"  {projections['size']} at batch {group['batch_size']} "
                f"({group['median_step_seconds'] * 1000:.1f} ms per step)"
            )
            for row in group["rows"]:
                lines.append(
                    f"    {row['run']:<6}{row['examples']:>7} examples x {row['epochs']:>5} epochs"
                    f" = {row['steps']:>8} steps  {_duration(row['seconds']):>10}"
                )
    return "\n".join(lines) + "\n"


# --- running cases ------------------------------------------------------------


def _measure_case(
    config: dict[str, Any], size: dict[str, Any], batch_size: int, device: str
) -> dict[str, Any]:
    case = _case(config, size, batch_size, device)
    conditions = _conditions()
    started = time.perf_counter()
    result, _ = _run_child(case, config)
    unsupported: list[str] = []
    # Without the fallback switch an unsupported operation stops the step.
    # Name it, then repeat with the fallback so the step can still be timed.
    if device == "mps" and not result["ok"]:
        match = apple_gpu_path.UNIMPLEMENTED.search(result["error"]["message"])
        if result["error"]["type"] == "NotImplementedError" and match:
            unsupported.append(match.group(1))
            result, _ = _run_child(case, config, fallback=True)
    wall_seconds = time.perf_counter() - started

    entry: dict[str, Any] = {
        "size": size["name"],
        "d_model": size["d_model"],
        "layers": size["layers"],
        "heads": size["heads"],
        "feedforward": size["feedforward"],
        "batch_size": batch_size,
        "device": device,
        "warmup_steps": config["warmup_steps"],
        "measured_steps": config["measured_steps"],
        "conditions": conditions,
        "wall_seconds": wall_seconds,
        "unsupported_operations": unsupported,
        "ok": result["ok"],
        "error": result.get("error"),
    }
    if not result["ok"]:
        return entry
    samples = result.pop("step_seconds")
    entry.update({key: value for key, value in result.items() if key not in ("ok", "device")})
    entry["step_seconds"] = _summary(samples)
    entry["examples_per_second"] = batch_size / entry["step_seconds"]["median"]
    return entry


def _audit_apple_gpu_path(config: dict[str, Any], size: dict[str, Any]) -> dict[str, Any]:
    """A few steps with the CPU fallback allowed and PyTorch's MPS profiler logging.

    The fallback is allowed so that every unsupported operation is named in
    one run. This run is never timed.
    """
    steps = 3
    case = _case(config, size, config["reference_batch_size"], "mps")
    case.update({"warmup_steps": 0, "measured_steps": steps, "phase_steps": 0})
    result, stderr = _run_child(case, config, fallback=True, profile=True)
    return {
        "size": size["name"],
        "batch_size": config["reference_batch_size"],
        "steps": steps,
        "ok": result["ok"],
        "error": result.get("error"),
        "warned_fallback_operations": result.get("cpu_fallback_operations", []),
        **apple_gpu_path.profiled(stderr),
    }


def _case(config: dict[str, Any], size: dict[str, Any], batch_size: int, device: str) -> dict[str, Any]:
    return {
        "size": size,
        "batch_size": batch_size,
        "device": device,
        "warmup_steps": config["warmup_steps"],
        "measured_steps": config["measured_steps"],
        "phase_steps": config.get("phase_steps", 0),
        "seed": config["seed"],
        "optimizer": config["optimizer"],
    }


def _run_child(
    case: dict[str, Any],
    config: dict[str, Any],
    fallback: bool = False,
    profile: bool = False,
) -> tuple[dict[str, Any], str]:
    environment = apple_gpu_path.environment(fallback, profile)
    timeout = config.get("case_timeout_seconds", 900)
    with tempfile.TemporaryDirectory() as folder:
        result_path = Path(folder) / "result.json"
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "core_ultra.step_case", str(result_path)],
                input=json.dumps(case),
                capture_output=True,
                text=True,
                env=environment,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _failure("Timeout", f"no result after {timeout} seconds"), ""
        if not result_path.exists():
            last_line = (completed.stderr.strip().splitlines() or [""])[-1]
            return (
                _failure(
                    "ProcessDied",
                    f"exit status {completed.returncode}: {_scrub(last_line)}".rstrip(": "),
                ),
                completed.stderr,
            )
        return json.loads(result_path.read_text()), completed.stderr


def _failure(kind: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"type": kind, "message": message}}


def _conditions() -> dict[str, Any]:
    """The state of the machine just before a case starts.

    Free memory, swap in use, the power source and Low Power Mode all change
    how long a step takes, so each case records them. Unknown is recorded as
    null, never guessed.
    """
    conditions: dict[str, Any] = {
        "memory_available_bytes": None,
        "swap_used_bytes": None,
        "power_source": None,
        "low_power_mode": None,
    }
    try:
        import psutil

        conditions["memory_available_bytes"] = psutil.virtual_memory().available
        conditions["swap_used_bytes"] = psutil.swap_memory().used
    except Exception:
        pass
    source = _POWER_SOURCE.search(_command("pmset", "-g", "batt"))
    if source:
        conditions["power_source"] = source.group(1)
    mode = _LOW_POWER_MODE.search(_command("pmset", "-g"))
    if mode:
        conditions["low_power_mode"] = mode.group(1) == "1"
    return conditions


def _command(*args: str) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _conditions_summary(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    conditions = [entry["conditions"] for entry in measurements]
    available = [c["memory_available_bytes"] for c in conditions if c["memory_available_bytes"] is not None]
    sources = sorted({c["power_source"] for c in conditions if c["power_source"]})
    low_power = [c["low_power_mode"] for c in conditions if c["low_power_mode"] is not None]
    throttled = any(low_power) or any(source != "AC Power" for source in sources)
    if not sources or not low_power:
        statement = "The power state could not be read for every case."
    elif throttled:
        statement = (
            "At least one case ran on battery or in Low Power Mode, which slows the CPU and GPU. "
            "These timings describe a throttled machine."
        )
    else:
        statement = "Every case ran on AC power with Low Power Mode off."
    return {
        "power_sources": sources,
        "low_power_mode_seen": any(low_power) if low_power else None,
        "min_memory_available_bytes": min(available) if available else None,
        "max_swap_used_bytes": max(
            (c["swap_used_bytes"] for c in conditions if c["swap_used_bytes"] is not None),
            default=None,
        ),
        "statement": statement,
    }


# --- derived sections ---------------------------------------------------------


def _device_comparison(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_case: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for entry in measurements:
        by_case.setdefault((entry["size"], entry["batch_size"]), {})[entry["device"]] = entry
    rows = []
    for (size, batch_size), devices in by_case.items():
        medians = {
            device: entry["step_seconds"]["median"] if entry["ok"] else None
            for device, entry in devices.items()
        }
        measured = {device: value for device, value in medians.items() if value is not None}
        row: dict[str, Any] = {
            "size": size,
            "batch_size": batch_size,
            "median_step_seconds": medians,
            "faster_device": min(measured, key=measured.get) if measured else None,
        }
        if medians.get("mps") and medians.get("cpu"):
            row["cpu_step_divided_by_mps_step"] = medians["cpu"] / medians["mps"]
        rows.append(row)
    return rows


def _apple_gpu_path_summary(
    measurements: list[dict[str, Any]], audits: list[dict[str, Any]]
) -> dict[str, Any]:
    mps = [entry for entry in measurements if entry["device"] == "mps"]
    unsupported = {name for entry in mps for name in entry["unsupported_operations"]}
    fallbacks = {name for entry in mps if entry["ok"] for name in entry["cpu_fallback_operations"]}
    for audit in audits:
        fallbacks.update(audit["warned_fallback_operations"])
        fallbacks.update(audit["profiler_fallback_operations"])
    unsupported |= fallbacks
    strict = [entry for entry in mps if entry["ok"] and not entry["mps_fallback_enabled"]]
    profiler_seen = bool(audits) and all(audit["profiler_output_seen"] for audit in audits)

    if not mps:
        statement = "The Apple GPU path was not measured."
    elif unsupported:
        statement = (
            "Operations the Apple GPU path does not implement, which run on the CPU when the "
            "fallback is allowed: " + ", ".join(sorted(unsupported)) + "."
        )
    elif len(strict) == len(mps):
        statement = (
            f"No unsupported operation and no CPU fallback: all {len(mps)} Apple GPU cases ran "
            "with the fallback switch off, where an unsupported operation stops the step"
            + (
                ", and PyTorch's MPS profiler logged no CPU fallback."
                if profiler_seen
                else ". PyTorch's MPS profiler output was not seen, so it confirms nothing."
            )
        )
    else:
        statement = (
            f"No unsupported operation was named, but only {len(strict)} of {len(mps)} Apple GPU "
            "cases completed with the fallback switch off; see the failed cases."
        )
    return {
        "unsupported_operations": sorted(unsupported),
        "cpu_fallback_operations": sorted(fallbacks),
        "statement": statement,
        "method": (
            "Timed cases run with PYTORCH_ENABLE_MPS_FALLBACK unset, so an operation PyTorch "
            "has not implemented for the Apple GPU path raises and is named. One further "
            "untimed run per size allows the fallback and turns on PyTorch's MPS profiler "
            "(PYTORCH_MPS_LOG_PROFILE_INFO), which logs each CPU fallback and counts copies "
            "between CPU and GPU memory. This covers the operations of the placeholder step "
            "only; the training renderer's operations are checked in S3."
        ),
        "audits": audits,
    }


def _projections(
    measurements: list[dict[str, Any]], config: dict[str, Any], chosen: str | None
) -> dict[str, Any]:
    plan = config["projection"]
    datasets = [("pilot", count) for count in plan["pilot_examples"]] + [
        ("full", count) for count in plan["full_examples"]
    ]
    groups = []
    for entry in measurements:
        if entry["size"] != chosen or entry["device"] != "mps" or not entry["ok"]:
            continue
        median = entry["step_seconds"]["median"]
        rows = []
        for run, examples in datasets:
            for epochs in plan["epochs"]:
                steps = math.ceil(examples / entry["batch_size"]) * epochs
                rows.append(
                    {
                        "run": run,
                        "examples": examples,
                        "epochs": epochs,
                        "steps": steps,
                        "seconds": steps * median,
                    }
                )
        groups.append(
            {"batch_size": entry["batch_size"], "median_step_seconds": median, "rows": rows}
        )
    return {
        "label": "projection",
        "size": chosen,
        "device": "mps",
        "basis": (
            "Each duration is the number of steps multiplied by the median measured step of the "
            "placeholder on the Apple GPU path. The epoch counts are assumptions for scale, not "
            "estimates of how long training takes to converge; no figure from a paper is used."
        ),
        "covers": "one structure-only run; the structure-plus-render arm cannot be projected until S3",
        "not_included": NOT_MEASURED,
        "by_batch_size": groups,
    }


# --- helpers ------------------------------------------------------------------


def _summary(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    count = len(ordered)
    middle = count // 2
    median = ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "median": median,
        "mean": sum(ordered) / count,
        "min": ordered[0],
        "max": ordered[-1],
        "p90": ordered[min(count - 1, math.ceil(0.9 * count) - 1)],
        "samples": samples,
    }


def _one_line(entry: dict[str, Any]) -> str:
    if not entry["ok"]:
        return f"FAILED {entry['error']['type']}: {entry['error']['message']}"
    return (
        f"{_millions(entry['parameters'])} parameters, "
        f"{entry['step_seconds']['median'] * 1000:.1f} ms per step, "
        f"peak {_gib(entry['memory']['process_peak_footprint_bytes'])}"
    )


def _doctor_record_name(report: dict[str, Any]) -> str:
    return doctor.default_record_path(report).relative_to(DEFAULT_RECORDS_ROOT).as_posix()


def _canonical_sha256(data: Any) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scrub(text: str) -> str:
    return text.replace(str(Path.home()), "~")


def _gib(count: int | None) -> str:
    return "unknown" if count is None else f"{count / 1024**3:.2f} GiB"


def _millions(count: int) -> str:
    return f"{count / 1e6:.2f}M"


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 90 * 60:
        return f"{seconds / 60:.1f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


__all__ = [
    "ConfigError",
    "DEFAULT_CONFIG",
    "DEFAULT_RECORDS_ROOT",
    "load_config",
    "measure",
    "other_measurements",
    "save",
    "select_starting_size",
    "to_json",
    "to_text",
]
