# Core Ultra — Build the neural interface engine

**Claude Code implementation brief · November 24, 2026**

**User direction:** Build “a new neural engine that directly generates interactive pixels or replaces the browser.” Take this literally.

**Status:** This is a build specification, not an implementation or a report of achieved results. Architecture, training sizes, and performance gates below are proposed engineering defaults. Their feasibility must be measured.

**Relationship to the earlier handoff:** This brief supersedes the browser frontend and code-generation execution target in `CORE_ULTRA_CLAUDE_CODE_HANDOFF.md`. It preserves Core Ultra’s experimental workspace, progressive tasks, repeated A/B/C comparisons, and adaptation from evidence. The earlier web harness may become a comparison baseline or data source; it does not satisfy this build.

## 1. Your assignment

Build a native application runtime in which a trained neural network produces the visible interface as an RGB image tensor. Mouse and keyboard events must cause real application operations, followed by new neural frames. The application must work without a browser, WebView, HTML, CSS, or JavaScript renderer in its production display path.

The first application is a small document workspace. A user creates a document, changes its title and body, closes it, reopens it, and finds the exact saved content after restarting the process. Its controls and surfaces must be visibly rendered by learned model weights.

The intended loop is:

1. Receive a native input event against the frame actually on screen.
2. Resolve it to a permitted application command.
3. Execute that command against authoritative application state.
4. Give the resulting state and interaction context to the neural rendering pipeline.
5. Present its pixels together with the matching interaction and accessibility metadata.

**A document depicted in generated video is insufficient. A document written to storage, manipulated through neural pixels, and recovered after restart is the target.**

Keep the ambition and make the first supported domain small. Do not quietly convert this assignment into a conventional web app, screenshot slideshow, prompt-to-code tool, or neural wallpaper behind ordinary widgets. Do not stop after implementing a model interface with a stub behind it.

### Claims this project can earn

| Claim | Evidence required |
| --- | --- |
| Direct neural pixel renderer | A trained network outputs the displayed raster, including actionable control surfaces. Weight and conditioning ablations affect those pixels. |
| Functional neural application runtime | Actions through that raster change real state correctly, survive restart, and support recovery. |
| Browser replacement for Core Ultra applications | Those applications run in the native host without a browser engine. Input, text, semantics, storage, and lifecycle are implemented by this runtime. |
| General replacement for Chrome/Safari/Firefox | Existing web content and applications work against an explicitly tested compatibility surface. The first three claims do not establish this one. |

Build toward the first three. Retain the general browser goal as a separate compatibility workstream with real conformance tests.

## 2. Architecture and responsibilities

Use a small executable kernel for truth and a learned renderer for presentation. A neural renderer does not require a neural database, neural permission system, or probabilistic file writes.

| Part | Responsibility | Initial implementation |
| --- | --- | --- |
| Application kernel | Records, commands, validation, transactions, undo, revisions | Python, typed contracts, SQLite |
| Semantic manifest | Stable entity IDs, roles, exact strings, enabled actions, relationships | Produced from the committed application snapshot |
| Layout model | Propose positions and grouping from semantics, viewport, and design conditions | Small PyTorch encoder with per-entity geometry heads |
| Pixel model | Produce the actual raster of the interface and its interaction states | Conditional convolutional decoder; upgrade only when evidence warrants it |
| Native host | Input, presentation, focus, text composition, clipboard, accessibility | PySide6 custom drawing surface; no QtWebEngine |
| Experiment controller | Task assignment, trials, preference records, adaptation checkpoints | Separate trusted module and persisted records |

This is an architecture proposal, not a claim that this exact network will achieve all quality targets. Change the model if experiments justify it; preserve the runtime contract.

### Suggested stack

- Python and PyTorch for training and initial inference. Inspect CUDA, MPS, and CPU support on the actual development machine. Do not infer GPU capability from a browser user-agent or this document.
- A custom PySide6 `QWidget` or `QWindow` that presents a model-produced image. Start with an image blit; move to a GPU texture presentation path when profiling shows a need. Qt supplies windowing and OS integration, not the application’s button/list/card renderer.
- SQLite with transactional commands and a journal for durable state. Separate document data, runtime revisions, and experiment records.
- A separate inference worker so training or inference cannot block native event handling. Use bounded queues and revision-tagged messages. Start with local IPC; a network service is unnecessary.
- Structured configuration, a locked dependency environment, resumable checkpoints, and portable tensor weights plus a manifest.

