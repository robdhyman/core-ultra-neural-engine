"""What PyTorch says about the Apple GPU path, and how to make it say it.

An operation PyTorch has not built for the Apple GPU either stops the run or,
with `PYTORCH_ENABLE_MPS_FALLBACK=1`, runs on the CPU with a warning. Both are
decided when PyTorch starts, so a run that is to be audited is a process of
its own, started with `environment`. `step_measurement` and `renderer_check`
read the same lines.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Bits of PYTORCH_MPS_LOG_PROFILE_INFO: CPU fallback info, and operation, copy
# and CPU fallback statistics at exit.
PROFILE_FLAGS = str((1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6))
UNIMPLEMENTED = re.compile(r"The operator '([^']+)' is not currently implemented for the MPS device")
FALLBACK_WARNING = re.compile(r"The operator '([^']+)' is not currently supported on the MPS backend")
PROFILED_FALLBACK = re.compile(r"^CPU Fallback::((?:\w+::)?[\w.]+)", re.MULTILINE)
PROFILED_COPIES = re.compile(r"^\s*(CPU to MPS|MPS to CPU|MPS to MPS)\s+(\d+)\s+([\d.]+\s*\w+)", re.MULTILINE)
PROFILER_HEADING = "MPS Operations Profiling"
NO_FALLBACKS = "There are no CPU Fallbacks logged"


def environment(fallback: bool = False, profile: bool = False) -> dict[str, str]:
    """This process's environment for a child: the CPU fallback allowed or
    not, and PyTorch's profiler of the Apple GPU path logging or not, whatever
    the caller's own environment says."""
    variables = os.environ.copy()
    variables.pop("PYTORCH_ENABLE_MPS_FALLBACK", None)
    variables.pop("PYTORCH_MPS_LOG_PROFILE_INFO", None)
    if fallback:
        variables["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    if profile:
        variables["PYTORCH_MPS_LOG_PROFILE_INFO"] = PROFILE_FLAGS
    return variables


def profiled(stderr: str) -> dict[str, Any]:
    """What the profiler printed when a child started with `profile` exited."""
    return {
        "profiler_output_seen": PROFILER_HEADING in stderr,
        "profiler_fallback_operations": sorted(set(PROFILED_FALLBACK.findall(stderr))),
        "profiler_reported_no_fallbacks": NO_FALLBACKS in stderr,
        "copies": [
            {"kind": kind, "count": int(count), "size": " ".join(amount.split())}
            for kind, count, amount in PROFILED_COPIES.findall(stderr)
        ],
    }
