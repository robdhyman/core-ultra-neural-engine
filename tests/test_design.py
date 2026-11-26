"""Tests for the design source: DESIGN.md, the generator configuration, the
visual presets and the font.

Through the scene session (test seam 1): the same application state is drawn
in every visual preset, and what is asserted is the scene, its image and its
hit-test answers. The values a preset should give are read here from
DESIGN.md's own YAML, not from the code that loads the configuration.

Through the command line (test seam 2): `design check` on the committed files
and on copies with one thing changed, and `design draw` into an empty folder.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from core_ultra import design, preset_sheet, scene as scene_schema, typography
from core_ultra.kernel import Kernel
from core_ultra.scene_session import Conditioning, RenderingMode, SceneSession

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_MD = REPO_ROOT / "DESIGN.md"
CONFIG = REPO_ROOT / "configs" / "design" / "v1.json"
IMAGES = REPO_ROOT / "records" / "design" / "v1"
A_REFERENCE = RenderingMode.A_REFERENCE

TITLES = ("Quarterly plan", "Café résumé — août", "Żółć gęślą jaźń")
BODY = "Première ligne: déjà vu, garçon.\nZweite Zeile: Größe, Übermut, Äpfel.\n\nCuarta línea: ¿mañana? ¡Sí!"
ACTIONABLE = ("documents.create", "toolbar.sort", "toolbar.filter", "toolbar.undo", "document:1", "document:2", "editor.title", "editor.body")
CHANGED_STATES = ("hover", "pressed", "focused", "disabled")


def front_matter(path: Path = DESIGN_MD) -> dict:
    """DESIGN.md's tokens, read as any consumer of the format would."""
    return yaml.safe_load(path.read_text().split("\n---\n")[0].removeprefix("---\n"))


WRITTEN = front_matter()
PRESETS = tuple(WRITTEN["presets"])
DEFAULT = WRITTEN["preset"]


def written(preset: str) -> dict:
    """A preset's token groups as DESIGN.md writes them."""
    return WRITTEN if preset == DEFAULT else WRITTEN["presets"][preset]


def px(value: str) -> float:
    assert value.endswith("px"), value
    return float(value[:-2])


def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def conditioning(preset: str | None) -> Conditioning:
    return Conditioning(960, 540, visual_preset=preset)


@pytest.fixture(scope="module")
def state():
    kernel = Kernel()
    for title in TITLES:
        kernel.create_document(title)
    kernel.open_document(2)
    kernel.edit(BODY)
    kernel.save()
    yield kernel.state()
    kernel.close()


@pytest.fixture(scope="module")
def session():
    return SceneSession()


@pytest.fixture(scope="module")
def frames(state, session):
    return {preset: session.frame(state, conditioning(preset), A_REFERENCE) for preset in PRESETS}


def stored(frame) -> dict:
    return json.loads(json.dumps(frame.scene.to_json(), allow_nan=False))


def bound(scene_json: dict) -> list[dict]:
    return [element["bound"] for element in scene_json["elements"] if "bound" in element]


def styles(scene_json: dict) -> dict[str, dict]:
    return {element["id"]: element["style"] for element in scene_json["elements"]}


def pixel_at(frame, x: float, y: float) -> tuple[int, int, int]:
    return tuple(int(channel) for channel in frame.image[int(y * frame.scale), int(x * frame.scale)][:3])


def backdrop(frame, element_id: str) -> tuple[float, float, float]:
    """The colour behind an element's text: the fills of its ancestors and its
    own, each at its opacity, one over the other."""
    by_id = {element.id: element for element in frame.scene.elements}
    chain = [by_id[element_id]]
    while chain[-1].parent is not None:
        chain.append(by_id[chain[-1].parent])
    colour = np.zeros(3)
    for element in reversed(chain):
        alpha = element.style.fill[3] * element.style.opacity
        colour = colour * (1 - alpha) + np.array(element.style.fill[:3]) * alpha
    return tuple(colour)


def luminance(colour) -> float:
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in colour[:3]]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(one, other) -> float:
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# --- the presets ---------------------------------------------------------------