If the installed Python bindings cannot expose the required accessibility or input interface correctly, write a small native bridge. Record the tested OS. Do not claim cross-platform accessibility because a library advertises support.

### State, geometry, and pixels

Implement these conceptual interfaces; adapt names to the repository:

```python
next_state = kernel.apply(command, expected_revision, command_id)
manifest = app.describe(next_state)
layout_proposal = layout_model(manifest, viewport, design_condition)
layout = validate_layout(layout_proposal, manifest, viewport)
raw_rgb = pixel_model(manifest, layout, interaction_state, render_mode)
bundle = build_and_validate_bundle(next_state, manifest, layout, raw_rgb)
host.present(bundle)
```

`validate_layout` may reject a proposal. If it projects geometry into allowed bounds, the pixel model must render the corrected geometry afterward. Never move hit regions or labels independently after pixels are generated.

The semantic manifest may identify a button as “Create document” and attach its allowed command. It must not contain a finished screenshot. The initial app adapter must not contain handwritten screen layout coordinates used as the neural runtime’s answer.

The learned layout is held stable during ordinary interaction. Hovering, typing, or focusing a control must not randomly rearrange the workspace. Recompute structure at a navigation change, viewport change, or explicit adaptation checkpoint. Version and log such changes.

### FrameBundle contract

Every presented scene must have one immutable bundle containing:

- `frame_id`, application revision, presentation revision, viewport and scale;
- model/checkpoint identifiers, seed, renderer mode, and inference timings;
- raw neural image and final presented image identifiers/hashes;
- validated entity geometry, clipping, z-order, and visible/enabled state;
- exact semantic labels and allowed command bindings from the kernel;
- focus order, text regions, and accessibility nodes derived from that same revision;
- a provenance mask for deterministic overlays, if any.

Input events carry the `frame_id` that was presented when they were received. Convert native coordinates using that bundle’s viewport, device scale, letterboxing, and scroll transform. Resolve pointer capture and pointer-down/up against stable targets. Reject stale actions when their state preconditions no longer hold; never reinterpret a click against a newly generated layout.

Commit actions once using command IDs and transactions. An inference retry must not repeat the write. Discard out-of-date inference results. During a failed update, retain the last valid scene with a clearly marked stale/pending state and prevent unsafe stale actions. Never represent old pixels as a successfully updated screen.

The model cannot invent an executable command, grant permission, select a filesystem destination, or declare an operation successful. A new application capability needs an executable adapter and tests. Its visual form need not be a registered widget template.

## 3. Implement three explicit rendering modes

### Mode A — `reference`

A deterministic renderer supplies training examples, comparison results, and diagnostic recovery. It can use conventional drawing functions. Its imports and assets belong in a separate package that neural launch modes do not load.

Always label this mode. It is not a neural milestone. Do not silently switch to it when neural inference fails.

### Mode B — `neural_raw`

The network supplies the entire application content raster, including text attempts, control surfaces, and visual responses. The native OS cursor, window decorations, and a clearly separate diagnostic panel are permitted and must be excluded from neural-coverage measurements.

No deterministic application labels, control outlines, conventional widgets, reference screenshots, or pre-rendered screen tiles may be composited into this mode. Save the tensor before display and the actual presented buffer so this can be audited.

This mode is mandatory. Evaluate actual text errors, misplaced controls, flicker, and failures without hiding them. A failed raw-text experiment is useful evidence, but it is not permission to call raw text reliable.

### Mode C — `neural_exact_text`

Use the same learned layout and genuine neural rasterization for application surfaces and controls. Add a deterministic text layer for exact labels, document contents, selection, caret, and input-method composition. Add a native accessibility bridge based on the same semantic manifest.

Train this mode with clean, text-free target regions before composition; do not paint correct labels on top of conflicting generated labels. The model may still produce spurious marks, so inspect for them and report failures. A model-produced confidence score does not guarantee visual correctness.

Use real text shaping and font metrics. Handle Unicode graphemes, selection, clipboard, and composition events rather than treating each keypress as one printable character. Wrapping must use the accepted text bounds; reject or regenerate a layout that cannot display its required content. Do not quietly repair the full interface with conventional widgets.

