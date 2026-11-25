"""Scene session tests (test seam 1), against A, Reference.

Every test supplies application state from a real kernel and asserts on what
the scene session returns: the scene, its validity, the drawn image and
hit-test answers. Nothing is mocked and no window is opened.

Where a test needs a judge of the image, the judge is independent of the
runtime renderer's own code: Qt's `QPainterPath.addText` for text, the scene's
stated colours for shapes, and the documented shadow formula for elevation.
"""

from __future__ import annotations

import copy
import ctypes
import dataclasses
import importlib.metadata
import importlib.util
import json
import logging
import math
import random
import sys

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath

from core_ultra.kernel import Kernel, KernelError
from core_ultra.scene_session import (
    Conditioning,
    ModeUnavailable,
    RenderingMode,
    SceneInvalid,
    SceneSession,
    TextNotDrawable,
)

TITLES = ("Quarterly plan", "Café résumé — août", "Żółć gęślą jaźń")
BODY = "Première ligne: déjà vu, garçon.\nZweite Zeile: Größe, Übermut, Äpfel.\n\nCuarta línea: ¿mañana? ¡Sí!"
CONDITIONING = Conditioning(960, 540)
A_REFERENCE = RenderingMode.A_REFERENCE
SCALES = (1, 2, 3.5)
STATES = ("default", "hover", "pressed", "focused", "disabled")
PARTS = {"workspace.toolbar", "workspace.list", "workspace.editor", "workspace.notification"}
BOUND_FIELDS = {"identity", "role", "text", "binding", "state", "relationships"}
STYLE_FIELDS = {
    "fill",
    "text_colour",
    "border_colour",
    "border_width",
    "corner_radius",
    "elevation",
    "opacity",
    "type_size",
    "type_weight",
}


def fill_workspace(kernel, titles=TITLES) -> None:
    """Three documents, the second open with a saved body: every part of the
    workspace is present, the notification included."""
    for title in titles:
        kernel.create_document(title)
    kernel.open_document(2)
    kernel.edit(BODY)
    kernel.save()


@pytest.fixture
def kernel(tmp_path):
    kernel = Kernel(tmp_path / "application.sqlite")
    fill_workspace(kernel)
    yield kernel
    kernel.close()


@pytest.fixture
def session():
    return SceneSession()


@pytest.fixture
def frame(kernel, session):
    return session.frame(kernel.state(), CONDITIONING, A_REFERENCE)


def stored(frame) -> dict:
    """The frame's scene as it is stored: through JSON text and back."""
    return json.loads(json.dumps(frame.scene.to_json(), allow_nan=False))


def entry(scene_json: dict, identity: str) -> dict:
    (found,) = [e for e in scene_json["elements"] if e.get("bound", {}).get("identity") == identity]
    return found


def structural(scene_json: dict, element_id: str) -> dict:
    (found,) = [e for e in scene_json["elements"] if e["id"] == element_id]
    return found


def close_to(pixel, colour, steps: int = 1) -> bool:
    """An opaque pixel of this colour, within a step of 8-bit rounding."""
    return all(abs(int(channel) - round(value * 255)) <= steps for channel, value in zip(pixel[:3], colour[:3]))


def centre(frame, identity: str) -> tuple[float, float]:
    element = frame.scene.element_for(identity)
    return element.x + element.width / 2, element.y + element.height / 2


def pixel_at(frame, x: float, y: float) -> np.ndarray:
    return frame.image[int(y * frame.scale), int(x * frame.scale)]


def backdrop(frame, element_id: str) -> tuple[float, float, float]:
    """The colour inside an element's box before its border and text: the fills
    of its ancestors and its own, each at its opacity, one over the other."""
    by_id = {element.id: element for element in frame.scene.elements}
    chain = [by_id[element_id]]
    while chain[-1].parent is not None:
        chain.append(by_id[chain[-1].parent])
    colour = np.zeros(3)
    for element in reversed(chain):
        alpha = element.style.fill[3] * element.style.opacity
        colour = colour * (1 - alpha) + np.array(element.style.fill[:3]) * alpha
    return tuple(colour)


# --- the session's contract -------------------------------------------------


def test_a_frame_is_the_validated_scene_its_image_and_a_hit_test_without_a_window(frame):
    assert frame.image.shape == (540, 960, 4)
    assert frame.image.dtype == np.uint8
    assert (frame.scene.viewport_width, frame.scene.viewport_height) == (960, 540)
    assert frame.hit_test(4, 100) is None

    assert QGuiApplication.platformName() == "offscreen"
    assert QGuiApplication.allWindows() == []


def test_the_same_state_draws_the_same_frame(kernel, session, frame):
    again = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    assert again.scene.to_json() == frame.scene.to_json()
    assert np.array_equal(again.image, frame.image)


def test_a_frame_is_not_edited_after_the_fact(frame):
    with pytest.raises(ValueError):
        frame.image[0, 0, 0] = 0
    with pytest.raises(AttributeError):
        frame.scene.elements = ()


def test_rendering_modes_are_named_letter_plus_name(kernel, session, frame):
    by_name = session.frame(kernel.state(), CONDITIONING, "A, Reference")
    assert np.array_equal(by_name.image, frame.image)
    with pytest.raises(ValueError):
        session.frame(kernel.state(), CONDITIONING, "A")
    with pytest.raises(ModeUnavailable):
        session.frame(kernel.state(), CONDITIONING, RenderingMode.D_NEURAL_SCENE)


# --- every state the app can reach ------------------------------------------


def test_every_state_reached_in_a_scripted_session_is_drawn_and_hit_tested(tmp_path, session):
    """A seeded session of 150 pointer and keyboard actions. Each action is
    found the way a host finds it: a point is hit tested and the binding of the
    element there is run. After every action the new state is drawn, and every
    bound element is hit at its own centre."""
    kernel = Kernel(tmp_path / "application.sqlite")
    chooser = random.Random(27)
    conditioning = Conditioning(960, 900)
    words = ("plan", "résumé", "fjord", "Żółć", "notes", "août", "Århus", "garçon", "naïve", "Ærø")
    ran, seen = [], set()

    for _ in range(150):
        state = kernel.state()
        frame = session.frame(state, conditioning, A_REFERENCE)
        assert frame.image.shape == (900, 960, 4)
        for bound in frame.bound_elements:
            assert frame.hit_test(*centre(frame, bound.identity)) == bound, bound.identity
        seen |= {bound.identity.split(":")[0] for bound in frame.bound_elements}
        seen |= {f"{bound.identity} {bound.state}" for bound in frame.bound_elements if bound.state != "default"}

        actionable = [bound for bound in frame.bound_elements if bound.binding is not None]
        target = chooser.choice(actionable)
        hit = frame.hit_test(*centre(frame, target.identity))
        command = hit.binding["command"]
        text = None
        if command in ("create", "rename"):
            text = " ".join(chooser.sample(words, 2)).capitalize()
        elif command == "edit":
            text = "\n".join(" ".join(chooser.sample(words, 4)) for _ in range(chooser.randint(0, 5)))
        elif command == "filter":
            text = chooser.choice(("", "a", "É", "fjord", "zzz"))
        if command == "create" and state.total_documents >= 12:
            continue
        try:
            kernel.execute(hit.binding, text)
        except KernelError:
            # A disabled element's command is refused by the kernel; an edit or
            # a rename may also happen to change nothing.
            assert hit.state == "disabled" or command in ("edit", "rename")
            continue
        assert hit.state != "disabled"
        ran.append(command)

    assert set(ran) == {"create", "open", "rename", "edit", "save", "sort", "filter", "undo"}
    assert seen >= {
        "documents.create",
        "toolbar.sort",
        "toolbar.filter.label",
        "toolbar.filter",
        "toolbar.save",
        "toolbar.undo",
        "documents.heading",
        "document",
        "documents.empty",
        "editor.title",
        "editor.revision",
        "editor.body",
        "editor.empty",
        "notification",
        "toolbar.save disabled",
        "toolbar.undo disabled",
    }
    report = session.report
    assert (report.scenes, report.valid, report.invalid, report.projections) == (150, 150, 0, 0)
    kernel.close()


