"""Scene session tests (test seam 1), against A, Reference.

Every test supplies application state from a real kernel and asserts on what
the scene session returns: the scene, its validity, the drawn image and
hit-test answers. Nothing is mocked and no window is opened.

Where a test needs a judge of the image, the judge is independent of the
runtime renderer's own code: Qt's `QPainterPath.addText` for text, and the
scene's stated colours for shapes.
"""

from __future__ import annotations

import copy
import ctypes
import dataclasses
import importlib.metadata
import importlib.util
import json
import math
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

TITLES = ("Quarterly plan", "Café résumé — août", "Notes on the fjord office")
CONDITIONING = Conditioning(640, 320)
A_REFERENCE = RenderingMode.A_REFERENCE
SCALES = (1, 2, 3.5)
STATES = ("default", "hover", "pressed", "focused", "disabled")
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


@pytest.fixture
def kernel(tmp_path):
    kernel = Kernel(tmp_path / "application.sqlite")
    for title in TITLES:
        kernel.create_document(title)
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


def close_to(pixel, colour) -> bool:
    """An opaque pixel of this colour, within one step of 8-bit rounding."""
    return all(abs(int(channel) - round(value * 255)) <= 1 for channel, value in zip(pixel[:3], colour[:3]))


# --- the session's contract -------------------------------------------------


def test_a_frame_is_the_validated_scene_its_image_and_a_hit_test_without_a_window(frame):
    assert frame.image.shape == (320, 640, 4)
    assert frame.image.dtype == np.uint8
    assert (frame.scene.viewport_width, frame.scene.viewport_height) == (640, 320)
    assert frame.hit_test(1, 1) is None

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


# --- application kernel -----------------------------------------------------


def test_documents_are_committed_to_sqlite(tmp_path, session):
    path = tmp_path / "application.sqlite"
    first = Kernel(path)
    for title in TITLES:
        first.create_document(title)
    first.close()

    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    reopened = Kernel(path)
    assert [document.title for document in reopened.list_documents()] == list(TITLES)
    frame = session.frame(reopened.state(), CONDITIONING, A_REFERENCE)
    assert [e.bound.text for e in frame.scene.bound_elements if e.bound.role == "list-item"] == list(TITLES)
    reopened.close()


def test_the_kernel_refuses_a_document_without_a_usable_title(kernel):
    for title in ("", "   ", "two\nlines"):
        with pytest.raises(KernelError):
            kernel.create_document(title)
    assert [document.title for document in kernel.list_documents()] == list(TITLES)


def test_an_empty_application_still_draws_its_heading_and_button(session):
    frame = session.frame(Kernel().state(), CONDITIONING, A_REFERENCE)
    assert [b.identity for b in frame.bound_elements] == ["documents.heading", "documents.create"]
    assert frame.hit_test(*centre(frame, "documents.create")).identity == "documents.create"


# --- documents app adapter --------------------------------------------------


def test_state_is_described_as_bound_elements_with_no_coordinates_and_no_style(frame):
    assert [dataclasses.asdict(b) for b in frame.bound_elements] == [
        {
            "identity": "documents.heading",
            "role": "heading",
            "text": "Documents",
            "binding": None,
            "state": "default",
            "relationships": (),
        },
        {
            "identity": "documents.create",
            "role": "button",
            "text": "New document",
            "binding": {"command": "create"},
            "state": "default",
            "relationships": (),
        },
        *[
            {
                "identity": f"document:{number}",
                "role": "list-item",
                "text": title,
                "binding": {"command": "open", "document": number},
                "state": "default",
                "relationships": ({"relation": "item_of", "target": "documents.heading"},),
            }
            for number, title in enumerate(TITLES, start=1)
        ],
    ]
    for bound in frame.bound_elements:
        assert {field.name for field in dataclasses.fields(bound)} == BOUND_FIELDS


def test_identities_are_stable_when_a_document_is_created(kernel, session, frame):
    kernel.create_document("A fourth document")
    after = session.frame(kernel.state(), CONDITIONING, A_REFERENCE)
    assert after.bound_elements[: len(frame.bound_elements)] == frame.bound_elements
    assert after.bound_elements[-1].identity == "document:4"


# --- scene schema -----------------------------------------------------------


def test_a_scene_is_a_tree_of_elements_stored_as_json(frame):
    scene = stored(frame)
    assert scene["kind"] == "scene"
    assert scene["viewport"] == {"width": 640, "height": 320}

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


def test_bound_elements_carry_what_the_application_supplied_unchanged(frame):
    scene = stored(frame)
    carried = [element["bound"] for element in scene["elements"] if element["type"] == "bound"]
    assert carried == [json.loads(json.dumps(bound.to_json())) for bound in frame.bound_elements]


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


@pytest.mark.parametrize("state", STATES)
def test_a_state_changes_style_and_never_text_or_binding(kernel, session, frame, state):
    in_state = session.frame(kernel.state().with_interaction({"document:2": state}), CONDITIONING, A_REFERENCE)
    before, after = entry(stored(frame), "document:2"), entry(stored(in_state), "document:2")

    assert after["bound"] == {**before["bound"], "state": state}
    assert after["box"] == before["box"]
    if state == "default":
        assert after["style"] == before["style"]
        assert np.array_equal(in_state.image, frame.image)
    else:
        assert after["style"] != before["style"]
        assert not np.array_equal(in_state.image, frame.image)


