"""Tests of the training renderer, through its public draw function only.

Every test draws with `training_renderer.draw` (and reads a scene with
`elements_of`, or an image with `to_rgba8`). The judges are not the renderer:
finite differences taken here, the runtime renderer's image of the same
scene, and cover counted from sample points by this file.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from core_ultra import runtime_renderer, training_renderer
from core_ultra import scene as scene_schema
from core_ultra.training_renderer import Elements, draw, elements_of, to_rgba8

F64 = torch.float64
ATTRIBUTES = ("box", "fill", "corner_radius", "opacity")
needs_apple_gpu = pytest.mark.skipif(not torch.backends.mps.is_available(), reason="PyTorch reports no usable Apple GPU")


def elements(*rows: tuple[list[float], list[float], float, float], dtype=F64, device="cpu") -> Elements:
    """Elements from (box, fill, corner radius, opacity) rows, in the order given."""
    return Elements(
        box=torch.tensor([row[0] for row in rows], dtype=dtype, device=device),
        fill=torch.tensor([row[1] for row in rows], dtype=dtype, device=device),
        corner_radius=torch.tensor([row[2] for row in rows], dtype=dtype, device=device),
        opacity=torch.tensor([row[3] for row in rows], dtype=dtype, device=device),
    )


def scene_of(viewport: tuple[float, float], *rows: tuple[list[float], list[float], float, float]) -> scene_schema.Scene:
    """A validated scene of structural elements: the first row is the root, the rest its children."""
    candidate = {
        "kind": "scene",
        "schema_version": 1,
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "elements": [
            {
                "id": f"e{index}",
                "type": "surface" if index == 0 else "panel",
                "parent": None if index == 0 else "e0",
                "box": dict(zip(("x", "y", "width", "height"), box)),
                "style": {
                    "fill": fill,
                    "text_colour": [0, 0, 0, 1],
                    "border_colour": [0, 0, 0, 0],
                    "border_width": 0,
                    "corner_radius": radius,
                    "elevation": 0,
                    "opacity": opacity,
                    "type_size": 15,
                    "type_weight": 400,
                },
            }
            for index, (box, fill, radius, opacity) in enumerate(rows)
        ],
    }
    return scene_schema.validate(candidate, [], viewport)


def leaves(given: Elements) -> list[torch.Tensor]:
    return [getattr(given, name).detach().clone().requires_grad_(True) for name in ATTRIBUTES]


def central_differences(scalar, tensors: list[torch.Tensor], step: float = 1e-5) -> list[torch.Tensor]:
    """The gradient of `scalar(tensors)` in every number, one number at a time."""
    found = []
    with torch.no_grad():
        for position, tensor in enumerate(tensors):
            gradient = torch.zeros_like(tensor)
            for index in range(tensor.numel()):
                ends = []
                for sign in (1, -1):
                    nudged = tensor.detach().clone()
                    nudged.view(-1)[index] += sign * step
                    ends.append(scalar([*tensors[:position], nudged, *tensors[position + 1 :]]))
                gradient.view(-1)[index] = (ends[0] - ends[1]) / (2 * step)
            found.append(gradient)
    return found


def premultiplied(rgba8: np.ndarray) -> np.ndarray:
    """The runtime renderer's 8-bit image with colour premultiplied, in levels of 255."""
    rgba = rgba8.astype(np.float64)
    return np.concatenate([rgba[..., :3] * rgba[..., 3:] / 255, rgba[..., 3:]], axis=-1)


def counted_cover(box: list[float], radius: float, viewport: tuple[int, int], side: int = 32) -> np.ndarray:
    """How much of each pixel a rounded rectangle covers, counted from side by side sample points."""
    width, height = viewport
    xs = (np.arange(width * side) + 0.5) / side
    ys = (np.arange(height * side) + 0.5) / side
    left, top, wide, high = box
    dx = np.abs(xs - (left + wide / 2))[None, :] - (wide / 2 - radius)
    dy = np.abs(ys - (top + high / 2))[:, None] - (high / 2 - radius)
    inside = (dx <= radius) & (dy <= radius) & ~((dx > 0) & (dy > 0) & (dx**2 + dy**2 > radius**2))
    return inside.reshape(height, side, width, side).mean(axis=(1, 3))