A fast text-edit path may reuse an unchanged neural surface while updating exact text, provided it creates a new coherent presentation revision and verifies that geometry and other visual state remain valid. Log this reuse. It does not count as a newly generated neural frame.

This is the initial usable mode. Report it precisely as a **native runtime with neural surfaces and deterministic text/semantics**. It does not satisfy the stronger claim that every content pixel is neural.

For every demo, expose raw-versus-final comparison, overlay masks, checkpoint ID, current mode, and whether a frame was generated, cached, or reused. Put these in developer instrumentation, not in the participant’s task flow.

## 4. First model: small, trained, inspectable

Do not begin by fine-tuning a text-only language model and expecting an RGB renderer to appear. Do not make reproduction of a large world model a prerequisite for the first experiment.

Start with a compact supervised model for the document workspace. These sizes are starting configurations, not validated requirements:

1. **Inputs:** a padded set of up to 32 visible semantic entities, parent/order information, type/role features, enabled/selected/focused flags, exact string encodings, viewport, design condition, and interaction state. Report and handle overflow rather than silently dropping entities. Use scrolling/virtualization through an explicit viewport contract.
2. **Layout encoder:** begin with roughly four transformer blocks, width 192, and per-entity normalized bounding-box/visibility heads. Use stable input slots bound to kernel entity IDs; do not ask the model to generate arbitrary IDs or command strings.
3. **Raster conditioning:** construct spatial feature fields from predicted geometry and learned entity embeddings. These fields are model inputs, not finished control artwork. A deterministic splat of abstract features is permissible; a hidden conventional renderer supplying final buttons is not.
4. **Pixel decoder:** start with a compact multiscale convolutional decoder producing `[B, 3, H, W]`. Begin at 256×160 for the plumbing check, then test 512×320 and increase resolution only after measurements. Keep displayed scale and native model resolution explicit.
5. **Training modes:** condition on `raw` versus `exact_text`; provide the corresponding full-text or text-free target. Use byte/character-aware text features for raw experiments. Exact text remains a hard research test, especially for unseen strings.
6. **Losses:** begin with normalized pixel L1, edge reconstruction, per-entity geometry, visibility, and invalid-overlap penalties. Add region weighting so background pixels cannot dominate small controls. Record each term and weight. Geometry and mask supervision must be grounded in independently generated labels.

First overfit a tiny known batch to prove gradient flow and data alignment. Then train on disjoint examples and evaluate generalization. An overfit model is a plumbing milestone, not a useful renderer.

Begin stateless: render from current committed state so a long history cannot silently overwrite facts. Add previous-frame or recurrent conditioning only if needed for transitions and continuity. When introduced, keep explicit state as the anchor, train on some model-generated histories, and evaluate long rollouts and history resets. Measure whether conditioning on the previous frame causes the model to ignore changes.

A deterministic regressor may blur ambiguous targets. Make each target reproducible from its conditioning and seed. If fidelity remains inadequate, compare a latent decoder or conditional flow/diffusion renderer behind the same interface. A checkpoint conversion, distillation, or additional model requires an actual held-out comparison before promotion.

Do not require a particular unpublished model or unavailable weights. If reusing a public checkpoint, verify its actual download, license, hardware needs, and inference path; record its hash. If none fits, execute the small from-scratch experiment.

### Prove the neural contribution

On the same previously unseen states, record:

- trained weights versus randomly initialized weights;
- trained weights versus disabled inference, with caches cleared;
- correct versus shuffled state conditioning;
- correct versus withheld interaction-state conditioning;
- raw neural output versus final composited output;
- the reference renderer versus each neural mode.

Removing trained weights must prevent the neural modes from producing the working interface. Changing a record, selection, or action must affect the corresponding pixels. A trained neural background behind deterministic controls fails this test.

Also measure functional generalization. Weight sensitivity alone does not rule out memorization or screenshot retrieval.

## 5. Generate the training environment and dataset

Build a deterministic reference document workspace and scripted interaction generator. The reference renderer is the teacher and baseline; it must not be a runtime dependency of the neural mode.

Each example/transition records:

```text
episode_id, split, app_id, generator_version, generation_seed
state_before, input_event, validated_command, state_after
semantic_manifest, viewport, design_condition, layout_targets
full_rgb_target, text_free_rgb_target, entity_masks, text_regions
focus, selection, scroll, clipping, expected_task_outcome
```