def test_there_are_three_to_five_presets_each_a_complete_set_of_the_same_tokens():
    assert 3 <= len(PRESETS) <= 5
    groups = ("colors", "typography", "spacing", "dimensions", "borders", "rounded", "elevation", "density", "opacity")
    for preset in PRESETS:
        entry = WRITTEN["presets"][preset]
        assert entry["title"] and entry["summary"]
        for group in groups:
            assert set(written(preset)[group]) == set(WRITTEN[group]), (preset, group)
    assert len({WRITTEN["presets"][preset]["title"] for preset in PRESETS}) == len(PRESETS)


def test_presets_differ_in_colour_type_spacing_radius_elevation_and_density():
    for group in ("colors", "typography", "spacing", "rounded", "elevation", "density"):
        values = [json.dumps(written(preset)[group], sort_keys=True) for preset in PRESETS]
        assert len(set(values)) >= 3, group


@pytest.mark.parametrize("preset", PRESETS)
def test_the_same_state_is_a_valid_scene_in_every_preset(frames, preset):
    frame = frames[preset]
    assert frame.image.shape == (540, 960, 4)
    assert bound(stored(frame)) == bound(stored(frames[DEFAULT]))
    assert [element["id"] for element in stored(frame)["elements"]] == [element["id"] for element in stored(frames[DEFAULT])["elements"]]


@pytest.mark.parametrize("preset", PRESETS)
def test_every_bound_element_is_hit_where_it_is_drawn_in_every_preset(frames, preset):
    frame = frames[preset]
    for element in frame.scene.elements:
        if element.bound is not None:
            assert frame.hit_test(element.x + element.width / 2, element.y + element.height / 2) == element.bound


def test_a_preset_changes_how_the_state_looks_and_never_what_it_says_or_does(frames):
    pictures = {preset: frames[preset].image.tobytes() for preset in PRESETS}
    assert len(set(pictures.values())) == len(PRESETS)
    for preset in PRESETS:
        if preset != DEFAULT:
            assert styles(stored(frames[preset])) != styles(stored(frames[DEFAULT]))


def test_a_frame_without_a_preset_is_drawn_in_the_default_preset(state, session, frames):
    frame = session.frame(state, Conditioning(960, 540), A_REFERENCE)
    assert frame.scene.to_json() == frames[DEFAULT].scene.to_json()
    assert np.array_equal(frame.image, frames[DEFAULT].image)


def test_an_unknown_preset_is_refused_by_name(state, session):
    with pytest.raises(design.DesignError) as refused:
        session.frame(state, conditioning("no-such-preset"), A_REFERENCE)
    assert "no-such-preset" in str(refused.value)
    for preset in PRESETS:
        assert preset in str(refused.value)
    with pytest.raises(ValueError):
        Conditioning(960, 540, visual_preset=3)


# --- DESIGN.md is what is drawn ------------------------------------------------


