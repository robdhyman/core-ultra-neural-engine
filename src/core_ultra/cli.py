"""The project's single command-line entry point.

`doctor`, `measure step`, `design check` and `design draw` exist so far. The
spec's later verbs
(`data generate`, `data gallery`, `renderer check`, `train`, `evaluate`,
`report`) are added by the issues that build them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

_DEFAULT_SAVE = object()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    return args.run(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="core-ultra",
        description="Core Ultra neural engine.",
    )
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="VERB")

    doctor = verbs.add_parser(
        "doctor",
        help="report the machine every later number is tied to",
        description=(
            "Report OS, Python, accelerators, memory, free disk and usable ML "
            "dependencies. Exits 1 when the report lists a problem."
        ),
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="print the report as JSON instead of text",
    )
    doctor.add_argument(
        "--save",
        nargs="?",
        const=_DEFAULT_SAVE,
        default=None,
        metavar="PATH",
        help=(
            "also write the report as a JSON record; without PATH it goes to "
            "records/doctor/<time>-<environment id>.json under the current directory"
        ),
    )
    doctor.set_defaults(run=_doctor)

    measure = verbs.add_parser(
        "measure",
        help="measure what this machine can run",
        description="Measurements that later estimates rest on.",
    )
    kinds = measure.add_subparsers(dest="what", required=True, metavar="WHAT")
    step = kinds.add_parser(
        "step",
        help="time a complete training step and read its peak memory",
        description=(
            "Run a complete training step (forward, loss, backward, optimiser update) of a "
            "placeholder scene model at each size, batch size and device in the configuration, "
            "and save the measurement record with the doctor record it is tied to. Takes "
            "minutes. Exits 1 when doctor lists a problem, another measurement is running or no "
            "starting size could be chosen."
        ),
    )
    step.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="measurement configuration (default: configs/measure/training-step-v1.json)",
    )
    step.add_argument(
        "--records",
        type=Path,
        default=None,
        metavar="DIR",
        help="folder the records are written under (default: records)",
    )
    step.add_argument(
        "--json",
        action="store_true",
        help="print the measurement record as JSON instead of text",
    )
    step.set_defaults(run=_measure_step)

    design = verbs.add_parser(
        "design",
        help="check the design source and draw its visual presets",
        description="The design source: DESIGN.md, the generator configuration and the visual presets.",
    )
    actions = design.add_subparsers(dest="what", required=True, metavar="WHAT")
    check = actions.add_parser(
        "check",
        help="fail when DESIGN.md and the generator configuration disagree",
        description=(
            "Compare DESIGN.md with the generator configuration: every token of every visual "
            "preset, every component and the states. Exits 1 and lists each disagreement when "
            "they differ or either file is malformed."
        ),
    )
    check.add_argument("--design-md", type=Path, default=None, metavar="PATH", help="the written design (default: DESIGN.md)")
    check.add_argument(
        "--config", type=Path, default=None, metavar="PATH", help="generator configuration (default: configs/design/v1.json)"
    )
    check.set_defaults(run=_design_check)
    draw = actions.add_parser(
        "draw",
        help="draw one application state in A, Reference in every visual preset",
        description=(
            "Draw the same application state in A, Reference in every visual preset and save one "
            "PNG per preset, a sheet of all of them and a manifest of hashes. Exits 2 when a file "
            "exists with other contents; nothing is overwritten."
        ),
    )
    draw.add_argument(
        "--out", type=Path, default=None, metavar="DIR", help="folder the images are written to (default: records/design/v<version>)"
    )
    draw.add_argument("--scale", type=float, default=2.0, metavar="N", help="pixels per viewport unit (default: 2)")
    draw.set_defaults(run=_design_draw)
    return parser


def _doctor(args: argparse.Namespace) -> int:
    from core_ultra import doctor

    report = doctor.collect_report()
    sys.stdout.write(doctor.to_json(report) if args.json else doctor.to_text(report))

    if args.save is not None:
        path = (
            doctor.default_record_path(report)
            if args.save is _DEFAULT_SAVE
            else Path(args.save)
        )
        try:
            digest = doctor.save_record(report, path)
        except FileExistsError:
            print(f"core-ultra: {path} already exists; records are never overwritten", file=sys.stderr)
            return 2
        # With --json, stdout stays a single JSON document.
        notice = sys.stderr if args.json else sys.stdout
        print(f"Saved record       {path}", file=notice)
        print(f"Record SHA-256     {digest}", file=notice)
        print(f"Environment        {report['environment_id']}", file=notice)

    return 1 if report["problems"] else 0


def _measure_step(args: argparse.Namespace) -> int:
    from core_ultra import doctor, step_measurement

    try:
        config = step_measurement.load_config(args.config or step_measurement.DEFAULT_CONFIG)
    except step_measurement.ConfigError as error:
        print(f"core-ultra: {error}", file=sys.stderr)
        return 2

    running = step_measurement.other_measurements()
    if running:
        print(
            "core-ultra: nothing was measured, because another measurement is running "
            f"(process {', '.join(map(str, running))}); overlapping measurements slow each other",
            file=sys.stderr,
        )
        return 1

    report = doctor.collect_report()
    if report["problems"]:
        print("core-ultra: nothing was measured, because doctor lists a problem:", file=sys.stderr)
        for problem in report["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    record = step_measurement.measure(
        config, report, progress=lambda message: print(message, file=sys.stderr, flush=True)
    )
    root = args.records or step_measurement.DEFAULT_RECORDS_ROOT
    try:
        saved = step_measurement.save(record, report, root)
    except FileExistsError as error:
        print(f"core-ultra: {error.filename} already exists; records are never overwritten", file=sys.stderr)
        return 2

    sys.stdout.write(
        step_measurement.to_json(record) if args.json else step_measurement.to_text(record)
    )
    # With --json, stdout stays a single JSON document.
    notice = sys.stderr if args.json else sys.stdout
    print(file=notice)
    print(f"Saved record       {saved['measurement']['path']}", file=notice)
    print(f"Record SHA-256     {saved['measurement']['sha256']}", file=notice)
    print(f"Doctor record      {saved['doctor']['path']}", file=notice)
    print(f"Doctor SHA-256     {saved['doctor']['sha256']}", file=notice)
    return 0 if record["selection"]["chosen"] else 1


def _design_check(args: argparse.Namespace) -> int:
    from core_ultra import design

    problems = design.check(args.design_md, args.config)
    if problems:
        print(f"core-ultra: DESIGN.md and the generator configuration do not agree ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"DESIGN.md and the generator configuration agree: {design.summary(args.config)}.")
    return 0


def _design_draw(args: argparse.Namespace) -> int:
    from core_ultra import design, preset_sheet

    try:
        version = design.load().version
    except design.DesignError as error:
        print(f"core-ultra: the generator configuration cannot be used: {error}", file=sys.stderr)
        return 2
    out = args.out or Path("records") / "design" / f"v{version}"
    try:
        manifest = preset_sheet.write(out, args.scale)
    except FileExistsError as error:
        print(f"core-ultra: {error} already exists with other contents; nothing was written", file=sys.stderr)
        return 2
    for image in manifest["images"]:
        print(f"{image['visual_preset']:<16} {out / image['file']}  {image['sha256']}")
    print(f"{'every preset':<16} {out / manifest['sheet']['file']}  {manifest['sheet']['sha256']}")
    print(f"{'manifest':<16} {out / preset_sheet.MANIFEST_NAME}")
    return 0
