---
version: alpha
name: Core Ultra document workspace
description: The design source of the Core Ultra document workspace. One set of components, drawn in four original visual presets.
omitted:
  - section: Motion & Micro-interaction
    reason: A scene is one still frame, and the scene schema has no motion value.
  - section: Voice & Content Strategy
    reason: Every word on screen is the application's own text. The design writes none of it.
preset: calm-blue
states: [default, hover, pressed, focused, disabled]
colors:
  page: "#F2F2F5"
  surface: "#FFFFFF"
  well: "#FAFAFC"
  line: "#D9D9E0"
  field-line: "#B8BDC9"
  field-line-hover: "#7A8294"
  field-pressed: "#F0F5FC"
  ink: "#1A1C21"
  muted: "#666B78"
  primary: "#245EDB"
  primary-hover: "#2F68E0"
  primary-pressed: "#1747B3"
  on-primary: "#FFFFFF"
  quiet: "#EDF0F5"
  quiet-hover: "#E0E6ED"
  quiet-pressed: "#D1D6E3"
  focus-ring: "#0A297A"
  row-open: "#E6EDFC"
  row-hover: "#EDF2FC"
  row-pressed: "#D6E0F7"
  notification: "#21242B"
  on-notification: "#FFFFFF"
typography:
  heading:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: 700
  title:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: 500
  body:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 400
  row:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 400
  row-open:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 500
  button:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 500
  label:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: 400
  notification:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 500
rounded:
  control: 8px
  field: 8px
  row: 8px
  panel: 12px
  notification: 10px
spacing:
  margin: 16px
  gap: 8px
  button-padding: 14px
  row-inset: 4px
  panel-padding: 12px
  editor-padding: 16px
dimensions:
  filter-width-min: 96px
  filter-width-max: 240px
  list-width-min: 220px
  list-width-max: 320px
  list-share: 0.34
borders:
  panel: 1px
  control: 1px
  field: 1px
  focus: 2px
  divider: 1px
elevation:
  panel: 2px
  notification: 8px
density:
  toolbar-height: 56px
  control-height: 36px
  row-height: 40px
  title-height: 40px
  notification-height: 40px
opacity:
  disabled: 0.4
components:
  page:
    backgroundColor: "{colors.page}"
  toolbar:
    backgroundColor: "{colors.surface}"
    height: "{density.toolbar-height}"
  divider:
    backgroundColor: "{colors.line}"
    height: "{borders.divider}"
  panel:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.line}"
    borderWidth: "{borders.panel}"
    rounded: "{rounded.panel}"
    elevation: "{elevation.panel}"
  heading:
    textColor: "{colors.ink}"
    typography: "{typography.heading}"
  label:
    textColor: "{colors.muted}"
    typography: "{typography.label}"
  notification:
    backgroundColor: "{colors.notification}"
    textColor: "{colors.on-notification}"
    typography: "{typography.notification}"
    rounded: "{rounded.notification}"
    elevation: "{elevation.notification}"
    height: "{density.notification-height}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: "{density.control-height}"
    padding: "{spacing.button-padding}"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-pressed:
    backgroundColor: "{colors.primary-pressed}"
  button-primary-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  button-primary-disabled:
    opacity: "{opacity.disabled}"
  button-quiet:
    backgroundColor: "{colors.quiet}"
    textColor: "{colors.ink}"
    borderColor: "{colors.line}"
    borderWidth: "{borders.control}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    height: "{density.control-height}"
    padding: "{spacing.button-padding}"
  button-quiet-hover:
    backgroundColor: "{colors.quiet-hover}"
  button-quiet-pressed:
    backgroundColor: "{colors.quiet-pressed}"
  button-quiet-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  button-quiet-disabled:
    opacity: "{opacity.disabled}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.field-line}"
    borderWidth: "{borders.field}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    height: "{density.control-height}"
  field-hover:
    borderColor: "{colors.field-line-hover}"
  field-pressed:
    backgroundColor: "{colors.field-pressed}"
  field-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  field-disabled:
    opacity: "{opacity.disabled}"
  title-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.field-line}"
    borderWidth: "{borders.field}"
    typography: "{typography.title}"
    rounded: "{rounded.field}"
    height: "{density.title-height}"
  title-field-hover:
    borderColor: "{colors.field-line-hover}"
  title-field-pressed:
    backgroundColor: "{colors.field-pressed}"
  title-field-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  title-field-disabled:
    opacity: "{opacity.disabled}"
  editor-body:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    borderColor: "{colors.field-line}"
    borderWidth: "{borders.field}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
  editor-body-hover:
    borderColor: "{colors.field-line-hover}"
  editor-body-pressed:
    backgroundColor: "{colors.field-pressed}"
  editor-body-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  editor-body-disabled:
    opacity: "{opacity.disabled}"
  row:
    textColor: "{colors.ink}"
    typography: "{typography.row}"
    rounded: "{rounded.row}"
    height: "{density.row-height}"
  row-hover:
    backgroundColor: "{colors.row-hover}"
  row-pressed:
    backgroundColor: "{colors.row-pressed}"
  row-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  row-disabled:
    opacity: "{opacity.disabled}"
  row-open:
    backgroundColor: "{colors.row-open}"
    textColor: "{colors.ink}"
    typography: "{typography.row-open}"
    rounded: "{rounded.row}"
    height: "{density.row-height}"
  row-open-hover:
    backgroundColor: "{colors.row-hover}"
  row-open-pressed:
    backgroundColor: "{colors.row-pressed}"
  row-open-focused:
    borderColor: "{colors.focus-ring}"
    borderWidth: "{borders.focus}"
  row-open-disabled:
    opacity: "{opacity.disabled}"
