# Pixel-model spec (deferred baseline)

Status: deferred on 2026-11-24. See `docs/adr/0001-scene-model-replaces-pixel-model.md`.

This is the text of GitHub issue 1 ("Spec: first neural interface engine build, through the M3 exit") as it stood before the issue was revised for the scene-model pre-alpha. It is kept unchanged below as the specification of the deferred baseline: the rendering modes B, Neural Raw and C, Neural Exact Text. Nothing in it has been built.

---

## Problem Statement

Rob wants an interface whose visible pixels are produced by a trained neural network, not by a browser or a conventional widget toolkit, and wants it to be a real application rather than a picture of one. Today nothing exists: the repository holds only the build brief (`CORE_ULTRA_NEURAL_ENGINE_CLAUDE_CODE_HANDOFF.md`), a glossary and agent setup.

The brief covers seven milestones (M0 to M6). Planning all of them at once would mean writing most of the plan before anyone knows how well or how fast a small model trains on the one machine available (an Apple M5 with 16 GB of memory, macOS 27). The first build therefore needs a stopping point that is small enough to finish and strong enough to prove the idea is real.

## Solution

Build the engine through the brief's M3 exit: a native macOS application, with no browser engine anywhere in its display path, in which a person creates a document, edits its title and body, closes it, reopens it, and finds the exact saved content after restarting the process, all through an interface drawn by a trained neural network.

A small conventional kernel holds the truth (documents, commands, undo, revisions). A trained layout model and pixel model produce the picture. Three rendering modes exist side by side and are always named in full:

- **A, Reference**: a deterministic, conventionally drawn renderer. It is the teacher and the baseline, never a neural result.
- **B, Neural Raw**: the trained network produces every application pixel, including its attempts at text.
- **C, Neural Exact Text**: the trained network produces surfaces and controls; a deterministic layer supplies exact text. This is the usable mode.

The build ends with an honest acceptance report that says exactly what passed, what failed and what is unproven, on named hardware.

## User Stories

### Using the document workspace

1. As a person using the workspace, I want to create a new document, so that I have somewhere to write.
2. As a person using the workspace, I want to rename a document, so that I can find it later.
3. As a person using the workspace, I want to edit a document's body across multiple lines, so that I can write real content.
4. As a person using the workspace, I want my edits saved to storage, so that they are not only a picture on screen.
5. As a person using the workspace, I want to close a document and reopen it, so that I can move between documents.
6. As a person using the workspace, I want to find the exact content I saved after quitting and restarting the app, so that I can trust it with my writing.
7. As a person using the workspace, I want to see a list of my documents, so that I can choose one.
8. As a person using the workspace, I want to sort and filter the document list, so that I can find a document among many.
9. As a person using the workspace, I want to see a clear empty state and a clear no-match state, so that I know the list is empty on purpose.
10. As a person using the workspace, I want to undo my last change, so that a mistake does not cost me work.
11. As a person using the workspace, I want undo to restore document content without touching anything else I saved, so that recovering from one mistake cannot cause another.
12. As a person using the workspace, I want a click to act on the control I can see under the pointer, so that the picture and the behaviour agree.
13. As a person using the workspace, I want a click made while a new frame is still being generated to be rejected rather than applied to a different control, so that a slow frame never causes a wrong action.
14. As a person using the workspace, I want a rapid double click to commit its action once, so that I do not create two documents by accident.
15. As a person using the workspace, I want the layout to hold still while I hover, focus and type, so that controls do not move under my pointer.
16. As a person using the workspace, I want to move focus and activate controls from the keyboard, so that I am not forced to use the pointer.
17. As a person using the workspace, I want to scroll a long document list and a long document, so that content beyond the window is reachable.
18. As a person using the workspace, I want to resize the window and still hit the control I see, so that the interface survives ordinary window use.

### Text

19. As a person writing, I want the text I see in C, Neural Exact Text to be exactly the text that is saved, so that I never read a wrong character.
20. As a person writing, I want to type accented letters using macOS dead keys and press-and-hold accents, so that composition works the way it does in other apps.
21. As a person writing, I want multi-part emoji to behave as single characters when I select or delete them, so that my text is not corrupted.
22. As a person writing, I want to select text with pointer and keyboard, so that I can replace or copy it.
23. As a person writing, I want to copy, cut and paste through the system clipboard, so that I can move text in and out of the app.
24. As a person writing, I want long lines to wrap inside the text area the layout accepted, so that text never spills over a control.
25. As a person writing, I want to see a caret where my typing will land, so that I know where I am.
26. As a person writing, I want a fast response while typing even when the neural surface is reused, so that typing does not wait on the network for every key.

