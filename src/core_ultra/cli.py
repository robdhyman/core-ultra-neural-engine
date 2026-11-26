"""The project's single command-line entry point.

`doctor`, `measure step`, `design check`, `design draw`, `data generate` and
`data check` exist so far. The spec's later verbs (`data gallery`,
`renderer check`, `train`, `evaluate`, `report`) are added by the issues that
build them.

`scene export` and `scene compare` (issue #32) write a scene as an editable
SVG and measure that SVG against the runtime renderer.
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

    data = verbs.add_parser(
        "data",
        help="generate a dataset and check a written one",
        description="Datasets: scripted sessions written as traceable dataset records.",
    )
    actions = data.add_subparsers(dest="what", required=True, metavar="WHAT")
    generate = actions.add_parser(
        "generate",
        help="run scripted sessions and write dataset records and a manifest",
        description=(
            "Run the scripted sessions of a dataset configuration against the application kernel, "
            "write the true scene of every state reached as a dataset record with its reference "
            "image, and write a manifest of hashes. The same configuration always gives the same "
            "bytes. Exits 2 when the configuration cannot be used or the folder already holds a "
            "different dataset; a dataset is never overwritten."
        ),
    )
    generate.add_argument("--config", type=Path, required=True, metavar="PATH", help="dataset configuration, such as configs/data/tiny-v1.json")
    generate.add_argument(
        "--out", type=Path, default=None, metavar="DIR", help="folder the dataset is written to (default: artifacts/datasets/<name>-v<version>)"
    )
    generate.set_defaults(run=_data_generate)
    verify = actions.add_parser(
        "check",
        help="check a written dataset against its manifest and regenerate it",
        description=(
            "Check a written dataset: every file has the hash its manifest gives, no record's "
            "model inputs hold the target or diagnostic metadata, every target is a valid scene, "
            "and generating the dataset again from its own configuration gives the same bytes. "
            "Exits 1 and lists every problem when it does not hold."
        ),
    )
    verify.add_argument("folder", type=Path, metavar="DIR", help="the dataset folder, the one that holds manifest.json")
    verify.set_defaults(run=_data_check)

    scene = verbs.add_parser(
        "scene",
        help="write a scene as an editable SVG and measure the SVG against the runtime renderer",
        description="A stored scene as an editable vector document. The SVG is an export, never what visual results are measured with.",
    )
    actions = scene.add_subparsers(dest="what", required=True, metavar="WHAT")
    export = actions.add_parser(
        "export",
        help="write a dataset record's true scene, or a scene file, as one SVG",
        description=(
            "Write a validated scene as an SVG of separate objects, made to be opened in a design "
            "tool: one group for each scene element, named by its id and nested by parent, with its "
            "shape as a rectangle and its text as text in Inter. The same scene always gives the same "
            "bytes. Exits 1 when the scene is invalid, listing every problem, or holds text that "
            "cannot be written, and 2 when the file holds no scene or the SVG exists with other "
            "contents; nothing is overwritten."
        ),
    )
    export.add_argument("source", type=Path, metavar="PATH", help="a dataset record (its true scene is exported) or a scene file")
    export.add_argument(
        "--out", type=Path, default=None, metavar="FILE", help="the SVG to write (default: the input's name with .svg, in the current folder)"
    )
    export.set_defaults(run=_scene_export)
    compare = actions.add_parser(
        "compare",
        help="measure every exported SVG of a dataset against the runtime renderer's image",
        description=(
            "For every record of a written dataset, export the true scene as SVG, rasterise the SVG "
            "with Qt's SVG module and compare it pixel by pixel with the runtime renderer's image of "
            "the same scene, whole and with every text emptied. Prints the differences overall and by "
            "visual preset. Exits 2 when the folder is not a dataset whose every record can be "
            "exported, or the record exists with other contents."
        ),
    )
    compare.add_argument("folder", type=Path, metavar="DIR", help="the dataset folder, the one that holds manifest.json")
    compare.add_argument("--out", type=Path, default=None, metavar="FILE", help="also write the comparison as a JSON record")
    compare.add_argument("--json", action="store_true", help="print the comparison as JSON instead of text")
    compare.set_defaults(run=_scene_compare)
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


def _data_generate(args: argparse.Namespace) -> int:
    import hashlib

    from core_ultra import generator

    try:
        config = generator.load_config(args.config)
        out = args.out or generator.default_out(config)
        manifest = generator.write(config, out)
    except generator.ConfigError as error:
        print(f"core-ultra: the dataset configuration cannot be used ({len(error.problems)}):", file=sys.stderr)
        for problem in error.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    except generator.DatasetDiffers as error:
        print(f"core-ultra: {error}; nothing was written", file=sys.stderr)
        return 2

    counts = manifest["counts"]
    manifest_path = out / generator.MANIFEST_NAME
    print(f"Dataset            {config.name} version {config.version}, seed {config.seed}")
    print(f"Scripted sessions  {counts['sessions']}")
    print(f"Records            {counts['records']} ({counts['application_states']} application states)")
    for name, count in counts["by_visual_preset"].items():
        print(f"  {name:<16} {count}")
    print(f"Rejected           {counts['rejected']}")
    for rejection in manifest["rejected"]:
        codes = ", ".join(sorted({problem["code"] for problem in rejection["problems"]}))
        print(f"  {rejection['id']:<16} {codes}")
    print(f"Written to         {out}")
    print(f"Manifest           {manifest_path}")
    print(f"Manifest SHA-256   {hashlib.sha256(manifest_path.read_bytes()).hexdigest()}")
    return 0


def _data_check(args: argparse.Namespace) -> int:
    from core_ultra import generator

    problems = generator.check(args.folder)
    if problems:
        print(f"core-ultra: {args.folder} is not the dataset its manifest describes ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"{args.folder} is the dataset its manifest describes, and generating it again gives the same bytes.")
    return 0


def _scene_export(args: argparse.Namespace) -> int:
    import hashlib

    from core_ultra import scene_export
    from core_ultra.scene import SceneInvalid
    from core_ultra.typography import TextNotDrawable

    out = args.out or Path(f"{args.source.stem}.svg")
    try:
        scene, source = scene_export.load(args.source)
        data = scene_export.to_svg(scene).encode("utf-8")
    except scene_export.SourceError as error:
        print(f"core-ultra: {error}", file=sys.stderr)
        return 2
    except SceneInvalid as refused:
        print(f"core-ultra: the scene in {args.source} is invalid and was not exported ({len(refused.problems)}):", file=sys.stderr)
        for problem in refused.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except (TextNotDrawable, scene_export.NotExportable) as refused:
        print(f"core-ultra: the scene in {args.source} was not exported: {refused}", file=sys.stderr)
        return 1
    if not _write_once(out, data):
        return 2
    print(f"Scene              {args.source} ({source})")
    print(f"Elements           {len(scene.elements)} ({len(scene.bound_elements)} bound, {len(scene.structural_elements)} structural)")
    print(f"Written to         {out}")
    print(f"SVG SHA-256        {hashlib.sha256(data).hexdigest()}")
    return 0


def _scene_compare(args: argparse.Namespace) -> int:
    from core_ultra import scene_export_comparison
    from core_ultra.scene_export import SourceError

    try:
        record = scene_export_comparison.measure(args.folder)
    except SourceError as error:
        print(f"core-ultra: {error}", file=sys.stderr)
        return 2
    if args.out is not None and not _write_once(args.out, scene_export_comparison.to_json(record).encode("utf-8")):
        return 2
    sys.stdout.write(scene_export_comparison.to_json(record) if args.json else scene_export_comparison.to_text(record))
    if args.out is not None:
        # With --json, stdout stays a single JSON document.
        print(f"Saved record       {args.out}", file=sys.stderr if args.json else sys.stdout)
    return 0


def _write_once(path: Path, data: bytes) -> bool:
    """Write the file, or leave an identical one alone. False, with the reason
    printed, when it exists with other contents or cannot be written."""
    try:
        if path.exists():
            if path.read_bytes() == data:
                return True
            print(f"core-ultra: {path} already exists with other contents; nothing was written", file=sys.stderr)
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as error:
        print(f"core-ultra: {path} cannot be written: {error.strerror or error}", file=sys.stderr)
        return False
    return True
