"""The project's single command-line entry point.

Only `doctor` exists so far. The spec's later verbs (`data generate`,
`data gallery`, `renderer check`, `train`, `evaluate`, `report`) are added by
the issues that build them.
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