def test_documents_committed_to_sqlite_are_drawn_from_a_reopened_store(tmp_path, session):
    path = tmp_path / "application.sqlite"
    first = Kernel(path)
    fill_workspace(first)
    first.edit(BODY + "\nUne ligne non enregistrée.")
    before = session.frame(first.state(), CONDITIONING, A_REFERENCE)
    first.close()

    reopened = Kernel(path)
    after = session.frame(reopened.state(), CONDITIONING, A_REFERENCE)
    assert after.bound_elements == before.bound_elements
    assert after.scene.element_for("editor.body").bound.text.endswith("Une ligne non enregistrée.")
    assert np.array_equal(after.image, before.image)
    reopened.close()


def test_an_empty_application_still_draws_its_workspace(session):
    frame = session.frame(Kernel().state(), CONDITIONING, A_REFERENCE)
    assert [(b.identity, b.text, b.state) for b in frame.bound_elements] == [
        ("documents.create", "New document", "default"),
        ("toolbar.sort", "Sort: oldest first", "default"),
        ("toolbar.filter.label", "Filter", "default"),
        ("toolbar.filter", "", "default"),
        ("toolbar.save", "Save", "disabled"),
        ("toolbar.undo", "Undo", "disabled"),
        ("documents.heading", "Documents", "default"),
        ("documents.empty", "No documents yet", "default"),
        ("editor.empty", "No document is open", "default"),
    ]
    assert frame.hit_test(*centre(frame, "documents.create")).identity == "documents.create"


def test_a_filter_that_matches_nothing_says_so(kernel, session):
    kernel.filter_documents("xyz")
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    assert frame.scene.element_for("documents.empty").bound.text == "No title contains “xyz”"
    assert frame.scene.element_for("toolbar.filter").bound.text == "xyz"
    assert not [b for b in frame.bound_elements if b.role == "list-item"]
    assert frame.scene.element_for("editor.title").bound.text == "Café résumé — août"  # still open


# --- documents app adapter --------------------------------------------------


def test_state_is_described_as_bound_elements_with_no_coordinates_and_no_style(frame):
    def part(name):
        return {"relation": "part_of", "target": f"workspace.{name}"}

    assert [dataclasses.asdict(b) for b in frame.bound_elements] == [
        {
            "identity": "documents.create",
            "role": "button",
            "text": "New document",
            "binding": {"command": "create"},
            "state": "default",
            "relationships": (part("toolbar"),),
        },
        {
            "identity": "toolbar.sort",
            "role": "button",
            "text": "Sort: oldest first",
            "binding": {"command": "sort", "key": "created", "descending": True},
            "state": "default",
            "relationships": (part("toolbar"), {"relation": "controls", "target": "documents.heading"}),
        },
        {
            "identity": "toolbar.filter.label",
            "role": "label",
            "text": "Filter",
            "binding": None,
            "state": "default",
            "relationships": (part("toolbar"), {"relation": "labels", "target": "toolbar.filter"}),
        },
        {
            "identity": "toolbar.filter",
            "role": "text-field",
            "text": "",
            "binding": {"command": "filter"},
            "state": "default",
            "relationships": (part("toolbar"), {"relation": "controls", "target": "documents.heading"}),
        },
        {
            "identity": "toolbar.save",
            "role": "button",
            "text": "Save",
            "binding": {"command": "save"},
            "state": "disabled",
            "relationships": (part("toolbar"), {"relation": "controls", "target": "editor.body"}),
        },
        {
            "identity": "toolbar.undo",
            "role": "button",
            "text": "Undo",
            "binding": {"command": "undo"},
            "state": "default",
            "relationships": (part("toolbar"),),
        },
        {
            "identity": "documents.heading",
            "role": "heading",
            "text": "Documents",
            "binding": None,
            "state": "default",
            "relationships": (part("list"),),
        },
        *[
            {
                "identity": f"document:{number}",
                "role": "list-item",
                "text": title,
                "binding": {"command": "open", "document": number},
                "state": "default",
                "relationships": (
                    part("list"),
                    {"relation": "item_of", "target": "documents.heading"},
                    *([{"relation": "shown_in", "target": "editor.body"}] if number == 2 else []),
                ),
            }
            for number, title in enumerate(TITLES, start=1)
        ],
        {
            "identity": "editor.title",
            "role": "text-field",
            "text": "Café résumé — août",
            "binding": {"command": "rename", "document": 2},
            "state": "default",
            "relationships": (part("editor"), {"relation": "labels", "target": "editor.body"}),
        },
        {
            "identity": "editor.revision",
            "role": "label",
            "text": "Revision 2",
            "binding": None,
            "state": "default",
            "relationships": (part("editor"), {"relation": "labels", "target": "editor.body"}),
        },
        {
            "identity": "editor.body",
            "role": "text-area",
            "text": BODY,
            "binding": {"command": "edit", "document": 2},
            "state": "default",
            "relationships": (part("editor"),),
        },
        {
            "identity": "notification",
            "role": "status",
            "text": "Saved “Café résumé — août”, revision 2",
            "binding": None,
            "state": "default",
            "relationships": (part("notification"),),
        },
    ]
    for bound in frame.bound_elements:
        assert {field.name for field in dataclasses.fields(bound)} == BOUND_FIELDS