### Seeing that it is really neural

27. As Rob, I want to launch the app in each of the three rendering modes by name, so that I can compare them myself.
28. As Rob, I want the current rendering mode always shown in a developer panel, so that I never mistake A, Reference for a neural result.
29. As Rob, I want the app to refuse to fall back silently to A, Reference when neural inference fails, so that a failure is visible as a failure.
30. As Rob, I want to see the raw network output beside the final presented image, with a mask of anything drawn deterministically, so that I can see exactly which pixels are learned.
31. As Rob, I want to see the checkpoint in use and whether each frame was generated, cached or reused, so that I know what I am looking at.
32. As Rob, I want the neural modes to stop producing a working interface when the trained weights are replaced with random ones, so that I know the weights are doing the work.
33. As Rob, I want changing a document, a selection or an action to change the corresponding pixels, so that I know the picture follows the state and is not a stored screenshot.
34. As Rob, I want B, Neural Raw's text errors measured and shown rather than hidden, so that I know how far raw neural text is from usable.
35. As Rob, I want a short clip of a real interaction built from the app's own presented frames, so that I can show the result without recording my screen.
36. As Rob, I want the neural modes to run with the reference renderer's code absent, so that I know the teacher is not secretly drawing the interface.

### Trusting the result

37. As Rob, I want one acceptance report with a status for every test row and a path to its evidence, so that I can check any claim.
38. As Rob, I want failed and blocked rows left visible in that report, so that the report cannot flatter the result.
39. As Rob, I want the report to state whether the build is only a pipeline proof or reaches a usable level, so that I know which claim it has earned.
40. As Rob, I want the M3 exit gated by a scripted driver over 100 held-out document episodes with an independent check of stored content, so that the result rests on more than one lucky run.
41. As Rob, I want to perform one manual pass of the workflow myself after the scripted gate, so that a human has confirmed the interface is usable and not only passable by a script.
42. As Rob, I want at most one diagnosed retraining attempt if a gate fails, followed by a report, so that the build cannot turn into open-ended tuning.
43. As Rob, I want every reported number tied to the hardware, checkpoint, dataset split and rendering mode that produced it, so that results can be reproduced.
44. As Rob, I want training evidence to be real loss logs and a reloadable checkpoint, so that nobody can claim a model was trained by checking in an unrun script.

### Cost, privacy and consent

45. As Rob, I want all training and inference to run on this Mac first, so that the build costs nothing unless a measurement says otherwise.
46. As Rob, I want any cloud run brought to me as one concrete configuration with card, hours and price before it starts, so that the pre-approved $50 is spent on a measured need.
47. As Rob, I want the app to keep a use log whenever it runs, limited to pointer positions, key presses and text typed inside the app's own window, so that failures I hit by hand can be replayed.
48. As Rob, I want a visible marker in the developer panel while the use log is recording, so that I always know it is on.
49. As Rob, I want the use log, weights and datasets kept on this Mac and out of git, so that nothing I type reaches the public repository.
50. As Rob, I want to remove the use log by deleting one folder, so that removal needs no tool.
51. As Rob, I want to be asked again, in a consent form, before the app records anything beyond what I agreed to, so that the scope of recording cannot grow quietly.

### Building and maintaining it

52. As a developer, I want a doctor command that reports OS, Python, accelerators, memory, disk and usable ML dependencies, so that every later number is tied to a known machine.
53. As a developer, I want a locked, reproducible Python environment, so that a fresh session can run the build without guessing versions.
54. As a developer, I want a smoke configuration that generates data, trains, evaluates and runs in minutes, so that the whole pipeline can be checked quickly.
55. As a developer, I want a pilot configuration capped at two hours with resumable checkpoints, so that an interrupted run is not lost.
56. As a developer, I want compute and time caps in configuration, so that a run cannot exceed what was agreed.
57. As a developer, I want training data generated by scripted sessions with splits assigned before generation, so that test frames never leak from training trajectories.
58. As a developer, I want each training example to record the state before, the input event, the validated command and the state after, so that the model learns action effects and not only appearance.
59. As a developer, I want invalid actions, rapid input, cancellation and recovery included in the scripted sessions, so that the model is not trained only on happy paths.
60. As a developer, I want an ablation runner (trained versus random weights, correct versus shuffled conditioning, correct versus withheld interaction state, raw versus final, reference versus each neural mode), so that the neural contribution is measured and not asserted.
61. As a developer, I want to drive the whole runtime without a window, feeding input events and reading presented frames, so that most behaviour is tested quickly and deterministically.
62. As a developer, I want inference to run in a separate worker with revision-tagged messages, so that a slow or crashed model cannot freeze input handling or apply an out-of-date frame.
63. As a developer, I want the look of A, Reference specified in one machine-readable DESIGN.md, so that the teacher's appearance is declared data and its variations are named factors.
64. As a developer, I want a record at the end of each milestone of what runs, what was tested, what failed and the next executable step, so that the next session starts from facts.
65. As a future maintainer, I want the model, the dataset and the checkpoint described by manifests with hashes, so that a result can be traced to the exact artifacts that produced it.

