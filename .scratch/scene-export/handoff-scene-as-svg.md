# Hand-off: the scene as an editable SVG (issue #32)

Written 2026-11-26 for Rob, to open before the pilot review (#10).

## What to open

Eight scenes from the tiny dataset, two in each visual preset, exported by `core-ultra scene export`. They were sent to Rob as files with this note. In the checkout they were written in they are in `artifacts/scene-export/tiny-v1/`, which git ignores.

| SVG | Dataset record | Visual preset | Viewport | What it shows |
| --- | --- | --- | --- | --- |
| `night-teal-saved.svg` | `first-documents-0.015` | `night-teal` | 960 by 540 | Two rows, a document open, three lines of body, a notification, Save disabled |
| `night-teal-save-hover.svg` | `first-documents-0.013` | `night-teal` | 960 by 540 | The same document unsaved, the pointer on Save |
| `calm-blue-saved.svg` | `revise-and-undo-0.012` | `calm-blue` | 1120 by 630 | One row, a document open, a notification |
| `calm-blue-four-lines.svg` | `revise-and-undo-0.015` | `calm-blue` | 1120 by 630 | Four lines of body, nothing disabled |
| `dense-ink-open.svg` | `find-and-sort-0.024` | `dense-ink` | 960 by 540 | Three rows, a document open |
| `dense-ink-filter-focused.svg` | `find-and-sort-0.014` | `dense-ink` | 960 by 540 | Three rows, no document open, the filter field focused |
| `warm-paper-renamed.svg` | `rename-and-reorder-0.012` | `warm-paper` | 1120 by 630 | Two rows, a renamed document open, a notification |
| `warm-paper-sort-pressed.svg` | `rename-and-reorder-0.014` | `warm-paper` | 1120 by 630 | The same, the sort button pressed |

What each should look like is the runtime renderer's image of the same record, `artifacts/datasets/tiny-v1/images/<record>.png`.

The SVGs are not in git. The repository keeps generated evidence under `artifacts/`, out of git, and commits the manifest that describes it; a test from issue #6 also fails on any `.svg` in the repository that is not a recorded asset. What git keeps is `artifacts/scene-export/tiny-v1/manifest.json`, with the record and the SHA-256 of each SVG, and a test that `scene export` still writes those bytes. To write the eight again, with the tiny dataset generated:

```bash
for pair in night-teal-saved=first-documents-0.015 night-teal-save-hover=first-documents-0.013 calm-blue-saved=revise-and-undo-0.012 calm-blue-four-lines=revise-and-undo-0.015 dense-ink-open=find-and-sort-0.024 dense-ink-filter-focused=find-and-sort-0.014 warm-paper-renamed=rename-and-reorder-0.012 warm-paper-sort-pressed=rename-and-reorder-0.014; do uv run core-ultra scene export "artifacts/datasets/tiny-v1/records/${pair#*=}.json" --out "artifacts/scene-export/tiny-v1/${pair%%=*}.svg"; done
```

Drag a file into the design tool. The text is named as Inter and not embedded, so the tool needs Inter installed; this Mac has it.

What you should find in the layer list: one group for each scene element, named by the element's id (`s.root`, `s.toolbar`, `b.documents.create`, `b.document:1`), nested the way the scene's parent links nest them, in drawing order. Inside each group there is one rectangle, and one text when the element says anything.

## What was checked, and what was not

- **Measured, all 82 records, Qt's SVG module against the runtime renderer** (`core-ultra scene compare`, record in `records/measurements/scene-export/tiny-v1.json`). Mean absolute difference 0.433 levels of 255 (largest record 1.121); 0.73% of pixels differ by more than 16 levels (largest record 1.54%). With every text emptied in both: 0.015 (largest 0.046), and 0.0006% of pixels. So the rectangles, borders, corners, opacity and shadows land where the runtime renderer puts them, and nearly all of the difference is how the text is rasterised.
- **Qt's SVG module misplaces text on several lines.** It ignores the position of a `<tspan>` and draws all the lines as one line at the top left corner. That is 7 of the 82 records; their mean is 1.058 against 0.374 for the other 75.
- **Spot check in a browser** (the Claude app's built-in one, Chrome 156, with the Inter installed on this Mac), four scenes, one in each preset, the SVG drawn to a canvas and compared with the dataset's image: 1.015 (`night-teal-saved`), 0.633 (`calm-blue-saved`), 0.509 (`dense-ink-open`), 0.302 (record `rename-and-reorder-0.010`, `warm-paper`, which is not one of the eight). Qt's SVG module gave 1.121, 0.606, 0.494 and 0.351 for the same four. The browser put the three lines of body text in their places. This was run by hand, once; the page is [by-hand/browser-spot-check.html](by-hand/browser-spot-check.html) and its numbers are in no record.
- **Not checked: any design tool.** No file was opened in Figma, Sketch, Illustrator, Affinity or Inkscape. Three things are worth a look there, because tools differ on them: whether the shadow filter arrives as an editable shadow, as a flattened image or not at all; whether text on several lines arrives as one text object or one for each line; and whether the layer names are the element ids.

## Where the export already had to bend

These are places where SVG and the scene do not say the same thing, and the export chose.

| Scene | SVG | What the export does |
| --- | --- | --- |
| A border lies inside the element's outline | A stroke is centred on the outline | The rectangle is written half a border in. In the tool, a bordered element's rectangle is one border smaller than the scene's box, and its corner radius half a border smaller |
| Opacity is the element's own | `opacity` on a group covers everything in it | Opacity is on the rectangle and on the text, separately |
| Elevation is one number; the runtime renderer turns it into a shadow by a fixed rule | A shadow is a filter with its own offset, blur and colour | A blur of half the elevation, moved down half the elevation, black at alpha 0.24 |
| Where text sits is a rule of the runtime renderer, by role | Text has its own position | The position the rule gives is written as numbers. Moving the rectangle in the tool does not move the text |
| A text-area's text is one value with line feeds | SVG text has no lines | One `<tspan>` for each line |
| The font is always Inter and the scene does not say so | Text names its font | `font-family="Inter"` on every text |

## What an SVG or a design document can express that the scene schema cannot

The scene schema, version 1, is: up to 32 bound and 16 structural elements in one tree; each an upright rectangle inside the viewport with nine style values (fill, text colour, border colour, border width, corner radius, elevation, opacity, type size, type weight); a bound element also carries the application's text, role, binding, state and relationships.

**Shape**

- Free paths: curves, polygons, lines, ellipses. The scene has upright rounded rectangles only.
- Rotation, skew and flipping.
- A different radius for each corner.
- Shapes combined or cut by other shapes; masks and clipping. The scene clips nothing.
- Anything outside the viewport, anything that scrolls, more than one frame or page.

**Paint**

- Images and icons. The scene has no element that holds a picture.
- Gradients, patterns and image fills; more than one fill on a shape; blend modes.
- Borders on chosen sides only, dashed borders, borders centred on or outside the outline, more than one border.
- A shadow with its own offset, blur, spread and colour; several shadows; inner shadows; blurs of the element or of what is behind it.
- Opacity of a whole group.

**Text**

- A font family, italics, letter spacing, line height, underline and other decoration.
- Alignment, as a value. In the scene it follows from the role.
- A text box separate from its background: padding, wrapping, truncation, text that resizes its box.
- More than one style inside one text, more than one text in an element, an icon beside a text.

**Structure**

- A group that is only a group. Every scene element is a rectangle with a full set of style values.
- Children of a bound element. In the scene only structural elements have children.
- Components and instances: one definition drawn many times, with overrides. Every row in a scene is written out in full.
- Named styles and tokens. The scene holds the resolved values and not which token a value came from, nor which visual preset.
- Constraints and automatic layout: pinning to an edge, padding, gaps, hug and fill. The scene holds finished boxes, and a new viewport size needs a new scene.
- Several states of one element side by side, and links between frames. A scene is one frame in one state.
- Hidden or locked layers, layer names apart from ids, notes.
- Motion.

**The other way round**, for balance: the scene carries what the application supplied (text that may not be altered, role, binding, state, relationships), and the shape that is drawn is the shape a pointer hits. An SVG has no place for any of that. The export keeps the id and, as `data-type` and `data-role` attributes, the element's type and role; a design tool will drop those attributes on import.

## What this says for #10

Seen as a vector document, a scene is a stack of named rounded rectangles, each with at most one text. It is editable in the sense that every element is a separate named object with the right fill, border, radius and type. It is thin in the sense that three ordinary moves in a design tool (make a component of a row, pin an element to an edge, drop in an icon) have nowhere to go in the schema. Whether that is too thin is the first question under "Questions held for later" in `docs/roadmap.md`; this note is the evidence for it and does not answer it.