def test_every_relationship_names_a_bound_element_or_a_part_of_the_workspace(kernel, session, frame):
    kernel.filter_documents("xyz")
    filtered = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    empty = session.frame(Kernel().state(), CONDITIONING, A_REFERENCE)
    for described in (frame, filtered, empty):
        identities = {bound.identity for bound in described.bound_elements}
        assert len(identities) == len(described.bound_elements)
        for bound in described.bound_elements:
            relations = [relationship["relation"] for relationship in bound.relationships]
            assert relations.count("part_of") == 1
            for relationship in bound.relationships:
                assert set(relationship) == {"relation", "target"}
                assert relationship["target"] in (PARTS if relationship["relation"] == "part_of" else identities)

    rows = [bound for bound in frame.bound_elements if bound.role == "list-item"]
    assert all({"relation": "item_of", "target": "documents.heading"} in bound.relationships for bound in rows)


def test_identities_are_stable_through_create_rename_sort_and_filter(kernel, session, frame):
    def rows(shown):
        return {b.identity: b.binding for b in shown.bound_elements if b.role == "list-item"}

    kernel.create_document("A fourth document")
    kernel.rename_document(1, "Plan trimestriel")
    kernel.sort_documents("title", descending=True)
    after = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    assert [b.identity for b in after.bound_elements if b.role == "list-item"] == [
        "document:3",
        "document:1",
        "document:2",
        "document:4",
    ]
    assert rows(after) == {**rows(frame), "document:4": {"command": "open", "document": 4}}
    assert after.scene.element_for("document:1").bound.text == "Plan trimestriel"

    kernel.filter_documents("plan")
    assert rows(session.frame(kernel.state(), CONDITIONING, A_REFERENCE)) == {"document:1": rows(frame)["document:1"]}


def test_the_application_disables_save_and_undo_when_they_have_nothing_to_act_on(session):
    kernel = Kernel()

    def states():
        shown = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
        return {identity: shown.scene.element_for(identity).bound.state for identity in ("toolbar.save", "toolbar.undo")}

    assert states() == {"toolbar.save": "disabled", "toolbar.undo": "disabled"}
    kernel.create_document("Quarterly plan")
    assert states() == {"toolbar.save": "disabled", "toolbar.undo": "default"}
    kernel.open_document(1)
    kernel.edit("A draft")
    assert states() == {"toolbar.save": "default", "toolbar.undo": "default"}
    kernel.save()
    assert states() == {"toolbar.save": "disabled", "toolbar.undo": "default"}

    # A pointer over a disabled element does not enable it, and the kernel
    # refuses its command.
    hovered = session.frame(kernel.state().with_interaction({"toolbar.save": "hover"}), CONDITIONING, A_REFERENCE)
    hit = hovered.hit_test(*centre(hovered, "toolbar.save"))
    assert (hit.state, hit.binding) == ("disabled", {"command": "save"})
    with pytest.raises(KernelError):
        kernel.execute(hit.binding)


def test_interaction_must_name_an_element_with_an_action_and_a_real_state(kernel, session):
    for interaction in ({"document:99": "hover"}, {"document:1": "selected"}, {"documents.heading": "hover"}):
        with pytest.raises(ValueError):
            session.frame(kernel.state().with_interaction(interaction), CONDITIONING, A_REFERENCE)


# --- scene schema -----------------------------------------------------------


def test_a_scene_is_a_tree_of_elements_stored_as_json(frame):
    scene = stored(frame)
    assert scene["kind"] == "scene"
    assert scene["viewport"] == {"width": 960, "height": 540}

    by_id = {element["id"]: element for element in scene["elements"]}
    assert len(by_id) == len(scene["elements"])
    for element in scene["elements"]:
        assert isinstance(element["type"], str)
        assert set(element["box"]) == {"x", "y", "width", "height"}
        assert set(element["style"]) == STYLE_FIELDS
        assert "parent" in element

    roots = [element for element in scene["elements"] if element["parent"] is None]
    assert len(roots) == 1
    for element in scene["elements"]:
        steps = 0
        while element["parent"] is not None:
            element = by_id[element["parent"]]
            assert element["type"] != "bound"
            steps += 1
            assert steps <= len(by_id)
        assert element is roots[0]


def test_each_part_of_the_workspace_is_drawn_inside_its_own_structural_element(frame):
    scene = stored(frame)
    parents = {
        "workspace.toolbar": "s.toolbar",
        "workspace.list": "s.list",
        "workspace.editor": "s.editor",
        "workspace.notification": "s.root",
    }
    for element in scene["elements"]:
        if element["type"] != "bound":
            continue
        (part,) = [r["target"] for r in element["bound"]["relationships"] if r["relation"] == "part_of"]
        assert element["parent"] == parents[part], element["id"]
        if part != "workspace.notification":
            outer, inner = structural(scene, parents[part])["box"], element["box"]
            assert outer["x"] <= inner["x"] and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
            assert outer["y"] <= inner["y"] and inner["y"] + inner["height"] <= outer["y"] + outer["height"]


def test_bound_elements_carry_what_the_application_supplied_unchanged(frame):
    scene = stored(frame)
    carried = [element["bound"] for element in scene["elements"] if element["type"] == "bound"]
    supplied = [json.loads(json.dumps(bound.to_json())) for bound in frame.bound_elements]
    assert sorted(carried, key=lambda bound: bound["identity"]) == sorted(supplied, key=lambda bound: bound["identity"])


def test_structural_elements_carry_no_identity_role_text_binding_or_state(frame):
    scene = stored(frame)
    structural_elements = [element for element in scene["elements"] if element["type"] != "bound"]
    assert {element["type"] for element in structural_elements} == {"surface", "container", "divider", "panel"}
    for element in structural_elements:
        assert set(element) == {"id", "type", "parent", "box", "style"}


def test_a_stored_scene_draws_the_same_frame(kernel, session, frame):
    redrawn = session.frame_from_scene(kernel.state(), CONDITIONING, stored(frame))
    assert redrawn.scene.to_json() == frame.scene.to_json()
    assert np.array_equal(redrawn.image, frame.image)


ACTIONABLE = (
    "documents.create",
    "toolbar.sort",
    "toolbar.filter",
    "toolbar.undo",
    "document:1",
    "document:2",
    "editor.title",
    "editor.body",
)


@pytest.mark.parametrize("identity", ACTIONABLE)
@pytest.mark.parametrize("state", STATES)
def test_a_state_changes_style_and_never_text_or_binding(kernel, session, frame, identity, state):
    in_state = session.frame(kernel.state().with_interaction({identity: state}), CONDITIONING, A_REFERENCE)
    before, after = stored(frame), stored(in_state)
    was, now = entry(before, identity), entry(after, identity)

    assert now["bound"] == {**was["bound"], "state": state}
    assert now["box"] == was["box"]
    # No other element is touched.
    assert [e for e in after["elements"] if e is not now] == [e for e in before["elements"] if e is not was]
    if state == "default":
        assert now["style"] == was["style"]
        assert np.array_equal(in_state.image, frame.image)
    else:
        assert now["style"] != was["style"]
        assert not np.array_equal(in_state.image, frame.image)


# --- runtime renderer: shapes -----------------------------------------------