## Implementation Decisions

### Scope and sequence

- The spec covers the brief's milestones M0 (repository and hardware assessment), M1 (real application kernel and native host), M2 (first genuinely trained neural display) and M3 (closed interaction loop and dependable text), with the exits the brief gives each one.
- The brief remains the detailed reference for contracts this spec summarises. Where this spec and the brief differ, this spec wins, because it records decisions made after the brief was written.
- Tested platform is macOS 27 on an Apple M5 with 16 GB of memory. No cross-platform claim is made.
- The earlier handoff the brief mentions (`CORE_ULTRA_CLAUDE_CODE_HANDOFF.md`) and its web harness are not available. The build proceeds without them; A, Reference is the only baseline.

### Architecture

- **Application kernel.** Holds documents, commands, validation, transactions, undo and revisions in SQLite. Commands are create, open, rename, edit, save, list, sort/filter and undo. Each command carries a command ID and an expected revision; a command commits at most once, and a retry of inference never repeats a write.
- **Documents app adapter.** Describes the committed application state as a semantic manifest: stable entity IDs, roles, exact strings, enabled actions and relationships. It contains no screen coordinates and no finished image.
- **Layout model.** A small trained transformer encoder (starting point: about four blocks, width 192) that proposes per-entity position and visibility from the semantic manifest, the viewport and the design condition, for up to 32 visible entities. Overflow is reported, never silently dropped.
- **Layout validation.** A proposed layout may be rejected or projected into allowed bounds. The pixel model always renders the validated geometry. Hit regions and labels are never moved after pixels are generated.
- **Pixel model.** A compact trained multiscale convolutional decoder producing the RGB raster from the manifest, the validated layout, the interaction state and the rendering mode. Resolution starts at 256×160 for the plumbing check, then 512×320. It is stateless: it renders from the current committed state, with no previous-frame conditioning in this spec.
- **Inference worker.** Runs the models in a separate process from the native host, over local messaging with bounded queues. Messages carry revisions; out-of-date results are discarded.
- **Frame bundle.** Every presented scene is one immutable bundle: frame identity, application and presentation revisions, viewport and scale, checkpoint and mode, timings, raw and final image hashes, validated geometry, exact labels with their permitted command bindings, focus order, text regions, accessibility node data, and a mask of deterministic overlays. The accessibility node data is carried in the bundle now; exposing it to the operating system is a later spec.
- **Runtime session.** The single interface that ties the above together: it accepts an input event tagged with the frame it was aimed at and returns the next frame bundle. It resolves coordinates using the bundle that was on screen, rejects actions whose preconditions no longer hold, and on a failed update keeps the last valid scene marked stale while blocking unsafe actions. It runs with or without a window and in all three rendering modes. This is the primary test seam.
- **Native host.** A PySide6 custom drawing surface that presents the bundle's image and forwards pointer, keyboard, text-composition and clipboard events to the runtime session. No QtWebEngine, WebView, HTML, CSS or JavaScript renderer anywhere in the display path. Qt supplies the window and OS integration only, not buttons, lists or cards.
- **Display scaling.** Model output is letterboxed and scaled to the window. Exact text is drawn at the screen's native resolution.
- **Deterministic text layer (C, Neural Exact Text only).** Draws exact labels, document content, selection, caret and composition using real text shaping and font metrics, inside the text bounds the layout accepted. The pixel model is trained on text-free targets for this mode; correct labels are never painted over conflicting generated labels. A fast text-edit path may reuse an unchanged neural surface, creating a new presentation revision and logging the reuse; a reused surface does not count as a newly generated neural frame.
- **Reference renderer.** A separate package that the neural launch modes do not load. It produces training targets and the comparison baseline. The neural modes must run with it absent.
- **Developer instrumentation.** A panel separate from the application content showing the rendering mode, checkpoint, raw-versus-final comparison, overlay mask, whether the frame was generated, cached or reused, and the use log marker. It is excluded from neural-coverage measurements.
- **The model's limits.** The model cannot invent an executable command, grant a permission, choose a file destination or declare an operation successful. Commands come only from the kernel's bindings in the frame bundle.

