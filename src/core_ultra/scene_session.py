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

Projection is separate and asked for by name. `frame_from_scene(...,
project=True)` first moves each out-of-bounds value onto its bound, then
validates what results. Every value moved is on the frame, in the session's
report and in the log. A, Reference is never projected.

The session keeps count. `session.report` says how many candidate scenes it
has seen, which were invalid and why, and which values were projected. Invalid
scenes and projected values are counted apart: a projected scene that then
validates is not an invalid one. Both are also sent to the
`core_ultra.scene_session` logger, an invalid scene as a warning and a
projected value as information.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from core_ultra import documents_adapter, runtime_renderer, scene as scene_schema
from core_ultra.documents_adapter import BoundElement
from core_ultra.kernel import ApplicationState
from core_ultra.scene import Problem, Projection, Scene, SceneInvalid
from core_ultra.typography import TextNotDrawable

__all__ = [
    "Conditioning",
    "Frame",
    "InvalidScene",
    "ModeUnavailable",
    "Problem",
    "ProjectedScene",
    "Projection",
    "RenderingMode",
    "Scene",
    "SceneInvalid",
    "SceneSession",
    "SessionReport",
    "TextNotDrawable",
]

_log = logging.getLogger(__name__)
SUPPLIED = "supplied scene"


class RenderingMode(Enum):
    A_REFERENCE = "A, Reference"
    D_NEURAL_SCENE = "D, Neural Scene"


class ModeUnavailable(Exception):
    """The rendering mode exists but cannot produce a scene yet."""


@dataclass(frozen=True)
class Conditioning:
    """What the scene writer is told besides application state.

    The viewport size, and the visual preset by its name in the generator
    configuration (`core_ultra.design`); without a name it is the
    configuration's default preset. The design condition joins them when the
    generator is built.
    """

    viewport_width: float
    viewport_height: float
    visual_preset: str | None = None

    def __post_init__(self) -> None:
        for name in ("viewport_width", "viewport_height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} is {value!r}; it is a finite number above zero")
        if self.visual_preset is not None and not isinstance(self.visual_preset, str):
            raise ValueError(f"visual_preset is {self.visual_preset!r}; it is a preset's name")

    @property
    def viewport(self) -> tuple[float, float]:
        return (self.viewport_width, self.viewport_height)


@dataclass(frozen=True)
class Frame:
    """One drawn interface frame.

    `bound_elements` is what the application supplied; `scene` is the validated
    scene that carries them; `image` and `hit_test` were both read from `scene`.
    `hit_test` takes a point in viewport units, whatever scale the image was
    drawn at. `projections` lists every value that was moved into its bounds
    before validation; it is empty unless projection was asked for.
    """

    bound_elements: tuple[BoundElement, ...]
    scene: Scene
    image: np.ndarray
    scale: float
    hit_test: Callable[[float, float], BoundElement | None]
    projections: tuple[Projection, ...] = ()


@dataclass(frozen=True)
class InvalidScene:
    """A candidate scene that was refused. `scene` is its number among the
    candidates this session has seen, starting at 1; `source` is the rendering
    mode that wrote it, or "supplied scene"."""

    scene: int
    source: str
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class ProjectedScene:
    """A candidate scene in which values were moved into their bounds."""

    scene: int
    source: str
    projections: tuple[Projection, ...]


@dataclass(frozen=True)
class SessionReport:
    """What a scene session has seen so far."""

    scenes: int
    invalid_scenes: tuple[InvalidScene, ...]
    projected_scenes: tuple[ProjectedScene, ...]

    @property
    def valid(self) -> int:
        return self.scenes - self.invalid

    @property
    def invalid(self) -> int:
        return len(self.invalid_scenes)

    @property
    def invalid_by_code(self) -> Mapping[str, int]:
        """For each problem code, the number of scenes that had it."""
        return dict(Counter(code for entry in self.invalid_scenes for code in sorted({p.code for p in entry.problems})))

    @property
    def projections(self) -> int:
        """The number of values projected, over all scenes."""
        return sum(len(entry.projections) for entry in self.projected_scenes)

    @property
    def projections_by_field(self) -> Mapping[str, int]:
        return dict(Counter(p.field for entry in self.projected_scenes for p in entry.projections))

    def summary(self) -> str:
        lines = [
            f"scenes: {self.scenes}",
            f"valid: {self.valid}",
            f"invalid: {self.invalid}",
            *[f"  {code}: {count}" for code, count in sorted(self.invalid_by_code.items())],
            f"scenes with projected values: {len(self.projected_scenes)}",
            f"values projected: {self.projections}",
            *[f"  {name}: {count}" for name, count in sorted(self.projections_by_field.items())],
        ]
        return "\n".join(lines)


class SceneSession:
    def __init__(self) -> None:
        self._scenes = 0
        self._invalid: list[InvalidScene] = []
        self._projected: list[ProjectedScene] = []

    @property
    def report(self) -> SessionReport:
        """The counts and the log so far. A report does not change after it is taken."""
        return SessionReport(self._scenes, tuple(self._invalid), tuple(self._projected))

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
            from core_ultra import design, reference_layout

            preset = design.load().preset(conditioning.visual_preset)
            candidate = reference_layout.write_scene(bound_elements, conditioning.viewport, preset)
        else:
            raise ModeUnavailable(f"{mode.value} has no scene model yet")
        return self._frame(bound_elements, conditioning, candidate, scale, mode.value, project=False)

    def frame_from_scene(
        self,
        state: ApplicationState,
        conditioning: Conditioning,
        candidate: Any,
        *,
        scale: float = 1.0,
        project: bool = False,
    ) -> Frame:
        """The frame for this state drawn from a scene written elsewhere.

        `candidate` is scene JSON data: a stored scene, a hand-written one, or
        a scene model's output. It is validated against this state exactly as a
        rendering mode's own scene is, and is never modified.

        With `project=True`, values outside their bounds are first moved onto
        them (`core_ultra.scene.project` says which), and each one is recorded
        on the frame and in the session's report.
        """
        bound_elements = documents_adapter.describe(state)
        return self._frame(bound_elements, conditioning, candidate, scale, SUPPLIED, project=project)

    def _frame(
        self,
        bound_elements: tuple[BoundElement, ...],
        conditioning: Conditioning,
        candidate: Any,
        scale: float,
        source: str,
        *,
        project: bool,
    ) -> Frame:
        self._scenes += 1
        number = self._scenes
        projections: tuple[Projection, ...] = ()
        if project:
            candidate, projections = scene_schema.project(candidate, conditioning.viewport)
            if projections:
                self._projected.append(ProjectedScene(number, source, projections))
                for projection in projections:
                    _log.info("scene %d (%s): %s", number, source, projection)
        try:
            scene = scene_schema.validate(candidate, bound_elements, conditioning.viewport)
        except SceneInvalid as refused:
            self._invalid.append(InvalidScene(number, source, refused.problems))
            _log.warning("scene %d (%s) is invalid and was not drawn: %s", number, source, refused)
            raise
        image = runtime_renderer.draw(scene, scale)
        image.setflags(write=False)
        return Frame(
            bound_elements=bound_elements,
            scene=scene,
            image=image,
            scale=scale,
            hit_test=lambda x, y: runtime_renderer.hit_test(scene, x, y),
            projections=projections,
        )
