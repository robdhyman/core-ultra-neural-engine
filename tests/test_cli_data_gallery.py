"""Command-line tests for `data gallery`, the pilot dataset and its review
gallery (test seam 2).

`data generate` and `data gallery` are run for real: on a small configuration
made here, in which the validators reject some states, and on the committed
pilot configuration.

The judges are independent of the gallery's code. The page is read with the
standard library's HTML parser. What a picture should be labelled with, and
what the coverage summary should count, are worked out here from the
dataset's own records and manifest. A picture is compared byte for byte with
the dataset's file, or, for a rejected state, read as a PNG with Qt.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = REPO_ROOT / "configs" / "data" / "families-v2.json"
PILOT = REPO_ROOT / "configs" / "data" / "pilot-v2.json"
COMMITTED_PILOT_MANIFEST = REPO_ROOT / "artifacts" / "datasets" / "pilot-v2" / "manifest.json"
COMMITTED_GALLERY_MANIFEST = REPO_ROOT / "artifacts" / "galleries" / "pilot-v2" / "manifest.json"
# The first pilot, in layout version 3, which version 2 replaces. Its configuration and manifest stay.
FIRST_PILOT = REPO_ROOT / "configs" / "data" / "pilot-v1.json"
COMMITTED_FIRST_PILOT_MANIFEST = REPO_ROOT / "artifacts" / "datasets" / "pilot-v1" / "manifest.json"
LAYOUT_V4 = REPO_ROOT / "configs" / "layout" / "v4.json"

STATES = ("default", "hover", "pressed", "focused", "disabled")
STRESS_CASES = ("viewport-too-small", "titles-too-long", "characters-the-font-lacks", "covered-button")
# A caption names three design factors by a shorter word.
FACTOR_WORDS = {"navigation_position": "navigation", "panel_arrangement": "panels", "notification_location": "notification"}


def run_cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "core_ultra", *map(str, args)], capture_output=True, text=True, cwd=REPO_ROOT, timeout=600
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_of(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def small_config(**changes) -> dict:
    """Four scripted sessions in three layout families and two visual presets.
    The viewport sizes are dealt, and one of them is too small for anything,
    so the validators reject states; three content lengths are declared for
    four sessions in two scenarios, and six pairs of family and preset for
    four sessions, so some declared values are shown by no record."""
    base = json.loads(FAMILIES.read_text())
    config = {
        **base,
        "name": "gallery-test",
        "version": 1,
        "layout_families": ["top-bar-list-left", "left-rail-list-top", "bottom-bar-list-right"],
        "visual_presets": ["warm-paper", "night-teal"],
        "viewports": [[480, 300], [960, 540], [1440, 900]],
        "viewport_choice": "dealt",
        "sessions_per_scenario": 2,
        "scenarios": {"note": ["create", "open", "edit", "save"], "pair": ["create", "create", "open", "rename"]},
        "stress_tests": [case for case in base["stress_tests"] if case["name"] in STRESS_CASES],
        **changes,
    }
    return {name: value for name, value in config.items() if value is not None}


def generate(folder: Path, config: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    out = folder / "dataset"
    result = run_cli("data", "generate", "--config", path, "--out", out)
    assert result.returncode == 0, result.stderr
    return out


class Page(HTMLParser):
    """An HTML page as the tests need it: its figures, each with the ids of
    the sections it lies in, its picture, its labels and its words; its
    tables by caption; and everything it could load."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.figures: list[dict] = []
        self.tables: dict[str, list[list[str]]] = {}
        self.loads: list[tuple[str, str, str]] = []
        self.tags: Counter = Counter()
        self.words: list[str] = []
        self._sections: list[str | None] = []
        self._figure: dict | None = None
        self._label: str | None = None
        self._table: list[list[str]] | None = None
        self._caption: list[str] | None = None
        self._cell: list[str] | None = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        for name in ("src", "href", "srcset", "action", "data", "poster"):
            if name in attrs:
                self.loads.append((tag, name, attrs[name]))
        if tag == "section":
            self._sections.append(attrs.get("id"))
        elif tag == "figure":
            self._figure = {"attrs": attrs, "sections": [name for name in self._sections if name], "img": None, "labels": {}, "words": []}
        elif tag == "img" and self._figure is not None:
            self._figure["img"] = attrs
        elif tag == "dd" and self._figure is not None and "data-label" in attrs:
            self._label = attrs["data-label"]
            self._figure["labels"][self._label] = ""
        elif tag == "table":
            self._table = []
        elif tag == "caption":
            self._caption = []
        elif tag == "tr" and self._table is not None:
            self._table.append([])
        elif tag in ("td", "th") and self._table:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "section":
            self._sections.pop()
        elif tag == "figure":
            self._figure["text"] = " ".join(" ".join(self._figure.pop("words")).split())
            self.figures.append(self._figure)
            self._figure = None
        elif tag == "dd":
            self._label = None
        elif tag in ("td", "th") and self._cell is not None:
            self._table[-1].append("".join(self._cell).strip())
            self._cell = None
        elif tag == "table":
            self.tables["".join(self._caption or []).strip()] = self._table
            self._table = self._caption = None

    def handle_data(self, data):
        self.words.append(data)
        if self._figure is not None:
            self._figure["words"].append(data)
            if self._label is not None:
                self._figure["labels"][self._label] += data
        if self._cell is not None:
            self._cell.append(data)
        elif self._caption is not None and self._table == []:
            self._caption.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.words).split())


