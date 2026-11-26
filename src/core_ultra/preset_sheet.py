"""One application state drawn in A, Reference in every visual preset, as
images a person can compare.

The state is fixed: three documents, the second opened, edited and saved, so
that the list, the editor, the toolbar and the notification are all present.
The first row is hovered, the sort button pressed and the filter field
focused, and the application has disabled Save, so all five states are in the
picture.

`write` saves one PNG per preset, one sheet with every preset side by side and
a manifest with the SHA-256 of each image, of each scene and of the design
they were drawn from. A file that exists with other contents is never
overwritten.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from core_ultra import design as design_source
from core_ultra import runtime_renderer, scene as scene_schema, typography
from core_ultra.kernel import ApplicationState, Kernel
from core_ultra.scene_session import Conditioning, Frame, RenderingMode, SceneSession

VIEWPORT = (960, 540)
TITLES = ("Quarterly plan", "Café résumé — août", "Żółć gęślą jaźń")
BODY = "Première ligne: déjà vu, garçon.\nZweite Zeile: Größe, Übermut, Äpfel.\n\nCuarta línea: ¿mañana? ¡Sí!"
INTERACTION = {"document:1": "hover", "toolbar.sort": "pressed", "toolbar.filter": "focused"}
STATE_DESCRIPTION = (
    "Three documents; the second opened, edited and saved. The first row hovered, the sort button "
    "pressed, the filter field focused; Save disabled by the application."
)
SHEET_NAME = "all-presets.png"
MANIFEST_NAME = "manifest.json"

_COLUMNS = 2
_GUTTER = 24.0
_CAPTION = 56.0
_PAPER = (1.0, 1.0, 1.0, 1.0)
_INK = (0.1, 0.1, 0.12, 1.0)
_GREY = (0.38, 0.39, 0.43, 1.0)


def demonstration_state() -> ApplicationState:
    """The state every preset is drawn in, reached by real kernel commands."""
    kernel = Kernel()
    try:
        for title in TITLES:
            kernel.create_document(title)
        kernel.open_document(2)
        kernel.edit(BODY)
        kernel.save()
        return kernel.state().with_interaction(INTERACTION)
    finally:
        kernel.close()


def frames(scale: float = 2.0) -> dict[str, Frame]:
    """The demonstration state in every visual preset, by preset name."""
    session = SceneSession()
    state = demonstration_state()
    return {
        name: session.frame(state, Conditioning(*VIEWPORT, visual_preset=name), RenderingMode.A_REFERENCE, scale=scale)
        for name in design_source.load().presets
    }


def sheet(images: dict[str, np.ndarray], scale: float) -> np.ndarray:
    """Every preset's image on one sheet, each under its title and summary."""
    typography.ensure_gui()
    design = design_source.load()
    width, height = VIEWPORT
    rows = math.ceil(len(images) / _COLUMNS)
    sheet_width = _GUTTER + _COLUMNS * (width + _GUTTER)
    sheet_height = _GUTTER + rows * (_CAPTION + height + _GUTTER)
    canvas = QImage(math.ceil(sheet_width * scale), math.ceil(sheet_height * scale), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor.fromRgbF(*_PAPER))

    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for index, (name, image) in enumerate(images.items()):
            preset = design.preset(name)
            x = _GUTTER + (index % _COLUMNS) * (width + _GUTTER)
            y = _GUTTER + (index // _COLUMNS) * (_CAPTION + height + _GUTTER)
            painter.resetTransform()
            painter.scale(scale, scale)
            _text(painter, f"{preset.title} ({name})", x, y, 20.0, 600.0, _INK)
            _text(painter, preset.summary, x, y + 28, 13.0, 400.0, _GREY)
            pixels = np.ascontiguousarray(image)
            picture = QImage(pixels.data, image.shape[1], image.shape[0], 4 * image.shape[1], QImage.Format.Format_RGBA8888)
            painter.resetTransform()
            painter.drawImage(QRectF(x * scale, (y + _CAPTION) * scale, image.shape[1], image.shape[0]), picture)
    finally:
        painter.end()

    canvas = canvas.convertToFormat(QImage.Format.Format_RGBA8888)
    data = np.frombuffer(canvas.constBits(), dtype=np.uint8)
    return data.reshape(canvas.height(), canvas.bytesPerLine() // 4, 4)[:, : canvas.width()].copy()


def write(out: str | Path, scale: float = 2.0) -> dict[str, Any]:
    """Draw every preset and save the images, the sheet and the manifest under
    `out`. Returns the manifest. Raises `FileExistsError` for a file that
    exists with other contents; nothing is written in that case."""
    out = Path(out)
    design = design_source.load()
    drawn = frames(scale)
    files = {f"{name}.png": runtime_renderer.png_bytes(frame.image) for name, frame in drawn.items()}
    files[SHEET_NAME] = runtime_renderer.png_bytes(sheet({name: frame.image for name, frame in drawn.items()}, scale))

    manifest = {
        "kind": "preset-images",
        "design": {"name": design.name, "version": design.version, "sha256": _sha256(design_source.DEFAULT_CONFIG.read_bytes())},
        "font": {"family": typography.FONT_FAMILY, "sha256": _sha256(typography.FONT_FILE.read_bytes())},
        "rendering_mode": RenderingMode.A_REFERENCE.value,
        "state": STATE_DESCRIPTION,
        "viewport": {"width": VIEWPORT[0], "height": VIEWPORT[1]},
        "pixels_per_viewport_unit": scale,
        "images": [
            {
                "visual_preset": name,
                "file": f"{name}.png",
                "sha256": _sha256(files[f"{name}.png"]),
                "scene_sha256": _sha256(scene_schema.dumps(frame.scene).encode()),
            }
            for name, frame in drawn.items()
        ],
        "sheet": {"file": SHEET_NAME, "sha256": _sha256(files[SHEET_NAME])},
    }
    files[MANIFEST_NAME] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()

    for name, data in files.items():
        path = out / name
        if path.exists() and path.read_bytes() != data:
            raise FileExistsError(str(path))
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    return manifest


def _text(painter: QPainter, text: str, x: float, y: float, size: float, weight: float, colour: tuple[float, ...]) -> None:
    factor = typography.reference_scale(size)
    painter.save()
    painter.translate(x, y)
    painter.scale(factor, factor)
    painter.fillPath(typography.shape(text, weight).outline, QColor.fromRgbF(*colour))
    painter.restore()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = ["frames", "demonstration_state", "sheet", "write", "VIEWPORT", "SHEET_NAME", "MANIFEST_NAME"]
