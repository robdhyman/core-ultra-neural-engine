"""Is the exported text offset from the runtime renderer's? (issue #32, by hand)

Two records of the tiny dataset, at one and at four pixels per viewport unit.
The rasterised SVG is moved by one pixel in each of the eight directions; if
the mean absolute difference is smallest with no move, the text is not offset.

    uv run python .scratch/scene-export/by-hand/shift.py
"""

import numpy as np

from core_ultra import runtime_renderer, scene_export, scene_export_comparison

for record in ("revise-and-undo-0.005", "find-and-sort-0.010"):
    scene, _ = scene_export.load(f"artifacts/datasets/tiny-v1/records/{record}.json")
    for scale in (1, 4):
        drawn = runtime_renderer.draw(scene, scale).astype(np.int16)
        exported = scene_export_comparison.rasterise(scene_export.to_svg(scene), drawn.shape[1], drawn.shape[0]).astype(np.int16)
        moved = {
            (dx, dy): float(np.abs(drawn[2:-2, 2:-2] - np.roll(exported, (dy, dx), axis=(0, 1))[2:-2, 2:-2]).mean())
            for dy in (-1, 0, 1) for dx in (-1, 0, 1)
        }
        best = min(moved, key=moved.get)
        print(f"{record}, {scale} px per unit: no move {moved[(0, 0)]:.4f}, smallest at {best} {moved[best]:.4f}")