# Numbers chosen so that no edge and no corner's centre falls on a pixel's
# boundary or centre, where a gradient is one-sided.
OVERLAPPING = (
    ([1.37, 0.83, 36.21, 26.12], [0.93, 0.94, 0.9, 0.95], 3.3, 0.97),
    ([4.31, 3.72, 18.44, 13.27], [0.9, 0.4, 0.2, 0.6], 4.1, 0.9),
    ([12.53, 8.26, 20.18, 15.09], [0.2, 0.5, 0.9, 0.5], 6.2, 0.7),
    ([16.42, 11.63, 9.75, 6.36], [0.15, 0.7, 0.45, 0.96], 1.4, 0.93),
)
PAST_THE_VIEWPORT = (
    ([-5.42, 6.37, 14.81, 10.26], [0.9, 0.3, 0.3, 0.9], 3.2, 0.9),
    ([13.33, -4.61, 12.72, 10.44], [0.3, 0.9, 0.3, 0.9], 2.6, 0.9),
    ([31.27, 20.66, 13.38, 11.73], [0.3, 0.3, 0.9, 0.9], 4.1, 0.9),
)
VIEWPORT = (40, 28)


# --- what is drawn ---------------------------------------------------------------


def test_the_image_has_the_size_the_runtime_renderer_gives_the_same_scene():
    scene = scene_of((40.5, 28.25), ([0, 0, 40.5, 28.25], [1, 1, 1, 1], 0, 1))
    for scale in (1.0, 2.0, 0.5, 1.5):
        ours = draw(elements_of(scene), (40.5, 28.25), scale)
        assert tuple(ours.shape) == runtime_renderer.draw(scene, scale).shape


def test_square_boxes_on_whole_numbers_are_the_runtime_renderers_pixels():
    scene = scene_of(
        (40, 28),
        ([0, 0, 40, 28], [1.0, 1.0, 1.0, 1], 0, 1),
        ([0, 0, 40, 6], [0.2, 0.4, 0.6, 1], 0, 1),
        ([4, 10, 20, 12], [0.8, 0.6, 0.4, 1], 0, 1),
        ([24, 10, 1, 12], [0.0, 0.0, 0.0, 1], 0, 1),
    )
    for scale in (1.0, 2.0):
        ours = to_rgba8(draw(elements_of(scene, F64), (40, 28), scale))
        theirs = runtime_renderer.draw(scene, scale)
        assert ours.dtype == theirs.dtype and ours.shape == theirs.shape
        assert np.abs(ours.astype(int) - theirs.astype(int)).max() <= 1


def test_boxes_without_a_corner_radius_agree_with_the_runtime_renderer_however_thin():
    scene = scene_of(
        (48, 36),
        ([0, 0, 48, 36], [0.95, 0.95, 0.9, 1], 0, 1),
        ([5.3, 4.7, 20.4, 12.2], [0.2, 0.4, 0.8, 0.8], 0, 0.9),
        ([10.6, 9.2, 22.3, 14.8], [0.9, 0.3, 0.2, 0.5], 0, 1),
        ([4.25, 30.3, 30.0, 0.4], [0, 0, 0, 1], 0, 1),
        ([40.35, 6.5, 0.3, 20.0], [0, 0, 0, 1], 0, 1),
    )
    for scale in (1.0, 2.0, 0.5):
        ours = draw(elements_of(scene, F64), (48, 36), scale).numpy() * 255
        theirs = premultiplied(runtime_renderer.draw(scene, scale))
        # Two renderers' rounding to 8 bits, and nothing else.
        assert np.abs(ours - theirs).max() < 4