Start with 64–256 frames for a smoke test, then a 5,000-frame pilot. Use its learning curves and throughput to decide whether to expand toward 25,000–100,000 frames. Those are planning ranges, not a promise of adequate data. Record storage size and generation/training time before scaling.

Vary real factors: document count, titles and bodies, empty/no-match states, enabled/disabled controls, focused/pressed states, scroll positions, viewport size, navigation position, density, spacing, and notification location. Include invalid actions, rapid input, cancellation, and recovery. Do not train only on successful happy paths.

Assign splits before generating episodes. A reasonable initial split is 80/10/10 by episode family. Keep document strings, task seeds, and selected layout/viewport combinations held out. Never randomly split neighboring frames from the same trajectory across train and test. Detect duplicates and reference-image leakage. Maintain a separate harder set for unseen compositions rather than implying within-distribution accuracy establishes open-ended behavior.

Use synthetic or explicitly supplied content. Preserve provenance and license information for any added external dataset. Do not upload the user’s workspace history merely because telemetry would be useful.

Repeated screenshots can teach appearance but not reliable action effects on their own. Store the command/state correspondence. The generator and evaluators must share a declared contract without using the trained model to invent expected results.

Once the first runtime is operational, capture its failures as replayable training candidates. Review and correct labels before promoting them. Freeze test sets and record dataset versions; failed held-out cases moved into training require a new independent evaluation set.

## 6. Build in milestones with runnable exits

### M0 — Repository and hardware assessment

Read repository instructions, inspect existing work, and create an isolated branch/directory without discarding it. Record OS, Python, available accelerators, memory, disk, and usable ML dependencies. Read current official dependency documentation where needed.

Produce a short architecture note and actual run commands. Adopt defaults here instead of conducting another product-discovery interview. Continue through independent implementation if a credential, download, or GPU is unavailable; mark dependent checks blocked.

**Exit:** environment report, configured local compute/time limits, repository skeleton, and documented module contracts. No “engine built” claim yet.

### M1 — Real application kernel and native host

Implement create, open, rename, edit, save, list, sort/filter, and undo commands. Persist document IDs and content. Open a native surface, capture input, establish the frame contract, and drive it with the explicitly labeled reference renderer. Implement revision checks and crash/restart tests now.

**Exit:** the document workflow works and survives restart. This is the functional substrate, still conventionally rendered.

### M2 — First genuinely trained neural display

Generate the smoke dataset, train the first decoder, save weights, and connect inference to the native surface. Then run the pilot with disjoint examples. Implement both raw and exact-text output targets and the ablation runner.

**Exit:** actions in the native app produce newly inferred RGB tensors; a checkpoint and real training logs exist; held-out outputs and failures are saved. The reference renderer can be removed from the neural runtime environment without breaking inference. State whether this is only a pipeline proof or meets a usable quality level.

Do not complete M2 by checking in a training script that nobody ran. If training cannot run, report M2 blocked and continue only with work that does not pretend it succeeded.

### M3 — Closed interaction loop and dependable text

Connect predicted geometry, pixels, exact labels, and command bindings. Implement focus, keyboard activation, scrolling, text selection, undo, and input-method composition. Reject invalid or stale frames. Test rapid interaction while inference is delayed. Add raw/final/provenance inspection.

**Exit:** a person creates, edits, closes, and reopens a document through the neural interface. An independent state check confirms exact content. Every tested click resolves against the correct displayed frame and record.

### M4 — Accessibility, performance, and recovery

Implement a real platform accessibility tree, including names, roles, bounds, enabled/focused state, action interfaces, and change events. Verify it with the target OS’s accessibility inspector and at least one screen reader. A JSON tree in a debug panel is insufficient.

Profile host input, kernel commit, layout inference, raster inference, transfer, composition, and presentation separately. Test renderer crashes, malformed output, stale jobs, and model reload. Reuse model weights across sessions; store/recover the selected layout condition without rolling back documents.

**Exit:** the acceptance report below identifies passed/failed/blocked checks on named hardware. Working exact-text mode and limitations of raw mode are reported separately.

### M5 — The experimental workspace

Implement progressively harder tasks: create; edit/find; sort/filter/change view; handle a notification and resume; evaluate three interface alternatives and adopt one. Keep tasks and completion criteria as editable data.

For each study, vary one declared factor first—such as navigation position. Generate A/B/C through model conditioning, validate and freeze them, and expose equivalent capabilities. Persist seeds, checkpoint hashes, layout conditions, and accepted frame/layout references. Do not merely select three pre-baked screen images.