@pytest.mark.parametrize("scale", SCALES)
def test_rounded_rectangles_are_drawn_as_vectors_at_any_size(kernel, session, scale):
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    assert frame.image.shape == (math.ceil(540 * scale), math.ceil(960 * scale), 4)

    scene = stored(frame)
    button = entry(scene, "documents.create")
    behind = backdrop(frame, "s.toolbar")
    fill = button["style"]["fill"]
    box = button["box"]
    assert button["style"]["corner_radius"] > 0

    # Filled inside, and the box's very corner is left to the toolbar: it is rounded.
    assert close_to(pixel_at(frame, box["x"] + 5, box["y"] + box["height"] / 2), fill)
    assert close_to(pixel_at(frame, box["x"] + 0.4, box["y"] + 0.4), behind)
    assert close_to(pixel_at(frame, box["x"] + box["width"] - 0.4, box["y"] + box["height"] - 0.4), behind)

    # Drawn at this size, not drawn small and enlarged: the left edge goes from
    # toolbar to fill within two pixels at every scale.
    row = frame.image[int((box["y"] + box["height"] / 2) * scale)]
    edge = int(box["x"] * scale)
    span = row[edge - 3 : edge + 4]
    blended = [pixel for pixel in span if not close_to(pixel, behind) and not close_to(pixel, fill)]
    assert len(blended) <= 2
    assert close_to(span[0], behind) and close_to(span[-1], fill)


def restyled(kernel, session, frame, element_id: str, scale: float = 1, **style):
    """The frame drawn from the same scene with some style values of one element replaced."""
    candidate = stored(frame)
    structural(candidate, element_id)["style"].update(style)
    return session.frame_from_scene(kernel.state(), CONDITIONING, candidate, scale=scale)


def test_fill_border_and_corner_radius_are_drawn(kernel, session, frame):
    green, violet = [0.1, 0.7, 0.3, 1.0], [0.5, 0.2, 0.8, 1.0]
    box = structural(stored(frame), "s.list")["box"]
    left, middle = box["x"], box["y"] + box["height"] - 2.5  # a row of pixels below the list's last row

    filled = restyled(kernel, session, frame, "s.list", fill=green, border_width=0.0)
    assert close_to(pixel_at(filled, left + 0.5, middle - 20), green)
    assert close_to(pixel_at(filled, left + 6.5, middle), green)

    bordered = restyled(kernel, session, frame, "s.list", fill=green, border_colour=violet, border_width=5.0)
    assert close_to(pixel_at(bordered, left + 0.5, middle - 20), violet)
    assert close_to(pixel_at(bordered, left + 4.5, middle - 20), violet)
    assert close_to(pixel_at(bordered, left + 5.5, middle - 20), green)

    thin = restyled(kernel, session, frame, "s.list", fill=green, border_colour=violet, border_width=2.0)
    assert close_to(pixel_at(thin, left + 1.5, middle - 20), violet)
    assert close_to(pixel_at(thin, left + 2.5, middle - 20), green)

    # The corner: square at radius 0, cut away at radius 30.
    corner = (left + 1.5, box["y"] + 1.5)
    square = restyled(kernel, session, frame, "s.list", fill=green, border_width=0.0, corner_radius=0.0, elevation=0.0)
    assert close_to(pixel_at(square, *corner), green)
    rounder = restyled(kernel, session, frame, "s.list", fill=green, border_width=0.0, corner_radius=30.0, elevation=0.0)
    assert close_to(pixel_at(rounder, *corner), backdrop(frame, "s.root"))
    assert close_to(pixel_at(rounder, left + 10.5, box["y"] + 10.5), green)


def test_opacity_blends_an_element_with_what_is_behind_it(kernel, session, frame):
    page = np.array(backdrop(frame, "s.root"))
    red = [0.9, 0.1, 0.1, 1.0]
    point = (6, 28)  # the toolbar, left of its first button
    assert frame.hit_test(*point) is None

    opaque = restyled(kernel, session, frame, "s.toolbar", fill=red)
    assert close_to(pixel_at(opaque, *point), red)
    for opacity in (0.75, 0.25, 0.0):
        faded = restyled(kernel, session, frame, "s.toolbar", fill=red, opacity=opacity)
        assert close_to(pixel_at(faded, *point), page * (1 - opacity) + np.array(red[:3]) * opacity)

    # Opacity is the element's own: its border and text fade with it, its children do not.
    button = restyled(kernel, session, frame, "b.documents.create", opacity=0.5)
    _, y = centre(frame, "documents.create")
    edge = (frame.scene.element_for("documents.create").x + 3, y)
    blue, white = np.array(frame.scene.element_for("documents.create").style.fill[:3]), np.ones(3)
    assert close_to(pixel_at(button, *edge), (blue + white) / 2)
    assert np.array_equal(
        restyled(kernel, session, frame, "s.toolbar", opacity=0.5).image[20:36, 200:260],
        frame.image[20:36, 200:260],
    )


def shadow_alpha(distance: float, elevation: float) -> float:
    """The documented shadow: full within the moved outline, gone `elevation`
    outside it, a smoothstep between."""
    along = min(max((elevation - distance) / (2 * elevation), 0.0), 1.0)
    return 0.24 * along * along * (3 - 2 * along)


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("elevation", (4.0, 12.0))
def test_elevation_is_drawn_as_the_documented_shadow_at_any_size(kernel, session, frame, scale, elevation):
    page = np.array(backdrop(frame, "s.root")) * 255
    box = structural(stored(frame), "s.list")["box"]
    x = box["x"] + box["width"] / 2
    bottom = box["y"] + box["height"]

    flat = restyled(kernel, session, frame, "s.list", scale=scale, elevation=0.0)
    raised = restyled(kernel, session, frame, "s.list", scale=scale, elevation=elevation)

    # Every row of pixels from just below the panel's edge to two elevations below it.
    column = int(x * scale)
    drawn = []
    for row in range(math.ceil(bottom * scale), int((bottom + 2 * elevation) * scale)):
        assert close_to(flat.image[row, column], page / 255)
        pixel = raised.image[row, column, :3].astype(float)
        # The shadow's outline is the panel's, moved down by half the elevation.
        depth = (row + 0.5) / scale - bottom
        expected = page * (1 - shadow_alpha(depth - elevation / 2, elevation))
        assert np.abs(pixel - expected).max() <= 4, (depth, pixel, expected)
        drawn.append(pixel.sum())

    assert drawn == sorted(drawn)  # never darker further from the element
    assert drawn[0] < page.sum() - 60  # dark at the edge
    assert drawn[-1] >= page.sum() - 3  # gone a little beyond one and a half elevations
    # A shadow is not part of the shape that is hit, and it leaves the element itself alone.
    assert raised.hit_test(x, bottom + 1) is None
    inside = (slice(int((box["y"] + 20) * scale), int((bottom - 20) * scale)), slice(int((box["x"] + 20) * scale), int((box["x"] + box["width"] - 20) * scale)))
    assert np.array_equal(raised.image[inside], flat.image[inside])