def build(dataset: Path, out: Path) -> dict:
    result = run_cli("data", "gallery", dataset, "--out", out)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((dataset / "manifest.json").read_text())
    return {
        "result": result,
        "dataset": dataset,
        "out": out,
        "dataset_manifest": manifest,
        "records": [json.loads((dataset / entry["file"]).read_text()) for entry in manifest["records"]],
        "manifest": json.loads((out / "manifest.json").read_text()),
        "page": Page((out / "index.html").read_text(encoding="utf-8")),
    }


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("data-gallery")


@pytest.fixture(scope="module")
def run(folder) -> dict:
    """One real run of `data gallery` on the small dataset."""
    return build(generate(folder / "small", small_config()), folder / "small" / "gallery")


@pytest.fixture(scope="module")
def pilot(folder) -> dict:
    """The committed pilot configuration, generated and its gallery built."""
    out = folder / "pilot" / "dataset"
    result = run_cli("data", "generate", "--config", PILOT, "--out", out)
    assert result.returncode == 0, result.stderr
    return build(out, folder / "pilot" / "gallery")


def as_shown(detail: str) -> str:
    """A reason as the page words it: its measurements to one decimal place at
    most. None of the reasons in these datasets quotes text with a decimal."""
    shorter = re.sub(r"\d+\.\d+", lambda number: f"{float(number.group()):.1f}".removesuffix(".0"), detail)
    return " ".join(shorter.split())


def record_figures(page: Page) -> list[dict]:
    return [figure for figure in page.figures if "records" in figure["sections"]]


def apart_figures(page: Page, group: str) -> dict[str, dict]:
    return {figure["attrs"]["data-id"]: figure for figure in page.figures if group in figure["sections"]}


def states_of(record: dict) -> Counter:
    return Counter(element["state"] for element in record["application"]["bound_elements"])


# --- what the command writes -----------------------------------------------------------


def test_the_command_writes_a_page_a_manifest_and_every_picture(run):
    out, manifest = run["out"], run["manifest"]
    written = files_of(out)
    assert manifest["kind"] == "dataset-gallery" and manifest["page"] == "index.html"
    assert manifest["dataset"]["name"] == "gallery-test"
    assert manifest["dataset"]["manifest_sha256"] == sha256((run["dataset"] / "manifest.json").read_bytes())
    # The manifest lists every other file with its hash, and nothing else is written.
    assert set(manifest["files"]) == set(written) - {"manifest.json"}
    assert all(sha256(written[name]) == listed for name, listed in manifest["files"].items())
    assert {f"images/{record['id']}.png" for record in run["records"]} <= set(written)
    stdout = run["result"].stdout
    assert f"Records shown      {len(run['records'])}" in stdout
    assert f"Open               {out / 'index.html'}" in stdout
    assert f"Manifest SHA-256   {sha256(written['manifest.json'])}" in stdout


def test_every_record_is_on_the_page_once_with_its_own_reference_image(run):
    figures = record_figures(run["page"])
    assert [figure["attrs"]["id"] for figure in figures] and len(figures) == len(run["records"]) > 0
    by_id = {figure["attrs"]["id"].removeprefix("record-"): figure for figure in figures}
    assert set(by_id) == {record["id"] for record in run["records"]} and len(by_id) == len(figures)
    for record in run["records"]:
        picture = by_id[record["id"]]["img"]
        shown = (run["out"] / picture["src"]).read_bytes()
        assert shown == (run["dataset"] / record["reference_image"]["file"]).read_bytes()
        assert sha256(shown) == record["reference_image"]["sha256"]
        assert (int(picture["width"]), int(picture["height"])) == (record["reference_image"]["width"], record["reference_image"]["height"])


def test_every_picture_is_labelled_with_its_layout_family_visual_preset_design_condition_and_state(run):
    by_id = {figure["attrs"]["id"].removeprefix("record-"): figure for figure in record_figures(run["page"])}
    seen_states = set()
    for record in run["records"]:
        labels = by_id[record["id"]]["labels"]
        assert set(labels) == {"layout family", "visual preset", "design condition", "state"}
        assert labels["layout family"] == record["diagnostics"]["layout_family"]
        assert labels["visual preset"] == record["diagnostics"]["visual_preset"]
        # The design condition is every factor value the scene model was given, each with its factor.
        condition = record["inputs"]["design_condition"]
        assert len(condition) == 7
        assert labels["design condition"] == ", ".join(
            f"{FACTOR_WORDS.get(factor, factor.replace('_', ' '))} {value}" for factor, value in condition.items()
        )
        # The state is what is pointed at and how, then every element state the frame shows.
        pointed, shows = labels["state"].split("; shows ")
        interaction = record["application"]["state"]["interaction"]
        assert pointed == (", ".join(f"{state} on {identity}" for identity, state in sorted(interaction.items())) or "nothing pointed at")
        assert shows.split(", ") == [state for state in STATES if states_of(record)[state]]
        seen_states.update(shows.split(", "))
    assert seen_states == set(STATES)