Use matched task instances, independent trial state snapshots, and randomized or counterbalanced order. Record completion, time, mistakes, recovery, generation delay, invalid-frame frequency, and explicit preference including “no preference” and “none of these.” Keep visual generation failures separate from the UX factor under test: an unreadable label can confound a navigation comparison.

Freeze model weights within a study block. Keep renderer training data and user-preference evidence separate. Adapt at visible checkpoints, defaulting to a proposal with apply/keep/undo. Do not rearrange the interface during a task unless that behavior is itself the experiment. Exclude reserved evaluation trials from preference updates and log exposure/assignment policy changes.

**Exit:** a full trial block produces a reviewable adaptation linked to recorded evidence. Documents survive variant changes. Results can be inconclusive without the system treating that as a software failure.

Preserve the user’s hypothesis: repeated tests may reveal an individual UX/UI preference. Keep stated preference, measured performance, and repeatability distinct. Resemblance to the user’s own design work is a motivating prediction, not a trained target or acceptance criterion. One person’s results do not establish universal conventions.

### M6 — Intent, AI collaboration, and a second application

Add the selected Claude API provider for high-level intent and discussion. Use a configurable model ID and current official documentation. Claude Code is the development agent; the application’s Claude API is a separate optional configuration until this milestone. The renderer itself must not require an LLM call per click or frame.

Translate intent into validated semantic/design proposals and permitted tool commands. Support discussion of a change, three functioning candidate previews on isolated branches, and adoption of the selected interface while preserving current document data. Missing API access blocks this AI acceptance case, not local rendering or document operations.

Add a second small adapter, such as tasks with status/priority and list/board presentations, using the same runtime contract. Test it with the frozen checkpoint first to measure transfer; if training is needed, version the expanded dataset/checkpoint and report that fact. Do not call retraining zero-shot generalization.

**Exit:** the engine runs two app adapters without a custom handwritten renderer for each screen. Unsupported intents are reported concretely. New executable capabilities require real implementation; apparent visual flexibility is not evidence of arbitrary software execution.

## 7. Acceptance report and measurement rules

Write `reports/acceptance.md` with evidence paths, hardware, checkpoint, dataset split, renderer mode, and a status for every row. The figures below are initial project gates, not research findings or guaranteed achievable performance. If a target needs revision, explain and version it before evaluating the new run; retain the original result.

| ID | Test | Initial gate/evidence |
| --- | --- | --- |
| N1 | Browser independence | Native workflow runs with no browser/WebView engine or remote browser renderer. Inspect imports/processes and runtime packaging. |
| N2 | Neural raster provenance | Raw tensor, final buffer, overlay mask, model hash, and trained/random/off/shuffled ablations demonstrate learned rendering of controls. |
| N3 | Training executed | Real loss logs and reloadable weights; overfit smoke test separated from held-out pilot results. |
| N4 | Held-out visual/interaction quality | At least 1,000 held-out state frames; report accepted/rejected coverage. Initial goal: at least 95% accepted without conventional fallback. Inspect at least 30 stratified images independently for visible controls and misleading marks. |
| N5 | Real task completion | At least 100 held-out multi-step document episodes; initial goal: at least 95 completed through displayed coordinates. Every acknowledged commit must match the intended record and content. |
| N6 | Persistence and undo | Restart and crash-recovery cases preserve acknowledged writes and IDs. UI/model rollback does not revert document data. |
| N7 | Visible target alignment | Independently selected screen coordinates activate the visually indicated control. Include edges, overlaps, clipping, scroll, resize, and device scaling. Initial geometric diagnostic: visible-region/hit-region IoU at least 0.90, with distributions reported. |
| N8 | Exact text | In exact-text mode, corpus labels/content equal committed or explicitly pending edit text; verify copied text, glyph placement, selection, composition, and wrapping. Test unseen strings, Unicode, and multiline content. Report raw-mode character/word errors separately. |
| N9 | Revision/race handling | A delayed frame, rapid double click, resize, and model restart never route a stale event to a different action or repeat a transaction. |
| N10 | Input-to-presentation latency | Measure at least 1,000 interactions after a separately reported warmup. Initial usable target: p95 at most 150 ms at 512×320 neural resolution on named hardware; report all stages, tail failures, and cold start. |
| N11 | Continuous interaction | If claiming smooth animation/dragging, show sustained newly generated frames and action latency for that workload. A later target is at least 30 fresh neural frames/s; OS cursor or reused frames do not count. |
| N12 | Accessibility | A real screen reader can navigate, identify, and operate the supported workflow. Names, bounds, roles, and events track the displayed scene. Record the tested platform. |
| N13 | Long sessions and faults | A 30-minute varied session plus injected inference failures preserves correct state and bounded resource use. Report drift, invalid frames, recoveries, and task interruptions. |
| N14 | Experiment integrity | Known fixture outcomes yield consistent, conflicting, and inconclusive summaries correctly; assignment, held-out trials, failures, and adaptation history remain auditable. |
| N15 | New application transfer | A second adapter runs through the common engine; report frozen-checkpoint results and any subsequent training separately. |

