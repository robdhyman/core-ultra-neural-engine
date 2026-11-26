"""How far an exported SVG is from the runtime renderer's image, measured.

For every record of a written dataset, the true scene is exported as SVG, the
SVG is rasterised by Qt's SVG module (`QSvgRenderer`, part of
PySide6-Essentials) at the record's pixels per viewport unit, and the result
is compared with the runtime renderer's image of the same scene, pixel by
pixel. Each scene is compared twice: whole, and with every text emptied in
both, which separates what the shapes and shadows differ by from what the text
differs by.

Three numbers for each comparison, over 8-bit RGBA:

- `mean_absolute_difference`: the mean of |a - b| over every channel of every
  pixel, in levels of 255;
- `share_of_pixels_over_16`: the share of pixels in which some channel differs
  by more than 16 levels;
- `largest_difference`: the largest |a - b| of any channel of any pixel.

The numbers say how Qt's SVG module draws the export. Another rasteriser, or a
design tool, draws it differently again; nothing here measures those.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from core_ultra import runtime_renderer, scene as scene_schema, scene_export
from core_ultra.scene import Scene, SceneInvalid
from core_ultra.scene_export import NotExportable, SourceError
from core_ultra.typography import TextNotDrawable

KIND = "scene-export-comparison"
SCHEMA_VERSION = 1
THRESHOLD = 16
PARTS = ("whole", "without_text")
MANIFEST_NAME = "manifest.json"


def rasterise(svg: str, width: int, height: int) -> np.ndarray:
    """The SVG drawn by Qt's SVG module onto `width` by `height` transparent pixels, as RGBA."""
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from core_ultra import typography

    typography.ensure_gui()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("Qt's SVG module could not read the SVG")
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, width, height))
    finally:
        painter.end()
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
    return pixels.reshape(height, image.bytesPerLine() // 4, 4)[:, :width].copy()


def difference(scene: Scene, scale: float) -> tuple[dict[str, Any], list[int]]:
    """The three numbers for one scene, its SVG by Qt's SVG module against the
    runtime renderer, and the width and height in pixels both were drawn at."""
    drawn = runtime_renderer.draw(scene, scale)
    exported = rasterise(scene_export.to_svg(scene), drawn.shape[1], drawn.shape[0])
    apart = np.abs(exported.astype(np.int16) - drawn.astype(np.int16))
    numbers = {
        "mean_absolute_difference": float(apart.mean()),
        "share_of_pixels_over_16": float((apart.max(axis=2) > THRESHOLD).mean()),
        "largest_difference": int(apart.max()),
    }
    return numbers, [int(drawn.shape[1]), int(drawn.shape[0])]


def without_text(scene: Scene) -> Scene:
    """The same scene with every bound element's text emptied."""
    candidate = scene.to_json()
    for element in candidate["elements"]:
        if "bound" in element:
            element["bound"]["text"] = ""
    supplied = [dataclasses.replace(element.bound, text="") for element in scene.bound_elements]
    return scene_schema.validate(candidate, supplied, (scene.viewport_width, scene.viewport_height))


def measure(folder: str | Path) -> dict[str, Any]:
    """Compare every record of the dataset in `folder`. Raises `SourceError` when it cannot be read."""
    import PySide6
    from PySide6.QtCore import qVersion

    folder = Path(folder)
    try:
        manifest_bytes = (folder / MANIFEST_NAME).read_bytes()
        manifest = json.loads(manifest_bytes)
        listed = [(entry["id"], entry["file"]) for entry in manifest["records"]]
        dataset = {"name": manifest["dataset"]["name"], "version": manifest["dataset"]["version"]}
    except OSError as error:
        raise SourceError(f"{folder / MANIFEST_NAME} cannot be read: {error.strerror or error}") from None
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
        raise SourceError(f"{folder / MANIFEST_NAME} is not a dataset manifest: {error!r}") from None

    entries: list[dict[str, Any]] = []
    several_lines: list[str] = []
    for record_id, record_file in listed:
        path = folder / record_file
        try:
            record = json.loads(path.read_bytes())
            scene = scene_export.from_record(record, path)
            scale = record["reference_image"]["pixels_per_viewport_unit"]
            preset = record["diagnostics"]["visual_preset"]
            if not (scene_schema._is_finite_number(scale) and scale > 0):
                raise SourceError(f"{path} gives {scale!r} pixels per viewport unit")
            whole, pixels = difference(scene, scale)
            emptied, _ = difference(without_text(scene), scale)
        except OSError as error:
            raise SourceError(f"{path} cannot be read: {error.strerror or error}") from None
        except SceneInvalid as refused:
            raise SourceError(f"{path} holds an invalid scene: {refused}") from None
        except (TextNotDrawable, NotExportable) as refused:
            raise SourceError(f"{path} holds a scene that cannot be exported: {refused}") from None
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError, OverflowError, ValueError) as error:
            raise SourceError(f"{path} is not a dataset record that can be compared: {error!r}") from None
        entries.append(
            {
                "id": record_id,
                "visual_preset": preset,
                "pixels_per_viewport_unit": scale,
                "pixels": pixels,
                "whole": whole,
                "without_text": emptied,
            }
        )
        if any(element.bound.text and len(runtime_renderer.text_lines(element)) > 1 for element in scene.bound_elements):
            several_lines.append(record_id)

    presets = sorted({entry["visual_preset"] for entry in entries})
    on_several = [entry for entry in entries if entry["id"] in set(several_lines)]
    on_one = [entry for entry in entries if entry["id"] not in set(several_lines)]
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "dataset": {**dataset, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()},
        "exported_by": "core-ultra scene export",
        "rasterised_by": {"tool": "Qt SVG (QSvgRenderer, PySide6-Essentials)", "pyside6": PySide6.__version__, "qt": qVersion()},
        "compared_with": "runtime renderer",
        "numbers": {
            "mean_absolute_difference": "mean of |a - b| over every channel of every pixel, in levels of 255",
            "share_of_pixels_over_16": f"share of pixels in which some channel differs by more than {THRESHOLD} levels",
            "largest_difference": "largest |a - b| of any channel of any pixel",
            "without_text": "the same scene with every text emptied, in the SVG and in the runtime renderer's image",
        },
        "overall": _summary(entries),
        "by_visual_preset": {preset: _summary([entry for entry in entries if entry["visual_preset"] == preset]) for preset in presets},
        # Qt's SVG module ignores the x and y of a <tspan>, so it draws text on
        # several lines as one line at the origin. These records are counted in
        # the numbers above and also apart.
        "records_with_text_on_several_lines": {"ids": several_lines, **_summary(on_several)},
        "records_with_text_on_one_line_only": _summary(on_one),
        "records": entries,
    }