def test_the_records_are_grouped_by_layout_family_and_no_rejected_state_is_among_them(run):
    manifest = run["dataset_manifest"]
    figures = record_figures(run["page"])
    families = [figure["labels"]["layout family"] for figure in figures]
    # One run of pictures for each family, in the configuration's order.
    assert [family for index, family in enumerate(families) if index == 0 or families[index - 1] != family] == [
        family for family in small_config()["layout_families"] if family in families
    ]
    shown = {figure["attrs"]["id"].removeprefix("record-") for figure in figures}
    assert not shown & {rejection["id"] for rejection in manifest["rejected"]}
    assert not shown & {case["id"] for case in manifest["stress_tests"]["records"]}
    assert all("apart" not in figure["sections"] for figure in figures)


# --- what is shown apart ---------------------------------------------------------------


def test_rejected_states_are_shown_apart_each_with_every_reason(run):
    manifest = run["dataset_manifest"]
    assert manifest["counts"]["rejected"] > 1
    figures = apart_figures(run["page"], "rejected")
    assert set(figures) == {rejection["id"] for rejection in manifest["rejected"]}
    reasons = Counter()
    for rejection in manifest["rejected"]:
        figure = figures[rejection["id"]]
        assert figure["sections"] == ["apart", "rejected"]
        assert "rejected: not a dataset record" in figure["text"]
        assert rejection["layout_family"] in figure["text"] and rejection["visual_preset"] in figure["text"]
        for problem in rejection["problems"]:
            assert problem["code"] in figure["text"] and problem["validator"] in figure["text"]
            assert as_shown(problem["detail"]) in figure["text"]
        assert figure["attrs"]["data-codes"] == ", ".join(sorted({problem["code"] for problem in rejection["problems"]}))
        reasons[rejection["reason"]] += 1
        size = rejection["viewport"]
        if rejection["reason"] == "scene_invalid":
            # Scene validation refused it, so nothing can draw it, and the page says so.
            assert figure["img"] is None and "No picture" in figure["text"]
        else:
            # The validators rejected a scene that can be drawn: it is drawn again, at its viewport size.
            picture = QImage(str(run["out"] / figure["img"]["src"]))
            assert not picture.isNull() and (picture.width(), picture.height()) == (int(size["width"]), int(size["height"]))
            assert figure["img"]["src"] == f"rejected/{rejection['id']}.png"
            assert not (run["dataset"] / "images" / f"{rejection['id']}.png").exists()
    assert reasons["scene_invalid"] and reasons["rejected_by_validators"]
    counts = run["manifest"]["counts"]
    assert counts["rejected"] == len(manifest["rejected"])
    assert (counts["rejected_states_drawn"], counts["rejected_states_not_drawn"]) == (reasons["rejected_by_validators"], reasons["scene_invalid"])
    assert f"Shown apart        {len(manifest['rejected'])} rejected" in run["result"].stdout


def test_a_rejected_state_is_drawn_as_the_scene_the_validators_judged(run):
    """The picture of a rejected state is the runtime renderer's drawing of
    the reference layout's scene for that state, in the session's design."""
    from core_ultra import generator, reference_layout, runtime_renderer, scene as scene_schema, scripted_session
    import random

    manifest = run["dataset_manifest"]
    config = generator.load_config(run["dataset"] / "config.json")
    rejection = next(rejection for rejection in manifest["rejected"] if rejection["reason"] == "rejected_by_validators")
    session = next(session for session in manifest["sessions"] if session["id"] == rejection["session"])
    content = config.content_lengths[session["content_length"]]
    moments = list(scripted_session.run(config.scenarios[session["scenario"]], content, random.Random(session["seed"])))
    moment = moments[int(rejection["id"].rsplit(".", 1)[1])]
    viewport = (rejection["viewport"]["width"], rejection["viewport"]["height"])
    family = config.layout.family(rejection["layout_family"])
    candidate = reference_layout.write_scene(moment.bound_elements, viewport, config.design.preset(rejection["visual_preset"]), family.design_condition)
    expected = runtime_renderer.png_bytes(runtime_renderer.draw(scene_schema.validate(candidate, moment.bound_elements, viewport), config.scale))
    assert (run["out"] / "rejected" / f"{rejection['id']}.png").read_bytes() == expected