A failed or blocked row remains visible. N1–N9 establish the core implemented path only to the extent actually tested; latency, accessibility, and study claims need their own evidence. A measured slow neural renderer is still a neural renderer, but not a low-latency runtime.

Do not use the model’s own masks, confidences, or descriptions as the sole judge of correctness. Geometry metrics can pass while the raster depicts the wrong control. Use independent state assertions, visual checks, and end-to-end actions on the visible output. Record both rejection rate and success rate so rejecting every difficult frame cannot improve the apparent result.

Measure GPU execution with the necessary synchronization. Include copies and composition in end-to-end results. Distinguish CPU submission/paint timings from actual photon latency; only claim display latency if measured accordingly. Report peak memory, model size, training wall time, accelerator time, and energy where reliably available.

Compare with the deterministic reference on identical tasks and hardware. The neural engine may be slower or less reliable. Its potential advantages—adaptability, learned interaction behavior, or improved user outcomes—must be demonstrated separately from proving it exists.

## 8. Compute limits and progress discipline

Inspect the local machine and run a brief training/inference benchmark first. Use that measurement to estimate the next run; do not quote foundation-model hardware as the requirement for this small prototype.

Start with a local smoke run capped at roughly 10 minutes and a pilot capped at two hours, saving resumable checkpoints and logs. Make caps configurable. If hardware is weak, reduce batch size, model width, or smoke resolution while reporting the change. CPU can validate plumbing without establishing interactive performance.

Do not launch paid remote training or download enormous checkpoints without an explicitly configured allowance. Prepare a concrete run configuration, expected usage, and the unresolved decision if extra resources are required. Continue local implementation and tests that do not need them. Do not fabricate measurements or substitute a mock inference result.

At the end of each milestone, record what runs, what was tested, what failed, and the next executable step. Preserve checkpoints and data manifests. Continue through implementation; do not replace the requested build with a long research document. If an external prerequisite blocks completion, deliver the runnable portion and the exact blocked command/configuration.

## 9. Required repository deliverables

Use this organization or an equivalent with equally clear boundaries:

```text
src/core_kernel/          # commands, transactions, snapshots, undo
src/apps/documents/      # semantic manifest and real document operations
src/apps/tasks/          # second adapter when reached
src/native_host/         # native surface, events, text, accessibility
src/neural/              # layout model, raster model, inference worker
src/experiments/         # trials, outcomes, preference/adaptation policy
reference/               # teacher/baseline, excluded from neural runtime
training/                # generation, splits, training, checkpoint export
evaluation/              # replay, independent checks, ablations, benchmarks
configs/                 # smoke, pilot, runtime, study, compute limits
tests/                   # meaningful contract and workflow tests
reports/                 # environment, model card, acceptance, benchmarks
artifacts/               # manifest-addressed local weights and evidence
```

Implement and document commands equivalent to these; they are requested CLI contracts, not commands that already exist:

```bash
python -m core_ultra doctor
python -m core_ultra data generate --config configs/smoke.yaml
python -m core_ultra train --config configs/smoke.yaml
python -m core_ultra evaluate --config configs/smoke.yaml
python -m core_ultra run --renderer neural_raw --checkpoint artifacts/smoke
python -m core_ultra run --renderer neural_exact_text --checkpoint artifacts/smoke
python -m core_ultra evaluate --suite acceptance --checkpoint artifacts/pilot
python -m core_ultra evaluate --suite ablations --checkpoint artifacts/pilot
```