# --- runtime renderer -------------------------------------------------------


def centre(frame, identity: str) -> tuple[float, float]:
    element = frame.scene.element_for(identity)
    return element.x + element.width / 2, element.y + element.height / 2


def pixel_at(frame, x: float, y: float) -> np.ndarray:
    return frame.image[int(y * frame.scale), int(x * frame.scale)]


@pytest.mark.parametrize("scale", SCALES)
def test_rounded_rectangles_are_drawn_as_vectors_at_any_size(kernel, session, scale):
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    assert frame.image.shape == (math.ceil(320 * scale), math.ceil(640 * scale), 4)

    scene = stored(frame)
    button = entry(scene, "documents.create")
    page = structural(scene, "s.root")["style"]["fill"]
    fill = button["style"]["fill"]
    box = button["box"]
    assert button["style"]["corner_radius"] > 0

    # Filled inside, and the box's very corner is left to the page: it is rounded.
    assert close_to(pixel_at(frame, box["x"] + 5, box["y"] + box["height"] / 2), fill)
    assert close_to(pixel_at(frame, box["x"] + 0.4, box["y"] + 0.4), page)
    assert close_to(pixel_at(frame, box["x"] + box["width"] - 0.4, box["y"] + box["height"] - 0.4), page)

    # Drawn at this size, not drawn small and enlarged: the left edge goes from
    # page to fill within two pixels at every scale.
    row = frame.image[int((box["y"] + box["height"] / 2) * scale)]
    edge = int(box["x"] * scale)
    span = row[edge - 3 : edge + 4]
    blended = [pixel for pixel in span if not close_to(pixel, page) and not close_to(pixel, fill)]
    assert len(blended) <= 2
    assert close_to(span[0], page) and close_to(span[-1], fill)


def text_drawn_by_qt(frame, identity: str, text: str, background) -> np.ndarray:
    """The frame's image area for one element as Qt's own text-to-path draws
    `text` there: on the box's vertical centre, a button's text centred, other
    text as far from the left edge as from the top."""
    element = frame.scene.element_for(identity)
    style = element.style
    font = QFont("Helvetica Neue")
    font.setPixelSize(100)
    font.setWeight(QFont.Weight(int(style.type_weight)))
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    metrics = QFontMetricsF(font)
    size = style.type_size / 100
    inset = (element.height - (metrics.ascent() + metrics.descent()) * size) / 2
    if element.bound.role == "button":
        x = element.x + (element.width - metrics.horizontalAdvance(text) * size) / 2
    else:
        x = element.x + inset

    path = QPainterPath()
    path.addText(QPointF(0, metrics.ascent()), font, text)
    height, width, _ = frame.image.shape
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor.fromRgbF(*background))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(frame.scale, frame.scale)
    painter.translate(x, element.y + inset)
    painter.scale(size, size)
    painter.fillPath(path, QColor.fromRgbF(*style.text_colour))
    painter.end()
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, image.bytesPerLine() // 4, 4)
    return area(pixels[:, :width], frame, identity)


def area(pixels: np.ndarray, frame, identity: str) -> np.ndarray:
    """The pixels of an element's box, clear of its rounded corners and border."""
    element = frame.scene.element_for(identity)
    margin = element.style.corner_radius + element.style.border_width
    left = math.ceil((element.x + margin) * frame.scale)
    right = math.floor((element.x + element.width - margin) * frame.scale)
    top = math.ceil(element.y * frame.scale) + 1
    bottom = math.floor((element.y + element.height) * frame.scale) - 1
    return pixels[top:bottom, left:right, :3].astype(int)


@pytest.mark.parametrize("scale", SCALES)
def test_the_drawn_text_is_exactly_the_applications_text(kernel, session, scale):
    frame = session.frame(kernel.state(), CONDITIONING, A_REFERENCE, scale=scale)
    scene = stored(frame)
    page = structural(scene, "s.root")["style"]["fill"]
    panel = structural(scene, "s.list")["style"]["fill"]
    documents = kernel.list_documents()

    expected = [("documents.heading", "Documents", page)]
    expected += [("documents.create", "New document", entry(scene, "documents.create")["style"]["fill"])]
    expected += [(f"document:{document.id}", document.title, panel) for document in documents]

    for identity, text, background in expected:
        assert frame.scene.element_for(identity).bound.text == text
        drawn = area(frame.image, frame, identity)
        judge = text_drawn_by_qt(frame, identity, text, background)
        blank = text_drawn_by_qt(frame, identity, "", background)
        ink = np.abs(judge - blank).sum()
        assert ink > 0
        assert np.abs(drawn - judge).sum() <= 0.002 * ink, identity

    # The judge can tell one accent from another, so the agreement above means
    # every character.
    drawn = area(frame.image, frame, "document:2")
    for wrong in ("Cafe résumé — août", "Café résumé — aoùt", "Café résumé - août"):
        judge = text_drawn_by_qt(frame, "document:2", wrong, panel)
        ink = np.abs(judge - text_drawn_by_qt(frame, "document:2", "", panel)).sum()
        assert np.abs(drawn - judge).sum() > 0.005 * ink, wrong


