"""`renderer check`: is the training renderer's stage right, and what does it support?

A stage of the training renderer is used in training only after this passes.
The check draws the known scenes of a check configuration
(`configs/renderer/check-v1.json`) through `training_renderer.draw` and
nothing else of that module, and writes one record:

- **Finite differences.** On the CPU in 64-bit floats, the gradient autograd
  gives for every number of every element is compared with a central finite
  difference, for two scalars of the image: the summed squared difference
  from a target image (the same scene with every number moved a little), and
  a sum of the image weighted by fixed pseudo-random weights. Neither has a
  kink of its own, so a disagreement is the renderer's. The render loss,
  which has one wherever a pixel equals its target, is checked by the moves.
- **Apple GPU path.** In a process of its own, in 32-bit floats: the forward
  pass alone, compared with the CPU's image; then the backward pass, compared
  with the CPU's gradients. Operations PyTorch has not built for the Apple
  GPU, and any that fall back to the CPU, are profiled and listed.
- **Moves.** An element moved toward its target in steps: the render loss
  falls at every step, is zero on the target, and its gradient points along
  the move.
- **Zero gradients.** Cases whose gradient is rightly zero, each told apart
  from a disconnected computation: `gradient_state` says `zero` only when
  the number is part of the computation.
- **Agreement.** Each valid scene is drawn by the runtime renderer too, and
  both are compared with exact cover: the same compositing with each pixel's
  cover counted from sample points, by code that shares nothing with either
  renderer. Differences are in levels of 255 over premultiplied
  RGBA.
- **Support matrix.** Each primitive: whether it is drawn, which attributes
  receive gradients, and whether each cell was verified by this run.

Nothing here is a tolerance on appearance. A difference between the two
renderers is measured and reported, never hidden by changing a target.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core_ultra import apple_gpu_path, doctor

KIND = "renderer-check"
SCHEMA_VERSION = 1
DEFAULT_CONFIG = Path("configs") / "renderer" / "check-v1.json"
DEFAULT_RECORDS_ROOT = Path("records")
CHECKS_DIR = Path("renderer")
ATTRIBUTES = ("x", "y", "width", "height", "corner_radius", "fill", "opacity")
SCALARS = {
    "squared_difference_from_target": "the sum of (image - target image) squared over every channel of every pixel",
    "weighted_sum": "the sum of the image times fixed pseudo-random weights in -1 to 1",
}
THRESHOLD = 16
DEFINITIONS = {
    "finite_difference": "(f(v + step) - f(v - step)) / (2 step), one number at a time, on the CPU in 64-bit floats",
    "passes": "|autograd - other| <= absolute_tolerance + relative_tolerance * |other|, for every number of the attribute",
    "render_loss": "the mean of |image - target image| over every channel of every pixel, both drawn by the training renderer",
    "gradient_state": (
        "disconnected: the number is not part of the computation. zero: it is, and every part of its gradient is "
        "within zero_tolerance of zero. non-zero: otherwise."
    ),
    "levels": "differences between images are in levels of 255 over RGBA with colour premultiplied by alpha",
    "mean_absolute_difference": "mean of |a - b| over every channel of every pixel",
    "share_of_pixels_over_16": f"share of pixels in which some channel differs by more than {THRESHOLD} levels",
    "largest_difference": "largest |a - b| of any channel of any pixel",
    "exact_cover": (
        "each pixel's cover by each element counted from exact_cover_samples sample points, no two in one column or "
        "row of the pixel, then composited as both renderers composite; computed here with numpy"
    ),
    "verified": (
        "drawn is verified when the Apple GPU path's image agrees with the CPU's and agreement with the runtime "
        "renderer was measured; an attribute is verified when its finite differences pass on the CPU and its "
        "gradient on the Apple GPU path agrees with the CPU's"
    ),
}

Progress = Callable[[str], None]
_STYLE_DEFAULTS = {
    "text_colour": [0, 0, 0, 1],
    "border_colour": [0, 0, 0, 0],
    "border_width": 0,
    "elevation": 0,
    "type_size": 15,
    "type_weight": 400,
}
_ELEMENT_KEYS = {"box", "fill", "corner_radius", "opacity"}
_CASE_TIMEOUT_SECONDS = 600


class ConfigError(ValueError):
    """The check configuration cannot be used."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


# --- configuration -----------------------------------------------------------