presets:
  calm-blue:
    title: Calm Blue
    summary: Cool light greys, white panels, one blue accent, medium corners, soft shadows, regular density.
  warm-paper:
    title: Warm Paper
    summary: Warm off-whites, brown-black ink, a rust accent, small corners, almost flat, larger type, comfortable density.
    colors:
      page: "#F4EFE6"
      surface: "#FBF8F2"
      well: "#FFFDF9"
      line: "#DDD3C3"
      field-line: "#BFB29D"
      field-line-hover: "#8A7C66"
      field-pressed: "#F3ECDF"
      ink: "#2B2620"
      muted: "#6A5F50"
      primary: "#9A4A2B"
      primary-hover: "#A65331"
      primary-pressed: "#7E3A20"
      on-primary: "#FFFAF3"
      quiet: "#EEE7DA"
      quiet-hover: "#E4DBCB"
      quiet-pressed: "#D6CBB7"
      focus-ring: "#5A2A14"
      row-open: "#F1E4D6"
      row-hover: "#F5ECE0"
      row-pressed: "#E7D5C3"
      notification: "#3A3128"
      on-notification: "#FBF6EC"
    typography:
      heading:
        fontFamily: Inter
        fontSize: 22px
        fontWeight: 600
      title:
        fontFamily: Inter
        fontSize: 20px
        fontWeight: 500
      body:
        fontFamily: Inter
        fontSize: 16px
        fontWeight: 400
      row:
        fontFamily: Inter
        fontSize: 16px
        fontWeight: 400
      row-open:
        fontFamily: Inter
        fontSize: 16px
        fontWeight: 600
      button:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 500
      label:
        fontFamily: Inter
        fontSize: 14px
        fontWeight: 400
      notification:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 500
    rounded:
      control: 4px
      field: 4px
      row: 4px
      panel: 6px
      notification: 4px
    spacing:
      margin: 20px
      gap: 10px
      button-padding: 18px
      row-inset: 6px
      panel-padding: 16px
      editor-padding: 22px
    dimensions:
      filter-width-min: 110px
      filter-width-max: 260px
      list-width-min: 240px
      list-width-max: 340px
      list-share: 0.34
    borders:
      panel: 1px
      control: 1px
      field: 1px
      focus: 2px
      divider: 1px
    elevation:
      panel: 0px
      notification: 3px
    density:
      toolbar-height: 64px
      control-height: 40px
      row-height: 46px
      title-height: 46px
      notification-height: 46px
    opacity:
      disabled: 0.45
  night-teal:
    title: Night Teal
    summary: Dark blue-greys, raised panels, a light teal accent with dark text on it, large corners, deep shadows, regular density.
    colors:
      page: "#14181F"
      surface: "#1D232D"
      well: "#171C24"
      line: "#2F3846"
      field-line: "#46536A"
      field-line-hover: "#7286A6"
      field-pressed: "#232B38"
      ink: "#E8ECF2"
      muted: "#9AA6B8"
      primary: "#5FD4C0"
      primary-hover: "#7DE0CF"
      primary-pressed: "#45B8A5"
      on-primary: "#0B2420"
      quiet: "#283140"
      quiet-hover: "#323D50"
      quiet-pressed: "#3D4A61"
      focus-ring: "#B6F2E7"
      row-open: "#223A40"
      row-hover: "#232C39"
      row-pressed: "#2C3848"
      notification: "#E8ECF2"
      on-notification: "#14181F"
    typography:
      heading:
        fontFamily: Inter
        fontSize: 20px
        fontWeight: 600
      title:
        fontFamily: Inter
        fontSize: 18px
        fontWeight: 600
      body:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 400
      row:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 400
      row-open:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 600
      button:
        fontFamily: Inter
        fontSize: 14px
        fontWeight: 600
      label:
        fontFamily: Inter
        fontSize: 13px
        fontWeight: 500
      notification:
        fontFamily: Inter
        fontSize: 14px
        fontWeight: 600
    rounded:
      control: 10px
      field: 10px
      row: 10px
      panel: 14px
      notification: 12px
    spacing:
      margin: 16px
      gap: 8px
      button-padding: 16px
      row-inset: 4px
      panel-padding: 12px
      editor-padding: 18px
    dimensions:
      filter-width-min: 96px
      filter-width-max: 240px
      list-width-min: 220px
      list-width-max: 320px
      list-share: 0.34
    borders:
      panel: 1px
      control: 1px
      field: 1px
      focus: 2px
      divider: 1px
    elevation:
      panel: 4px
      notification: 12px
    density:
      toolbar-height: 56px
      control-height: 36px
      row-height: 40px
      title-height: 40px
      notification-height: 40px
    opacity:
      disabled: 0.38
  dense-ink:
    title: Dense Ink
    summary: White with black rules, a violet accent, square corners, no shadows, small heavy type, compact density.
    colors:
      page: "#ECECEC"
      surface: "#FFFFFF"
      well: "#FFFFFF"
      line: "#111111"
      field-line: "#111111"
      field-line-hover: "#4A2FC9"
      field-pressed: "#EEEAFB"
      ink: "#0D0D0D"
      muted: "#4F4F4F"
      primary: "#4A2FC9"
      primary-hover: "#5B41D6"
      primary-pressed: "#38219E"
      on-primary: "#FFFFFF"
      quiet: "#FFFFFF"
      quiet-hover: "#E9E9E9"
      quiet-pressed: "#D4D4D4"
      focus-ring: "#C2410C"
      row-open: "#E4DEFA"
      row-hover: "#F1EEFC"
      row-pressed: "#D3CAF6"
      notification: "#0D0D0D"
      on-notification: "#FFFFFF"
    typography:
      heading:
        fontFamily: Inter
        fontSize: 16px
        fontWeight: 800
      title:
        fontFamily: Inter
        fontSize: 15px
        fontWeight: 700
      body:
        fontFamily: Inter
        fontSize: 13px
        fontWeight: 400
      row:
        fontFamily: Inter
        fontSize: 13px
        fontWeight: 500
      row-open:
        fontFamily: Inter
        fontSize: 13px
        fontWeight: 700
      button:
        fontFamily: Inter
        fontSize: 12px
        fontWeight: 700
      label:
        fontFamily: Inter
        fontSize: 11px
        fontWeight: 600
      notification:
        fontFamily: Inter
        fontSize: 12px
        fontWeight: 600
    rounded:
      control: 2px
      field: 2px
      row: 0px
      panel: 0px
      notification: 2px
    spacing:
      margin: 8px
      gap: 6px
      button-padding: 10px
      row-inset: 2px
      panel-padding: 8px
      editor-padding: 10px
    dimensions:
      filter-width-min: 80px
      filter-width-max: 200px
      list-width-min: 180px
      list-width-max: 260px
      list-share: 0.3
    borders:
      panel: 1.5px
      control: 1.5px
      field: 1.5px
      focus: 3px
      divider: 1.5px
    elevation:
      panel: 0px
      notification: 0px
    density:
      toolbar-height: 40px
      control-height: 26px
      row-height: 28px
      title-height: 30px
      notification-height: 30px
    opacity:
      disabled: 0.35