# --- runtime renderer: text -------------------------------------------------


def text_drawn_by_qt(frame, identity: str, text: str) -> np.ndarray:
    """The frame's image area for one element as Qt's own text-to-path draws
    `text` there, by the runtime renderer's stated rules: a text-area's lines
    start half a line height in from the top and left and are 1.25 line heights
    apart; any other text is one line on the box's vertical centre, a button's
    centred, the rest as far from the left edge as from the top."""
    element = frame.scene.element_for(identity)
    style = element.style
    font = QFont("Helvetica Neue")
    font.setPixelSize(100)
    font.setWeight(QFont.Weight(int(style.type_weight)))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    metrics = QFontMetricsF(font)
    size = style.type_size / 100
    line_height = (metrics.ascent() + metrics.descent()) * size
    if element.bound.role == "text-area":
        lines = [
            (line, element.x + line_height / 2, element.y + line_height / 2 + index * 1.25 * line_height)
            for index, line in enumerate(text.split("\n"))
        ]
    else:
        inset = (element.height - line_height) / 2
        if element.bound.role == "button":
            x = element.x + (element.width - metrics.horizontalAdvance(text) * size) / 2
        else:
            x = element.x + inset
        lines = [(text, x, element.y + inset)]

    height, width, _ = frame.image.shape
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor.fromRgbF(*backdrop(frame, element.id)))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setOpacity(style.opacity)
    for line, x, y in lines:
        path = QPainterPath()
        path.addText(QPointF(0, metrics.ascent()), font, line)
        painter.resetTransform()
        painter.scale(frame.scale, frame.scale)
        painter.translate(x, y)
        painter.scale(size, size)
        painter.fillPath(path, QColor.fromRgbF(*style.text_colour))
    painter.end()
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, image.bytesPerLine() // 4, 4)
    return area(pixels[:, :width], frame, identity)


def area(pixels: np.ndarray, frame, identity: str) -> np.ndarray:
    """The pixels of an element's box, clear of its rounded corners and border."""
    element = frame.scene.element_for(identity)
    border = element.style.border_width
    margin = element.style.corner_radius + border
    left = math.ceil((element.x + margin) * frame.scale)
    right = math.floor((element.x + element.width - margin) * frame.scale)
    top = math.ceil((element.y + border) * frame.scale) + 1
    bottom = math.floor((element.y + element.height - border) * frame.scale) - 1
    return pixels[top:bottom, left:right, :3].astype(int)


def difference(drawn: np.ndarray, judge: np.ndarray) -> int:
    """How far two images of text are apart, ignoring what 8-bit rounding of a
    blended backdrop can account for."""
    apart = np.abs(drawn - judge)
    apart[apart <= 2] = 0
    return int(apart.sum())


def distance_from(frame, identity: str, text: str) -> float:
    """How far the drawn element is from Qt's drawing of `text`, as a share of that text's ink."""
    judge = text_drawn_by_qt(frame, identity, text)
    ink = difference(judge, text_drawn_by_qt(frame, identity, ""))
    assert ink > 0, identity
    return difference(area(frame.image, frame, identity), judge) / ink


EXACT = 0.0005


def assert_text_is_exact(frame, identity: str) -> None:
    assert distance_from(frame, identity, frame.scene.element_for(identity).bound.text) <= EXACT, identity


@pytest.mark.parametrize("scale", SCALES)
def test_the_drawn_text_is_exactly_the_applications_text(kernel, session, scale):
    with_notification = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    assert_text_is_exact(with_notification, "notification")

    # The notification lies over the editor body, so the rest is judged in the
    # same state without it.
    kernel.open_document(2)
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    judged = [bound for bound in frame.bound_elements if bound.text]
    assert {bound.role for bound in judged} == {"button", "label", "heading", "list-item", "text-field", "text-area"}
    assert frame.scene.element_for("editor.body").bound.text == BODY
    assert [bound.text for bound in judged if bound.role == "list-item"] == list(TITLES)
    for bound in judged:
        assert_text_is_exact(frame, bound.identity)

    # One wrong accent anywhere, even in the body's four lines, is further from
    # the drawn image than the agreement asked for above, so that agreement
    # means every character on every line.
    cases = {
        "document:2": ("Cafe résumé — août", "Café résumé — aoùt", "Café résumé - août"),
        "document:3": ("Zółć gęślą jaźń", "Żółć geślą jaźń", "Żółć gęślą jaźn"),
        "editor.body": (
            BODY.replace("déjà", "déja"),
            BODY.replace("Größe", "Grösse"),
            BODY.replace("¿mañana?", "¿manana?"),
            BODY.replace("\n\n", "\n"),
        ),
    }
    for identity, wrongs in cases.items():
        for wrong in wrongs:
            assert distance_from(frame, identity, wrong) > 2 * EXACT, wrong


@pytest.mark.parametrize(
    "identity, style",
    [
        ("documents.heading", {"text_colour": [0.8, 0.1, 0.1, 1.0]}),
        ("document:1", {"text_colour": [0.1, 0.5, 0.2, 1.0]}),
        ("document:1", {"type_size": 22.0}),
        ("editor.body", {"type_size": 11.0}),
        ("document:1", {"type_weight": 700.0}),
        ("editor.body", {"type_weight": 200.0}),
        ("documents.create", {"type_size": 18.0, "type_weight": 700.0, "text_colour": [1.0, 0.9, 0.2, 1.0]}),
    ],
)
def test_text_colour_type_size_and_type_weight_are_drawn(kernel, session, identity, style):
    kernel.open_document(2)  # clears the notification that lies over the editor body
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=2)
    changed = restyled(kernel, session, frame, f"b.{identity}", scale=2, **style)
    assert not np.array_equal(area(changed.image, changed, identity), area(frame.image, frame, identity))
    assert_text_is_exact(changed, identity)

    if "type_weight" in style and len(style) == 1:
        behind = np.array(backdrop(frame, f"b.{identity}")) * 255
        ink = [np.abs(area(shown.image, shown, identity) - behind).sum() for shown in (frame, changed)]
        heavier = style["type_weight"] > frame.scene.element_for(identity).style.type_weight
        assert (ink[1] > 1.1 * ink[0]) if heavier else (ink[1] < 0.9 * ink[0])


def test_changing_one_title_changes_only_that_rows_pixels(session, frame):
    other = Kernel()
    fill_workspace(other, ("Quarterly plan", "Café résumé — août", "Żółć gęślą jaźń, wydanie drugie"))
    changed = session.frame(other.state(), CONDITIONING, A_REFERENCE)

    differs = np.any(changed.image != frame.image, axis=2)
    rows, columns = np.nonzero(differs)
    row = frame.scene.element_for("document:3")
    assert differs.any()
    assert row.y <= rows.min() and rows.max() < row.y + row.height
    assert row.x <= columns.min() and columns.max() < row.x + row.width