def load_config(path: str | Path) -> dict[str, Any]:
    """Read a check configuration. Raises `ConfigError` listing every problem."""
    from core_ultra import training_renderer

    try:
        config = json.loads(Path(path).read_text())
    except OSError as error:
        raise ConfigError([f"{path} cannot be read: {error.strerror or error}"]) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ConfigError([f"{path} is not JSON: {error}"]) from None
    if not isinstance(config, dict):
        raise ConfigError([f"{path} is not a JSON object"])

    problems: list[str] = []
    for key in ("name", "version", "stage", "seed", "scales", "finite_differences", "apple_gpu_path", "zero_tolerance", "exact_cover_samples", "scenes"):
        if key not in config:
            problems.append(f"{key} is missing")
    if problems:
        raise ConfigError(problems)
    if config["stage"] != training_renderer.STAGE:
        problems.append(f"stage is {config['stage']!r}; the training renderer is at stage {training_renderer.STAGE}")
    if not (isinstance(config["scales"], list) and config["scales"] and all(_positive(scale) for scale in config["scales"])):
        problems.append("scales is not a list of numbers above zero")
    for group, keys in (
        ("finite_differences", ("step", "absolute_tolerance", "relative_tolerance")),
        ("apple_gpu_path", ("image_tolerance", "gradient_absolute_tolerance", "gradient_relative_tolerance")),
    ):
        if not (isinstance(config[group], dict) and all(_positive(config[group].get(key)) for key in keys)):
            problems.append(f"{group} does not give {', '.join(keys)} as numbers above zero")
    if not _positive(config["zero_tolerance"]):
        problems.append("zero_tolerance is not a number above zero")
    if not (isinstance(config["exact_cover_samples"], int) and 64 <= config["exact_cover_samples"] <= 4096):
        problems.append("exact_cover_samples is not a whole number from 64 to 4096")

    names: set[str] = set()
    scenes = config["scenes"] if isinstance(config["scenes"], list) else []
    if not scenes:
        problems.append("scenes is not a list of at least one scene")
    for index, entry in enumerate(scenes):
        label = f"scene {entry.get('name', index)!r}" if isinstance(entry, dict) else f"scene {index}"
        if not (isinstance(entry, dict) and isinstance(entry.get("name"), str) and _viewport(entry.get("viewport"))):
            problems.append(f"{label} does not give a name and a viewport of two numbers above zero")
            continue
        if entry["name"] in names:
            problems.append(f"{label} is named twice")
        names.add(entry["name"])
        problems += [f"{label}: {problem}" for problem in _element_problems(entry.get("elements"))]
        if not problems and not entry.get("leaves_viewport"):
            from core_ultra.scene import SceneInvalid

            try:
                _scene_of(entry)
            except SceneInvalid as refused:
                problems += [f"{label}: {problem}" for problem in refused.problems]
    if scenes and not problems and all(entry.get("on_kinks") for entry in scenes):
        problems.append("every scene is on_kinks, so no finite difference would be taken")

    for index, entry in enumerate(config.get("moves", [])):
        label = f"move {entry.get('name', index)!r}" if isinstance(entry, dict) else f"move {index}"
        if not (isinstance(entry, dict) and isinstance(entry.get("name"), str) and _viewport(entry.get("viewport"))):
            problems.append(f"{label} does not give a name and a viewport")
            continue
        if not (isinstance(entry.get("steps"), int) and entry["steps"] >= 2):
            problems.append(f"{label}: steps is not a whole number of at least 2")
        ends = [entry.get("from"), entry.get("to")] + ([entry["backdrop"]] if "backdrop" in entry else [])
        problems += [f"{label}: {problem}" for problem in _element_problems(ends)]
    for index, entry in enumerate(config.get("zero_gradients", [])):
        label = f"zero gradient {entry.get('name', index)!r}" if isinstance(entry, dict) else f"zero gradient {index}"
        if not (isinstance(entry, dict) and isinstance(entry.get("name"), str) and _viewport(entry.get("viewport"))):
            problems.append(f"{label} does not give a name and a viewport")
            continue
        found = _element_problems(entry.get("elements")) + _element_problems(entry.get("target"))
        problems += [f"{label}: {problem}" for problem in found]
        if found:
            continue
        if len(entry["elements"]) != len(entry["target"]):
            problems.append(f"{label}: elements and target are not the same number of elements")
        if not (isinstance(entry.get("element"), int) and 0 <= entry["element"] < len(entry["elements"])):
            problems.append(f"{label}: element is not the index of one of its elements")
        stated = list(entry.get("zero", [])) + list(entry.get("non_zero", []))
        if sorted(stated) != sorted(ATTRIBUTES):
            problems.append(f"{label}: zero and non_zero together do not name each of {', '.join(ATTRIBUTES)} once")
    if problems:
        raise ConfigError(problems)
    return config


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _viewport(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(_positive(side) for side in value)


def _element_problems(items: Any) -> list[str]:
    if not (isinstance(items, list) and items):
        return ["its elements are not a list of at least one element"]
    problems = []
    for index, item in enumerate(items):
        label = f"element {item.get('id', index)!r}" if isinstance(item, dict) else f"element {index}"
        numbers = lambda value, count: isinstance(value, list) and len(value) == count and all(_finite(part) for part in value)  # noqa: E731
        if not (
            isinstance(item, dict)
            and _ELEMENT_KEYS <= set(item)
            and numbers(item["box"], 4)
            and numbers(item["fill"], 4)
            and _finite(item["corner_radius"])
            and _finite(item["opacity"])
        ):
            problems.append(f"{label} does not give box and fill as four numbers each, corner_radius and opacity")
    return problems


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _scene_of(entry: dict[str, Any]) -> Any:
    """A configuration's scene as a validated `Scene` of structural elements."""
    from core_ultra import scene as scene_schema

    width, height = entry["viewport"]
    candidate = {
        "kind": "scene",
        "schema_version": scene_schema.SCHEMA_VERSION,
        "viewport": {"width": width, "height": height},
        "elements": [
            {
                "id": item.get("id", f"e{index}"),
                "type": item.get("type", "surface" if item.get("parent") is None else "panel"),
                "parent": item.get("parent"),
                "box": dict(zip(scene_schema.BOX_FIELDS, item["box"])),
                "style": {**_STYLE_DEFAULTS, "fill": item["fill"], "corner_radius": item["corner_radius"], "opacity": item["opacity"]},
            }
            for index, item in enumerate(entry["elements"])
        ],
    }
    return scene_schema.validate(candidate, [], (width, height))


# --- drawing the configuration's scenes ---------------------------------------


def _listed(items: Sequence[dict[str, Any]], dtype: Any, device: Any = "cpu") -> Any:
    """Elements in the order they are listed."""
    import torch

    from core_ultra.training_renderer import Elements

    def tensor(rows: list) -> Any:
        return torch.tensor(rows, dtype=dtype, device=device)

    return Elements(
        box=tensor([item["box"] for item in items]),
        fill=tensor([item["fill"] for item in items]),
        corner_radius=tensor([item["corner_radius"] for item in items]),
        opacity=tensor([item["opacity"] for item in items]),
    )


def _elements_of(entry: dict[str, Any], dtype: Any, device: Any = "cpu") -> Any:
    """A scene's elements in drawing order: from the validated scene's tree,
    or as listed for a scene that leaves the viewport and so cannot be one."""
    from core_ultra import training_renderer

    if entry.get("leaves_viewport"):
        return _listed(entry["elements"], dtype, device)
    return training_renderer.elements_of(_scene_of(entry), dtype, device)


def _target_of(elements: Any, seed: int) -> Any:
    """The same elements with every number moved a little, by a fixed seed."""
    import torch

    from core_ultra.training_renderer import Elements

    generator = torch.Generator().manual_seed(seed)

    def moved(tensor: Any, by: float) -> Any:
        return tensor + (torch.rand(tensor.shape, generator=generator, dtype=torch.float64) * 2 - 1) * by

    box = moved(elements.box, 1.5)
    box = torch.cat([box[..., :2], box[..., 2:].clamp(min=0.25)], dim=-1)
    half = box[..., 2:].min(dim=-1).values / 2
    return Elements(
        box=box,
        fill=moved(elements.fill, 0.15).clamp(0.02, 0.98),
        corner_radius=torch.minimum(moved(elements.corner_radius, 0.3).clamp(min=0.05), half * 0.95),
        opacity=moved(elements.opacity, 0.15).clamp(0.02, 0.98),
    )


def _weights(shape: Sequence[int], seed: int) -> Any:
    import torch

    return torch.rand(tuple(shape), generator=torch.Generator().manual_seed(seed + 1), dtype=torch.float64) * 2 - 1


def _leaves(elements: Any) -> list[Any]:
    return [tensor.detach().clone().requires_grad_(True) for tensor in (elements.box, elements.fill, elements.corner_radius, elements.opacity)]


def _by_attribute(box: Any, fill: Any, corner_radius: Any, opacity: Any) -> dict[str, Any]:
    """Four tensors shaped as an `Elements` holds them, split by attribute."""
    return {"x": box[..., 0], "y": box[..., 1], "width": box[..., 2], "height": box[..., 3], "corner_radius": corner_radius, "fill": fill, "opacity": opacity}


class _Scalars:
    """The two scalars of one scene at one scale, on one device and dtype."""

    def __init__(self, entry: dict[str, Any], scale: float, seed: int, dtype: Any, device: Any = "cpu") -> None:
        import torch

        from core_ultra import training_renderer

        self._draw, self._elements_type = training_renderer.draw, training_renderer.Elements
        self.viewport, self.scale = tuple(entry["viewport"]), scale
        exact = _elements_of(entry, torch.float64)
        # The dtype first: the Apple GPU holds no 64-bit floats.
        self.elements = self._elements_type(*(tensor.to(dtype).to(device) for tensor in _fields(exact)))
        target = self._elements_type(*(tensor.to(dtype).to(device) for tensor in _fields(_target_of(exact, seed))))
        with torch.no_grad():
            self.target_image = self._draw(target, self.viewport, scale)
        self.weights = _weights(self.target_image.shape, seed).to(dtype).to(device)

    def image(self, tensors: Sequence[Any]) -> Any:
        return self._draw(self._elements_type(*tensors), self.viewport, self.scale)

    def value(self, name: str, tensors: Sequence[Any]) -> Any:
        image = self.image(tensors)
        if name == "squared_difference_from_target":
            return ((image - self.target_image) ** 2).sum()
        return (image * self.weights).sum()


def _fields(elements: Any) -> tuple[Any, Any, Any, Any]:
    return elements.box, elements.fill, elements.corner_radius, elements.opacity


# --- finite differences ---------------------------------------------------------


def _finite_differences(entry: dict[str, Any], scale: float, config: dict[str, Any]) -> list[dict[str, Any]]:
    import torch

    step = config["finite_differences"]["step"]
    absolute, relative = config["finite_differences"]["absolute_tolerance"], config["finite_differences"]["relative_tolerance"]
    scalars = _Scalars(entry, scale, config["seed"], torch.float64)
    rows = []
    for name in SCALARS:
        leaves = _leaves(scalars.elements)
        analytic = torch.autograd.grad(scalars.value(name, leaves), leaves)
        numeric = []
        with torch.no_grad():
            for position, leaf in enumerate(leaves):
                values = leaf.detach().clone()
                found = torch.zeros_like(values)
                for index in range(values.numel()):
                    ends = []
                    for sign in (1, -1):
                        nudged = values.clone()
                        nudged.view(-1)[index] += sign * step
                        ends.append(scalars.value(name, [*leaves[:position], nudged, *leaves[position + 1 :]]))
                    found.view(-1)[index] = (ends[0] - ends[1]) / (2 * step)
                numeric.append(found)
        ours, theirs = _by_attribute(*analytic), _by_attribute(*numeric)
        for attribute in ATTRIBUTES:
            error = (ours[attribute] - theirs[attribute]).abs()
            rows.append(
                {
                    "scene": entry["name"],
                    "scale": scale,
                    "scalar": name,
                    "attribute": attribute,
                    "numbers": int(error.numel()),
                    "largest_gradient": float(theirs[attribute].abs().max()),
                    "largest_error": float(error.max()),
                    "passed": bool((error <= absolute + relative * theirs[attribute].abs()).all()),
                }
            )
    return rows


# --- the Apple GPU path -----------------------------------------------------------


def apple_gpu_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run inside a process of its own (`core_ultra.renderer_case`): every scene
    drawn on the Apple GPU path in 32-bit floats, forward alone and then
    backward, each compared with the CPU in 64-bit floats."""
    import warnings

    import torch

    config = case["config"]
    tolerances = config["apple_gpu_path"]
    forward, backward = [], []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for entry in config["scenes"]:
            for scale in config["scales"]:
                on_cpu = _Scalars(entry, scale, config["seed"], torch.float64)
                on_gpu = _Scalars(entry, scale, config["seed"], torch.float32, "mps")

                with torch.no_grad():
                    image = on_gpu.image(_fields(on_gpu.elements))
                    expected = on_cpu.image(_fields(on_cpu.elements))
                torch.mps.synchronize()
                apart = float((image.cpu().double() - expected).abs().max())
                forward.append(
                    {
                        "scene": entry["name"],
                        "scale": scale,
                        "pixels": [int(image.shape[1]), int(image.shape[0])],
                        "largest_difference": apart,
                        "passed": apart <= tolerances["image_tolerance"],
                    }
                )

                # A value 32-bit floats round across a kink has a different,
                # equally right, one-sided gradient; those scenes are forward only.
                if entry.get("on_kinks"):
                    continue
                for name in SCALARS:
                    leaves = _leaves(on_gpu.elements)
                    found = torch.autograd.grad(on_gpu.value(name, leaves), leaves)
                    torch.mps.synchronize()
                    leaves = _leaves(on_cpu.elements)
                    wanted = torch.autograd.grad(on_cpu.value(name, leaves), leaves)
                    ours = _by_attribute(*(tensor.cpu().double() for tensor in found))
                    theirs = _by_attribute(*wanted)
                    for attribute in ATTRIBUTES:
                        error = (ours[attribute] - theirs[attribute]).abs()
                        allowed = tolerances["gradient_absolute_tolerance"] + tolerances["gradient_relative_tolerance"] * theirs[attribute].abs()
                        backward.append(
                            {
                                "scene": entry["name"],
                                "scale": scale,
                                "scalar": name,
                                "attribute": attribute,
                                "numbers": int(error.numel()),
                                "largest_gradient": float(theirs[attribute].abs().max()),
                                "largest_error": float(error.max()),
                                "passed": bool((error <= allowed).all()),
                            }
                        )
    messages = [str(warning.message).splitlines()[0] for warning in caught]
    return {
        "ok": True,
        "torch": torch.__version__,
        "forward": forward,
        "backward": backward,
        "cpu_fallback_operations": sorted({match.group(1) for message in messages if (match := apple_gpu_path.FALLBACK_WARNING.search(message))}),
    }


def _apple_gpu_path(config: dict[str, Any], say: Progress) -> dict[str, Any]:
    import torch

    section: dict[str, Any] = {
        "dtype": "float32",
        "compared_with": "the CPU in 64-bit floats",
        "tolerances": config["apple_gpu_path"],
        "available": bool(torch.backends.mps.is_available()),
    }
    if not section["available"]:
        section.update({"passed": False, "statement": "PyTorch reports no usable Apple GPU, so nothing was run on it and no cell is verified there."})
        return section

    say("Apple GPU path: forward and backward, CPU fallback not allowed")
    plain, _ = _run_child(config)
    unsupported: list[str] = []
    if not plain["ok"]:
        match = apple_gpu_path.UNIMPLEMENTED.search(plain["error"]["message"])
        if plain["error"]["type"] == "NotImplementedError" and match:
            unsupported.append(match.group(1))
    # The fallback is allowed here so that every unsupported operation is
    # named in one run, with PyTorch's profiler of the Apple GPU path logging.
    say("Apple GPU path: again with the CPU fallback allowed and PyTorch's profiler logging")
    audited, stderr = _run_child(config, fallback=True, profile=True)
    profile = apple_gpu_path.profiled(stderr)
    used = plain if plain["ok"] else audited
    fallbacks = sorted(set(audited.get("cpu_fallback_operations", [])) | set(profile["profiler_fallback_operations"]) | set(unsupported))
    section.update(
        {
            "ran_without_cpu_fallback": plain["ok"],
            "error": plain.get("error"),
            "unsupported_operations": unsupported,
            "cpu_fallback_operations": fallbacks,
            "profile": {"ok": audited["ok"], "error": audited.get("error"), **profile},
            "forward": used.get("forward", []),
            "backward": used.get("backward", []),
        }
    )
    section["forward_passed"] = bool(section["forward"]) and all(row["passed"] for row in section["forward"])
    section["backward_passed"] = bool(section["backward"]) and all(row["passed"] for row in section["backward"])
    section["passed"] = section["forward_passed"] and section["backward_passed"]
    if not used["ok"]:
        section["statement"] = "The scenes could not be drawn on the Apple GPU path, with or without the CPU fallback."
    elif fallbacks:
        section["statement"] = "Operations fell back to the CPU: " + ", ".join(fallbacks) + "."
    elif not profile["profiler_output_seen"]:
        section["statement"] = "Forward and backward ran without the CPU fallback. PyTorch's profiler printed nothing, so its count of fallbacks is unknown."
    else:
        section["statement"] = "Forward and backward ran on the Apple GPU path with no unsupported operation and no CPU fallback."
    return section


def _run_child(config: dict[str, Any], fallback: bool = False, profile: bool = False) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryDirectory() as folder:
        result_path = Path(folder) / "result.json"
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "core_ultra.renderer_case", str(result_path)],
                input=json.dumps({"config": config}),
                capture_output=True,
                text=True,
                env=apple_gpu_path.environment(fallback, profile),
                timeout=_CASE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": {"type": "Timeout", "message": f"no result after {_CASE_TIMEOUT_SECONDS} seconds"}}, ""
        if not result_path.exists():
            last_line = (completed.stderr.strip().splitlines() or [""])[-1].replace(str(Path.home()), "~")
            message = f"exit status {completed.returncode}: {last_line}".rstrip(": ")
            return {"ok": False, "error": {"type": "ProcessDied", "message": message}}, completed.stderr
        return json.loads(result_path.read_text()), completed.stderr


# --- moves and zero gradients -------------------------------------------------------


def gradient_state(scalar: Any, number: Any, zero_tolerance: float) -> str:
    """Whether `scalar` has a gradient in `number`: `non-zero`, `zero`, or
    `disconnected` when `number` is no part of the computation of `scalar`.

    A gradient that is rightly zero and a computation that never used the
    number both look like "nothing to learn from"; only the first is sound.
    """
    import torch

    if not scalar.requires_grad:
        return "disconnected"
    (found,) = torch.autograd.grad(scalar, number, allow_unused=True, retain_graph=True)
    if found is None:
        return "disconnected"
    return "zero" if float(found.abs().max()) <= zero_tolerance else "non-zero"


def _numbers_of(item: dict[str, Any]) -> dict[str, Any]:
    """One element's attributes, each a tensor of its own that takes a gradient."""
    import torch

    def leaf(value: Any) -> Any:
        return torch.tensor(value, dtype=torch.float64, requires_grad=True)

    box = dict(zip(("x", "y", "width", "height"), item["box"]))
    return {**{name: leaf(value) for name, value in box.items()}, "corner_radius": leaf(item["corner_radius"]), "fill": leaf(item["fill"]), "opacity": leaf(item["opacity"])}


def _assembled(elements: Sequence[dict[str, Any]]) -> Any:
    """Elements from per-attribute tensors, in the order given."""
    import torch

    from core_ultra.training_renderer import Elements

    return Elements(
        box=torch.stack([torch.stack([numbers[name] for name in ("x", "y", "width", "height")]) for numbers in elements]),
        fill=torch.stack([numbers["fill"] for numbers in elements]),
        corner_radius=torch.stack([numbers["corner_radius"] for numbers in elements]),
        opacity=torch.stack([numbers["opacity"] for numbers in elements]),
    )


def _render_loss(elements: Any, target_image: Any, viewport: tuple[float, float], scale: float) -> Any:
    from core_ultra import training_renderer

    return (training_renderer.draw(elements, viewport, scale) - target_image).abs().mean()


def _move(entry: dict[str, Any], scale: float) -> dict[str, Any]:
    import torch

    from core_ultra import training_renderer

    viewport = tuple(entry["viewport"])
    behind = [entry["backdrop"]] if "backdrop" in entry else []
    start, end = _numbers_of(entry["from"]), _numbers_of(entry["to"])
    with torch.no_grad():
        target_image = training_renderer.draw(_listed([*behind, entry["to"]], torch.float64), viewport, scale)
    losses, slopes = [], []
    for index in range(entry["steps"] + 1):
        along = index / entry["steps"]
        # Written so that the last step is the target's own numbers, exactly.
        here = {name: (start[name] * (1 - along) + end[name] * along).detach().requires_grad_(True) for name in ATTRIBUTES}
        loss = _render_loss(_assembled([*(_numbers_of(item) for item in behind), here]), target_image, viewport, scale)
        losses.append(loss.item())
        if index < entry["steps"]:
            found = torch.autograd.grad(loss, [here[name] for name in ATTRIBUTES], allow_unused=True)
            slopes.append(
                float(sum(((gradient * (end[name] - start[name]).detach()).sum() for name, gradient in zip(ATTRIBUTES, found) if gradient is not None), torch.zeros((), dtype=torch.float64)))
            )
    falls = all(later < earlier for earlier, later in zip(losses, losses[1:]))
    return {
        "name": entry["name"],
        "about": entry.get("about", ""),
        "scale": scale,
        "render_loss": losses,
        "slope_along_the_move": slopes,
        "loss_falls_at_every_step": falls,
        "loss_is_zero_on_the_target": losses[-1] == 0.0,
        "gradient_points_along_the_move": all(slope < 0 for slope in slopes),
        "passed": falls and losses[-1] == 0.0 and all(slope < 0 for slope in slopes),
    }


def _zero_gradient(entry: dict[str, Any], scale: float, zero_tolerance: float) -> dict[str, Any]:
    import torch

    from core_ultra import training_renderer

    viewport = tuple(entry["viewport"])
    with torch.no_grad():
        target_image = training_renderer.draw(_listed(entry["target"], torch.float64), viewport, scale)
    elements = [_numbers_of(item) for item in entry["elements"]]
    watched = elements[entry["element"]]
    loss = _render_loss(_assembled(elements), target_image, viewport, scale)
    weights = _weights(target_image.shape, 0)
    reaches_image = (training_renderer.draw(_assembled(elements), viewport, scale) * weights).sum()

    # The same loss with the watched element's numbers cut out of the
    # computation: what a disconnected computation looks like.
    cut = list(elements)
    cut[entry["element"]] = {name: number.detach() for name, number in watched.items()}
    cut_loss = _render_loss(_assembled(cut), target_image, viewport, scale)

    attributes = []
    for name in ATTRIBUTES:
        (found,) = torch.autograd.grad(loss, watched[name], allow_unused=True, retain_graph=True)
        state = gradient_state(loss, watched[name], zero_tolerance)
        expected = "zero" if name in entry["zero"] else "non-zero"
        attributes.append(
            {
                "attribute": name,
                "expected": expected,
                "state": state,
                "largest_gradient": None if found is None else float(found.abs().max()),
                "image_depends_on_it": gradient_state(reaches_image, watched[name], zero_tolerance) == "non-zero",
                "state_when_cut_out": gradient_state(cut_loss, watched[name], zero_tolerance),
                "passed": state == expected and gradient_state(cut_loss, watched[name], zero_tolerance) == "disconnected",
            }
        )
    return {
        "name": entry["name"],
        "about": entry.get("about", ""),
        "scale": scale,
        "render_loss": loss.item(),
        "attributes": attributes,
        "passed": all(row["passed"] for row in attributes),
    }


# --- agreement with the runtime renderer ----------------------------------------------


def exact_cover(entry: dict[str, Any], scale: float, samples: int) -> Any:
    """The scene with each pixel's cover counted from `samples` points, as
    premultiplied RGBA in 0 to 1, shape (height, width, 4).

    The points of a pixel lie on a lattice in which no two share a column or
    a row, so the cover of an upright edge is right to one part in `samples`.
    """
    import numpy as np

    width = math.ceil(entry["viewport"][0] * scale - 1e-9)
    height = math.ceil(entry["viewport"][1] * scale - 1e-9)
    stride = next(step for step in range(round(samples * 0.618), samples + 1) if math.gcd(step, samples) == 1)
    index = np.arange(samples)
    across = np.arange(width)[None, :, None] + (index + 0.5) / samples
    down = np.arange(height)[:, None, None] + ((index * stride) % samples + 0.5) / samples
    image = np.zeros((height, width, 4))
    for element in _scene_of(entry).elements:
        left, top, wide, high = (value * scale for value in (element.x, element.y, element.width, element.height))
        radius = element.style.corner_radius * scale
        # A point is inside when it is in the box and, where it is in a
        # corner's square, within `radius` of that corner's centre.
        dx = np.abs(across - (left + wide / 2)) - (wide / 2 - radius)
        dy = np.abs(down - (top + high / 2)) - (high / 2 - radius)
        inside = (dx <= radius) & (dy <= radius) & ~((dx > 0) & (dy > 0) & (dx * dx + dy * dy > radius * radius))
        cover = inside.mean(axis=2)
        alpha = (cover * element.style.fill[3] * element.style.opacity)[..., None]
        source = np.concatenate([np.asarray(element.style.fill[:3]) * alpha, alpha], axis=-1)
        image = source + image * (1 - alpha)
    return image


def _agreement(entry: dict[str, Any], scale: float, samples: int) -> dict[str, Any]:
    import numpy as np
    import torch

    from core_ultra import runtime_renderer, training_renderer

    scene = _scene_of(entry)
    with torch.no_grad():
        training = training_renderer.draw(training_renderer.elements_of(scene, torch.float64), (scene.viewport_width, scene.viewport_height), scale).numpy() * 255
    straight = runtime_renderer.draw(scene, scale).astype(np.float64)
    runtime = np.concatenate([straight[..., :3] * straight[..., 3:] / 255, straight[..., 3:]], axis=-1)
    exact = exact_cover(entry, scale, samples) * 255

    def numbers(one: Any, other: Any) -> dict[str, Any]:
        apart = np.abs(one - other)
        return {
            "mean_absolute_difference": float(apart.mean()),
            "share_of_pixels_over_16": float((apart.max(axis=2) > THRESHOLD).mean()),
            "largest_difference": float(apart.max()),
        }

    return {
        "scene": entry["name"],
        "scale": scale,
        "pixels": [int(training.shape[1]), int(training.shape[0])],
        "has_corner_radius": any(element.style.corner_radius > 0 for element in scene.elements),
        "training_against_runtime": numbers(training, runtime),
        "training_against_exact_cover": numbers(training, exact),
        "runtime_against_exact_cover": numbers(runtime, exact),
    }


_COMPARISONS = ("training_against_runtime", "training_against_exact_cover", "runtime_against_exact_cover")


def _agreement_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"scenes_drawn": len(rows)}
    for comparison in _COMPARISONS:
        if rows:
            summary[comparison] = {
                "mean_absolute_difference": sum(row[comparison]["mean_absolute_difference"] for row in rows) / len(rows),
                "largest_share_of_pixels_over_16": max(row[comparison]["share_of_pixels_over_16"] for row in rows),
                "largest_difference": max(row[comparison]["largest_difference"] for row in rows),
            }
    return summary