---

# Core Ultra document workspace

## Overview

This is the design source of the Core Ultra document workspace: a document list, an editor, a toolbar and a notification. It is original work written for this project. No value in it was taken from an existing product, brand, screenshot or design collection.

The file follows the Google Labs DESIGN.md format, version alpha. The tokens are the YAML above; this prose says what they are for. The same design is held in machine-readable form in `configs/design/v1.json`, the generator configuration, which is what the reference layout reads. `uv run core-ultra design check` fails when the two files disagree.

**One set of components, four visual presets.** A visual preset is a complete, coherent set of token values. Components are written once and name tokens, so a preset changes how every element looks without changing what any element is. The top-level tokens are the default preset, named by `preset`. The other presets are complete sets under `presets`.

| Preset | Character |
| --- | --- |
| Calm Blue (`calm-blue`, the default) | Cool light greys, white panels, one blue accent, medium corners, soft shadows, regular density. |
| Warm Paper (`warm-paper`) | Warm off-whites, brown-black ink, a rust accent, small corners, almost flat, larger type, comfortable density. |
| Night Teal (`night-teal`) | Dark blue-greys, raised panels, a light teal accent with dark text on it, large corners, deep shadows, regular density. |
| Dense Ink (`dense-ink`) | White with black rules, a violet accent, square corners, no shadows, small heavy type, compact density. |