@pytest.mark.parametrize("preset", PRESETS)
def test_the_scene_carries_the_values_design_md_writes_for_the_preset(state, session, preset):
    tokens = written(preset)
    interaction = {"toolbar.filter": "focused", "document:1": "hover", "toolbar.sort": "pressed"}
    frame = session.frame(state.with_interaction(interaction), conditioning(preset), A_REFERENCE)
    scene = frame.scene

    def element(identity):
        return scene.element_for(identity)

    def colour(style_value):
        return tuple(round(channel * 255) for channel in style_value[:3])

    create, sort, save = element("documents.create"), element("toolbar.sort"), element("toolbar.save")
    field, row, open_row = element("toolbar.filter"), element("document:1"), element("document:2")
    heading, title, body, label = element("documents.heading"), element("editor.title"), element("editor.body"), element("editor.revision")
    notification = element("notification")
    panel = next(e for e in scene.elements if e.id == "s.list")
    toolbar = next(e for e in scene.elements if e.id == "s.toolbar")
    divider = next(e for e in scene.elements if e.id == "s.divider")
    page = next(e for e in scene.elements if e.id == "s.root")

    colours = tokens["colors"]
    assert colour(page.style.fill) == rgb(colours["page"])
    assert colour(toolbar.style.fill) == rgb(colours["surface"])
    assert colour(divider.style.fill) == rgb(colours["line"])
    assert colour(panel.style.fill) == rgb(colours["surface"])
    assert colour(panel.style.border_colour) == rgb(colours["line"])
    assert colour(create.style.fill) == rgb(colours["primary"])
    assert colour(create.style.text_colour) == rgb(colours["on-primary"])
    assert colour(sort.style.fill) == rgb(colours["quiet-pressed"])
    assert colour(save.style.fill) == rgb(colours["quiet"])
    assert colour(field.style.border_colour) == rgb(colours["focus-ring"])
    assert colour(row.style.fill) == rgb(colours["row-hover"])
    assert colour(open_row.style.fill) == rgb(colours["row-open"])
    assert colour(heading.style.text_colour) == rgb(colours["ink"])
    assert colour(label.style.text_colour) == rgb(colours["muted"])
    assert colour(body.style.fill) == rgb(colours["well"])
    assert colour(body.style.border_colour) == rgb(colours["field-line"])
    assert colour(notification.style.fill) == rgb(colours["notification"])
    assert colour(notification.style.text_colour) == rgb(colours["on-notification"])

    for found, token in ((heading, "heading"), (title, "title"), (body, "body"), (row, "row"), (open_row, "row-open"), (create, "button"), (label, "label"), (notification, "notification")):
        assert found.style.type_size == px(tokens["typography"][token]["fontSize"]), token
        assert found.style.type_weight == tokens["typography"][token]["fontWeight"], token

    density, spacing, sizes = tokens["density"], tokens["spacing"], tokens["dimensions"]
    assert toolbar.height == px(density["toolbar-height"])
    assert create.height == sort.height == field.height == px(density["control-height"])
    assert row.height == open_row.height == px(density["row-height"])
    assert title.height == px(density["title-height"])
    assert notification.height == px(density["notification-height"])
    assert create.x == panel.x == px(spacing["margin"])
    assert sort.x - (create.x + create.width) == pytest.approx(px(spacing["gap"]))
    assert create.width == pytest.approx(typography.measure("New document", create.style.type_size, create.style.type_weight) + 2 * px(spacing["button-padding"]))
    assert row.x - panel.x == px(spacing["row-inset"])
    assert title.x - element("editor.body").x == 0
    editor = next(e for e in scene.elements if e.id == "s.editor")
    assert title.x - editor.x == px(spacing["editor-padding"])
    assert px(sizes["list-width-min"]) <= panel.width <= px(sizes["list-width-max"])
    assert panel.width == pytest.approx(min(max(sizes["list-share"] * 960, px(sizes["list-width-min"])), px(sizes["list-width-max"])))
    assert px(sizes["filter-width-min"]) <= field.width <= px(sizes["filter-width-max"])

    borders, rounded, elevation = tokens["borders"], tokens["rounded"], tokens["elevation"]
    assert divider.height == px(borders["divider"])
    assert panel.style.border_width == px(borders["panel"])
    assert save.style.border_width == px(borders["control"])
    assert body.style.border_width == px(borders["field"])
    assert field.style.border_width == px(borders["focus"])
    assert create.style.corner_radius == px(rounded["control"])
    assert field.style.corner_radius == px(rounded["field"])
    assert row.style.corner_radius == px(rounded["row"])
    assert panel.style.corner_radius == px(rounded["panel"])
    assert notification.style.corner_radius == px(rounded["notification"])
    assert panel.style.elevation == px(elevation["panel"])
    assert notification.style.elevation == px(elevation["notification"])
    assert save.bound.state == "disabled" and save.style.opacity == tokens["opacity"]["disabled"]

    # And the image shows them: the accent inside the primary button above its
    # text, and the page in the margin.
    assert pixel_at(frame, create.x + create.width / 2, create.y + 2) == rgb(colours["primary"])
    assert pixel_at(frame, 3, 537) == rgb(colours["page"])


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("changed", CHANGED_STATES)
def test_every_state_changes_style_and_never_box_text_or_binding_in_every_preset(state, session, frames, preset, changed):
    before = stored(frames[preset])
    for identity in ACTIONABLE:
        after = stored(session.frame(state.with_interaction({identity: changed}), conditioning(preset), A_REFERENCE))
        was = next(e for e in before["elements"] if e.get("bound", {}).get("identity") == identity)
        now = next(e for e in after["elements"] if e.get("bound", {}).get("identity") == identity)
        assert now["bound"] == {**was["bound"], "state": changed}
        assert now["box"] == was["box"]
        assert now["style"] != was["style"], (identity, changed)
        assert [e for e in after["elements"] if e is not now] == [e for e in before["elements"] if e is not was]