# --- the record ---------------------------------------------------------------------


def check(config: dict[str, Any], doctor_report: dict[str, Any], progress: Progress | None = None) -> dict[str, Any]:
    """Run every check of `config` on this machine and return the record."""
    import torch

    from core_ultra import training_renderer

    say = progress or (lambda message: None)
    scenes = config["scenes"]

    say("Finite differences on the CPU in 64-bit floats")
    finite = [row for entry in scenes if not entry.get("on_kinks") for scale in config["scales"] for row in _finite_differences(entry, scale, config)]
    gpu = _apple_gpu_path(config, say)
    say("Moves and zero gradients")
    moves = [_move(entry, scale) for entry in config.get("moves", []) for scale in config["scales"]]
    zeros = [_zero_gradient(entry, scale, config["zero_tolerance"]) for entry in config.get("zero_gradients", []) for scale in config["scales"]]
    say("Agreement with the runtime renderer and with exact cover")
    valid = [entry for entry in scenes if not entry.get("leaves_viewport")]
    agreement = [_agreement(entry, scale, config["exact_cover_samples"]) for entry in valid for scale in config["scales"]]

    matrix = _support_matrix(training_renderer.SUPPORT, finite, gpu, agreement)
    sections = {
        "finite_differences": bool(finite) and all(row["passed"] for row in finite),
        "apple_gpu_path": gpu["passed"],
        "moves": all(row["passed"] for row in moves),
        "zero_gradients": all(row["passed"] for row in zeros),
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
            "record": doctor.default_record_path(doctor_report).relative_to(DEFAULT_RECORDS_ROOT).as_posix(),
        },
        "torch": torch.__version__,
        "training_renderer_stage": training_renderer.STAGE,
        "config": config,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "definitions": {**DEFINITIONS, "scalars": SCALARS},
        "passed": all(sections.values()),
        "sections_passed": sections,
        "support_matrix": matrix,
        "not_drawn": list(training_renderer.NOT_DRAWN),
        "limits": list(training_renderer.LIMITS),
        "finite_differences": {
            "device": "cpu",
            "dtype": "float64",
            **config["finite_differences"],
            "scenes_left_out": [entry["name"] for entry in scenes if entry.get("on_kinks")],
            "rows": finite,
        },
        "apple_gpu_path": gpu,
        "moves": moves,
        "zero_gradients": zeros,
        "agreement": {
            "scenes_left_out": [entry["name"] for entry in scenes if entry.get("leaves_viewport")],
            "exact_cover_samples": config["exact_cover_samples"],
            "overall": _agreement_summary(agreement),
            "without_corner_radius": _agreement_summary([row for row in agreement if not row["has_corner_radius"]]),
            "rows": agreement,
        },
    }