Presets are named for what they look like and never after a brand.

**Extensions to the format.** The format has no place for some things a scene needs, and it allows extra keys. These are this project's: the token groups `dimensions`, `borders`, `elevation`, `density` and `opacity`; the keys `preset`, `presets` and `states`; and the component properties `borderColor`, `borderWidth`, `elevation` and `opacity`.

**Units.** Every length is in px, and one px is one viewport unit of a scene. A scene is drawn as vectors at any number of pixels per viewport unit.

## Colors

Colours are named for the job they do, never for their hue, so every preset has the same names.

| Token | Job |
| --- | --- |
| `page` | The background behind everything. |
| `surface` | Toolbar, panels and text fields. |
| `well` | The editor body, set slightly apart from its panel. |
| `line` | Panel borders, the toolbar divider and quiet button borders. |
| `field-line`, `field-line-hover` | A text field's border, at rest and under the pointer. |
| `field-pressed` | A text field's fill while pressed. |
| `ink` | Text. |
| `muted` | Labels and other secondary text. |
| `primary`, `primary-hover`, `primary-pressed` | The one accent: the primary button's fill in its states. |
| `on-primary` | Text on the accent. |
| `quiet`, `quiet-hover`, `quiet-pressed` | A quiet button's fill in its states. |
| `focus-ring` | The border of whatever has keyboard focus. |
| `row-open` | The row of the document shown in the editor. |
| `row-hover`, `row-pressed` | A row under the pointer and while pressed. |
| `notification`, `on-notification` | The notification's fill and its text. |

Each preset uses one accent. In every preset, text has a contrast ratio of at least 4.5 to 1 against each fill it is drawn on: `ink` on `surface`, `well`, the quiet fills, the row fills and `field-pressed`; `muted` on `surface`; `on-primary` on the three accent fills; `on-notification` on `notification`. A test holds every preset to this.

Night Teal is the dark preset. Its accent is light, so `on-primary` is dark, and its notification is light on a dark page.

## Typography

All text is set in Inter, a variable font licensed under the SIL Open Font License 1.1 and kept in this repository. `ASSETS.md` records its source, version and attribution. The weight axis is set to the token's weight, rounded to the nearest hundred. The optical size axis is pinned at 16 so that a line of text has the same outline at every size.

| Token | Used for |
| --- | --- |
| `heading` | The heading of the document list. |
| `title` | The open document's title field. |
| `body` | The editor body and the filter field. |
| `row`, `row-open` | A row of the document list; the open document's row is heavier. |
| `button` | Button text. |
| `label` | Labels: the filter label, the revision line, empty-state text. |
| `notification` | The notification. |