@pytest.mark.parametrize("preset", PRESETS)
def test_text_has_a_contrast_of_at_least_4_5_to_1_in_every_preset_and_state(state, session, preset):
    interactions = [{}] + [{identity: changed} for identity in ACTIONABLE for changed in ("hover", "pressed", "focused")]
    checked = 0
    for interaction in interactions:
        frame = session.frame(state.with_interaction(interaction), conditioning(preset), A_REFERENCE)
        for element in frame.scene.elements:
            if element.bound is None or not element.bound.text or element.bound.state == "disabled":
                continue
            ratio = contrast(element.style.text_colour, backdrop(frame, element.id))
            assert ratio >= 4.5, (preset, element.bound.identity, element.bound.state, round(ratio, 2))
            checked += 1
    assert checked > 100


def test_an_empty_application_is_drawn_in_every_preset(session):
    kernel = Kernel()
    try:
        for preset in PRESETS:
            frame = session.frame(kernel.state(), conditioning(preset), A_REFERENCE)
            assert {b["identity"] for b in bound(stored(frame))} >= {"documents.empty", "editor.empty"}
    finally:
        kernel.close()


# --- the check that keeps the two files consistent -------------------------------


def copies(tmp_path: Path) -> tuple[Path, Path]:
    written_copy, config_copy = tmp_path / "DESIGN.md", tmp_path / "design.json"
    written_copy.write_text(DESIGN_MD.read_text())
    config_copy.write_text(CONFIG.read_text())
    return written_copy, config_copy


def edit_design_md(path: Path, change) -> None:
    head, _, body = path.read_text().removeprefix("---\n").partition("\n---\n")
    tokens = yaml.safe_load(head)
    change(tokens)
    path.write_text("---\n" + yaml.safe_dump(tokens, sort_keys=False, allow_unicode=True) + "---\n" + body)


def edit_config(path: Path, change) -> None:
    raw = json.loads(path.read_text())
    change(raw)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))


def test_the_committed_design_md_and_generator_configuration_agree():
    assert design.check() == []


def test_design_md_rewritten_by_a_yaml_library_still_agrees(tmp_path):
    written_copy, config_copy = copies(tmp_path)
    edit_design_md(written_copy, lambda tokens: None)
    assert design.check(written_copy, config_copy) == []


def set_in(path: str, value):
    """A change that sets the value at a dotted path."""

    def change(tree):
        *parents, last = path.split(".")
        for key in parents:
            tree = tree[key]
        tree[last] = value

    return change


def delete_in(path: str):
    def change(tree):
        *parents, last = path.split(".")
        for key in parents:
            tree = tree[key]
        del tree[last]

    return change