def test_changing_one_title_changes_only_that_rows_pixels(session, frame):
    other = Kernel()
    for title in ("Quarterly plan", "Café résumé — septembre", "Notes on the fjord office"):
        other.create_document(title)
    changed = session.frame(other.state(), CONDITIONING, A_REFERENCE)

    differs = np.any(changed.image != frame.image, axis=2)
    rows, columns = np.nonzero(differs)
    row = frame.scene.element_for("document:2")
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
    hit = frame.hit_test(*centre(frame, "documents.create"))
    assert (hit.identity, hit.binding) == ("documents.create", {"command": "create"})

    assert frame.hit_test(*centre(frame, "documents.heading")).identity == "documents.heading"
    for document in kernel.list_documents():
        hit = frame.hit_test(*centre(frame, f"document:{document.id}"))
        assert hit.text == document.title
        assert hit.binding == {"command": "open", "document": document.id}


def test_a_point_outside_every_bound_element_hits_nothing(frame):
    button = frame.scene.element_for("documents.create")
    first_row = frame.scene.element_for("document:1")
    last_row = frame.scene.element_for("document:3")
    for point in [
        (5, 5),  # the header, left of the heading
        (button.x - 4, button.y + button.height / 2),  # just left of the button
        (button.x + 0.3, button.y + 0.3),  # inside the button's box, outside its rounded corner
        (first_row.x - 2, first_row.y + 10),  # the panel, between its edge and a row
        (320, last_row.y + last_row.height + 30),  # the page below the panel
        (-5, 100),
        (100, 5000),  # outside the viewport
    ]:
        assert frame.hit_test(*point) is None, point


@pytest.mark.parametrize("scale", SCALES)
def test_hit_targets_are_the_shapes_that_were_drawn(kernel, session, scale):
    """Around every corner of a filled bound element, each pixel that shows the
    element's fill hits it and each pixel that shows what lies behind does not."""
    state = kernel.state().with_interaction({"document:2": "hover"})
    frame = session.frame(state, CONDITIONING, A_REFERENCE, scale=scale)
    scene = stored(frame)
    behind = {
        "documents.create": structural(scene, "s.root")["style"]["fill"],
        "document:2": structural(scene, "s.list")["style"]["fill"],
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


INVALID = {
    "a bound element is missing": (remove("document:2"), "bound_missing"),
    "a bound element is duplicated": (duplicate("document:2"), "bound_duplicated"),
    "a bound element was invented": (add_unknown_bound, "bound_unknown"),
    "text is altered": (set_bound("document:2", "text", "Cafe resume — aout"), "bound_altered"),
    "text is truncated": (set_bound("document:3", "text", "Notes on the fjord…"), "bound_altered"),
    "a binding is altered": (set_bound("document:2", "binding", {"command": "open", "document": 3}), "bound_altered"),
    "a binding is removed": (set_bound("documents.create", "binding", None), "bound_altered"),
    "a role is altered": (set_bound("documents.create", "role", "heading"), "bound_altered"),
    "a state is altered": (set_bound("document:1", "state", "disabled"), "bound_altered"),
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
    "a box leaves the viewport": (set_value("b.documents.create", "box", "x", 600.0), "outside_viewport"),
    "a box has no area": (set_value("s.divider", "box", "height", 0.0), "out_of_range"),
    "a corner radius exceeds the box": (set_value("b.documents.create", "style", "corner_radius", 400.0), "out_of_range"),
    "an opacity is above one": (set_value("s.list", "style", "opacity", 1.5), "out_of_range"),
    "a style value is missing": (drop_style_value, "malformed"),
    "a number is text": (set_value("s.list", "box", "x", "24"), "malformed"),
    "a type is unknown": (set_field("s.divider", "type", "canvas"), "malformed"),
    "the elements are not a list": (lambda scene: scene.update(elements={}), "malformed"),
    "the viewport is not the conditioning's": (lambda scene: scene.update(viewport={"width": 800, "height": 320}), "malformed"),
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
    assert refused.value.codes == {"bound_missing"}


def test_more_bound_elements_than_the_limit_is_reported_not_dropped(session):
    kernel = Kernel()
    for number in range(30):
        kernel.create_document(f"Document {number + 1}")
    tall = Conditioning(640, 2000)
    assert len(session.frame(kernel.state(), tall, A_REFERENCE).bound_elements) == 32

    kernel.create_document("One too many")
    with pytest.raises(SceneInvalid) as refused:
        session.frame(kernel.state(), tall, A_REFERENCE)
    assert refused.value.codes == {"limit_exceeded"}


def test_a_list_that_does_not_fit_the_viewport_is_reported_not_clipped(kernel, session):
    with pytest.raises(SceneInvalid) as refused:
        session.frame(kernel.state(), Conditioning(640, 180), A_REFERENCE)
    assert refused.value.codes == {"outside_viewport"}


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