There is no line height token. A line is as tall as the font's ascent plus its descent at the type size, and the lines of the editor body are 1.25 line heights apart. Text is never wrapped, elided or clipped by the design; that is a rule of the runtime renderer.

Warm Paper sets larger, lighter type. Dense Ink sets small type and makes up for it with weight.

## Layout

The workspace has one arrangement. The toolbar spans the top. Below it the document list sits on the left and the editor fills the rest. The notification lies over the lower right corner of the editor.

`spacing` holds the distances between things:

| Token | Distance |
| --- | --- |
| `margin` | From the viewport edge to a panel, and between the two panels. The notification is three margins in from the right and bottom edges. |
| `gap` | Between neighbours in the toolbar, and between stacked items inside a panel. |
| `button-padding` | From a button's edge to its text, left and right. |
| `row-inset` | From the list panel's edge to a row. |
| `panel-padding` | From the top of the list panel to its heading. |
| `editor-padding` | From the editor panel's edge to its contents. |

`dimensions` holds widths. The filter field takes the room left in the toolbar, between `filter-width-min` and `filter-width-max`. The list panel is `list-share` of the viewport's width, between `list-width-min` and `list-width-max`.

`density` holds heights: `toolbar-height`, `control-height` (buttons and the filter field), `row-height`, `title-height` and `notification-height`. Density is how much of the screen one item takes. Calm Blue and Night Teal are regular, Warm Paper is comfortable and Dense Ink is compact.

Nothing is made to fit. A workspace too large for its viewport is reported as an invalid scene, never squeezed or clipped.

## Elevation & Depth

`elevation` holds one number per raised thing: `panel` and `notification`. An element of elevation e casts a shadow of its own shape moved down by half of e, in black at an alpha of 0.24, fading to nothing across a band two e wide. An elevation of zero casts none. The shadow's formula belongs to the runtime renderer; the design chooses only e.

Calm Blue lifts panels slightly and the notification more. Night Teal uses deeper shadows. Warm Paper keeps panels flat and lifts only the notification. Dense Ink has no shadows at all and separates things with rules.

## Shapes

`rounded` holds corner radii: `control` (buttons), `field` (text fields and the editor body), `row`, `panel` and `notification`. Corners range from square in Dense Ink to large in Night Teal.

`borders` holds line widths: `panel`, `control` (quiet buttons), `field`, `focus` (the focus border, always wider than the others) and `divider` (the rule under the toolbar). A border is drawn inside the element's outline, so the shape that is seen is the shape that is hit.

Every element is a rounded rectangle. There is no other shape.

## Components

A component names the tokens one kind of element is drawn with. A component named `<component>-<state>` is that component in a state, and lists only what the state changes.

| Component | Element |
| --- | --- |
| `page` | The background. |
| `toolbar`, `divider` | The toolbar and the rule beneath it. |
| `panel` | The list panel and the editor panel. |
| `heading`, `label` | The list's heading; every label. |
| `button-primary` | The button that creates a document. One per workspace. |
| `button-quiet` | Every other button: sort, Save, Undo. |
| `field` | The filter field. |
| `title-field` | The open document's title. |
| `editor-body` | The open document's text. |
| `row`, `row-open` | A row of the list; the row of the open document. |
| `notification` | The notification. |

### States

The supported states are `default`, `hover`, `pressed`, `focused` and `disabled`. A state changes style values only. It never changes an element's box, its text or what it does.

- **hover** and **pressed** change a fill, or for a field at hover its border colour.
- **focused** replaces the border with `focus-ring` at the `focus` width, on every component alike.
- **disabled** draws the element at the `disabled` opacity, on every component alike.

Only elements that do something take a state: buttons, fields, the editor body and rows.

## Do's and Don'ts

- Do name a colour for its job. Don't add a token named for a hue.
- Do give every preset the same token names. A preset that needs a new token means every preset gets it.
- Do keep one accent per preset.
- Do change both this file and `configs/design/v1.json` together, and run `uv run core-ultra design check`.
- Don't name a preset after a brand, a product or a company.
- Don't copy a value from an existing product, a screenshot or an external design collection.
- Don't let a state move or resize an element.
- Don't put text below a contrast ratio of 4.5 to 1.