### Reference look

- The appearance of A, Reference is specified by one original, neutral DESIGN.md written for this project in the Google Labs DESIGN.md format (machine-readable tokens for colour, type, spacing, radius and components). Third-party style files are used only as a model of structure and are not copied into the repository.
- The design condition is the declared set of design factors that training varies: navigation position, density, spacing and notification location. The layout is recomputed only at a navigation change, a viewport change or an explicit design-condition change, never during hover, focus or typing.

### Data and training

- Training and test data come from scripted sessions against the kernel, drawn by the reference renderer. Each example records state before, input event, validated command, state after, semantic manifest, viewport, design condition, layout targets, full and text-free image targets, entity masks, text regions, focus, selection, scroll and clipping.
- Splits are assigned before generation, 80/10/10 by episode family, with document strings, task seeds and selected layout and viewport combinations held out. Neighbouring frames of one trajectory never straddle train and test. Duplicates and reference-image leakage are checked.
- Sizes: a smoke set of 64 to 256 frames, then a 5,000-frame pilot. Expansion toward 25,000 to 100,000 frames is decided from the pilot's learning curves and throughput.
- Training order: overfit a tiny known batch first to prove gradient flow and data alignment, then train on disjoint examples and evaluate on held-out ones. The overfit result is reported as a plumbing check, not as a renderer.
- Both targets are trained: the full-text target for B, Neural Raw and the text-free target for C, Neural Exact Text.
- Losses start with pixel L1, edge reconstruction, per-entity geometry, visibility and invalid-overlap penalties, with region weighting so that background cannot dominate small controls. Each term and weight is recorded.
- Checkpoints are resumable and described by a manifest with hashes. Portable tensor weights only.

### Commands

The engine is driven by one command-line entry point with these verbs: `doctor` (environment report), `data generate`, `train`, `evaluate` (including the acceptance and ablation suites) and `run` (with a rendering mode and a checkpoint). Smoke and pilot are configurations, not separate programs. This is the second test seam.

### Compute

- Python 3.12 managed with `uv`, with locked dependencies. PyTorch on the Apple GPU path (MPS), which does not support 64-bit floats; CPU validates plumbing only.
- Caps: smoke run about 10 minutes, pilot 2 hours, both configurable.
- Up to $50 of rented cloud GPU is pre-approved for this small model, to be used only if the timed pilot shows the Mac is the limit. The default is one RTX 4090 on RunPod. Before any spend, the session brings Rob one concrete run (card, hours, price). Rob creates the cloud account and enters payment himself. No diffusion or flow renderer and no large checkpoint download is covered.

### Use log and local artifacts

- The app keeps a use log whenever it runs. It records pointer positions, key presses and text typed inside the app's own window only. It is stored on this Mac under the local artifacts area, read only by Rob and by agent sessions working in this repository, never uploaded, and removed by deleting its folder. Rob agreed to exactly this on 2026-11-24. Recording anything more requires a new consent form first.
- Weights, datasets, evidence and the use log stay local and out of git. Manifests, hashes and reports are committed. The repository is public.
- The demo clip is assembled from the app's own presented frames, not from screen recording.

### Exit and failure rule

- The M3 exit is gated by a scripted driver that posts real pointer and key events at displayed coordinates over 100 held-out multi-step document episodes, with an independent check of stored content, followed by one manual pass by Rob.
- If a gate fails, one diagnosed retraining attempt is allowed within the compute caps. If it still fails, the spec ends with the failure recorded. Unreadable text in B, Neural Raw is an expected finding and is reported, not tuned.

### Acceptance rows in this spec

The acceptance report covers the brief's rows N1 to N9 with a pass, fail or blocked status each: browser independence, neural raster provenance, training executed, held-out visual and interaction quality (at least 1,000 held-out frames, 30 inspected by eye), real task completion (at least 95 of 100 episodes), persistence and undo, visible target alignment (visible-region to hit-region overlap of at least 0.90), exact text, and revision and race handling. Input-to-presentation latency (N10) is measured and reported per stage but is not a gate here. Rows N11 to N15 are listed as not attempted in this spec.