def test_refused_viewport_sizes_are_shown_apart_with_the_first_state_rejected_there(folder):
    made = build(generate(folder / "fitting", small_config(viewport_choice="fitting")), folder / "fitting" / "gallery")
    manifest = made["dataset_manifest"]
    refusals = [(session, refusal) for session in manifest["sessions"] for refusal in session["viewports_refused"]]
    assert refusals and manifest["rejected"] == []
    figures = apart_figures(made["page"], "viewports-refused")
    assert len(figures) == len(refusals) == made["manifest"]["counts"]["viewports_refused"]
    for session, refusal in refusals:
        size = refusal["viewport"]
        figure = figures[f"{session['id']}.{refusal['moment']:03d} at {size['width']:g} by {size['height']:g}"]
        assert figure["sections"] == ["apart", "viewports-refused"]
        assert f"the session was given {session['viewport']['width']:g} by {session['viewport']['height']:g}" in figure["text"]
        assert all(problem["code"] in figure["text"] and as_shown(problem["detail"]) in figure["text"] for problem in refusal["problems"])
    assert apart_figures(made["page"], "rejected") == {}
    assert "No state was rejected." in made["page"].text


def test_a_session_no_viewport_size_fits_is_listed_apart_and_a_gallery_without_records_is_still_built(folder):
    made = build(generate(folder / "nothing-fits", small_config(viewport_choice="fitting", viewports=[[480, 300]])), folder / "nothing-fits" / "gallery")
    manifest = made["dataset_manifest"]
    refused = manifest["sessions_refused"]
    assert len(refused) == 4 and manifest["records"] == [] and record_figures(made["page"]) == []
    assert made["manifest"]["counts"]["sessions_refused"] == 4 and made["manifest"]["counts"]["records"] == 0
    listed = {row[0]: row for row in made["page"].tables[""][1:]}
    assert set(listed) == {session["id"] for session in refused}
    for session in refused:
        assert listed[session["id"]][1:] == [session["layout_family"], session["visual_preset"], "no_viewport_fits"]
    # The size each was refused is among the viewport sizes refused, with its reasons.
    sizes = apart_figures(made["page"], "viewports-refused")
    assert {name.split(".")[0] for name in sizes} == {session["id"] for session in refused}
    assert all("the session was given" not in figure["text"] and "outside_viewport" in figure["text"] for figure in sizes.values())
    summary = made["manifest"]["coverage_summary"]
    assert summary["by"]["visual preset"]["not_shown"] == small_config()["visual_presets"]
    assert f"Records shown      0" in made["result"].stdout


def test_a_rejected_state_is_not_drawn_for_a_dataset_another_generator_version_wrote(run, folder):
    """The scene made again would not be the one that was judged."""
    copy = folder / "older"
    shutil.copytree(run["dataset"], copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["generator"]["version"] -= 1
    (copy / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    made = build(copy, folder / "older-gallery")
    figures = apart_figures(made["page"], "rejected")
    assert len(figures) == len(manifest["rejected"])
    assert all(figure["img"] is None for figure in figures.values())
    assert any("written by another version of the generator" in figure["text"] for figure in figures.values())
    assert made["manifest"]["counts"]["rejected_states_drawn"] == 0
    assert not (made["out"] / "rejected").exists()
    # The records and the stress-test set are the dataset's own files, and are shown as before.
    assert len(record_figures(made["page"])) == len(run["records"])
    assert any(figure["img"] for figure in apart_figures(made["page"], "stress-tests").values())


def test_the_stress_test_set_is_shown_apart_and_labelled_never_a_training_target(run):
    manifest = run["dataset_manifest"]
    cases = manifest["stress_tests"]["records"]
    figures = apart_figures(run["page"], "stress-tests")
    assert set(figures) == {case["id"] for case in cases} == {f"stress.{name}" for name in STRESS_CASES}
    with_picture = 0
    for case in cases:
        record = json.loads((run["dataset"] / case["file"]).read_text())
        figure = figures[case["id"]]
        assert figure["sections"] == ["apart", "stress-tests"]
        assert "stress test: never a training target" in figure["text"]
        assert " ".join(record["why"].split()) in figure["text"]
        assert all(code in figure["text"] for code in case["codes"])
        assert all(as_shown(problem["detail"]) in figure["text"] for problem in record["rejection"]["problems"])
        if case["image"] is None:
            assert figure["img"] is None and "No picture" in figure["text"]
        else:
            with_picture += 1
            assert (run["out"] / figure["img"]["src"]).read_bytes() == (run["dataset"] / case["image"]["file"]).read_bytes()
    assert 0 < with_picture < len(cases)
    assert all(entry["training_target"] is False and entry["set"] == "stress-test" for entry in run["manifest"]["shown_apart"]["stress_tests"])


def test_a_reason_is_shown_with_its_measurements_rounded_and_quoted_text_left_as_it_is(run):
    from core_ultra import gallery

    manifest = run["dataset_manifest"]
    longest = max((problem["detail"] for rejection in manifest["rejected"] for problem in rejection["problems"]), key=len)
    assert re.search(r"\d\.\d{3,}", longest), "the dataset has no measurement written out at length"
    shown = " ".join(figure["text"] for figure in run["page"].figures if "apart" in figure["sections"])
    assert as_shown(longest) in shown and longest not in shown
    # No measurement on the page has more than one decimal place, and none ends in ".0".
    # A record's id ends in its moment, as in `note-1.000`, and is no measurement.
    measured = re.sub(r"[a-z-]+-\d+\.\d{3}\b", "", shown)
    assert not re.search(r"\d\.\d{2,}", measured) and not re.search(r"\d\.0(?!\d)", measured)
    # The manifest keeps the full figures.
    assert longest in (run["dataset"] / "manifest.json").read_text()
    assert gallery._rounded("'Version 3.14159 of 2.50' runs from x 298.60 to 775.0; the box is 0.04 wide") == (
        "'Version 3.14159 of 2.50' runs from x 298.6 to 775; the box is 0.04 wide"
    )


# --- the coverage summary --------------------------------------------------------------


def counted(records: list[dict], manifest: dict) -> dict[str, dict[str, dict[str, int]]]:
    """The coverage summary worked out here from the records alone."""
    length = {session["id"]: session["content_length"] for session in manifest["sessions"]}
    by: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"records": 0, "sessions": set()}))
    for record in records:
        session = record["diagnostics"]["related"]["session"]
        viewport = record["inputs"]["viewport"]
        values = {
            "layout family": [record["diagnostics"]["layout_family"]],
            "visual preset": [record["diagnostics"]["visual_preset"]],
            "density": [record["inputs"]["design_condition"]["density"]],
            "content length": [length[session]],
            "element state": list(states_of(record)),
            "viewport": [f"{viewport['width']:g} by {viewport['height']:g}"],
        }
        for dimension, found in values.items():
            for value in found:
                by[dimension][value]["records"] += 1
                by[dimension][value]["sessions"].add(session)
    return {dimension: {value: {"records": c["records"], "sessions": len(c["sessions"])} for value, c in values.items()} for dimension, values in by.items()}