def test_a_rounded_rectangle_is_close_to_counted_cover_and_to_the_runtime_renderer():
    box, viewport = [5.37, 4.21, 26.44, 18.83], (40, 28)
    for radius in (3.0, 6.0, 9.4):
        scene = scene_of(viewport, (box, [1, 1, 1, 1], radius, 1))
        ours = draw(elements_of(scene, F64), viewport)[..., 3].numpy()
        counted = counted_cover(box, radius, viewport)
        # An arc is drawn as its tangent, which is never less than the arc covers.
        assert (ours - counted).max() < 0.04
        assert (ours - counted).min() > -0.02
        theirs = runtime_renderer.draw(scene)[..., 3] / 255
        assert np.abs(ours - theirs).mean() < 0.004
        assert (np.abs(ours - theirs) > 16 / 255).mean() < 0.02


def test_a_corner_radius_past_half_the_shorter_side_draws_as_half_the_shorter_side():
    at_half = draw(elements(([4.3, 5.2, 20.6, 9.4], [1, 1, 1, 1], 4.7, 1)), VIEWPORT)
    past_half = draw(elements(([4.3, 5.2, 20.6, 9.4], [1, 1, 1, 1], 30.0, 1)), VIEWPORT)
    assert torch.equal(at_half, past_half)


def test_opacity_multiplies_the_fills_alpha():
    half = draw(elements(([4.3, 5.2, 20.6, 9.4], [0.2, 0.6, 0.8, 1.0], 2.0, 0.5)), VIEWPORT)
    same = draw(elements(([4.3, 5.2, 20.6, 9.4], [0.2, 0.6, 0.8, 0.5], 2.0, 1.0)), VIEWPORT)
    assert torch.allclose(half, same, atol=1e-15)
    assert half[10, 12].tolist() == pytest.approx([0.1, 0.3, 0.4, 0.5])


def test_elements_are_drawn_in_the_order_given_the_later_over_the_earlier():
    red = ([4, 4, 20, 14], [1.0, 0.0, 0.0, 1], 0, 1)
    blue = ([12, 8, 20, 14], [0.0, 0.0, 1.0, 1], 0, 1)
    assert draw(elements(red, blue), VIEWPORT)[12, 16].tolist() == [0, 0, 1, 1]
    assert draw(elements(blue, red), VIEWPORT)[12, 16].tolist() == [1, 0, 0, 1]


def test_drawing_order_is_the_scenes_tree_and_never_a_sort_of_values():
    """A parent is drawn before its children, whatever order the scene lists
    them in and whatever their numbers are."""
    style = {"text_colour": [0, 0, 0, 1], "border_colour": [0, 0, 0, 0], "border_width": 0, "corner_radius": 0, "elevation": 0, "opacity": 1, "type_size": 15, "type_weight": 400}

    def item(name, parent, box, fill, kind="panel"):
        return {"id": name, "type": kind, "parent": parent, "box": dict(zip(("x", "y", "width", "height"), box)), "style": {**style, "fill": fill}}

    listed = [
        item("child", "panel", [12, 8, 8, 6], [0, 0, 1, 1]),
        item("panel", "root", [8, 6, 20, 14], [1, 0, 0, 1]),
        item("root", None, [0, 0, 40, 28], [1, 1, 1, 1], "surface"),
    ]
    scene = scene_schema.validate({"kind": "scene", "schema_version": 1, "viewport": {"width": 40, "height": 28}, "elements": listed}, [], (40, 28))
    assert [element.id for element in scene.elements] == ["root", "panel", "child"]
    given = elements_of(scene, F64)
    assert given.box.tolist() == [[0, 0, 40, 28], [8, 6, 20, 14], [12, 8, 8, 6]]
    image = draw(given, (40, 28))
    assert image[10, 14].tolist() == [0, 0, 1, 1]
    assert image[16, 24].tolist() == [1, 0, 0, 1]
    assert image[2, 2].tolist() == [1, 1, 1, 1]


def test_scenes_in_a_batch_are_drawn_as_they_are_alone():
    first, second = elements(*OVERLAPPING[:2]), elements(*OVERLAPPING[2:])
    together = Elements(*(torch.stack([getattr(first, name), getattr(second, name)]) for name in ATTRIBUTES))
    batch = draw(together, VIEWPORT, 2.0)
    assert batch.shape == (2, 56, 80, 4)
    assert torch.equal(batch[0], draw(first, VIEWPORT, 2.0))
    assert torch.equal(batch[1], draw(second, VIEWPORT, 2.0))


