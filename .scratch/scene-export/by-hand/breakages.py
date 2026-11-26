"""Deliberate breakages of scene export, one at a time (issue #32, by hand).

Each entry changes one line of the code, runs tests/test_cli_scene_export.py and
puts the line back. CAUGHT means a test failed, which is what is wanted.
Run from the repository root, with nothing else running the tests:

    uv run python .scratch/scene-export/by-hand/breakages.py

The patterns are the code as it was on 2026-11-26. A pattern that no longer
matches is reported as SKIPPED, never as caught.
"""
import subprocess, sys
from pathlib import Path
E = Path('src/core_ultra/scene_export.py'); C = Path('src/core_ultra/scene_export_comparison.py')
M = [
 ("border not inset", E, "half = style.border_width / 2 if bordered else 0.0", "half = 0.0"),
 ("opacity on the group", E, '''lines.append(f'{indent}<g id={_attribute(element.id)} data-type="{element.type}"{role}>')''', '''lines.append(f'{indent}<g id={_attribute(element.id)} data-type="{element.type}"{role}' + (f' opacity="{_number(element.style.opacity)}"' if element.style.opacity < 1 else "") + ">")'''),
 ("blur of a whole elevation", E, "half = _number(elevation / 2)", "half = _number(elevation)"),
 ("children in reverse", E, "for child in children.get(element.id, []):", "for child in reversed(children.get(element.id, [])):"),
 ("weight always 400", E, "font-weight=\"{_number(typography.font_weight(style.type_weight))}\"", "font-weight=\"400\""),
 ("record validated against what it carries", E, "return scene_schema.validate(candidate, supplied, viewport)", "return _from_scene_file(candidate)"),
 ("button text not anchored", E, "if element.bound.role == \"button\":", "if False:"),
 ("text below the baseline", E, "y=\"{_number(top + ascent)}\"", "y=\"{_number(top)}\""),
 ("whitespace not preserved", E, "        'xml:space=\"preserve\"',\n", ""),
 ("text not escaped", E, "return escape(_writable(value), {\"\\r\": \"&#13;\"})", "return value"),
 ("empty lines kept as tspans", E, "for text, x, top in placed if text)", "for text, x, top in placed)"),
 ("flat tree", E, "write(child, depth + 1)\n        lines.append(f\"{indent}</g>\")", "pass\n        lines.append(f\"{indent}</g>\")\n        for child in children.get(element.id, []):\n            write(child, depth)"),
 ("filter named after an element", E, "prefix = \"_\" + prefix", "break"),
 ("corner radius not written", E, "if radius > 0:", "if False:"),
 ("fill alpha ignored", E, "if alpha <= 0:", "if False:"),
 ("comparison keeps the text", C, "element[\"bound\"][\"text\"] = \"\"", "pass"),
 ("comparison at another threshold", C, "THRESHOLD = 16", "THRESHOLD = 32"),
 ("comparison of the SVG with itself", C, "drawn = runtime_renderer.draw(scene, scale)\n    exported = rasterise(scene_export.to_svg(scene), drawn.shape[1], drawn.shape[0])", "drawn = runtime_renderer.draw(scene, scale)\n    exported = drawn"),
 ("elevations told apart past six decimals", E, "elevations = sorted({_elevation(element) for element in scene.elements} - {0.0})", "elevations = sorted({element.style.elevation for element in scene.elements} - {0.0})"),
 ("only a button's text is shaped", E, "        typography.shape(text, style.type_weight)\n", "        pass\n"),
 ("weight written between hundreds", E, "_number(typography.font_weight(style.type_weight))", "_number(style.type_weight)"),
 ("comparison lets undrawable text through", C, "except (TextNotDrawable, NotExportable) as refused:", "except NotExportable as refused:"),
]
for name, path, old, new in M:
    original = path.read_text()
    if original.count(old) != 1:
        print(f"SKIPPED  {name}: pattern found {original.count(old)} times", flush=True); continue
    path.write_text(original.replace(old, new))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_cli_scene_export.py", "-q", "-x", "--no-header", "-p", "no:cacheprovider"], capture_output=True, text=True)
    finally:
        path.write_text(original)
    last = [l for l in r.stdout.splitlines() if l.startswith("FAILED") or l.startswith("ERROR")]
    print(("CAUGHT   " if r.returncode else "MISSED   ") + name + (": " + last[0][:150] if last else ""), flush=True)