def test_text_the_font_cannot_draw_is_refused_not_substituted(session):
    kernel = Kernel()
    kernel.create_document("日本語")
    with pytest.raises(TextNotDrawable):
        session.frame(kernel.state(), CONDITIONING, A_REFERENCE)


# --- hit testing ------------------------------------------------------------


def test_a_point_inside_a_drawn_bound_element_hits_that_element(kernel, frame):
    for bound in frame.bound_elements:
        assert frame.hit_test(*centre(frame, bound.identity)) is bound

    hit = frame.hit_test(*centre(frame, "documents.create"))
    assert (hit.identity, hit.binding) == ("documents.create", {"command": "create"})
    for document in kernel.list_documents():
        hit = frame.hit_test(*centre(frame, f"document:{document.id}"))
        assert hit.text == document.title
        assert hit.binding == {"command": "open", "document": document.id}


def test_a_click_on_a_drawn_row_opens_that_document(kernel, session, frame):
    kernel.execute(frame.hit_test(*centre(frame, "document:3")).binding)
    after = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    assert after.scene.element_for("editor.title").bound.text == "Żółć gęślą jaźń"
    assert {"relation": "shown_in", "target": "editor.body"} in after.scene.element_for("document:3").bound.relationships


def test_the_notification_is_hit_where_it_lies_over_the_editor(frame):
    notification = frame.scene.element_for("notification")
    body = frame.scene.element_for("editor.body")
    x, y = centre(frame, "notification")
    assert body.x < x < body.x + body.width and body.y < y < body.y + body.height
    assert frame.hit_test(x, y).identity == "notification"
    assert frame.hit_test(notification.x - 6, y).identity == "editor.body"
    assert frame.hit_test(notification.x + 0.3, notification.y + 0.3).identity == "editor.body"  # outside its rounded corner


def test_a_point_outside_every_bound_element_hits_nothing(frame):
    button = frame.scene.element_for("documents.create")
    first_row = frame.scene.element_for("document:1")
    last_row = frame.scene.element_for("document:3")
    title = frame.scene.element_for("editor.title")
    for point in [
        (5, 5),  # the toolbar, left of the first button
        (button.x + button.width + 4, button.y + button.height / 2),  # the gap between two buttons
        (button.x + 0.3, button.y + 0.3),  # inside the button's box, outside its rounded corner
        (first_row.x - 2, first_row.y + 10),  # the list panel, between its edge and a row
        (first_row.x + 40, last_row.y + last_row.height + 60),  # the page below the list
        (title.x - 8, title.y + 10),  # the editor panel's padding
        (-5, 100),
        (100, 5000),  # outside the viewport
    ]:
        assert frame.hit_test(*point) is None, point


@pytest.mark.parametrize("scale", SCALES)
def test_hit_targets_are_the_shapes_that_were_drawn(kernel, session, scale):
    """Around every corner of a filled bound element, each pixel that shows the
    element's fill hits it and each pixel that shows what lies behind does not."""
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    # A filled button, a bordered one, the open document's row and the
    # notification over the editor. Each is filled in a colour that no blend of
    # its neighbours' edges can pass for.
    behind = {
        "documents.create": backdrop(frame, "s.toolbar"),
        "toolbar.sort": backdrop(frame, "s.toolbar"),
        "document:2": backdrop(frame, "s.list"),
        "notification": backdrop(frame, "b.editor.body"),
    }
    reach = 10

    for identity, background in behind.items():
        element = frame.scene.element_for(identity)
        fill = element.style.fill
        for corner_x in (element.x, element.x + element.width):
            for corner_y in (element.y, element.y + element.height):
                shown = hits = misses = 0
                for pixel_y in range(int((corner_y - reach) * scale), int((corner_y + reach) * scale)):
                    for pixel_x in range(int((corner_x - reach) * scale), int((corner_x + reach) * scale)):
                        pixel = frame.image[pixel_y, pixel_x]
                        hit = frame.hit_test((pixel_x + 0.5) / scale, (pixel_y + 0.5) / scale)
                        is_hit = hit is not None and hit.identity == identity
                        if close_to(pixel, fill):
                            shown += 1
                            assert is_hit, (identity, pixel_x, pixel_y)
                        elif close_to(pixel, background):
                            assert not is_hit, (identity, pixel_x, pixel_y)
                        hits += is_hit
                        misses += not is_hit
                # Both kinds of pixel were seen, and the rounded corner takes
                # more than a square corner's share away from the target.
                assert shown > 0
                assert misses > hits > 0


# --- scene validation -------------------------------------------------------


def remove(identity):
    def tamper(scene):
        scene["elements"].remove(entry(scene, identity))

    return tamper


def duplicate(identity):
    def tamper(scene):
        twin = copy.deepcopy(entry(scene, identity))
        twin["id"] += ".again"
        scene["elements"].append(twin)

    return tamper


def set_bound(identity, field, value):
    def tamper(scene):
        entry(scene, identity)["bound"][field] = value

    return tamper


def set_value(element_id, group, field, value):
    def tamper(scene):
        structural(scene, element_id)[group][field] = value

    return tamper


def set_field(element_id, field, value):
    def tamper(scene):
        structural(scene, element_id)[field] = value

    return tamper


def drop_style_value(scene):
    del structural(scene, "s.list")["style"]["fill"]


def add_cycle(scene):
    for element_id, parent in (("s.loop.one", "s.loop.two"), ("s.loop.two", "s.loop.one")):
        twin = copy.deepcopy(structural(scene, "s.divider"))
        twin.update(id=element_id, parent=parent)
        scene["elements"].append(twin)


def duplicate_id(scene):
    scene["elements"].append(copy.deepcopy(structural(scene, "s.divider")))


def add_unknown_bound(scene):
    twin = copy.deepcopy(entry(scene, "document:2"))
    twin["id"] += ".invented"
    twin["bound"]["identity"] = "document:99"
    scene["elements"].append(twin)


def add_structural(count):
    def tamper(scene):
        for number in range(count):
            twin = copy.deepcopy(structural(scene, "s.divider"))
            twin["id"] = f"s.extra.{number}"
            scene["elements"].append(twin)

    return tamper


