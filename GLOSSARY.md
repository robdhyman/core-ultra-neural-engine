# Core Ultra neural engine

A native application runtime in which a trained neural network writes the visible interface as a scene that deterministic code draws, while a conventional kernel holds the truth. This glossary fixes the words used to describe it.

## Language

### Scene

**Scene**:
The structured description of one interface frame: its elements, their geometry and style values, the relationships between them and their states. It is the single source for both what is drawn and where a pointer hits.
_Avoid_: Layout, design scene, scene graph, frame

**Bound element**:
A scene element that carries text or an action. The application supplies its identity, role, text, binding and current state; the scene model never invents or alters them.
_Avoid_: Control, widget, interactive element

**Structural element**:
A scene element that carries neither text nor an action, such as a panel, divider or container. The scene model predicts whether it exists.
_Avoid_: Decoration, background, chrome

**Scene model**:
The trained network whose output is a scene, neither pixels nor code.
_Avoid_: Layout model, design model, generator

**Training renderer**:
The differentiable renderer that turns a predicted scene into an image so a training loss can compare it with a target image.
_Avoid_: Rasteriser, differentiable renderer alone

**Runtime renderer**:
The deterministic renderer that draws a scene as vectors in the running app. Visual results are always measured with it.
_Avoid_: Rasteriser, compiler, display renderer

### Rendering

**Rendering mode**:
One of the named ways the visible interface is produced. Always written as letter plus name: **A, Reference**; **B, Neural Raw**; **C, Neural Exact Text**; **D, Neural Scene**. The letters A to D belong to rendering modes only.
_Avoid_: Mode A/B/C/D alone, renderer, pipeline

**A, Reference**:
The rendering mode in which the generator's own known scene is drawn by the runtime renderer. It is the teacher and the baseline, never a neural result.
_Avoid_: Fallback, default renderer

**D, Neural Scene**:
The rendering mode in which the scene model writes the scene and the runtime renderer draws it. It is the primary neural mode.
_Avoid_: Vector mode, scene mode

**B, Neural Raw**:
The rendering mode in which a trained network produces every application pixel, including its attempts at text. Deferred baseline.
_Avoid_: Pure neural, full neural

**C, Neural Exact Text**:
The rendering mode in which a trained network produces surfaces and controls as pixels and a deterministic layer supplies exact text. Deferred baseline.
_Avoid_: Hybrid, composited mode

### Sessions

**Scripted session**:
A synthetic run of the app produced by the interaction generator, with no person involved.
_Avoid_: Synthetic episode, bot run

**Use log**:
The record of a person's real pointer, key and text input inside the app's own window.
_Avoid_: Telemetry, analytics, session recording

### Experiments

**Variant**:
One of the interface alternatives compared against each other in a study. Written **Variant 1**, **Variant 2**, **Variant 3**, never by letter.
_Avoid_: A/B/C, alternative, candidate, option

**Design condition**:
The declared set of design factors (such as navigation position, density, spacing) that distinguishes one variant from another.
_Avoid_: Layout condition, theme, style

**Visual preset**:
A named, coherent set of original style values (colour, type, spacing, radius, elevation, density) that the generator draws scenes in. Named descriptively, never after an existing brand.
_Avoid_: Theme, skin, brand

**Layout family**:
A group of generated scenes that share one structural arrangement and differ only in content, state or visual preset. Held out whole in evaluation.
_Avoid_: Template, layout type