DISAGREEMENTS = [
    # (which file is changed, the change, the place the check must name)
    ("design", set_in("colors.primary", "#245EDC"), "presets.calm-blue.colours.primary"),
    ("design", set_in("presets.night-teal.colors.ink", "#E8ECF3"), "presets.night-teal.colours.ink"),
    ("design", set_in("typography.heading.fontWeight", 600), "presets.calm-blue.type.heading.weight"),
    ("design", set_in("presets.dense-ink.typography.label.fontSize", "12px"), "presets.dense-ink.type.label.size"),
    ("design", set_in("typography.body.fontFamily", "Another Sans"), "presets.calm-blue.type.body.family"),
    ("design", set_in("presets.warm-paper.spacing.gap", "12px"), "presets.warm-paper.spacing.gap"),
    ("design", set_in("dimensions.list-share", 0.4), "presets.calm-blue.dimensions.list-share"),
    ("design", set_in("presets.dense-ink.borders.focus", "2px"), "presets.dense-ink.borders.focus"),
    ("design", set_in("rounded.panel", "16px"), "presets.calm-blue.radii.panel"),
    ("design", set_in("presets.warm-paper.elevation.notification", "4px"), "presets.warm-paper.elevation.notification"),
    ("design", set_in("density.row-height", "44px"), "presets.calm-blue.density.row-height"),
    ("design", set_in("presets.night-teal.opacity.disabled", 0.5), "presets.night-teal.opacity.disabled"),
    ("design", set_in("components.button-primary-hover.backgroundColor", "{colors.primary-pressed}"), "components.button-primary-hover.fill"),
    ("design", set_in("components.panel.elevation", "{elevation.notification}"), "components.panel.elevation"),
    ("design", delete_in("components.row-focused"), "components.row-focused"),
    ("design", delete_in("components.field.borderWidth"), "components.field.border_width"),
    ("design", delete_in("presets.dense-ink.colors.row-pressed"), "presets.dense-ink.colours.row-pressed"),
    ("design", delete_in("presets.warm-paper.density"), "presets.warm-paper.density"),
    ("design", set_in("states", ["default", "hover", "pressed", "focused"]), "states"),
    ("design", set_in("presets.warm-paper.summary", "Something else."), "presets.warm-paper.summary"),
    ("config", set_in("presets.calm-blue.colours.page", "#F2F2F6"), "presets.calm-blue.colours.page"),
    ("config", set_in("presets.warm-paper.spacing.margin", 21), "presets.warm-paper.spacing.margin"),
    ("config", set_in("presets.night-teal.type.title.weight", 500), "presets.night-teal.type.title.weight"),
    ("config", set_in("presets.dense-ink.radii.control", 3), "presets.dense-ink.radii.control"),
    ("config", set_in("font.family", "Another Sans"), "type.heading.family"),
    ("config", set_in("default_preset", "warm-paper"), "default_preset"),
    ("config", set_in("components.badge", {"fill": "{colours.primary}"}), "components.badge"),
    ("config", set_in("components.row-open.fill", "{colours.row-hover}"), "components.row-open.fill"),
    ("config", set_in("components.notification.height", "{density.control-height}"), "components.notification.height"),
]


@pytest.mark.parametrize("which, change, place", DISAGREEMENTS, ids=[f"{which}: {place}" for which, _, place in DISAGREEMENTS])
def test_one_changed_value_in_either_file_is_a_named_disagreement(tmp_path, which, change, place):
    written_copy, config_copy = copies(tmp_path)
    (edit_design_md if which == "design" else edit_config)(written_copy if which == "design" else config_copy, change)
    problems = design.check(written_copy, config_copy)
    assert problems, "the check passed although the two files differ"
    assert any(place in problem for problem in problems), problems


def swap_headings(one: str, other: str):
    def change(path: Path) -> None:
        text = path.read_text()
        assert f"\n## {one}\n" in text and f"\n## {other}\n" in text
        path.write_text(text.replace(f"\n## {one}\n", "\n## \x00\n").replace(f"\n## {other}\n", f"\n## {one}\n").replace("\n## \x00\n", f"\n## {other}\n"))

    return change


def replace_text(old: str, new: str):
    def change(path: Path) -> None:
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, new, 1))

    return change


def tokens_changed(change):
    return lambda path: edit_design_md(path, change)


NOT_THE_FORMAT = [
    (replace_text("---\n", ""), "front matter"),
    (tokens_changed(set_in("version", "beta")), "version"),
    (tokens_changed(delete_in("name")), "name"),
    (tokens_changed(delete_in("colors.primary")), "colors.primary"),
    (tokens_changed(set_in("colors.page", "pale grey")), "colors.page"),
    (tokens_changed(set_in("spacing.margin", 16)), "spacing.margin"),
    (tokens_changed(set_in("presets.warm-paper.rounded.panel", "6pt")), "presets.warm-paper.rounded.panel"),
    (tokens_changed(set_in("components.label.textColor", "{colors.faint}")), "components.label.textColor"),
    (tokens_changed(set_in("components.label.borderStyle", "dashed")), "components.label.borderStyle"),
    (tokens_changed(set_in("preset", "midnight")), "preset"),
    (tokens_changed(set_in("omitted", ["Shapes", "Motion", "Voice & Content Strategy"])), "'Shapes' is both written and listed"),
    (tokens_changed(set_in("omitted", ["Motion"])), "'Voice & Content Strategy' is neither written nor listed"),
    (swap_headings("Colors", "Typography"), "out of the format's order"),
    (replace_text("\n## Shapes\n", "\n## Colors\n"), "more than once"),
    (replace_text("\n## Elevation & Depth\n", "\n### Elevation & Depth\n"), "'Elevation & Depth' is neither written nor listed"),
    (tokens_changed(set_in("presets.warm-paper.title", "Toasted Paper")), "'Toasted Paper' is not mentioned"),
]