INVALID = {
    "a bound element is missing": (remove("document:2"), "bound_missing"),
    "a bound element is duplicated": (duplicate("document:2"), "bound_duplicated"),
    "a bound element was invented": (add_unknown_bound, "bound_unknown"),
    "text is altered": (set_bound("document:2", "text", "Cafe resume — aout"), "bound_altered"),
    "text is truncated": (set_bound("editor.body", "text", "Première ligne: déjà vu…"), "bound_altered"),
    "a binding is altered": (set_bound("document:2", "binding", {"command": "open", "document": 3}), "bound_altered"),
    "a binding is removed": (set_bound("documents.create", "binding", None), "bound_altered"),
    "a role is altered": (set_bound("documents.create", "role", "heading"), "bound_altered"),
    "a state is altered": (set_bound("toolbar.save", "state", "default"), "bound_altered"),
    "a relationship is altered": (set_bound("document:1", "relationships", []), "bound_altered"),
    "a box holds not-a-number": (set_value("s.list", "box", "x", float("nan")), "non_finite"),
    "a box holds infinity": (set_value("b.document:1", "box", "width", float("inf")), "non_finite"),
    "a style value is infinite": (set_value("s.list", "style", "opacity", float("-inf")), "non_finite"),
    "a colour holds not-a-number": (set_value("s.list", "style", "fill", [1.0, float("nan"), 1.0, 1.0]), "non_finite"),
    "a parent does not exist": (set_field("s.list", "parent", "s.nowhere"), "tree"),
    "there are two roots": (set_field("s.list", "parent", None), "tree"),
    "there is no root": (set_field("s.root", "parent", "s.list"), "tree"),
    "parents form a cycle": (add_cycle, "tree"),
    "a bound element is a parent": (set_field("s.divider", "parent", "b.documents.create"), "tree"),
    "two elements share an id": (duplicate_id, "tree"),
    "a structural element carries text": (set_field("s.list", "text", "Documents"), "structural_carries_bound"),
    "a structural element carries a binding": (set_field("s.list", "binding", {"command": "create"}), "structural_carries_bound"),
    "a box leaves the viewport": (set_value("b.documents.create", "box", "x", 900.0), "outside_viewport"),
    "a box has no area": (set_value("s.divider", "box", "height", 0.0), "out_of_range"),
    "a corner radius exceeds the box": (set_value("b.documents.create", "style", "corner_radius", 400.0), "out_of_range"),
    "an opacity is above one": (set_value("s.list", "style", "opacity", 1.5), "out_of_range"),
    "an elevation is negative": (set_value("s.list", "style", "elevation", -2.0), "out_of_range"),
    "a type size is zero": (set_value("b.document:1", "style", "type_size", 0.0), "out_of_range"),
    "a style value is missing": (drop_style_value, "malformed"),
    "a number is text": (set_value("s.list", "box", "x", "24"), "malformed"),
    "a type is unknown": (set_field("s.divider", "type", "canvas"), "malformed"),
    "the elements are not a list": (lambda scene: scene.update(elements={}), "malformed"),
    "the viewport is not the conditioning's": (lambda scene: scene.update(viewport={"width": 800, "height": 540}), "malformed"),
    "there are more than 16 structural elements": (add_structural(12), "limit_exceeded"),
}


@pytest.mark.parametrize("case", INVALID)
def test_an_invalid_scene_is_refused_with_its_reason_and_not_drawn(kernel, session, frame, case):
    tamper, code = INVALID[case]
    candidate = stored(frame)
    assert session.frame_from_scene(kernel.state(), CONDITIONING, copy.deepcopy(candidate))

    tamper(candidate)
    # As a stored scene would arrive: through JSON text, which can hold NaN.
    candidate = json.loads(json.dumps(candidate))
    with pytest.raises(SceneInvalid) as refused:
        session.frame_from_scene(kernel.state(), CONDITIONING, candidate)
    assert code in refused.value.codes, [str(problem) for problem in refused.value.problems]


def test_a_scene_for_another_state_is_refused(kernel, session, frame):
    candidate = stored(frame)
    kernel.create_document("Created after the scene was written")
    with pytest.raises(SceneInvalid) as refused:
        session.frame_from_scene(kernel.state(), CONDITIONING, candidate)
    assert refused.value.codes == {"bound_missing", "bound_altered"}  # the new row; the notification's text


def test_the_structural_limit_is_sixteen(kernel, session, frame):
    candidate = stored(frame)
    add_structural(11)(candidate)
    assert len(session.frame_from_scene(kernel.state(), CONDITIONING, candidate).scene.structural_elements) == 16


def test_more_bound_elements_than_the_limit_is_reported_not_dropped(session):
    kernel = Kernel()
    for number in range(21):
        kernel.create_document(f"Document {number + 1}")
    kernel.open_document(1)
    kernel.rename_document(1, "The first document")  # leaves a notification
    tall = Conditioning(960, 1100)
    assert len(session.frame(kernel.state(), tall, A_REFERENCE).bound_elements) == 32

    kernel.create_document("One too many")
    with pytest.raises(SceneInvalid) as refused:
        session.frame(kernel.state(), tall, A_REFERENCE)
    assert refused.value.codes == {"limit_exceeded"}
    assert "33 bound elements; the limit is 32" in str(refused.value)


@pytest.mark.parametrize("viewport", [(960, 230), (480, 540)], ids=["too short for the list", "too narrow for the toolbar"])
def test_a_workspace_that_does_not_fit_the_viewport_is_reported_not_clipped(kernel, session, viewport):
    with pytest.raises(SceneInvalid) as refused:
        session.frame(kernel.state(), Conditioning(*viewport), A_REFERENCE)
    assert refused.value.codes == {"outside_viewport"}


# --- counting, reporting and projection -------------------------------------


def test_invalid_scenes_are_counted_and_reported_by_reason(kernel, session, frame, caplog):
    good = stored(frame)
    assert (session.report.scenes, session.report.invalid) == (1, 0)

    tampers = [INVALID[case][0] for case in ("text is altered", "a box leaves the viewport", "an opacity is above one")]
    with caplog.at_level(logging.INFO, logger="core_ultra.scene_session"):
        for tamper in (*tampers, lambda scene: (tampers[0](scene), tampers[1](scene))):
            candidate = copy.deepcopy(good)
            tamper(candidate)
            with pytest.raises(SceneInvalid):
                session.frame_from_scene(kernel.state(), CONDITIONING, candidate)
        session.frame_from_scene(kernel.state(), CONDITIONING, good)
        with pytest.raises(SceneInvalid):
            session.frame(kernel.state(), Conditioning(960, 230), A_REFERENCE)

    report = session.report
    assert (report.scenes, report.valid, report.invalid) == (7, 2, 5)
    assert report.invalid_by_code == {"bound_altered": 2, "outside_viewport": 3, "out_of_range": 1}
    assert [(entry.scene, entry.source) for entry in report.invalid_scenes] == [
        (2, "supplied scene"),
        (3, "supplied scene"),
        (4, "supplied scene"),
        (5, "supplied scene"),
        (7, "A, Reference"),
    ]
    assert [problem.code for problem in report.invalid_scenes[3].problems] == ["outside_viewport", "bound_altered"]
    assert "Cafe resume — aout" in str(report.invalid_scenes[0].problems[0])
    assert (report.projections, report.projected_scenes) == (0, ())
    assert "invalid: 5" in report.summary() and "outside_viewport: 3" in report.summary()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 5
    assert "scene 2 (supplied scene) is invalid and was not drawn" in warnings[0].getMessage()

    # A report is what had been seen when it was taken.
    with pytest.raises(SceneInvalid):
        session.frame(kernel.state(), Conditioning(960, 230), A_REFERENCE)
    assert (report.invalid, session.report.invalid) == (5, 6)