def test_the_coverage_summary_counts_by_layout_family_visual_preset_density_content_length_and_state(run):
    summary = run["manifest"]["coverage_summary"]
    expected = counted(run["records"], run["dataset_manifest"])
    assert set(summary["by"]) == {"layout family", "visual preset", "density", "content length", "element state", "viewport"}
    assert summary["records"] == len(run["records"])
    for dimension, values in summary["by"].items():
        shown = {value: {"records": count["records"], "sessions": count["sessions"]} for value, count in values["values"].items() if count["records"]}
        assert shown == expected[dimension], dimension
    elements = Counter(state for record in run["records"] for state in states_of(record).elements())
    assert {state: count["elements"] for state, count in summary["by"]["element state"]["values"].items()} == {state: elements[state] for state in STATES}

    # The page shows the same numbers, one table for each, and the command prints them.
    stdout = run["result"].stdout
    for dimension, values in summary["by"].items():
        rows = {row[0]: row for row in run["page"].tables[dimension.capitalize()][1:]}
        assert list(rows) == list(values["values"])
        for value, count in values["values"].items():
            assert rows[value][1:3] == [str(count["records"]), str(count["sessions"])]
            assert any(line.split()[: len(value.split())] == value.split() and str(count["records"]) in line.split() for line in stdout.splitlines())


def test_a_declared_value_no_record_shows_is_listed_as_not_shown(run):
    config = small_config()
    summary = run["manifest"]["coverage_summary"]
    families = {record["diagnostics"]["layout_family"] for record in run["records"]}
    pairs = {(record["diagnostics"]["layout_family"], record["diagnostics"]["visual_preset"]) for record in run["records"]}
    declared_pairs = [[family, preset] for family in config["layout_families"] for preset in config["visual_presets"]]
    missing_pairs = [pair for pair in declared_pairs if tuple(pair) not in pairs]
    assert missing_pairs and summary["pairs_not_shown"] == missing_pairs
    assert summary["by"]["layout family"]["not_shown"] == [family for family in config["layout_families"] if family not in families]
    # A viewport size too small for anything is declared, and every state in it was rejected.
    assert summary["by"]["viewport"]["not_shown"] == ["480 by 300"]
    assert summary["by"]["viewport"]["values"]["480 by 300"] == {"records": 0, "sessions": 0}
    text = run["page"].text
    assert "Not shown: 480 by 300" in text
    assert "Pairs not shown: " + ", ".join(f"{family} in {preset}" for family, preset in missing_pairs) in text
    assert "not shown: 480 by 300" in run["result"].stdout
    cross = summary["layout_family_by_visual_preset"]
    assert {(family, preset) for family, row in cross.items() for preset, count in row.items() if count["records"]} == pairs
    assert sum(count["records"] for row in cross.values() for count in row.values()) == len(run["records"])


# --- a local page ----------------------------------------------------------------------