def test_draw_refuses_shapes_scales_and_scenes_it_cannot_read():
    good = elements(*OVERLAPPING)
    with pytest.raises(ValueError, match=r"\(\.\.\., N, 4\)"):
        draw(Elements(good.box[:, :3], good.fill, good.corner_radius, good.opacity), VIEWPORT)
    with pytest.raises(ValueError, match=r"\(\.\.\., N\)"):
        draw(Elements(good.box, good.fill, good.corner_radius[:2], good.opacity), VIEWPORT)
    for scale in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="scale"):
            draw(good, VIEWPORT, scale)
    with pytest.raises(ValueError, match="viewport"):
        draw(good, (0, 28))
    with pytest.raises(TypeError, match="validated Scene"):
        elements_of({"kind": "scene"})


# --- gradients ---------------------------------------------------------------------


@pytest.mark.parametrize("rows", [OVERLAPPING, PAST_THE_VIEWPORT], ids=["overlapping", "past the viewport"])
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_gradients_agree_with_finite_differences_on_the_cpu_in_64_bit_floats(rows, scale):
    given = elements(*rows)
    target = draw(elements(*[([x + 0.7, y - 0.4, w + 0.9, h - 0.6], [min(c + 0.1, 0.98) for c in fill], r * 0.8, o - 0.1) for (x, y, w, h), fill, r, o in rows]), VIEWPORT, scale)
    weights = torch.rand(target.shape, generator=torch.Generator().manual_seed(4), dtype=F64) * 2 - 1
    scalars = {
        "squared difference from a target image": lambda tensors: ((draw(Elements(*tensors), VIEWPORT, scale) - target) ** 2).sum(),
        "weighted sum of the image": lambda tensors: (draw(Elements(*tensors), VIEWPORT, scale) * weights).sum(),
    }
    for name, scalar in scalars.items():
        tensors = leaves(given)
        analytic = torch.autograd.grad(scalar(tensors), tensors)
        numeric = central_differences(scalar, tensors)
        for attribute, ours, theirs in zip(ATTRIBUTES, analytic, numeric):
            assert theirs.abs().max() > 1e-3, f"{attribute} does not move the {name}"
            assert torch.allclose(ours, theirs, rtol=1e-6, atol=1e-5), f"{attribute}, {name}: {(ours - theirs).abs().max()}"


def test_an_edge_on_a_whole_number_is_counted_once():
    """Where an edge lies on a pixel boundary the gradient is one-sided. The
    area of a box still changes by its height for each unit of width, by its
    width for each unit of height, and not at all when it moves."""
    tensors = leaves(elements(([10.0, 6.0, 20.0, 12.0], [1, 1, 1, 1], 0.0, 1.0)))
    area = draw(Elements(*tensors), VIEWPORT)[..., 3].sum()
    assert area.item() == 240.0
    (box,) = torch.autograd.grad(area, tensors[0])
    assert box.tolist() == [[0.0, 0.0, 12.0, 20.0]]


def test_a_box_that_fills_the_viewport_has_finite_gradients():
    tensors = leaves(elements(([0.0, 0.0, 40.0, 28.0], [0.5, 0.5, 0.5, 1], 0.0, 1.0), ([0.0, 0.0, 40.0, 6.0], [0.2, 0.2, 0.2, 1], 0.0, 0.0)))
    found = torch.autograd.grad(draw(Elements(*tensors), VIEWPORT).sum(), tensors)
    assert all(torch.isfinite(gradient).all() for gradient in found)


