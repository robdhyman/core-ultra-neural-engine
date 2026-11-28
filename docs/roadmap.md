# Roadmap

Written 2026-11-26, from the spec ([issue #1](https://github.com/robdhyman/core-ultra-neural-engine/issues/1)), the state of issues #2 to #24 and #32 and their blocked-by links on GitHub, and the milestone records in `records/milestones/`. Terms are explained in [the designers' guide to S0 to S2](milestones-s0-s2-for-designers.md).

This roadmap gives order, not dates. The spec makes no time estimate that is not backed by a measurement, and the only one so far is the training step in S0.

## Where things stand

The spec has six milestones and 23 work issues, and one issue (#32) was added on 2026-11-26. It ends in one document: a report on whether teaching the network with pictures as well as with scene data makes it better on layouts it has never seen.

| Milestone | What it delivers | Issues | Status |
| --- | --- | --- | --- |
| S0, environment and measurement | Proof that this Mac can train the planned network | #2, #3 | **Done** |
| S1, kernel, scene and runtime renderer | The documents app, drawn from a scene with no network | #4, #5 | **Done** |
| S2, generator and pilot | Design system, training data, a pilot gallery, the full dataset | #6 to #11, #32 | **Started.** 5 of 7 done. #10 waits on Rob |
| S3, training renderer | A second renderer the network can learn through | #12 to #14 | **Started.** 1 of 3 done. #13 can start now |
| S4, structure-only baseline | The first trained network, and the baseline result | #15 to #17, #19, #20 | Not started. #15 can start now |
| S5, comparison | The second training method, the hand-written test set, the report | #18, #21 to #24 | Not started. #22 can start now |

Counted by issue: 10 done, 14 not started. No network has been trained yet.

## The map

Arrows mean "must finish before". Issues #17 and #19 serve both S4 and S5; they are drawn in S4.

```mermaid
flowchart TD
    classDef done fill:#d7f0dd,stroke:#2e7d4f,color:#12301f
    classDef ready fill:#d6e6ff,stroke:#2457a6,color:#0f2547
    classDef waiting fill:#eeeeee,stroke:#888888,color:#222222
    classDef rob fill:#f6d9ef,stroke:#8e3a7c,color:#3a1232

    subgraph S0["S0 Environment and measurement"]
        i2["#2 Doctor and locked environment"]:::done
        i3["#3 Measured training step"]:::done
    end
    subgraph S1["S1 Kernel, scene, runtime renderer"]
        i4["#4 A, Reference tracer"]:::done
        i5["#5 Full document workspace"]:::done
    end
    subgraph S2["S2 Generator and pilot"]
        i6["#6 Design source and presets"]:::done
        i7["#7 Data generate tracer"]:::done
        i8["#8 Layout families and validators"]:::done
        i9["#9 Pilot dataset and gallery"]:::done
        i32["#32 Scene export as editable SVG"]:::done
        i10["#10 Rob reviews the pilot gallery"]:::rob
        i11["#11 Frozen splits and full dataset"]:::waiting
    end
    subgraph S3["S3 Training renderer"]
        i12["#12 Stage 1: rounded rectangles"]:::done
        i13["#13 Stage 2: borders and text"]:::ready
        i14["#14 Stage 3: shadows"]:::waiting
    end
    subgraph S4["S4 Structure-only baseline"]
        i15["#15 Scene model fits a tiny set"]:::ready
        i16["#16 D, Neural Scene in the scene session"]:::waiting
        i17["#17 Evaluate"]:::waiting
        i19["#19 Smoke configuration"]:::waiting
        i20["#20 Baseline: three seeds, full dataset"]:::waiting
    end
    subgraph S5["S5 Comparison"]
        i18["#18 Render loss on the tiny set"]:::waiting
        i21["#21 Structure plus render: three seeds"]:::waiting
        i22["#22 Hand-authored evaluation set"]:::ready
        i23["#23 Rob reviews the hand-authored set"]:::rob
        i24["#24 Comparison report"]:::waiting
    end

    i4 --> i6
    i5 --> i7
    i6 --> i7 --> i8 --> i9 --> i10 --> i11
    i5 --> i32 --> i10
    i4 --> i12 --> i13 --> i14
    i5 --> i13
    i3 --> i15
    i7 --> i15 --> i16 --> i17 --> i19
    i12 --> i18
    i15 --> i18 --> i19
    i11 --> i20
    i19 --> i20 --> i21
    i14 --> i21
    i5 --> i22
    i9 --> i22 --> i23 --> i24
    i21 --> i24
```

Green is done. Blue can start now. Grey is waiting on something. Pink is a decision only Rob can make.

## Done

| Issue | What landed | Evidence |
| --- | --- | --- |
| #2 | `doctor`: a health check that records the machine and the exact software, with a fingerprint | PRs #25, #26 |
| #3 | `measure step`: one training step timed across 30 cases. The planned network fits this Mac with room to spare, and a starting size of 10.73 million parameters was chosen | PR #27, [S0 record](../records/milestones/S0.md) |
| #4 | The first working path from app state to a drawn screen and a click target, with no window | PR #28 |
| #5 | The whole documents app (list, editor, toolbar, notification, undo) drawn in A, Reference, with 250 tests | PR #29, [S1 record](../records/milestones/S1.md) |
| #6 | The original design system (`DESIGN.md`), its machine-readable twin, the check that keeps them in sync, four visual presets and the Inter font, with 360 tests | PR #30, merged 2026-11-26, [S2 record so far](../records/milestones/S2.md) |
| #7 | `data generate`: scripted sessions drive the app and every screen they reach is saved as a traceable training example. A tiny dataset of 82 examples, a check that nothing the network is given contains the answer, and `data check`, with 415 tests | [S2 record so far](../records/milestones/S2.md) |
| #32 | `scene export`: any scene written as an SVG of separate named objects, with text as text, made to be opened in a design tool. No design tool has been tried yet. `scene compare` measures the SVG against the runtime renderer: on the tiny dataset the mean difference is 0.43 levels of 255, nearly all of it text. Eight SVGs were handed to Rob with a note for #10 that lists what the scene schema cannot express | [S2 record so far](../records/milestones/S2.md), [hand-off note](../.scratch/scene-export/handoff-scene-as-svg.md) |
| #8 | Eight layout families, each a different arrangement of the screen, varying in seven layout settings, grouping and alignment among them; designs sampled as whole sets with a window size that fits; six validators that reject broken examples and record why; and a labelled stress-test set of 20 examples that are wrong on purpose. A dataset of 358 examples across all eight families, with 525 tests | [S2 record so far](../records/milestones/S2.md) |
| #9 | The pilot: 476 examples from 32 sessions, with each of the eight layout families in each of the four presets, none rejected and no coverage gap. `data gallery` builds a local review page from it: every picture labelled, a coverage summary, and the rejected screens and the stress-test set shown apart. `measure generation` measured 22 ms and 69 KiB an example | [S2 record so far](../records/milestones/S2.md), [hand-off note](../.scratch/pilot-gallery/handoff-pilot-gallery.md) |
| #12 | The training renderer, stage 1: a second renderer, in PyTorch, that draws rounded rectangles so that a picture-based loss can teach the network. `renderer check` proves its learning signal: right against a slow independent calculation for all seven of its numbers, the same on the Mac's GPU as on its CPU, and zero only where it should be. It also found that the runtime renderer draws rounded corners slightly off, which is [#37](https://github.com/robdhyman/core-ultra-neural-engine/issues/37). Borders, text and shadows are not drawn yet | [S3 record so far](../records/milestones/S3.md) |

## Next

In the order they unlock:

1. **#10, Rob's go.** Ready now that #9 is done: the pilot gallery is built. Nothing is scaled up until Rob has looked at it and said go. He also opens the exported SVGs here and revisits the questions under "After this spec".
2. **#12, training renderer stage 1.** Done on 2026-11-27; see the table above. **#13, borders and text**, is ready in its place.
3. **#15, the scene model fits a tiny set.** Ready now. The first network, taught to reproduce the tiny dataset that #7 left.
5. **#32, scene export as editable SVG.** Done; see the table above. It trained nothing and changed no schema. It exists so that Rob sees the scene as an editable vector document before #10, and so that the gaps in the scene schema are known before #11 freezes the dataset.

The spec lets S3 proceed alongside S2, so #13 and #15 can run while #10 waits. #22, the hand-authored evaluation set, waited on #9 and can start too.

## Later

- **S2 closes with #11.** After Rob's go, the rules for splitting data into training and test sets are frozen, and the full dataset is generated.
- **S3 closes with #14.** Borders and text (#13), then shadows (#14), each added alone and checked before the next.
- **S4, the first trained network.** A small network learns a tiny set (#15), runs inside the app's drawing path as D, Neural Scene (#16), gets its measuring tools (#17), and the whole pipeline is made to run in minutes as a smoke test (#19). Then the baseline is trained three times on the full dataset (#20).
- **S5, the comparison.** The picture-based training method is proven on the tiny set (#18) and trained three times on the full dataset (#21). About 24 hand-written scenes test the network outside the generator's own style (#22), and Rob reviews them (#23). The comparison report (#24) ends the spec.

## The two points that wait on Rob

| Issue | Decision | What it holds up |
| --- | --- | --- |
| #10 | Do the pilot examples look coherent enough to scale? Seen as SVG, is the scene the editable document Rob expected? | #11 (full dataset), and through it every full training run |
| #23 | Is the hand-authored evaluation set acceptable? | #24 (the comparison report) |

## The longest chains

With #9 done, the data chain has five issues left and the model chain seven. Both end at #24:

- **Data:** #10 → #11 → #20 → #21 → #24
- **Model:** #15 → #16 → #17 → #19 → #20 → #21 → #24

They meet at #20, the first full training run, which needs both the full dataset (#11) and the smoke test (#19). The second full run (#21) also needs the finished training renderer (#14).

## After this spec

The spec stops at the comparison report. Left for the next spec: the interactive native app in a real window. Outside this spec altogether: networks that paint pixels (B, Neural Raw and C, Neural Exact Text), any recording of real use, platforms other than macOS 27 on Apple silicon, and any claim about design taste, usability, accessibility or production readiness.

### Questions held for later

Recorded 2026-11-26. These are questions, not milestones: none has a ticket, and none is to be designed toward until Rob opens it. Rob chose to finish the report first and test the editor idea cheaply through #32.

| Question | What would open it | Known cost |
| --- | --- | --- |
| Should the scene become a full design document (free paths, groups, image assets, constraints)? | #32 shows, at #10, that the exported scene is too thin to edit usefully | A new scene schema version. The dataset frozen at #11 and the training renderer from S3 would both have to be redone for it |
| Is a scene with real bindings the base of an editor that joins a design canvas with working interactions? | Rob asks for it after #10 or after the first network runs at #16 | A throwaway prototype on its own branch (move an element, its bound action still works). It needs no network, and it needs the real window the next spec owns |
| How does D, Neural Scene compare with a language model that writes HTML, CSS and JavaScript for the same application states? | D, Neural Scene runs (#16) and `evaluate` exists (#17) | A browser to measure in, kept outside the product path (ADR 0002), and API spend |
| Can a rendered page be turned into a scene (browser to design tool)? | Only as a new spec | The model here runs the other way, from application state to a scene. Design tools already ship the deterministic part of this conversion |

## Known limits that later issues must deal with

These come from the S1 and S2 records and are not yet assigned beyond what is noted:

- **Nothing scrolls**, and a screen holds at most 32 bound elements (21 list rows). Since #8 the generator stays inside that: its longest scripted list has nine documents, and a longer one is rejected with its reason. The limit itself has not moved.
- **Text fit is checked since #8**, by the generator's validators. A screen whose text does not fit is never a training example. Nothing wraps or truncates text, so long titles are simply left out of the data.
- **Roomier presets need larger windows.** Since #8 a session is given a window size in which all its screens pass the validators, and the sizes it was refused are recorded.
- **Eight layout families since #8.** Since #9 the pilot has every family in every preset, one session for each pairing. Each scenario still meets only four of the eight families.
- **A coverage gap does not fail the generator.** It is recorded and printed, and the gallery names every declared value no example shows. The pilot has none.
- **The pilot's lists are short.** Its longest has seven documents, in four of the eight families. #11 decides what the full dataset adds.
- **The stress-test set's expected reasons belong to one seed.** Another seed writes other titles, and a case can then be rejected for one reason more or fewer, which stops the run until the case is restated.
- **The network is told a text's width at one font weight.** Text drawn at another weight is not exactly that width scaled, so a small error in such widths is built in.
- **Whether each preset, and each pairing of preset and layout family, looks intentional** is judged at #10, in the pilot gallery.
- **The cost of the picture-based training step is unknown** until #18 measures it.