def _support_matrix(support: Sequence[dict[str, Any]], finite: list[dict[str, Any]], gpu: dict[str, Any], agreement: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def passed(rows: list[dict[str, Any]], attribute: str) -> bool | None:
        mine = [row for row in rows if row["attribute"] == attribute]
        return all(row["passed"] for row in mine) if mine else None

    matrix = []
    for row in support:
        entry: dict[str, Any] = {"primitive": row["primitive"], "stage": row["stage"], "drawn": row["drawn"]}
        if not row["drawn"]:
            entry.update({"drawn_verified": None, "attributes": [], "not_differentiable": list(row["not_differentiable"])})
            matrix.append(entry)
            continue
        entry["drawn_verified"] = bool(gpu.get("forward_passed")) and bool(agreement)
        entry["attributes"] = []
        for attribute in row["gradients"]:
            on_cpu, on_gpu = passed(finite, attribute), passed(gpu.get("backward", []), attribute)
            entry["attributes"].append(
                {
                    "attribute": attribute,
                    "gradient": True,
                    "finite_differences_on_cpu": on_cpu,
                    "apple_gpu_path": on_gpu,
                    "verified": bool(on_cpu) and bool(on_gpu),
                }
            )
        entry["not_differentiable"] = list(row["not_differentiable"])
        matrix.append(entry)
    return matrix


def save(record: dict[str, Any], doctor_report: dict[str, Any], root: Path) -> dict[str, Any]:
    """Write the doctor record and the check's record under `root`.

    Returns their paths and SHA-256 hashes. Records are evidence, so an
    existing file is never overwritten.
    """
    doctor_path = root / record["doctor"]["record"]
    stamp = re.sub(r"[-:]", "", record["created_at"])
    short_id = record["doctor"]["environment_id"].removeprefix("sha256:")[:12]
    path = root / CHECKS_DIR / f"{stamp}-stage-{record['training_renderer_stage']}-{short_id}.json"
    if path.exists():
        raise FileExistsError(17, "File exists", str(path))
    doctor_digest = doctor.save_record(doctor_report, doctor_path)
    data = to_json(record).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)
    return {
        "check": {"path": path, "sha256": hashlib.sha256(data).hexdigest()},
        "doctor": {"path": doctor_path, "sha256": doctor_digest},
    }


