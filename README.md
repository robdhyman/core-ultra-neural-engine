# Core Ultra neural engine

A pre-alpha in which a trained scene model writes an interface as a scene that deterministic code draws. The spec is [issue 1](https://github.com/robdhyman/core-ultra-neural-engine/issues/1); vocabulary is in [GLOSSARY.md](GLOSSARY.md).

Tested platform: macOS 27 on an Apple M5 with 16 GB of memory. No cross-platform claim is made, and the dependency lock is resolved for macOS on Apple silicon only.

## Set up

The environment is Python 3.12, managed and locked with [`uv`](https://docs.astral.sh/uv/). Nobody chooses a version: `.python-version` pins the interpreter and `uv.lock` pins every package.

```bash
uv sync --locked
```

## Command line

There is one entry point, `core-ultra` (also `python -m core_ultra`). Its only verb so far is `doctor`.

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

## What git keeps

| Location | In git | Holds |
| --- | --- | --- |
| `artifacts/` | No | Weights, datasets, run artifacts and anything else that stays on this machine. |
| `artifacts/**/manifest.json`, `*.manifest.json`, `*.sha256`, `SHA256SUMS` | Yes | The manifests and hashes that describe those artifacts. |
| `records/` | Yes | Doctor records and reports. |

Weight and array files (`*.pt`, `*.safetensors`, `*.npz` and similar) are ignored wherever they land.

## Tests

```bash
uv run pytest
```

The tests run the real command on the machine at hand. `test_report_matches_the_tested_platform` asserts the tested platform above and fails on any other machine on purpose.