@pytest.mark.parametrize("change, reason", NOT_THE_FORMAT, ids=[reason for _, reason in NOT_THE_FORMAT])
def test_a_design_md_that_breaks_the_format_is_reported(tmp_path, change, reason):
    written_copy, config_copy = copies(tmp_path)
    change(written_copy)
    problems = design.check(written_copy, config_copy)
    assert any(reason in problem for problem in problems), problems
    assert all(problem.startswith("DESIGN.md: ") for problem in problems), problems


UNUSABLE = [
    (delete_in("presets.warm-paper.colours.muted"), "presets.warm-paper.colours"),
    (set_in("presets.dense-ink.colours.extra", "#000000"), "presets.dense-ink.colours"),
    (set_in("presets.calm-blue.colours.page", "#F2F2"), "presets.calm-blue.colours.page"),
    (set_in("presets.calm-blue.type.body.weight", 950), "presets.calm-blue.type.body"),
    (set_in("presets.calm-blue.type.body.size", 0), "presets.calm-blue.type.body"),
    (set_in("presets.night-teal.opacity.disabled", 1.5), "presets.night-teal.opacity.disabled"),
    (set_in("presets.night-teal.spacing.gap", -1), "presets.night-teal.spacing.gap"),
    (delete_in("presets.warm-paper.elevation"), "presets.warm-paper.elevation"),
    (set_in("presets.Brand X", {}), "presets.Brand X"),
    (set_in("components.label.text_colour", "{colours.faint}"), "components.label.text_colour"),
    (set_in("components.label.text_colour", "{spacing.gap}"), "components.label.text_colour"),
    (set_in("components.label.border_style", "dashed"), "components.label.border_style"),
    (set_in("components.row-hover.height", 50), "components.row-hover.height"),
    (set_in("states", ["default", "hover"]), "states"),
    (set_in("default_preset", "midnight"), "default_preset"),
    (set_in("kind", "something-else"), "design-config"),
]


@pytest.mark.parametrize("change, place", UNUSABLE, ids=[place for _, place in UNUSABLE])
def test_a_generator_configuration_that_cannot_be_used_is_refused_with_its_reason(tmp_path, change, place):
    written_copy, config_copy = copies(tmp_path)
    edit_config(config_copy, change)
    with pytest.raises(design.DesignError) as refused:
        design.load(config_copy)
    assert place in str(refused.value)
    assert any(place in problem for problem in design.check(written_copy, config_copy))


def test_a_missing_file_is_reported_not_a_crash(tmp_path):
    written_copy, config_copy = copies(tmp_path)
    assert "does not exist" in design.check(tmp_path / "absent.md", config_copy)[0]
    assert "does not exist" in design.check(written_copy, tmp_path / "absent.json")[0]
    config_copy.write_text("{")
    assert "not valid JSON" in design.check(written_copy, config_copy)[0]


# --- the font and its provenance -------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_font_drawn_is_the_bundled_file_with_its_source_and_licence_recorded():
    font = json.loads(CONFIG.read_text())["font"]
    assert REPO_ROOT / font["file"] == typography.FONT_FILE
    assert font["family"] == typography.FONT_FAMILY
    assert font["optical_size"] == typography.OPTICAL_SIZE
    assert sha256(REPO_ROOT / font["file"]) == font["sha256"]
    assert sha256(REPO_ROOT / font["licence_file"]) == font["licence_sha256"]
    licence = (REPO_ROOT / font["licence_file"]).read_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence
    assert font["copyright"] in licence

    recorded = (REPO_ROOT / "ASSETS.md").read_text()
    for fact in (font["file"], font["sha256"], font["licence"], font["copyright"], font["source"], font["upstream"], font["version"]):
        assert fact in recorded, fact


def test_every_weight_from_100_to_900_is_a_different_drawing_of_the_same_text():
    widths = [typography.measure("Żółć gęślą jaźń, résumé", 100, weight) for weight in range(100, 1000, 100)]
    assert widths == sorted(widths) and len(set(widths)) == 9
    assert typography.measure("Résumé", 15, 449) == typography.measure("Résumé", 15, 400)