Every path must resolve to an actual produced artifact when reported as runnable. Provide installation, dataset generation, training, inference, test, and export instructions; a model card with exact training scope; a dataset manifest and split policy; checkpoint hashes; raw/final comparison images; a short real interaction recording; and an honest acceptance report.

Keep local work private. Package a native executable or reproducible environment after the core workflow is verified. A hosted dashboard can inspect results later, but a browser preview must never be presented as the browser-independent runtime.

## 10. Route toward broader browser replacement

After the first engine is measured, extend in this order:

1. **Broaden the native application contract:** larger collections, images, richer text, application switching, navigation history, authenticated service adapters, lifecycle, permissions, and recovery. Use standard network/OS libraries where appropriate.
2. **Improve learned presentation:** higher resolution, broader composition, temporal interaction behavior, bounded inference cost, and accessibility across supported platforms. Keep correctness and usability gates.
3. **Distribute applications for this runtime:** versioned app manifests, capability requests, installation/update semantics, isolation, and a portable state/interaction contract. This replaces the browser as a host for those applications.
4. **Add web compatibility deliberately:** select an HTML/CSS/DOM/JavaScript/API subset, implement or reuse its semantics, and run relevant Web Platform Tests with an explicit pass/fail/unsupported matrix. Expand only on evidence.

Using Chromium/WebKit/another engine as a compatibility sidecar can be an honest migration strategy, but web content handled by it remains browser-engine dependent. Using neural pixels for arbitrary websites without implementing their semantics does not preserve their behavior. A visual imitation of a login, transaction, or editor is not execution of that application.

Do not let the full compatibility ambition delay the first real neural engine. Do not let the first app be misrepresented as full web compatibility.

## 11. Research grounding and source boundaries

The implementation design above is a proposed synthesis, not a reproduction recipe or a claim of novelty. Read these primary sources for relevant methods and limitations. Pin exact versions of dependencies and any reused models during implementation.

- **Solaris, Runway, 2026:** directly studies action-conditioned generated interfaces and separates high-level reasoning from visual generation. Its limitations include reliable text, long-session coherence, trust, accessibility, and integration. It is relevant prior art, not evidence that this proposed runtime already works. [Paper](https://arxiv.org/abs/2609.00776) · [Full text](https://arxiv.org/html/2609.00776v1) · [Project announcement](https://runway.com/news/research/introducing-solaris)
- **NeuralOS, 2025; revised 2026:** predicts GUI frames using recurrent state and a diffusion renderer. Its stated limitations include fine keyboard input and external-resource integration. The revised paper reports 17,000 H200 and 6,000 H100 GPU hours; that is context for its broader research system, not an estimate for this deliberately small model. [Paper](https://arxiv.org/abs/2507.08800) · [Full text and limitations](https://arxiv.org/html/2507.08800v2)
- **GameNGen, 2024/2025:** demonstrates action-conditioned neural game simulation and reports 20 frames/s on one TPU. That benchmark does not establish editable application state, exact text, or this engine’s expected throughput. [Paper](https://arxiv.org/abs/2408.14837)
- **Qt native surfaces:** documents image/raster and OpenGL presentation mechanisms independently of a web engine. [QWindow](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QWindow.html)
- **Qt accessibility:** custom controls need actual accessible interfaces and events; a bitmap alone does not supply them. [Custom accessibility](https://doc.qt.io/qt-6/accessible-qwidget.html)
- **PyTorch MPS and timing:** inspect device availability and measure accelerator execution correctly. [MPS](https://docs.pytorch.org/docs/stable/notes/mps.html) · [Benchmark timing](https://docs.pytorch.org/tutorials/recipes/recipes/timer_quick_start.html)
- **Web Platform Tests:** a compatibility test suite for web-platform implementations, relevant to the separate general-browser claim. [Documentation](https://web-platform-tests.org/)

Sources checked November 24, 2026. No claim is made that the chosen small architecture matches these research systems.

## Start working

Read this brief and the repository’s instructions. In no more than five sentences, state the actual input-to-pixels-to-persisted-action path you will implement and the hardware you found. Then begin M0–M2. Continue into the interaction, accessibility, and experiment milestones as prerequisites become available. Do not stop at scaffolding, a proposal, or an untrained placeholder. The minimum substantive delivery includes a native window, a real trained checkpoint, neural pixels, a real persisted action, and an evidence report that says exactly what passed and what remains unproven.
