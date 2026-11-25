# Core Ultra neural engine

A pre-alpha in which a trained scene model writes an interface as a scene that deterministic code draws. The spec is [issue 1](https://github.com/robdhyman/core-ultra-neural-engine/issues/1); vocabulary is in [GLOSSARY.md](GLOSSARY.md).

Tested platform: macOS 27 on an Apple M5 with 16 GB of memory. No cross-platform claim is made, and the dependency lock is resolved for macOS on Apple silicon only.

## Set up

The environment is Python 3.12, managed and locked with [`uv`](https://docs.astral.sh/uv/). Nobody chooses a version: `.python-version` pins the interpreter and `uv.lock` pins every package.

```bash
uv sync --locked
```

## Command line

There is one entry point, `core-ultra` (also `python -m core_ultra`). Its verbs so far are `doctor` and `measure step`.

### `doctor`

```bash
uv run core-ultra doctor
```

`doctor` reports the OS version, Python version, accelerators, memory, free disk and every declared dependency with its version and whether it imports. The Apple GPU path counts as usable only when a small forward and backward pass runs on it in 32-bit floats and agrees with the CPU. It exits 1 when the report lists a problem.

| Flag | Effect |
| --- | --- |
| `--json` | Print the report as JSON instead of text. |
| `--save` | Also write the report to `records/doctor/<time>-<environment id>.json`. |
| `--save PATH` | Also write the report to `PATH`. An existing file is never overwritten. |

A saved record is what later measurements point at. `--save` prints the record's path, its SHA-256 and the report's `environment_id`, a hash of the fields that identify the environment (project version, OS build, hardware, Python, memory size, accelerators and dependency versions). Time, free memory and free disk are left out of that hash, so two runs on an unchanged machine share one id.

The report holds no host name, user name, serial number or absolute path, because records are committed to a public repository.

### `measure step`

```bash
uv run core-ultra measure step
```

`measure step` times a complete training step (zeroing gradients, forward, loss, backward, optimiser update) and reads its peak memory, for a placeholder scene model at every size, batch size and device in a configuration. It takes several minutes. Run it on AC power with Low Power Mode off and other applications closed: each case records free memory, swap in use, the power source and Low Power Mode, and the record says so when a case ran throttled. It exits 1 when doctor lists a problem or another measurement is already running (nothing is measured), or when no starting size could be chosen.

The placeholder ([src/core_ultra/placeholder.py](src/core_ultra/placeholder.py)) is a transformer encoder with the planned output positions (32 bound, 16 structural) and output fields. Its inputs and targets are random numbers, so the measurement says what a step costs and nothing about what a model learns.

| Flag | Effect |
| --- | --- |
| `--config PATH` | Measurement configuration. Default: `configs/measure/training-step-v1.json`. |
| `--records DIR` | Folder the records are written under. Default: `records`. |
| `--json` | Print the measurement record as JSON instead of text. |

Every run saves two records, neither ever overwritten: a doctor record in `records/doctor/` and the measurement in `records/measurements/training-step/`. The measurement names the doctor record with its SHA-256, and every case carries the doctor report's `environment_id`.

What the record holds:

- **Step time.** Every timed step of every case, with median, mean, minimum, maximum and 90th percentile. On the Apple GPU path the clock stops only after the device has finished its queued work. A separate set of steps, never counted in the step time, splits forward, loss, backward and update.
- **Peak memory.** Each case runs in its own process. The figure is the peak of the process's physical footprint as macOS accounts it, which on Apple silicon includes memory held for the GPU.
- **Apple GPU path.** Timed cases run with PyTorch's CPU fallback switched off, so an operation the path does not implement stops the step and is named. One further untimed run per size allows the fallback and turns on PyTorch's MPS profiler, which logs each CPU fallback and counts copies between CPU and GPU memory.
- **Starting size.** Chosen by the rule in the configuration: among sizes that ran on the Apple GPU path with no CPU fallback, inside the memory budget and the time budget, the one inside the planned parameter range nearest its middle. If memory or time rules out the whole range, the record names that limit.
- **Projections.** Run durations computed as steps multiplied by the measured median step, labelled as projections. The epoch counts in them are assumptions for scale. The record lists what the step does not include (the render loss, the assignment inside the structure loss, data loading, evaluation).

The chosen size is recorded in `configs/scene-model/v1.json`, which names the measurement record it came from with its SHA-256.

## Scene session

The scene session is the one interface from application state to a drawn interface. It runs without a window.

```python
from core_ultra.kernel import Kernel
from core_ultra.scene_session import Conditioning, RenderingMode, SceneSession

kernel = Kernel("application.sqlite")
kernel.create_document("Quarterly plan")

frame = SceneSession().frame(kernel.state(), Conditioning(640, 320), RenderingMode.A_REFERENCE, scale=2)
frame.scene             # the validated scene; frame.scene.to_json() is how it is stored
frame.image             # RGBA pixels drawn by the runtime renderer, 1280 by 640 here
frame.hit_test(600, 36) # the bound element at a point in viewport units, or None
```

| Step | Module | What it does |
| --- | --- | --- |
| Application kernel | [kernel.py](src/core_ultra/kernel.py) | Holds documents in SQLite. Commands so far: create and list. |
| Documents app adapter | [documents_adapter.py](src/core_ultra/documents_adapter.py) | Describes state as bound elements: identity, role, exact text, binding, state, relationships. No coordinates, no style. |
| Scene writer | [reference_layout.py](src/core_ultra/reference_layout.py) | In A, Reference, the reference layout writes the scene. D, Neural Scene has no scene model yet and says so. |
| Scene validation | [scene.py](src/core_ultra/scene.py) | Accepts the scene or refuses it with every reason. Nothing is repaired. The schema is at the top of the file. |
| Runtime renderer | [runtime_renderer.py](src/core_ultra/runtime_renderer.py) | Draws the validated scene as vectors with Qt's painter, off screen, and answers hit tests from the same outlines. |

`SceneSession.frame_from_scene` draws a scene written elsewhere (a stored scene, a hand-written one, later a scene model's output) after validating it against the same state. An invalid scene raises `SceneInvalid`, which lists each problem with a code: a bound element missing, duplicated, invented or altered; a number that is not finite or out of range; a box outside the viewport; a malformed tree; a structural element carrying text or a binding; more than 32 bound or 16 structural elements.

Limits of this first version, the A, Reference tracer:

- One arrangement of the document list in one set of plain style values. Visual presets, design conditions and layout families come with the generator.
- Text is one line in Helvetica Neue, a system font that is read and never redistributed. It is not elided, wrapped or clipped, and a character the font lacks is refused, not substituted.
- Where text sits in its box is a rule of the runtime renderer, not a scene value: on the vertical centre, a button's text centred, other text as far from the left edge as from the top.
- `elevation` is carried by the scene and not drawn yet.
- Pointer and focus state (`ApplicationState.interaction`) is supplied by the caller; no command changes it yet.

Why Qt's painter: [docs/adr/0002-qt-painter-is-the-runtime-renderer.md](docs/adr/0002-qt-painter-is-the-runtime-renderer.md).

## What git keeps

| Location | In git | Holds |
| --- | --- | --- |
| `artifacts/` | No | Weights, datasets, run artifacts and anything else that stays on this machine. |
| `artifacts/**/manifest.json`, `*.manifest.json`, `*.sha256`, `SHA256SUMS` | Yes | The manifests and hashes that describe those artifacts. |
| `records/` | Yes | Doctor records, measurement records, milestone records and reports. |
| `configs/` | Yes | Versioned configurations: what was measured and the model size chosen from it. |

Weight and array files (`*.pt`, `*.safetensors`, `*.npz` and similar) are ignored wherever they land.

## Tests

```bash
uv run pytest
```

The tests run the real commands on the machine at hand; `measure step` is run on a configuration small enough to finish in seconds. The scene session tests ([tests/test_scene_session.py](tests/test_scene_session.py)) build state in a real kernel and assert on the scene, its validity, the drawn image and hit-test answers; drawn text is judged against Qt's own text-to-path, not against the renderer's code. `test_report_matches_the_tested_platform` asserts the tested platform above and fails on any other machine on purpose.