OUT_OF_BOUNDS = {
    "box.x": ("b.documents.create", "box", "x", 900.0),
    "box.y": ("s.list", "box", "y", -30.0),
    "box.width": ("s.toolbar", "box", "width", 2000.0),
    "box.height": ("s.root", "box", "height", 541.5),
    "style.opacity": ("s.list", "style", "opacity", 1.5),
    "style.elevation": ("s.list", "style", "elevation", -2.0),
    "style.type_weight": ("b.document:1", "style", "type_weight", 950.0),
    "style.border_width": ("s.divider", "style", "border_width", 3.0),
    "style.corner_radius": ("b.documents.create", "style", "corner_radius", 400.0),
    "style.fill[1]": ("s.list", "style", "fill", [1.0, 1.25, 1.0, 1.0]),
    "style.text_colour[3]": ("b.document:1", "style", "text_colour", [0.1, 0.1, 0.1, -0.5]),
}


@pytest.mark.parametrize("field", OUT_OF_BOUNDS)
def test_a_value_is_projected_into_its_bounds_only_when_asked_and_every_projection_is_recorded(kernel, session, frame, field):
    element_id, group, name, value = OUT_OF_BOUNDS[field]
    candidate = stored(frame)
    structural(candidate, element_id)[group][name] = value
    given = copy.deepcopy(candidate)

    # Not asked: the scene is invalid, and counted as invalid.
    with pytest.raises(SceneInvalid) as refused:
        session.frame_from_scene(kernel.state(), CONDITIONING, candidate)
    assert refused.value.codes <= {"out_of_range", "outside_viewport"}
    assert (session.report.invalid, session.report.projections) == (1, 0)

    # Asked: the value is moved onto its bound, the scene is drawn, and the
    # projection is on the frame and in the report, apart from invalid scenes.
    projected = session.frame_from_scene(kernel.state(), CONDITIONING, candidate, project=True)
    assert candidate == given  # the scene that was passed in is not modified
    (projection,) = projected.projections
    assert (projection.element, projection.field) == (element_id, field)
    assert projection.given == (value if not isinstance(value, list) else value[int(field[-2])])

    used = structural(stored(projected), element_id)[group][name]
    used = used if not isinstance(used, list) else used[int(field[-2])]
    assert projection.used == used != projection.given
    untouched = stored(projected)
    structural(untouched, element_id)[group][name] = value
    assert untouched == given  # nothing else was changed

    report = session.report
    assert (report.scenes, report.valid, report.invalid) == (3, 2, 1)
    assert (report.projections, report.projections_by_field) == (1, {field: 1})
    assert [(entry.scene, entry.source, entry.projections) for entry in report.projected_scenes] == [
        (3, "supplied scene", (projection,))
    ]


def test_projections_are_logged_and_counted_apart_from_invalid_scenes(kernel, session, frame, caplog):
    candidate = stored(frame)
    for element_id, group, name, value in (OUT_OF_BOUNDS[field] for field in ("style.opacity", "box.x", "style.fill[1]")):
        structural(candidate, element_id)[group][name] = value
    broken = copy.deepcopy(candidate)
    remove("document:2")(broken)

    with caplog.at_level(logging.INFO, logger="core_ultra.scene_session"):
        drawn = session.frame_from_scene(kernel.state(), CONDITIONING, candidate, project=True)
        # Projection moves numbers only. A scene with a bound element missing
        # is still invalid, and its projected values are still counted.
        with pytest.raises(SceneInvalid) as refused:
            session.frame_from_scene(kernel.state(), CONDITIONING, broken, project=True)
    assert refused.value.codes == {"bound_missing"}
    assert sorted(p.field for p in drawn.projections) == ["box.x", "style.fill[1]", "style.opacity"]

    report = session.report
    assert (report.scenes, report.valid, report.invalid, report.projections) == (3, 2, 1, 6)
    assert report.invalid_by_code == {"bound_missing": 1}
    assert report.projections_by_field == {"box.x": 2, "style.fill[1]": 2, "style.opacity": 2}
    assert [entry.scene for entry in report.projected_scenes] == [2, 3]
    assert "values projected: 6" in report.summary() and "invalid: 1" in report.summary()

    logged = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert len(logged) == 6
    assert "scene 2 (supplied scene): s.list: style.opacity 1.5 projected to 1.0" in logged


NOT_PROJECTED = {
    "a value that is not a number": (set_value("s.list", "style", "opacity", float("nan")), "non_finite"),
    "a box without area": (set_value("s.divider", "box", "height", -4.0), "out_of_range"),
    "a type size that is not above zero": (set_value("b.document:1", "style", "type_size", -1.0), "out_of_range"),
    "altered text": (set_bound("document:2", "text", "Cafe resume — aout"), "bound_altered"),
    "a broken tree": (set_field("s.list", "parent", "s.nowhere"), "tree"),
}


@pytest.mark.parametrize("case", NOT_PROJECTED)
def test_what_has_no_nearest_allowed_value_is_never_projected(kernel, session, frame, case):
    tamper, code = NOT_PROJECTED[case]
    candidate = stored(frame)
    tamper(candidate)
    with pytest.raises(SceneInvalid) as refused:
        session.frame_from_scene(kernel.state(), CONDITIONING, json.loads(json.dumps(candidate)), project=True)
    assert refused.value.codes == {code}
    assert (session.report.invalid, session.report.projections) == (1, 0)


def test_a_scene_inside_its_bounds_is_untouched_by_projection(kernel, session, frame):
    again = session.frame_from_scene(kernel.state(), CONDITIONING, stored(frame), project=True)
    assert again.projections == () and frame.projections == ()
    assert np.array_equal(again.image, frame.image)
    assert session.report.projected_scenes == ()


# --- no browser engine ------------------------------------------------------


def test_no_browser_engine_is_in_the_runtime_renderers_path(frame):
    assert frame.image.any()
    engines = ("webengine", "webkit", "webview", "chromium")

    assert not [name for name in sys.modules if any(engine in name.lower() for engine in engines)]
    assert importlib.util.find_spec("PySide6.QtWebEngineCore") is None
    installed = {
        distribution.metadata["Name"].lower().replace("_", "-") for distribution in importlib.metadata.distributions()
    }
    assert "pyside6-essentials" in installed
    assert not installed & {"pyside6", "pyside6-addons"}

    # Every library loaded into this process, as the dynamic loader lists them.
    loader = ctypes.CDLL(None)
    loader._dyld_get_image_name.restype = ctypes.c_char_p
    loaded = [loader._dyld_get_image_name(index).decode() for index in range(loader._dyld_image_count())]
    assert any(path.endswith("QtGui") for path in loaded)
    assert not [path for path in loaded if any(engine in path.lower() for engine in engines)]