## Testing Decisions

- A good test here checks behaviour a person or an operator could observe: what is stored, which frame bundle is presented, which command an input resolves to, which files a command produces. It does not assert on network internals, layer shapes, private helpers or the order of internal calls.
- **Seam 1, the runtime session.** Most tests feed input events aimed at a presented frame and assert on the returned frame bundle and on the document store, which is read independently of the runtime. This seam covers the document workflow, restart and crash recovery, undo, stale and repeated input, delayed inference, coordinate conversion under resize and scaling, hit-region alignment, text editing and composition, and the rule that neural modes never fall back silently. It runs without a window. It runs against A, Reference for speed and determinism, and against the neural modes with a small fixed checkpoint.
- **Seam 2, the command line.** Tests run `doctor`, `data generate`, `train` and `evaluate` on a tiny configuration and assert on what is produced: the dataset manifest and its split policy, loss logs, a reloadable checkpoint with a matching hash, ablation outputs and the acceptance report's rows. Split-leakage and duplicate checks are tested here.
- **Native host.** A few thin tests open the real surface off screen and confirm that native pointer, key and composition events reach the runtime session with the correct frame identity. The scripted M3 driver exercises the real window end to end.
- **Independence of judges.** No test uses the model's own masks, confidences or descriptions as the only judge of correctness. Expected results come from the kernel and the generator's declared contract.
- **Browser independence** is tested by inspecting the imports and processes of a neural-mode run, and by running the neural modes with the reference package absent.
- **Prior art.** None: the repository has no code or tests yet. These two seams set the pattern for later specs.
- Measurements that need the real accelerator (training quality, latency) are produced by the evaluation commands and recorded in reports; they are not unit-test assertions.

## Out of Scope

- M4: a platform accessibility tree verified with a screen reader, latency and frame-rate gates, fault-injection and long-session testing, model reload.
- M5: the experimental workspace, variants, preference records and adaptation.
- M6: any Claude API or other language-model integration, intent handling, and a second application.
- The brief's route toward broader browser replacement, including any web compatibility work.
- Hand-verified Chinese, Japanese or Korean input, and right-to-left text. CJK composition is exercised with synthesized input-method events only.
- Previous-frame or recurrent conditioning, and any diffusion, flow or latent renderer.
- Reusing a public pretrained checkpoint.
- Cloud spend beyond the pre-approved $50, and any cloud account creation by an agent.
- Platforms other than macOS 27 on Apple silicon.
- Packaging a distributable native executable.

## Further Notes

- Decisions and their sources are recorded in the repository: the grilling note under `.scratch/m3-first-build/`, unit prices in `docs/research/compute-pricing-2026-11.md`, design sources in `docs/research/design-sources-2026-11.md`, and vocabulary in `GLOSSARY.md`.
- Vocabulary: rendering modes are always written letter plus name. "Variant" and "design condition" follow the glossary. "Frame bundle", "semantic manifest", "runtime session" and "kernel" are used here as the brief uses them and are not yet in the glossary.
- Every figure in the brief and in this spec (model sizes, dataset sizes, gates) is a starting configuration, not a validated requirement. A gate that needs revising is revised and versioned before the new run is evaluated, and the original result is kept.
- Measurements are never fabricated and a mock inference result is never substituted for a real one. If training cannot run, M2 is reported blocked.
- Standing rules for any session working this spec, carried verbatim from the owner's instructions:

  > - When work is finished, end with "Done. Next: <step>". Decide small leftovers (formats, defaults, wording) yourself, record them, and mention them in one clause at most. Never end by listing undecided items or asking whether to ask.
  > - If a decision is genuinely Rob's, put it in an AskUserQuestion form immediately: recommended option first, evidence and alternatives beside each option. This applies in every session, whatever the brief's scope.
  > - A brief written for another session carries the rules above verbatim, including the consent rule below.
  > - A hand-off or note for Rob is written inside the repo (`.scratch/<feature>/handoff-<slug>.md`), linked in the message, and sent with SendUserFile. Never only in a folder outside the repo.
  > - Consent before monitoring. Before asking Rob to install, enable, or keep running any software that records his activity (window titles, keystrokes, screen, browser history, location, audio, files, time tracking, analytics on his own use), stop and put it to him in an AskUserQuestion form that states in plain words: what it records, where the data is stored, who can read it, when it runs, and how to remove it. Do this before the install step, never after, and never as a line inside a longer guide. This holds in every session and every brief, with no expiry.