def _summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"records": len(entries)}
    for part in PARTS:
        if not entries:
            continue
        summary[part] = {
            **{
                name: {
                    "mean": sum(entry[part][name] for entry in entries) / len(entries),
                    "largest": max(entry[part][name] for entry in entries),
                }
                for name in ("mean_absolute_difference", "share_of_pixels_over_16")
            },
            "largest_difference": max(entry[part]["largest_difference"] for entry in entries),
        }
    return summary


def to_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def to_text(record: dict[str, Any]) -> str:
    dataset, tool = record["dataset"], record["rasterised_by"]
    lines = [
        f"Dataset            {dataset['name']} version {dataset['version']}, {record['overall']['records']} records",
        f"Exported SVG       rasterised by {tool['tool']}, PySide6 {tool['pyside6']}, Qt {tool['qt']}",
        f"Compared with      the {record['compared_with']}'s image of the same scene",
        "",
        "Mean absolute difference in levels of 255, and the share of pixels over "
        f"{THRESHOLD} levels; mean over records (largest record).",
        "",
        f"{'':<34}{'records':>8}  {'whole':<34}{'without text':<34}",
    ]

    def row(label: str, summary: dict[str, Any]) -> str:
        cells = []
        for part in PARTS:
            if part not in summary:
                cells.append(f"{'-':<34}")
                continue
            mean, share = summary[part]["mean_absolute_difference"], summary[part]["share_of_pixels_over_16"]
            cells.append(f"{mean['mean']:.3f} ({mean['largest']:.3f})  {share['mean']:.2%} ({share['largest']:.2%})".ljust(34))
        return f"{label:<34}{summary['records']:>8}  {''.join(cells)}".rstrip()

    lines.append(row("every record", record["overall"]))
    lines += [row(f"  {preset}", summary) for preset, summary in record["by_visual_preset"].items()]
    lines.append(row("text on one line only", record["records_with_text_on_one_line_only"]))
    lines.append(row("text on several lines", record["records_with_text_on_several_lines"]))
    return "\n".join(lines) + "\n"