def test_no_number_gives_a_gradient_that_is_not_finite():
    """Square corners, a radius at its bound, a box of no size and one of
    negative size: the places a distance or a division could give NaN."""
    rows = (
        ([4.3, 5.2, 20.6, 9.4], [0.2, 0.6, 0.8, 1.0], 0.0, 1.0),
        ([6.0, 8.0, 12.0, 8.0], [0.9, 0.6, 0.1, 0.7], 4.0, 1.0),
        ([20.0, 10.0, 0.0, 6.0], [0.9, 0.6, 0.1, 0.7], 1.0, 1.0),
        ([22.0, 12.0, -3.0, 6.0], [0.9, 0.6, 0.1, 0.7], 1.0, 1.0),
        ([30.5, 20.5, 6.0, 6.0], [0.1, 0.9, 0.1, 1.0], 3.0, 0.0),
    )
    for dtype in (F64, torch.float32):
        tensors = leaves(elements(*rows, dtype=dtype))
        image = draw(Elements(*tensors), VIEWPORT)
        assert torch.isfinite(image).all()
        for gradient in torch.autograd.grad((image**2).sum(), tensors):
            assert torch.isfinite(gradient).all()
    nothing = draw(elements(([20.0, 10.0, 0.0, 6.0], [1, 1, 1, 1], 0, 1), ([22.0, 12.0, -3.0, 6.0], [1, 1, 1, 1], 0, 1)), VIEWPORT)
    assert nothing.abs().max().item() == 0.0

    # Far from a small element in a wide image, in 32-bit floats.
    tensors = leaves(elements(([3.3, 2.4, 9.6, 7.2], [0.2, 0.6, 0.8, 1.0], 2.5, 1.0), dtype=torch.float32))
    wide = draw(Elements(*tensors), (4000, 12))
    assert torch.isfinite(wide).all()
    for gradient in torch.autograd.grad((wide**2).sum(), tensors):
        assert torch.isfinite(gradient).all() and gradient.abs().max() > 0


# --- the render loss -----------------------------------------------------------------


def render_loss(given: Elements, target: torch.Tensor, scale: float = 1.0) -> torch.Tensor:
    return (draw(given, VIEWPORT, scale) - target).abs().mean()


MOVES = {
    "position": (([4.3, 5.2, 14.6, 9.4], [0.2, 0.4, 0.8, 1], 2.2, 1.0), ([13.8, 9.7, 14.6, 9.4], [0.2, 0.4, 0.8, 1], 2.2, 1.0)),
    "size": (([8.6, 6.4, 7.2, 5.7], [0.2, 0.4, 0.8, 1], 1.6, 1.0), ([8.6, 6.4, 22.8, 15.3], [0.2, 0.4, 0.8, 1], 1.6, 1.0)),
    "corner radius": (([6.3, 4.6, 24.4, 17.7], [0.2, 0.4, 0.8, 1], 0.8, 1.0), ([6.3, 4.6, 24.4, 17.7], [0.2, 0.4, 0.8, 1], 8.6, 1.0)),
    "fill": (([6.3, 4.6, 24.4, 17.7], [0.9, 0.2, 0.3, 0.5], 3.2, 1.0), ([6.3, 4.6, 24.4, 17.7], [0.2, 0.6, 0.8, 0.95], 3.2, 1.0)),
    "opacity": (([6.3, 4.6, 24.4, 17.7], [0.2, 0.4, 0.8, 1], 3.2, 0.15), ([6.3, 4.6, 24.4, 17.7], [0.2, 0.4, 0.8, 1], 3.2, 0.9)),
}


@pytest.mark.parametrize("name", MOVES)
def test_moving_an_element_toward_its_target_lowers_the_render_loss(name):
    start, end = (elements(row) for row in MOVES[name])
    target = draw(end, VIEWPORT)
    losses = []
    for step in range(9):
        along = step / 8
        tensors = [(getattr(start, attribute) * (1 - along) + getattr(end, attribute) * along).requires_grad_(True) for attribute in ATTRIBUTES]
        loss = render_loss(Elements(*tensors), target)
        losses.append(loss.item())
        if step < 8:
            found = torch.autograd.grad(loss, tensors)
            toward = sum((gradient * (getattr(end, attribute) - getattr(start, attribute))).sum() for attribute, gradient in zip(ATTRIBUTES, found))
            assert toward.item() < 0, f"at step {step} the gradient does not point toward the target"
    assert all(later < earlier for earlier, later in zip(losses, losses[1:])), losses
    assert losses[-1] == 0.0