def test_the_page_opens_from_disk_and_loads_nothing_from_a_network(run):
    page = run["page"]
    assert page.tags["link"] == 0 and page.tags["iframe"] == 0 and page.tags["object"] == 0
    assert not any(tag == "script" for tag, _, _ in page.loads)
    for tag, attribute, value in page.loads:
        assert attribute in ("src", "href")
        if value.startswith("#"):
            continue
        assert "://" not in value and not value.startswith(("/", "data:", "//")), value
        assert (run["out"] / value).is_file(), value
    source = (run["out"] / "index.html").read_text(encoding="utf-8")
    assert "http://" not in source and "https://" not in source and "@import" not in source and "url(" not in source


def test_text_from_the_dataset_is_written_as_text_and_never_as_markup(folder):
    config = small_config(viewport_choice="fitting", viewports=[[1440, 900]], sessions_per_scenario=1)
    marked = '<img src="x.png"> & <script>alert(1)</script>'
    config["stress_tests"] = [{**case, "why": marked} for case in config["stress_tests"] if case["name"] == "covered-button"]
    made = build(generate(folder / "markup", config), folder / "markup" / "gallery")
    figure = apart_figures(made["page"], "stress-tests")["stress.covered-button"]
    assert marked in figure["text"]
    assert made["page"].tags["script"] == 1
    assert not any(value == "x.png" for _, _, value in made["page"].loads)


# --- the same bytes, and nothing overwritten ---------------------------------------------


def test_the_same_dataset_gives_the_same_gallery_and_a_gallery_is_never_overwritten(run, folder):
    again = folder / "small" / "gallery-again"
    assert run_cli("data", "gallery", run["dataset"], "--out", again).returncode == 0
    assert files_of(again) == files_of(run["out"])
    # Building it again into the same folder changes nothing.
    repeated = run_cli("data", "gallery", run["dataset"], "--out", again)
    assert repeated.returncode == 0 and files_of(again) == files_of(run["out"])

    page = again / "index.html"
    page.write_text(page.read_text(encoding="utf-8") + "<!-- changed -->", encoding="utf-8")
    before = files_of(again)
    refused = run_cli("data", "gallery", run["dataset"], "--out", again)
    assert refused.returncode == 2
    assert "already holds a different gallery (index.html has other contents); nothing was written" in refused.stderr
    assert files_of(again) == before
    assert not list(again.parent.glob(".gallery-again.partial-*"))


def test_building_a_gallery_changes_nothing_in_the_dataset(run):
    before = files_of(run["dataset"])
    out = run["dataset"].parent / "gallery-beside"
    assert run_cli("data", "gallery", run["dataset"], "--out", out).returncode == 0
    assert files_of(run["dataset"]) == before
    assert run_cli("data", "check", run["dataset"]).returncode == 0


def test_the_default_folder_is_named_after_the_dataset(run, folder):
    result = subprocess.run(
        [sys.executable, "-m", "core_ultra", "data", "gallery", str(run["dataset"])], capture_output=True, text=True, cwd=folder, timeout=600
    )
    assert result.returncode == 0, result.stderr
    assert (folder / "artifacts" / "galleries" / "gallery-test-v1" / "index.html").is_file()


# --- datasets a gallery is not built from -----------------------------------------------


def test_a_folder_that_is_not_a_dataset_is_refused(folder):
    empty = folder / "empty"
    empty.mkdir()
    out = folder / "empty-gallery"
    result = run_cli("data", "gallery", empty, "--out", out)
    assert result.returncode == 2 and "does not exist" in result.stderr and not out.exists()
    (empty / "manifest.json").write_text('{"kind": "something-else"}')
    result = run_cli("data", "gallery", empty, "--out", out)
    assert result.returncode == 2 and "is not a dataset manifest" in result.stderr and not out.exists()


@pytest.mark.parametrize(
    "damage, said",
    [
        (lambda dataset, manifest: (dataset / manifest["records"][0]["image"]["file"]).write_bytes(b"not the image"), "does not have the hash the manifest gives"),
        (lambda dataset, manifest: (dataset / manifest["records"][1]["file"]).unlink(), "is listed in the manifest and does not exist"),
        (lambda dataset, manifest: (dataset / "config.json").write_text("{}"), "config.json does not have the hash the manifest gives"),
        (
            lambda dataset, manifest: (dataset / manifest["stress_tests"]["records"][0]["file"]).write_text("{}"),
            "does not have the hash the manifest gives",
        ),
    ],
    ids=["an image changed", "a record missing", "the configuration changed", "a stress test changed"],
)
def test_a_dataset_whose_files_are_not_the_ones_its_manifest_lists_is_refused(run, folder, damage, said, request):
    copy = folder / f"damaged-{request.node.callspec.id.replace(' ', '-')}"
    shutil.copytree(run["dataset"], copy)
    damage(copy, run["dataset_manifest"])
    out = copy.with_name(copy.name + "-gallery")
    result = run_cli("data", "gallery", copy, "--out", out)
    assert result.returncode == 2
    assert "is not a dataset a gallery can be built from" in result.stderr and said in result.stderr
    assert not out.exists()