def test_a_line_of_text_is_the_same_outline_at_every_type_size():
    for weight in (400, 700):
        at_12, at_48 = typography.measure("Quarterly plan", 12, weight), typography.measure("Quarterly plan", 48, weight)
        assert at_48 == pytest.approx(4 * at_12, rel=1e-12)


def test_no_repository_file_other_than_the_recorded_assets_is_a_font_or_an_image_asset():
    tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    assets = [path for path in tracked.stdout.splitlines() if path.lower().endswith((".ttf", ".otf", ".woff", ".woff2", ".svg", ".jpg", ".jpeg", ".gif", ".ico"))]
    assert assets == ["src/core_ultra/assets/fonts/inter/Inter[opsz,wght].ttf"]


# --- the images a person can compare ---------------------------------------------


def test_the_committed_images_are_the_demonstration_state_in_every_preset():
    manifest = json.loads((IMAGES / preset_sheet.MANIFEST_NAME).read_text())
    assert [image["visual_preset"] for image in manifest["images"]] == list(PRESETS)
    assert manifest["rendering_mode"] == "A, Reference"
    assert manifest["design"]["sha256"] == sha256(CONFIG)
    assert manifest["font"]["sha256"] == sha256(typography.FONT_FILE)
    for image in [*manifest["images"], manifest["sheet"]]:
        assert sha256(IMAGES / image["file"]) == image["sha256"], image["file"]

    drawn = preset_sheet.frames(scale=1)
    for image in manifest["images"]:
        scene = drawn[image["visual_preset"]].scene
        assert hashlib.sha256(scene_schema.dumps(scene).encode()).hexdigest() == image["scene_sha256"], image["visual_preset"]
    states = {element.bound.state for element in drawn[DEFAULT].scene.elements if element.bound is not None}
    assert states == {"default", "hover", "pressed", "focused", "disabled"}


# --- the command line ------------------------------------------------------------


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "core_ultra", *args], capture_output=True, text=True, cwd=cwd, timeout=300)


def test_design_check_passes_on_the_committed_files(tmp_path):
    result = run_cli("design", "check", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"{len(PRESETS)} visual presets" in result.stdout
    assert result.stderr == ""


def test_design_check_exits_1_and_lists_each_disagreement(tmp_path):
    written_copy, config_copy = copies(tmp_path)
    edit_config(config_copy, set_in("presets.warm-paper.colours.primary", "#9A4A2C"))
    edit_config(config_copy, set_in("presets.dense-ink.density.row-height", 30))
    result = run_cli("design", "check", "--design-md", str(written_copy), "--config", str(config_copy))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "do not agree (2)" in result.stderr
    assert "presets.warm-paper.colours.primary: DESIGN.md says '#9A4A2B', the generator configuration says '#9A4A2C'" in result.stderr
    assert "presets.dense-ink.density.row-height: DESIGN.md says 28.0, the generator configuration says 30.0" in result.stderr


def test_design_draw_writes_an_image_for_every_preset_a_sheet_and_a_manifest(tmp_path):
    out = tmp_path / "images"
    result = run_cli("design", "draw", "--out", str(out), "--scale", "1")
    assert result.returncode == 0, result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    assert sorted(path.name for path in out.iterdir()) == sorted([*(f"{preset}.png" for preset in PRESETS), "all-presets.png", "manifest.json"])
    assert manifest["pixels_per_viewport_unit"] == 1
    hashes = [image["sha256"] for image in manifest["images"]]
    assert len(set(hashes)) == len(PRESETS)
    for image in [*manifest["images"], manifest["sheet"]]:
        assert sha256(out / image["file"]) == image["sha256"]
        assert image["sha256"] in result.stdout
        assert (out / image["file"]).read_bytes().startswith(b"\x89PNG")

    # Drawing again changes nothing; a file with other contents is never overwritten.
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    assert run_cli("design", "draw", "--out", str(out), "--scale", "1").returncode == 0
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before
    (out / f"{PRESETS[0]}.png").write_bytes(b"something else")
    refused = run_cli("design", "draw", "--out", str(out), "--scale", "1")
    assert refused.returncode == 2
    assert "already exists with other contents" in refused.stderr
    assert (out / f"{PRESETS[0]}.png").read_bytes() == b"something else"