def test_gradient_descent_on_the_render_loss_brings_an_overlapping_shape_onto_its_target():
    """The box alone is learned here, in the target's own corner radius, fill
    and opacity. Left free, fill and opacity can lower this loss by making
    the element vanish, and a corner radius stepped past its bound stays
    there (the test below): the first is the loss's doing, the second a
    stated limit, and neither is what this test is about."""
    target_row = ([15.3, 9.6, 14.2, 10.4], [0.2, 0.5, 0.8, 1.0], 3.0, 1.0)
    target = draw(elements(target_row), VIEWPORT)
    box, fill, radius, opacity = leaves(elements(([8.4, 5.1, 11.5, 13.2], [0.2, 0.5, 0.8, 1.0], 3.0, 1.0)))
    first = render_loss(Elements(box, fill, radius, opacity), target).item()
    optimiser = torch.optim.Adam([box], lr=0.05)
    # An absolute difference pulls as hard near the target as far from it, so
    # the step is made smaller for the last part of the way.
    schedule = torch.optim.lr_scheduler.StepLR(optimiser, step_size=400, gamma=0.1)
    for _ in range(1200):
        optimiser.zero_grad()
        render_loss(Elements(box, fill, radius, opacity), target).backward()
        optimiser.step()
        schedule.step()
    assert render_loss(Elements(box, fill, radius, opacity), target).item() < first / 20
    assert torch.allclose(box, torch.tensor([target_row[0]], dtype=F64), atol=0.5)


def test_a_corner_radius_past_its_bound_has_no_gradient_and_its_box_takes_it():
    """Past half the shorter side the radius drawn is the box's, not the
    number given: the number is in the computation and its gradient is zero,
    so a prediction must be kept inside the bound to be learned."""
    target = draw(elements(([6.3, 4.6, 24.4, 9.7], [0.2, 0.4, 0.8, 1], 1.5, 1.0)), VIEWPORT)
    inside = leaves(elements(([6.3, 4.6, 24.4, 9.7], [0.2, 0.4, 0.8, 1], 4.2, 1.0)))
    past = leaves(elements(([6.3, 4.6, 24.4, 9.7], [0.2, 0.4, 0.8, 1], 7.5, 1.0)))
    assert state(render_loss(Elements(*inside), target), inside[2]) == "non-zero"
    assert state(render_loss(Elements(*past), target), past[2]) == "zero"
    assert state(render_loss(Elements(*past), target), past[0]) == "non-zero"


# --- zero gradients --------------------------------------------------------------------


def state(scalar: torch.Tensor, number: torch.Tensor) -> str:
    """`disconnected` when the number is no part of the computation; else `zero` or `non-zero`."""
    (found,) = torch.autograd.grad(scalar, number, allow_unused=True, retain_graph=True)
    if found is None:
        return "disconnected"
    return "zero" if found.abs().max().item() <= 1e-12 else "non-zero"


def test_position_has_no_gradient_without_overlap_and_the_computation_is_still_connected():
    """A square-cornered element that does not touch its target: moving it
    changes which pixels differ and not how much."""
    target = draw(elements(([26.7, 14.3, 9.6, 8.27], [0.2, 0.4, 0.8, 1], 0.0, 0.9)), VIEWPORT)
    x, y, width, height = (torch.tensor(value, dtype=F64, requires_grad=True) for value in (5.3, 4.45, 9.6, 8.27))
    fill = torch.tensor([[0.2, 0.4, 0.8, 1.0]], dtype=F64, requires_grad=True)
    radius = torch.zeros(1, dtype=F64)
    opacity = torch.tensor([0.9], dtype=F64, requires_grad=True)

    def given(left: torch.Tensor) -> Elements:
        return Elements(torch.stack([left, y, width, height])[None, :], fill, radius, opacity)

    loss = render_loss(given(x), target)
    assert state(loss, x) == "zero"
    assert state(loss, y) == "zero"
    assert {state(loss, number) for number in (width, height, fill, opacity)} == {"non-zero"}
    # Zero, and yet the image depends on x: a weighted sum of it has a gradient.
    weights = torch.rand(target.shape, generator=torch.Generator().manual_seed(1), dtype=F64)
    assert state((draw(given(x), VIEWPORT) * weights).sum(), x) == "non-zero"
    # The same loss with x cut out of the computation is something else.
    assert state(render_loss(given(x.detach()), target), x) == "disconnected"


