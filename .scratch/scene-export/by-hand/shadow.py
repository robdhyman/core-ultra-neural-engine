"""The export's blur shadow against the runtime renderer's shadow (issue #32, by hand).

One white panel alone on a white surface, at four pixels per viewport unit, the
SVG rasterised by Qt's SVG module. Prints the largest difference of any channel
along the straight top and bottom edges and over the whole image.

    uv run python .scratch/scene-export/by-hand/shadow.py
"""

import numpy as np

from core_ultra import runtime_renderer, scene as scene_schema, scene_export, scene_export_comparison


def element(identity, parent, x, y, width, height, elevation=0.0, radius=0.0):
    return {
        "id": identity, "type": "surface" if parent is None else "panel", "parent": parent,
        "box": {"x": x, "y": y, "width": width, "height": height},
        "style": {
            "fill": [1, 1, 1, 1], "text_colour": [0, 0, 0, 1], "border_colour": [0, 0, 0, 0], "border_width": 0,
            "corner_radius": radius, "elevation": elevation, "opacity": 1, "type_size": 14, "type_weight": 400,
        },
    }


for elevation, radius in ((2, 8), (4, 14), (8, 8), (12, 14)):
    candidate = {
        "kind": "scene", "schema_version": 1, "viewport": {"width": 400, "height": 300},
        "elements": [element("s.root", None, 0, 0, 400, 300), element("s.panel", "s.root", 100, 80, 200, 120, elevation, radius)],
    }
    scene = scene_schema.validate(candidate, [], (400, 300))
    drawn = runtime_renderer.draw(scene, 4).astype(int)
    exported = scene_export_comparison.rasterise(scene_export.to_svg(scene), drawn.shape[1], drawn.shape[0]).astype(int)
    apart = np.abs(drawn - exported)[..., 0]
    print(f"elevation {elevation}, radius {radius}: straight edges {apart[:, 780:820].max()}, whole image {apart.max()}, mean {apart.mean():.4f}")
