"""The training renderer: a scene's numbers as tensors, drawn so that gradients reach them.

It is PyTorch and nothing else, and it is built in stages. This is stage 1:
the rounded rectangle with fill and opacity. `SUPPORT` says, for every
primitive of the scene schema, whether it is drawn and which attributes
receive gradients; `core-ultra renderer check` verifies each of those cells
and writes the support matrix. A stage is used in training only after its
checks pass.

What is drawn, per element, in the order the elements are given:

- the box as a rounded rectangle, filled with `fill`, its alpha multiplied by
  `opacity`.

Borders, text and shadows are not drawn (`NOT_DRAWN`). An image from this
renderer is therefore the runtime renderer's image only for a scene without
them, and `renderer check` measures how closely.

Drawing order. Elements are composited one over the other in the order they
are given, which `elements_of` takes from the scene's tree: a parent before
its children, siblings as the scene lists them. Nothing here sorts by a
predicted value, and drawing order receives no gradient.

Coverage. A pixel is a unit square. How much of it an element covers is the
lesser of two areas, neither ever less than the true one:

- the area of the pixel inside the element's box, corners ignored, which is
  exact for any box without a corner radius, however thin;
- at a corner, the area of the pixel on the near side of the straight line
  that touches the corner's arc at the point nearest the pixel's centre.

So an arc is drawn as its tangent. `renderer check` measures what that costs
against exact cover.

Compositing is source over, on transparent black, with no colour management:
channel values are blended as given, as the runtime renderer blends them.

Gradients. Coverage is piecewise smooth. A pixel wholly inside or wholly
outside an element gives no gradient to that element's position, size or
corner radius; only the pixels its outline crosses do. Where an edge lies
exactly on a pixel boundary the gradient is taken from the pixel the edge is
leaving, once, so that an edge on a whole number is not counted twice.

Values. `draw` validates nothing that carries a gradient, because a training
step cannot stop to refuse a prediction. A corner radius is used within 0 to
half the box's shorter side, as scene validation bounds it, and past that
bound it receives no gradient. A box with a width or height at or below zero
draws nothing. Colour channels and opacity are used as given; the caller
keeps them in 0 to 1. `LIMITS` lists what a caller must know.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
from torch import Tensor

from core_ultra.scene import Scene

STAGE = 1

# The starting support matrix (spec, "Training renderer"). `gradients` lists
# the attributes gradients reach; `not_differentiable` those they never will.
# Whether a cell is verified is not stated here: `renderer check` measures it.
SUPPORT: tuple[dict[str, object], ...] = (
    {
        "primitive": "rounded rectangle with fill and opacity",
        "stage": 1,
        "drawn": True,
        "gradients": ("x", "y", "width", "height", "corner_radius", "fill", "opacity"),
        "not_differentiable": ("drawing order",),
    },
    {
        "primitive": "border",
        "stage": 2,
        "drawn": False,
        "gradients": (),
        "not_differentiable": (),
    },
    {
        "primitive": "text",
        "stage": 2,
        "drawn": False,
        "gradients": (),
        "not_differentiable": ("font choice", "shaping", "line wrapping"),
    },
    {
        "primitive": "shadow",
        "stage": 3,
        "drawn": False,
        "gradients": (),
        "not_differentiable": (),
    },
)
NOT_DRAWN = tuple(str(row["primitive"]) for row in SUPPORT if not row["drawn"])

# What a caller must know before taking a loss through `draw`. Each is the
# renderer's true behaviour, covered by a test, and not a fault to repair.
LIMITS = (
    "An arc is drawn as its tangent, which never covers less than the arc: a corner of radius under about two "
    "pixels is drawn too full on its own few pixels, and a rounded element's whole cover changes a little with "
    "where its corners fall among the pixels.",
    "Position, size and corner radius receive a gradient only from the pixels the outline crosses. An element "
    "that shares no differing pixel with its target has no gradient in position.",
    "A corner radius past half the box's shorter side is drawn as that half and receives no gradient; a "
    "prediction is kept inside the bound to be learned.",
    "A box with a width or height at or below zero draws nothing and receives no gradient.",
    "Colour channels and opacity are used as given, in or out of 0 to 1.",
    "Drawing order is the order the elements are given in and receives no gradient.",
)


@dataclass(frozen=True)
class Elements:
    """The numbers of a scene's elements that this stage draws, in drawing order.

    N elements, with any leading batch dimensions:

    - `box`: (..., N, 4), x, y, width and height in viewport units;
    - `fill`: (..., N, 4), red, green, blue and alpha in 0 to 1, alpha not
      premultiplied;
    - `corner_radius`: (..., N), in viewport units;
    - `opacity`: (..., N), in 0 to 1.
    """

    box: Tensor
    fill: Tensor
    corner_radius: Tensor
    opacity: Tensor


def elements_of(scene: Scene, dtype: torch.dtype = torch.float32, device: torch.device | str = "cpu") -> Elements:
    """A validated scene's elements as tensors, in the scene's drawing order."""
    if not isinstance(scene, Scene):
        raise TypeError("elements_of reads a validated Scene; pass the candidate through scene.validate")

    def tensor(rows: list) -> Tensor:
        return torch.tensor(rows, dtype=dtype, device=device)

    elements = scene.elements
    return Elements(
        box=tensor([[element.x, element.y, element.width, element.height] for element in elements]),
        fill=tensor([list(element.style.fill) for element in elements]),
        corner_radius=tensor([element.style.corner_radius for element in elements]),
        opacity=tensor([element.style.opacity for element in elements]),
    )


def draw(elements: Elements, viewport: tuple[float, float], scale: float = 1.0) -> Tensor:
    """Draw the elements. Returns RGBA pixels, shape (..., height, width, 4).

    The colour channels are premultiplied by alpha, which is what a loss over
    pixels should compare; `to_rgba8` gives the runtime renderer's form.
    `viewport` is the scene's width and height in viewport units and `scale`
    is pixels per viewport unit: the image has the size the runtime renderer
    gives the same scene. The result has the dtype and device of
    `elements.box`.
    """
    box, fill, radius, opacity = elements.box, elements.fill, elements.corner_radius, elements.opacity
    if box.shape[-1] != 4 or fill.shape != box.shape or radius.shape != box.shape[:-1] or opacity.shape != box.shape[:-1]:
        raise ValueError(
            "box and fill are (..., N, 4) and corner_radius and opacity are (..., N); "
            f"got {tuple(box.shape)}, {tuple(fill.shape)}, {tuple(radius.shape)}, {tuple(opacity.shape)}"
        )
    if not (isinstance(scale, (int, float)) and math.isfinite(scale) and scale > 0):
        raise ValueError(f"scale is {scale!r}; it is a finite number above zero")
    viewport_width, viewport_height = viewport
    if not all(isinstance(side, (int, float)) and math.isfinite(side) and side > 0 for side in (viewport_width, viewport_height)):
        raise ValueError(f"viewport is {viewport!r}; its width and height are finite numbers above zero")

    width = math.ceil(viewport_width * scale - 1e-9)
    height = math.ceil(viewport_height * scale - 1e-9)
    # Pixel centres, in pixels: (height, 1) and (1, width).
    centre_y = (torch.arange(height, dtype=box.dtype, device=box.device) + 0.5)[:, None]
    centre_x = (torch.arange(width, dtype=box.dtype, device=box.device) + 0.5)[None, :]

    image = torch.zeros(*box.shape[:-2], height, width, 4, dtype=box.dtype, device=box.device)
    for index in range(box.shape[-2]):
        # One element's numbers, each shaped (..., 1, 1) to meet the pixel grid.
        left, top, wide, high = (box[..., index, part, None, None] * scale for part in range(4))
        covered = _coverage(centre_x, centre_y, left, top, wide, high, radius[..., index, None, None] * scale)
        alpha = (covered * fill[..., index, 3, None, None] * opacity[..., index, None, None])[..., None]
        colour = fill[..., index, None, None, :3]
        source = torch.cat([colour * alpha, alpha], dim=-1)
        image = source + image * (1 - alpha)
    return image


def to_rgba8(image: Tensor) -> np.ndarray:
    """An image from `draw` in the runtime renderer's form: 8 bits a channel,
    colour not premultiplied. It carries no gradient."""
    # To the CPU first: the Apple GPU holds no 64-bit floats.
    image = image.detach().cpu().double()
    alpha = image[..., 3:4]
    colour = torch.where(alpha > 0, image[..., :3] / torch.where(alpha > 0, alpha, torch.ones_like(alpha)), torch.zeros_like(alpha))
    straight = torch.cat([colour, alpha], dim=-1).clamp(0, 1)
    return (straight * 255).round().to(torch.uint8).numpy()


def _coverage(centre_x: Tensor, centre_y: Tensor, left: Tensor, top: Tensor, wide: Tensor, high: Tensor, radius: Tensor) -> Tensor:
    """How much of each pixel the rounded rectangle covers, 0 to 1. Everything is in pixels."""
    # The box, corners ignored: along each axis, the pixel's part right of the
    # near edge plus its part left of the far edge, less the whole pixel.
    across = (_ramp(centre_x + 0.5 - left) + _ramp(left + wide - centre_x + 0.5) - 1).clamp(min=0)
    down = (_ramp(centre_y + 0.5 - top) + _ramp(top + high - centre_y + 0.5) - 1).clamp(min=0)
    box = across * down

    # A corner: where the pixel's centre is past the centre of the corner's
    # circle on both axes, by (past_x, past_y).
    half_wide, half_high = wide / 2, high / 2
    radius = torch.minimum(radius.clamp(min=0), torch.minimum(half_wide, half_high).clamp(min=0))
    past_x = ((centre_x - (left + half_wide)).abs() - half_wide + radius).clamp(min=0)
    past_y = ((centre_y - (top + half_high)).abs() - half_high + radius).clamp(min=0)
    corner = (past_x > 0) & (past_y > 0)
    from_centre = _length(past_x, past_y)
    along = torch.where(corner, from_centre, torch.ones_like(from_centre))
    arc = _half_plane(radius - from_centre, past_x / along, past_y / along)

    # Both are never less than the true cover, so the lesser is the closer.
    return torch.where(corner & (arc < box), arc, box)


def _half_plane(inside: Tensor, normal_x: Tensor, normal_y: Tensor) -> Tensor:
    """The area of a unit pixel on the near side of a straight line.

    `inside` is how far the pixel's centre is on the near side of the line and
    (normal_x, normal_y) is the line's unit normal, neither part negative.
    Exact: a ramp across the middle, a parabola at each end where the line
    cuts only a corner of the pixel.
    """
    greater, lesser = torch.maximum(normal_x, normal_y), torch.minimum(normal_x, normal_y)
    # From the pixel's far corner, the line is `reach` in; the whole pixel is
    # `greater + lesser` across along the normal.
    reach = (inside + (greater + lesser) / 2).clamp(min=0)
    left_over = (greater + lesser - reach).clamp(min=0)
    twice_area = (2 * greater * lesser).clamp(min=1e-12)
    middle = (reach - lesser / 2) / greater.clamp(min=0.5)
    return torch.where(
        reach <= lesser,
        reach * reach / twice_area,
        torch.where(reach >= greater, 1 - left_over * left_over / twice_area, middle),
    ).clamp(0, 1)


def _ramp(value: Tensor) -> Tensor:
    """`value` kept in 0 to 1. The gradient passes where 0 < value <= 1: of two
    pixels that meet at an edge, only the one the edge is leaving gives one."""
    return torch.where((value > 0) & (value <= 1), value, value.detach().clamp(0, 1))


def _length(x: Tensor, y: Tensor) -> Tensor:
    """The length of (x, y), with a gradient of zero, never NaN, at the origin."""
    squared = x * x + y * y
    positive = squared > 0
    return torch.where(positive, torch.sqrt(torch.where(positive, squared, torch.ones_like(squared))), torch.zeros_like(squared))