def to_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def to_text(record: dict[str, Any]) -> str:
    def mark(value: bool | None) -> str:
        return "not run" if value is None else ("verified" if value else "NOT VERIFIED")

    def worst(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "nothing was compared"
        failed = sum(1 for row in rows if not row["passed"])
        numbers = sum(row["numbers"] for row in rows)
        largest = max(row["largest_error"] for row in rows)
        return f"{numbers} numbers in {len(rows)} comparisons, largest error {largest:.3g}, {failed} failed"

    config, gpu, sections = record["config"], record["apple_gpu_path"], record["sections_passed"]
    lines = [
        f"Training renderer  stage {record['training_renderer_stage']}, PyTorch {record['torch']}",
        f"Configuration      {config['name']} version {config['version']}: {len(config['scenes'])} scenes at "
        + ", ".join(f"{scale:g}" for scale in config["scales"])
        + " pixels per viewport unit",
        "",
        "Support matrix",
    ]
    for row in record["support_matrix"]:
        if not row["drawn"]:
            lines.append(f"  {row['primitive']:<42} not drawn (stage {row['stage']})")
            continue
        lines.append(f"  {row['primitive']:<42} drawn, {mark(row['drawn_verified'])}")
        for cell in row["attributes"]:
            lines.append(
                f"    {cell['attribute']:<16} gradient {mark(cell['verified']):<13} "
                f"finite differences on the CPU: {mark(cell['finite_differences_on_cpu'])}; Apple GPU path: {mark(cell['apple_gpu_path'])}"
            )
        lines.append(f"    no gradient, by design: {', '.join(row['not_differentiable'])}")

    lines += ["", f"Finite differences {'passed' if sections['finite_differences'] else 'FAILED'}: {worst(record['finite_differences']['rows'])}"]
    left_out = record["finite_differences"]["scenes_left_out"]
    if left_out:
        lines.append(f"                   not taken on {', '.join(left_out)} (on kinks, where a gradient is one-sided)")

    lines.append(f"Apple GPU path     {'passed' if sections['apple_gpu_path'] else 'FAILED'}: {gpu['statement']}")
    if gpu["available"]:
        forward = gpu["forward"]
        if forward:
            lines.append(
                f"  forward          {len(forward)} images, largest difference from the CPU {max(row['largest_difference'] for row in forward):.3g} "
                f"(allowed {gpu['tolerances']['image_tolerance']:g}), {sum(1 for row in forward if not row['passed'])} failed"
            )
        lines.append(f"  backward         {worst(gpu['backward'])}")
        lines.append(f"  unsupported      {', '.join(gpu['unsupported_operations']) or 'none'}")
        lines.append(f"  CPU fallbacks    {', '.join(gpu['cpu_fallback_operations']) or 'none'}")

    moves = record["moves"]
    lines.append(f"Moves              {'passed' if sections['moves'] else 'FAILED'}: {sum(1 for row in moves if row['passed'])} of {len(moves)} lower the render loss at every step")
    lines += [f"  FAILED           {row['name']} at {row['scale']:g}" for row in moves if not row["passed"]]
    zeros = record["zero_gradients"]
    lines.append(
        f"Zero gradients     {'passed' if sections['zero_gradients'] else 'FAILED'}: {sum(1 for row in zeros if row['passed'])} of {len(zeros)} "
        "are zero where stated and told apart from a disconnected computation"
    )
    lines += [f"  FAILED           {row['name']} at {row['scale']:g}" for row in zeros if not row["passed"]]

    lines += ["", "Agreement, in levels of 255: mean absolute difference, share of pixels over 16 levels, largest difference"]
    lines.append(f"  {'scene':<18}{'scale':>6}  {'training against runtime':<28}{'training against exact':<28}{'runtime against exact':<28}")
    for row in record["agreement"]["rows"]:
        cells = "".join(
            f"{row[comparison]['mean_absolute_difference']:.3f}  {row[comparison]['share_of_pixels_over_16']:.2%}  {row[comparison]['largest_difference']:.1f}".ljust(28)
            for comparison in _COMPARISONS
        )
        lines.append(f"  {row['scene']:<18}{row['scale']:>6g}  {cells}".rstrip())
    lines.append(f"  Not drawn by this stage, so not compared: {', '.join(record['not_drawn'])}")
    lines += ["", f"Check              {'PASSED' if record['passed'] else 'FAILED'}"]
    return "\n".join(lines) + "\n"
