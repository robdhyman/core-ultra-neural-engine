"""Run one training-step case in this process and write what was measured.

`step_measurement` starts one fresh interpreter per case
(`python -m core_ultra.step_case RESULT_PATH`, the case as JSON on stdin), so
that each case's peak memory is its own and one case's cached GPU buffers
cannot be counted against the next.
"""

from __future__ import annotations

import ctypes
import json
import os
import resource
import struct
import sys
import time
import warnings
from pathlib import Path
from typing import Any

from core_ultra import apple_gpu_path

_PHASES = ("forward", "loss", "backward", "update")


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """One case: build the placeholder, run warm-up and timed steps, read memory.

    A step is zeroing gradients, the forward pass, the loss, the backward pass
    and the optimiser update. On the Apple GPU path the clock stops only after
    the device has finished its queued work.
    """
    footprint_at_start = _process_memory()["footprint_bytes"]

    import torch

    from core_ultra import placeholder

    size = case["size"]
    device = torch.device(case["device"])
    on_mps = device.type == "mps"
    torch.manual_seed(case["seed"])

    def finish_device_work() -> None:
        if on_mps:
            torch.mps.synchronize()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        model = placeholder.PlaceholderSceneModel(
            d_model=size["d_model"],
            layers=size["layers"],
            heads=size["heads"],
            feedforward=size["feedforward"],
        ).to(device)
        model.train()
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=case["optimizer"]["learning_rate"],
            weight_decay=case["optimizer"]["weight_decay"],
        )
        generator = torch.Generator().manual_seed(case["seed"])
        batches = [
            {
                name: tensor.to(device)
                for name, tensor in placeholder.synthetic_batch(case["batch_size"], generator).items()
            }
            for _ in range(4)
        ]
        finish_device_work()
        footprint_before_steps = _process_memory()["footprint_bytes"]

        mps_current_peak = mps_driver_peak = 0
        step_seconds: list[float] = []
        losses: list[float] = []
        total_steps = case["warmup_steps"] + case["measured_steps"]
        for step in range(total_steps):
            batch = batches[step % len(batches)]
            finish_device_work()
            started = time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            loss = placeholder.placeholder_structure_loss(model(batch), batch)
            loss.backward()
            optimizer.step()
            finish_device_work()
            elapsed = time.perf_counter() - started
            if step >= case["warmup_steps"]:
                step_seconds.append(elapsed)
            losses.append(float(loss.detach()))
            if on_mps:
                mps_current_peak = max(mps_current_peak, torch.mps.current_allocated_memory())
                mps_driver_peak = max(mps_driver_peak, torch.mps.driver_allocated_memory())

        # Read before the phase steps below, so the peak belongs to plain steps.
        memory_after_steps = _process_memory()

        # Extra steps with the device made to finish between phases. Waiting
        # between phases costs time, so these are never part of the step time.
        phase_samples: dict[str, list[float]] = {phase: [] for phase in _PHASES}
        for step in range(case.get("phase_steps", 0)):
            batch = batches[step % len(batches)]
            optimizer.zero_grad(set_to_none=True)
            finish_device_work()
            marks = [time.perf_counter()]
            output = model(batch)
            finish_device_work()
            marks.append(time.perf_counter())
            loss = placeholder.placeholder_structure_loss(output, batch)
            finish_device_work()
            marks.append(time.perf_counter())
            loss.backward()
            finish_device_work()
            marks.append(time.perf_counter())
            optimizer.step()
            finish_device_work()
            marks.append(time.perf_counter())
            for index, phase in enumerate(_PHASES):
                phase_samples[phase].append(marks[index + 1] - marks[index])

    messages = [_scrub(str(warning.message).splitlines()[0]) for warning in caught]
    fallbacks = sorted(
        {match.group(1) for message in messages if (match := apple_gpu_path.FALLBACK_WARNING.search(message))}
    )
    dtypes = sorted({str(parameter.dtype).removeprefix("torch.") for parameter in model.parameters()})
    return {
        "device": device.type,
        "dtype": dtypes[0] if len(dtypes) == 1 else dtypes,
        "parameters": placeholder.count_parameters(model),
        "positions": {
            "bound": placeholder.BOUND_POSITIONS,
            "structural": placeholder.STRUCTURAL_POSITIONS,
            "conditioning": placeholder.CONDITIONING_POSITIONS,
        },
        "sequence_length": placeholder.SEQUENCE_LENGTH,
        "torch_threads": torch.get_num_threads(),
        "step_seconds": step_seconds,
        "phase_seconds": {phase: _median(samples) for phase, samples in phase_samples.items()},
        "loss_first": losses[0],
        "loss_last": losses[-1],
        "losses_finite": all(value == value and abs(value) != float("inf") for value in losses),
        "memory": {
            "process_footprint_at_start_bytes": footprint_at_start,
            "process_footprint_before_steps_bytes": footprint_before_steps,
            "process_peak_footprint_bytes": memory_after_steps["peak_footprint_bytes"],
            "process_peak_resident_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "mps_peak_current_allocated_bytes": mps_current_peak if on_mps else None,
            "mps_peak_driver_allocated_bytes": mps_driver_peak if on_mps else None,
            "mps_recommended_max_bytes": torch.mps.recommended_max_memory() if on_mps else None,
        },
        "mps_fallback_enabled": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1",
        "cpu_fallback_operations": fallbacks,
        "warnings": sorted(set(messages)),
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    result_path = Path(arguments[0])
    case = json.load(sys.stdin)
    try:
        result: dict[str, Any] = {"ok": True, **run_case(case)}
    except Exception as error:  # reported as a result, never as a traceback
        result = {
            "ok": False,
            "error": {
                "type": type(error).__name__,
                "message": _scrub(str(error).splitlines()[0] if str(error) else ""),
            },
        }
    result_path.write_text(json.dumps(result))
    return 0


def _process_memory() -> dict[str, int | None]:
    """This process's physical footprint and its lifetime peak, from the kernel.

    The footprint is what macOS charges the process for, and on Apple silicon
    it includes memory held for the GPU, which the resident set size leaves
    out. Read with `proc_pid_rusage` (flavor `RUSAGE_INFO_V4`).
    """
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buffer = ctypes.create_string_buffer(8 * 64)
        if libproc.proc_pid_rusage(os.getpid(), 4, buffer) != 0:
            raise OSError("proc_pid_rusage failed")
        # rusage_info_v4: a 16-byte UUID, then unsigned 64-bit fields.
        fields = struct.unpack_from("<16s35Q", buffer.raw)
        return {"footprint_bytes": fields[8], "peak_footprint_bytes": fields[29]}
    except (OSError, AttributeError, struct.error):
        return {"footprint_bytes": None, "peak_footprint_bytes": None}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _scrub(text: str) -> str:
    return text.replace(str(Path.home()), "~")


if __name__ == "__main__":
    sys.exit(main())