def rename_record(dataset: Path, manifest: dict, new_id: str, in_manifest: bool) -> None:
    """Give the first record another id, with its hash in the manifest kept true."""
    entry = manifest["records"][0]
    record = json.loads((dataset / entry["file"]).read_text())
    record["id"] = new_id
    data = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode()
    (dataset / entry["file"]).write_bytes(data)
    entry["sha256"] = sha256(data)
    if in_manifest:
        entry["id"] = new_id
    (dataset / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def without_a_moment(dataset: Path, manifest: dict) -> None:
    manifest["rejected"][0]["id"] = "no-moment"
    (dataset / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


@pytest.mark.parametrize(
    "change, said",
    [
        (lambda dataset, manifest: rename_record(dataset, manifest, "../../escaped", in_manifest=True), "would be written outside the gallery"),
        (lambda dataset, manifest: rename_record(dataset, manifest, "another-0.000", in_manifest=False), "is listed in the manifest as"),
        (without_a_moment, "is not as `data generate` writes it"),
    ],
    ids=["an id that is a path", "a record with another id", "a rejected state without a moment"],
)
def test_a_dataset_altered_by_hand_is_refused_with_its_reason_and_writes_nothing(run, folder, change, said, request):
    """Its hashes agree, so only its shape gives it away."""
    home = folder / f"altered-{request.node.callspec.id.replace(' ', '-')}"
    copy = home / "nested" / "dataset"
    shutil.copytree(run["dataset"], copy)
    change(copy, json.loads((copy / "manifest.json").read_text()))
    out = home / "nested" / "gallery"
    result = run_cli("data", "gallery", copy, "--out", out)
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr and said in result.stderr
    assert not out.exists()
    # Nothing was written anywhere but into the copy the test made.
    assert {path.relative_to(home).parts[:2] for path in home.rglob("*") if path.is_file()} == {("nested", "dataset")}


def test_a_dataset_with_many_missing_files_is_refused_with_the_first_ten_reasons(run, folder):
    copy = folder / "manifest-only"
    shutil.copytree(run["dataset"], copy)
    shutil.rmtree(copy / "records")
    assert len(run["records"]) > 10
    result = run_cli("data", "gallery", copy, "--out", folder / "manifest-only-gallery")
    assert result.returncode == 2 and f"({len(run['records'])})" in result.stderr
    assert len([line for line in result.stderr.splitlines() if line.startswith("  - ")]) == 11
    assert f"and {len(run['records']) - 10} more; `data check` lists every one" in result.stderr


# --- the pilot ---------------------------------------------------------------------------


def test_the_pilot_has_200_to_500_examples_and_every_layout_family_in_every_visual_preset(pilot):
    manifest, config = pilot["dataset_manifest"], json.loads(PILOT.read_text())
    assert 200 <= manifest["counts"]["records"] == len(pilot["records"]) <= 500
    assert len(config["layout_families"]) == 8 and len(config["visual_presets"]) == 4
    pairs = Counter((record["diagnostics"]["layout_family"], record["diagnostics"]["visual_preset"]) for record in pilot["records"])
    assert set(pairs) == {(family, preset) for family in config["layout_families"] for preset in config["visual_presets"]}
    # Every pair is a scripted session of its own, and no pair has more than one.
    sessions = Counter((session["layout_family"], session["visual_preset"]) for session in manifest["sessions"])
    assert set(sessions.values()) == {1} and len(sessions) == 32
    assert manifest["counts"]["rejected"] == 0 and manifest["counts"]["sessions_refused"] == 0 and manifest["coverage"]["gaps"] == []
    assert manifest["counts"]["stress_tests"] == 20


def test_the_committed_pilot_manifest_is_the_pilot_configuration_generated(pilot):
    assert COMMITTED_PILOT_MANIFEST.read_bytes() == (pilot["dataset"] / "manifest.json").read_bytes()


def test_no_text_of_the_pilot_sits_nearer_than_five_units_to_the_edge_of_its_box(pilot):
    """A text starts as far from the left edge of its box as its line is from
    the top, so the room above the line is the room before it. Layout version 4
    keeps compact density from taking it below 6 units, or below what the
    visual preset's own height leaves, which is 5.1 at the least."""
    from core_ultra import typography

    least = {}
    for record in pilot["records"]:
        preset = record["diagnostics"]["visual_preset"]
        for element in record["target"]["scene"]["elements"]:
            bound = element.get("bound")
            if bound is None or not bound["text"] or bound["role"] not in ("button", "text-field", "list-item", "status"):
                continue
            line = typography.line_height(element["style"]["type_size"], element["style"]["type_weight"])
            room = (element["box"]["height"] - line) / 2
            least[preset] = min(least.get(preset, room), room)
    assert set(least) == {"calm-blue", "warm-paper", "night-teal", "dense-ink"}
    assert all(room >= 5.0 for room in least.values()), least
    assert least["dense-ink"] == pytest.approx(5.13, abs=0.05)


def test_a_state_made_again_is_the_scene_the_layout_of_its_dataset_writes(pilot):
    """What the generator judges when it fits a viewport size, and what the
    gallery draws for a rejected state, is the scene in the dataset's own
    layout, least text inset and all: made again for a state that was
    written, it is that record's target."""
    from core_ultra import generator

    config = generator.load_config(pilot["dataset"] / "config.json")
    assert config.layout.least_text_inset == 6.0
    families = json.loads(LAYOUT_V4.read_text())["families"]
    compact = [
        record for record in pilot["records"]
        if record["diagnostics"]["visual_preset"] == "dense-ink"
        and families[record["diagnostics"]["layout_family"]]["design_condition"]["density"] == "compact"
        and record["diagnostics"]["scenario"]["moment"] in (0, 9)
    ]  # fmt: skip
    assert len(compact) == 6
    for record in compact:
        scenario, size = record["diagnostics"]["scenario"], record["inputs"]["viewport"]
        again = generator.rejected_scene(config, scenario["session"], scenario["moment"], (size["width"], size["height"]))
        assert again.to_json() == record["target"]["scene"], record["id"]


def test_the_second_pilot_differs_from_the_first_only_in_dense_ink_at_compact():
    """Read from the two committed manifests: the same records, the same
    model inputs and viewport sizes, and the same targets but where the
    least text inset of layout version 4 acts."""
    first, second = json.loads(COMMITTED_FIRST_PILOT_MANIFEST.read_text()), json.loads(COMMITTED_PILOT_MANIFEST.read_text())
    assert json.loads(FIRST_PILOT.read_text())["layout"] == "configs/layout/v3.json" and json.loads(PILOT.read_text())["layout"] == "configs/layout/v4.json"
    families = json.loads(LAYOUT_V4.read_text())["families"]
    before, after = ({entry["id"]: entry for entry in manifest["records"]} for manifest in (first, second))
    assert list(before) == list(after) and len(after) == 476
    changed = set()
    for record_id, entry in after.items():
        was = before[record_id]
        assert (entry["inputs_sha256"], entry["viewport"], entry["layout_family"], entry["visual_preset"]) == (
            was["inputs_sha256"], was["viewport"], was["layout_family"], was["visual_preset"],
        )  # fmt: skip
        acts = entry["visual_preset"] == "dense-ink" and families[entry["layout_family"]]["design_condition"]["density"] == "compact"
        assert (entry["target_sha256"] != was["target_sha256"]) == acts, record_id
        assert (entry["image"]["sha256"] != was["image"]["sha256"]) == acts, record_id
        if acts:
            changed.add(record_id.rsplit(".", 1)[0])
    assert len(changed) == 3 and len([i for i in after if i.rsplit(".", 1)[0] in changed]) == 36


def test_the_pilot_gallery_shows_every_record_labelled_and_every_declared_value(pilot):
    figures = record_figures(pilot["page"])
    assert len(figures) == len(pilot["records"])
    assert all(set(figure["labels"]) == {"layout family", "visual preset", "design condition", "state"} for figure in figures)
    summary = pilot["manifest"]["coverage_summary"]
    assert summary["pairs_not_shown"] == []
    for dimension in ("layout family", "visual preset", "density", "content length", "element state"):
        assert summary["by"][dimension]["not_shown"] == [], dimension
        assert all(count["records"] > 0 for count in summary["by"][dimension]["values"].values())
    assert list(summary["by"]["density"]["values"]) == ["compact", "preset", "roomy"]
    assert list(summary["by"]["content length"]["values"]) == ["brief", "medium", "long"]
    assert "Every layout family is shown in every visual preset." in pilot["page"].text
    # What the validators rejected in the pilot is apart: the sizes refused, each drawn, and the stress-test set.
    refused = apart_figures(pilot["page"], "viewports-refused")
    assert len(refused) == pilot["manifest"]["counts"]["viewports_refused"] > 0
    assert all(figure["img"] is not None for figure in refused.values())
    assert len(apart_figures(pilot["page"], "stress-tests")) == 20


def test_the_committed_gallery_manifest_is_the_pilot_gallery(pilot):
    assert COMMITTED_GALLERY_MANIFEST.read_bytes() == (pilot["out"] / "manifest.json").read_bytes()


def test_git_ignores_the_gallery_and_keeps_its_manifest():
    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 0

    assert ignored("artifacts/galleries/pilot-v2/index.html")
    assert ignored("artifacts/galleries/pilot-v2/images/quick-note-0.000.png")
    assert ignored("artifacts/datasets/pilot-v2/records/quick-note-0.000.json")
    assert not ignored("artifacts/galleries/pilot-v2/manifest.json")
    assert not ignored("artifacts/datasets/pilot-v2/manifest.json")
