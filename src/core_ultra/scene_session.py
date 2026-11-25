"""The scene session: application state in; validated scene, image and hit test out.

This is the single interface over the kernel's state, the documents app
adapter, the scene writer of a rendering mode, scene validation and the runtime
renderer, and the primary test seam. It runs without a window.

    session = SceneSession()
    frame = session.frame(kernel.state(), Conditioning(800, 480), RenderingMode.A_REFERENCE)
    frame.scene        # the validated scene
    frame.image        # RGBA pixels drawn by the runtime renderer
    frame.hit_test(x, y)   # the bound element at a point, or None

A scene that fails validation is never drawn: `SceneInvalid` is raised with
every problem listed, and nothing is repaired.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from core_ultra import documents_adapter, runtime_renderer, scene as scene_schema
from core_ultra.documents_adapter import BoundElement
from core_ultra.kernel import ApplicationState
from core_ultra.scene import Problem, Scene, SceneInvalid
from core_ultra.typography import TextNotDrawable

__all__ = [
    "Conditioning",
    "Frame",
    "ModeUnavailable",
    "Problem",
    "RenderingMode",
    "Scene",
    "SceneInvalid",
    "SceneSession",
    "TextNotDrawable",
]


class RenderingMode(Enum):
    A_REFERENCE = "A, Reference"
    D_NEURAL_SCENE = "D, Neural Scene"


class ModeUnavailable(Exception):
    """The rendering mode exists but cannot produce a scene yet."""


@dataclass(frozen=True)
class Conditioning:
    """What the scene writer is told besides application state.

    Only the viewport size so far. The design condition and the visual preset
    join it when the generator is built.
    """

    viewport_width: float
    viewport_height: float

    def __post_init__(self) -> None:
        for name in ("viewport_width", "viewport_height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} is {value!r}; it is a finite number above zero")

    @property
    def viewport(self) -> tuple[float, float]:
        return (self.viewport_width, self.viewport_height)


@dataclass(frozen=True)
class Frame:
    """One drawn interface frame.

    `bound_elements` is what the application supplied; `scene` is the validated
    scene that carries them; `image` and `hit_test` were both read from `scene`.
    `hit_test` takes a point in viewport units, whatever scale the image was
    drawn at.
    """

    bound_elements: tuple[BoundElement, ...]
    scene: Scene
    image: np.ndarray
    scale: float
    hit_test: Callable[[float, float], BoundElement | None]


class SceneSession:
    def frame(
        self,
        state: ApplicationState,
        conditioning: Conditioning,
        mode: RenderingMode | str,
        *,
        scale: float = 1.0,
    ) -> Frame:
        """The frame for this state in a rendering mode."""
        mode = RenderingMode(mode)
        bound_elements = documents_adapter.describe(state)
        if mode is RenderingMode.A_REFERENCE:
            # Imported here so that no other rendering mode loads the teacher.
            from core_ultra import reference_layout

            candidate = reference_layout.write_scene(bound_elements, conditioning.viewport)
        else:
            raise ModeUnavailable(f"{mode.value} has no scene model yet")
        return self._frame(bound_elements, conditioning, candidate, scale)

    def frame_from_scene(
        self,
        state: ApplicationState,
        conditioning: Conditioning,
        candidate: Any,
        *,
        scale: float = 1.0,
    ) -> Frame:
        """The frame for this state drawn from a scene written elsewhere.

        `candidate` is scene JSON data: a stored scene, a hand-written one, or
        a scene model's output. It is validated against this state exactly as a
        rendering mode's own scene is.
        """
        return self._frame(documents_adapter.describe(state), conditioning, candidate, scale)

    def _frame(
        self,
        bound_elements: tuple[BoundElement, ...],
        conditioning: Conditioning,
        candidate: Any,
        scale: float,
    ) -> Frame:
        scene = scene_schema.validate(candidate, bound_elements, conditioning.viewport)
        image = runtime_renderer.draw(scene, scale)
        image.setflags(write=False)
        return Frame(
            bound_elements=bound_elements,
            scene=scene,
            image=image,
            scale=scale,
            hit_test=lambda x, y: runtime_renderer.hit_test(scene, x, y),
        )
