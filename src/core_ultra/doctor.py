"""The doctor report: a description of the machine every later number is tied to.

The report is plain JSON-compatible data. It holds no host name, user name,
serial number or absolute path, because saved records are committed to a
public repository.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PROJECT = "core-ultra"
LOCKED_PYTHON = (3, 12)
DEFAULT_RECORDS_DIR = Path("records") / "doctor"

# Tolerance for the Apple GPU path (32-bit floats) against the CPU result.
_MPS_TOLERANCE = 1e-4


def collect_report() -> dict[str, Any]:
    """Inspect this machine and return the doctor report."""
    report: dict[str, Any] = {
        "kind": "doctor-report",
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": {"name": PROJECT, "version": _project_version()},
        "os": _os(),
        "hardware": _hardware(),
        "python": _python(),
        "accelerators": _accelerators(),
        "memory": _memory(),
        "disk": _disk(),
        "dependencies": _dependencies(),
    }
    report["problems"] = _problems(report)
    report["environment_id"] = environment_id(report)
    return report


def environment_id(report: dict[str, Any]) -> str:
    """Hash of the fields that identify the environment.

    Two reports from the same machine, OS build, Python and dependency set get
    the same id. Fields that change from minute to minute (time, free memory,
    free disk) are left out.
    """
    accelerators = report["accelerators"]
    stable = {
        "schema_version": report["schema_version"],
        "project": report["project"],
        "os": report["os"],
        "hardware": report["hardware"],
        "python": report["python"],
        "memory_total_bytes": report["memory"]["total_bytes"],
        "accelerators": {
            "default_device": accelerators["default_device"],
            "mps": {key: accelerators["mps"][key] for key in ("built", "available", "usable")},
            "cuda": accelerators["cuda"],
        },
        "dependencies": [
            {key: entry[key] for key in ("name", "version", "usable")}
            for entry in report["dependencies"]
        ],
    }
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2) + "\n"


def default_record_path(report: dict[str, Any]) -> Path:
    stamp = re.sub(r"[-:]", "", report["created_at"])
    short_id = report["environment_id"].removeprefix("sha256:")[:12]
    return DEFAULT_RECORDS_DIR / f"{stamp}-{short_id}.json"


def save_record(report: dict[str, Any], path: Path) -> str:
    """Write the report as a JSON record and return the file's SHA-256.

    A record is evidence that later measurements point at, so an existing
    file is never overwritten.
    """
    data = to_json(report).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


def to_text(report: dict[str, Any]) -> str:
    os_, hardware, python = report["os"], report["hardware"], report["python"]
    accelerators, memory, disk = report["accelerators"], report["memory"], report["disk"]
    mps = accelerators["mps"]
    lines = [
        f"Core Ultra doctor  {report['created_at']}",
        f"Environment        {report['environment_id']}",
        "",
        f"OS                 {os_['name']} {os_['version']} ({os_['build']}), kernel {os_['kernel']}",
        f"Hardware           {hardware['chip']}, {hardware['model']}, {hardware['machine']}, "
        f"{_count(hardware['cpu_cores_physical'])} cores",
        f"Python             {python['implementation']} {python['version']}",
        f"Memory             {_memory_text(memory)}",
        f"Disk               {_gib(disk['free_bytes'])} free of {_gib(disk['total_bytes'])}",
        "",
        "Accelerators",
        f"  Apple GPU (MPS)  {_usable(mps['usable'])}"
        f" (built {_yes(mps['built'])}, available {_yes(mps['available'])},"
        f" forward {_yes(mps['forward_ok'])}, backward {_yes(mps['backward_ok'])},"
        f" agrees with CPU {_yes(mps['agrees_with_cpu'])})",
    ]
    if mps["error"]:
        lines.append(f"                   {mps['error']}")
    lines += [
        f"  CUDA             {'available' if accelerators['cuda']['available'] else 'not available'}",
        f"  Default device   {accelerators['default_device']}",
        "",
        "Dependencies",
    ]
    for entry in report["dependencies"]:
        status = _usable(entry["usable"])
        detail = f"  {entry['error']}" if entry["error"] else ""
        lines.append(f"  {entry['name']:<20} {entry['version'] or 'missing':<12} {status}{detail}")
    lines.append("")
    if report["problems"]:
        lines.append("Problems")
        lines += [f"  - {problem}" for problem in report["problems"]]
    else:
        lines.append("No problems found.")
    return "\n".join(lines) + "\n"


# --- sections ---------------------------------------------------------------


def _os() -> dict[str, Any]:
    system = platform.system()
    if system == "Darwin":
        return {
            "name": "macOS",
            "version": platform.mac_ver()[0],
            "build": _command("sw_vers", "-buildVersion"),
            "kernel": platform.release(),
        }
    return {
        "name": system,
        "version": platform.version(),
        "build": None,
        "kernel": platform.release(),
    }


def _hardware() -> dict[str, Any]:
    psutil = _psutil()
    return {
        "machine": platform.machine(),
        "chip": _command("sysctl", "-n", "machdep.cpu.brand_string"),
        "model": _command("sysctl", "-n", "hw.model"),
        "cpu_cores_physical": psutil.cpu_count(logical=False) if psutil else None,
        "cpu_cores_logical": psutil.cpu_count(logical=True) if psutil else None,
    }


def _python() -> dict[str, Any]:
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
    }


def _memory() -> dict[str, Any]:
    psutil = _psutil()
    if psutil is None:
        return {"total_bytes": None, "available_bytes": None}
    memory = psutil.virtual_memory()
    return {"total_bytes": memory.total, "available_bytes": memory.available}


def _disk() -> dict[str, Any]:
    """Space on the volume that holds the working directory."""
    usage = shutil.disk_usage(os.getcwd())
    return {"total_bytes": usage.total, "free_bytes": usage.free}


def _accelerators() -> dict[str, Any]:
    mps = _check_mps()
    cuda = {"available": False}
    try:
        import torch

        cuda["available"] = bool(torch.cuda.is_available())
    except Exception:  # torch's absence is reported under dependencies
        pass
    if mps["usable"]:
        default = "mps"
    elif cuda["available"]:
        default = "cuda"
    else:
        default = "cpu"
    return {"default_device": default, "mps": mps, "cuda": cuda}


def _check_mps() -> dict[str, Any]:
    """Run a real forward and backward pass on the Apple GPU path.

    "Usable" means more than "PyTorch says it is available": a small
    computation runs forward and backward on the device in 32-bit floats and
    its value and gradient agree with the CPU.
    """
    result: dict[str, Any] = {
        "built": False,
        "available": False,
        "forward_ok": False,
        "backward_ok": False,
        "agrees_with_cpu": False,
        "max_abs_difference": None,
        "usable": False,
        "error": None,
    }
    try:
        import torch

        result["built"] = bool(torch.backends.mps.is_built())
        result["available"] = bool(torch.backends.mps.is_available())
        if not result["available"]:
            return result

        inputs = torch.linspace(-1.0, 1.0, 64, dtype=torch.float32).reshape(8, 8)
        weights = torch.linspace(0.5, -0.5, 64, dtype=torch.float32).reshape(8, 8)

        def forward(device: str):
            x = inputs.detach().clone().to(device).requires_grad_(True)
            return x, torch.tanh(x @ weights.to(device)).sum()

        x_cpu, y_cpu = forward("cpu")
        y_cpu.backward()

        x_mps, y_mps = forward("mps")
        value = y_mps.detach().cpu()
        result["forward_ok"] = bool(torch.isfinite(value))
        y_mps.backward()
        gradient = x_mps.grad.detach().cpu()
        result["backward_ok"] = bool(torch.isfinite(gradient).all())

        difference = max(
            float((value - y_cpu.detach()).abs()),
            float((gradient - x_cpu.grad).abs().max()),
        )
        result["max_abs_difference"] = difference
        result["agrees_with_cpu"] = difference <= _MPS_TOLERANCE
        result["usable"] = (
            result["forward_ok"] and result["backward_ok"] and result["agrees_with_cpu"]
        )
    except Exception as error:
        result["error"] = _describe(error)
    return result


def _dependencies() -> list[dict[str, Any]]:
    """Every runtime dependency the project declares, checked by importing it."""
    entries = []
    for name in _declared_dependencies():
        entry: dict[str, Any] = {"name": name, "version": None, "usable": False, "error": None}
        try:
            distribution = importlib.metadata.distribution(name)
            entry["version"] = distribution.version
            for module in _import_names(distribution):
                importlib.import_module(module)
            entry["usable"] = True
        except Exception as error:
            entry["error"] = _describe(error)
        entries.append(entry)
    return entries


def _declared_dependencies() -> list[str]:
    requirements = importlib.metadata.requires(PROJECT) or []
    names = set()
    for requirement in requirements:
        if "extra ==" in requirement:
            continue
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
        if match:
            names.add(match.group(0).lower().replace("_", "-"))
    return sorted(names)


def _import_names(distribution: importlib.metadata.Distribution) -> list[str]:
    top_level = distribution.read_text("top_level.txt")
    if top_level:
        names = [line.strip() for line in top_level.splitlines() if line.strip()]
        # A distribution may list a name it does not ship (PySide6-Essentials
        # lists Shiboken, which belongs to shiboken6). Only what it ships is
        # imported.
        shipped = {file.parts[0].split(".")[0] for file in distribution.files or []}
        names = [name for name in names if name in shipped] or names
    else:
        names = sorted(
            {
                file.parts[0].removesuffix(".py")
                for file in distribution.files or []
                if len(file.parts) > 1 and file.parts[1] == "__init__.py"
            }
        )
    public = [name for name in names if not name.startswith("_")]
    return public or [distribution.metadata["Name"].replace("-", "_")]


def _problems(report: dict[str, Any]) -> list[str]:
    problems = []
    version = report["python"]["version"]
    if tuple(map(int, version.split(".")[:2])) != LOCKED_PYTHON:
        wanted = ".".join(map(str, LOCKED_PYTHON))
        problems.append(f"Python is {version}; the locked environment is Python {wanted}.")
    for entry in report["dependencies"]:
        if not entry["usable"]:
            problems.append(f"Dependency {entry['name']} is not usable: {entry['error']}")
    mps = report["accelerators"]["mps"]
    if not mps["usable"]:
        reason = mps["error"] or (
            "PyTorch reports it unavailable"
            if not mps["available"]
            else "the forward and backward check failed"
        )
        problems.append(f"The Apple GPU path is not usable: {reason}.")
    return problems


# --- helpers ----------------------------------------------------------------


def _psutil() -> Any:
    """psutil, or None when it cannot be imported.

    Doctor exists to report a broken environment, so a missing dependency must
    not stop the report. Its absence is listed under dependencies and problems;
    the fields only it can measure are recorded as unknown.
    """
    try:
        import psutil
    except Exception:
        return None
    return psutil


def _project_version() -> str | None:
    try:
        return importlib.metadata.version(PROJECT)
    except importlib.metadata.PackageNotFoundError:
        return None


def _command(*args: str) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip()
    return output if result.returncode == 0 and output else None


def _describe(error: BaseException) -> str:
    """One line, with the home directory removed so no user name is recorded."""
    text = f"{type(error).__name__}: {error}".splitlines()[0]
    return text.replace(str(Path.home()), "~")


def _gib(count: int | None) -> str:
    return "unknown" if count is None else f"{count / 1024**3:.1f} GiB"


def _count(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _memory_text(memory: dict[str, Any]) -> str:
    if memory["total_bytes"] is None:
        return "unknown"
    return f"{_gib(memory['total_bytes'])} total, {_gib(memory['available_bytes'])} available"


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _usable(value: bool) -> str:
    return "usable" if value else "NOT usable"


__all__ = [
    "collect_report",
    "default_record_path",
    "environment_id",
    "save_record",
    "to_json",
    "to_text",
]