def test_an_element_under_an_opaque_one_and_an_element_of_no_opacity_have_zero_gradients():
    target = draw(elements(*OVERLAPPING[:2]), VIEWPORT)
    covered = leaves(elements(([12.4, 9.3, 14.6, 10.2], [0.9, 0.3, 0.2, 0.8], 2.2, 0.9)))
    cover = elements(([6.2, 4.1, 30.5, 20.6], [0.2, 0.4, 0.8, 1.0], 0.0, 1.0))
    both = Elements(*(torch.cat([mine, getattr(cover, attribute)]) for mine, attribute in zip(covered, ATTRIBUTES)))
    loss = render_loss(both, target)
    assert [state(loss, number) for number in covered] == ["zero", "zero", "zero", "zero"]

    unseen = leaves(elements(([8.4, 7.3, 20.6, 14.2], [0.9, 0.3, 0.2, 0.8], 3.2, 0.0)))
    loss = render_loss(Elements(*unseen), target)
    assert [state(loss, number) for number in unseen] == ["zero", "zero", "zero", "non-zero"]


# --- the Apple GPU path ------------------------------------------------------------------


@needs_apple_gpu
@pytest.mark.parametrize("rows", [OVERLAPPING, PAST_THE_VIEWPORT], ids=["overlapping", "past the viewport"])
def test_the_forward_pass_on_the_apple_gpu_path_agrees_with_the_cpu(rows):
    for scale in (1.0, 2.0):
        with torch.no_grad():
            on_gpu = draw(elements(*rows, dtype=torch.float32, device="mps"), VIEWPORT, scale)
            on_cpu = draw(elements(*rows), VIEWPORT, scale)
        assert on_gpu.device.type == "mps" and on_gpu.dtype == torch.float32
        assert (on_gpu.cpu().double() - on_cpu).abs().max().item() < 1e-4
        assert np.abs(to_rgba8(on_gpu).astype(int) - to_rgba8(on_cpu).astype(int)).max() <= 1


@needs_apple_gpu
@pytest.mark.parametrize("rows", [OVERLAPPING, PAST_THE_VIEWPORT], ids=["overlapping", "past the viewport"])
def test_the_backward_pass_on_the_apple_gpu_path_agrees_with_the_cpu(rows):
    target = draw(elements(*[([x + 0.7, y - 0.4, w + 0.9, h - 0.6], fill, r * 0.8, o - 0.1) for (x, y, w, h), fill, r, o in rows]), VIEWPORT)
    on_cpu = leaves(elements(*rows))
    wanted = torch.autograd.grad(((draw(Elements(*on_cpu), VIEWPORT) - target) ** 2).sum(), on_cpu)
    on_gpu = leaves(elements(*rows, dtype=torch.float32, device="mps"))
    found = torch.autograd.grad(((draw(Elements(*on_gpu), VIEWPORT) - target.float().to("mps")) ** 2).sum(), on_gpu)
    for attribute, ours, theirs in zip(ATTRIBUTES, found, wanted):
        assert ours.device.type == "mps"
        assert torch.allclose(ours.cpu().double(), theirs, rtol=2e-3, atol=2e-3), attribute


# --- what the module says of itself -----------------------------------------------------------


def test_the_starting_support_matrix_names_every_primitive_and_claims_only_stage_one():
    rows = {row["primitive"]: row for row in training_renderer.SUPPORT}
    assert list(rows) == ["rounded rectangle with fill and opacity", "border", "text", "shadow"]
    drawn = rows["rounded rectangle with fill and opacity"]
    assert drawn["drawn"] and drawn["gradients"] == ("x", "y", "width", "height", "corner_radius", "fill", "opacity")
    assert drawn["not_differentiable"] == ("drawing order",)
    for name in ("border", "text", "shadow"):
        assert not rows[name]["drawn"] and rows[name]["gradients"] == ()
    assert training_renderer.NOT_DRAWN == ("border", "text", "shadow")
