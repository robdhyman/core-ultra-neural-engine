# Roadmap

Written 2026-11-26, from the spec ([issue #1](https://github.com/robdhyman/core-ultra-neural-engine/issues/1)), the state of issues #2 to #24 and their blocked-by links on GitHub, and the milestone records in `records/milestones/`. Terms are explained in [the designers' guide to S0 to S2](milestones-s0-s2-for-designers.md).

This roadmap gives order, not dates. The spec makes no time estimate that is not backed by a measurement, and the only one so far is the training step in S0.

## Where things stand

The spec has six milestones and 23 work issues. It ends in one document: a report on whether teaching the network with pictures as well as with scene data makes it better on layouts it has never seen.

| Milestone | What it delivers | Issues | Status |
| --- | --- | --- | --- |
| S0, environment and measurement | Proof that this Mac can train the planned network | #2, #3 | **Done** |
| S1, kernel, scene and runtime renderer | The documents app, drawn from a scene with no network | #4, #5 | **Done** |
| S2, generator and pilot | Design system, training data, a pilot gallery, the full dataset | #6 to #11 | **Started.** 1 of 6 done. #7 can start now |
| S3, training renderer | A second renderer the network can learn through | #12 to #14 | Not started. #12 can start now |
| S4, structure-only baseline | The first trained network, and the baseline result | #15 to #17, #19, #20 | Not started |
| S5, comparison | The second training method, the hand-written test set, the report | #18, #21 to #24 | Not started |

Counted by issue: 5 done, 18 not started. No network has been trained yet.

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
        i7["#7 Data generate tracer"]:::ready
        i8["#8 Layout families and validators"]:::waiting
        i9["#9 Pilot dataset and gallery"]:::waiting
        i10["#10 Rob reviews the pilot gallery"]:::rob
        i11["#11 Frozen splits and full dataset"]:::waiting
    end
    subgraph S3["S3 Training renderer"]
        i12["#12 Stage 1: rounded rectangles"]:::ready
        i13["#13 Stage 2: borders and text"]:::waiting
        i14["#14 Stage 3: shadows"]:::waiting
    end
    subgraph S4["S4 Structure-only baseline"]
        i15["#15 Scene model fits a tiny set"]:::waiting
        i16["#16 D, Neural Scene in the scene session"]:::waiting
        i17["#17 Evaluate"]:::waiting
        i19["#19 Smoke configuration"]:::waiting
        i20["#20 Baseline: three seeds, full dataset"]:::waiting
    end
    subgraph S5["S5 Comparison"]
        i18["#18 Render loss on the tiny set"]:::waiting
        i21["#21 Structure plus render: three seeds"]:::waiting
        i22["#22 Hand-authored evaluation set"]:::waiting
        i23["#23 Rob reviews the hand-authored set"]:::rob
        i24["#24 Comparison report"]:::waiting
    end

    i4 --> i6
    i5 --> i7
    i6 --> i7 --> i8 --> i9 --> i10 --> i11
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

## Next

In the order they unlock:

1. **#7, the `data generate` tracer.** Ready now. Scripted sessions drive the app and each screen is saved as a training example.
2. **#12, training renderer stage 1.** Ready now. It depends only on #4. The first piece of the renderer the network learns through: rounded rectangles, with proof that its learning signal is correct.
3. **#8, layout families and validators.** More than one arrangement of the screen, with checks that reject broken samples. This is also where text fit gets checked.
4. **#9, pilot dataset and gallery.** 200 to 500 examples across every preset and layout family, in a gallery made for review.
5. **#10, Rob's go.** Nothing is scaled up until Rob has looked at the gallery and said go.

The spec lets S3 proceed alongside S2, so #12 and #7 can run side by side.

## Later

- **S2 closes with #11.** After Rob's go, the rules for splitting data into training and test sets are frozen, and the full dataset is generated.
- **S3 closes with #14.** Borders and text (#13), then shadows (#14), each added alone and checked before the next.
- **S4, the first trained network.** A small network learns a tiny set (#15), runs inside the app's drawing path as D, Neural Scene (#16), gets its measuring tools (#17), and the whole pipeline is made to run in minutes as a smoke test (#19). Then the baseline is trained three times on the full dataset (#20).
- **S5, the comparison.** The picture-based training method is proven on the tiny set (#18) and trained three times on the full dataset (#21). About 24 hand-written scenes test the network outside the generator's own style (#22), and Rob reviews them (#23). The comparison report (#24) ends the spec.

## The two points that wait on Rob

| Issue | Decision | What it holds up |
| --- | --- | --- |
| #10 | Do the pilot examples look coherent enough to scale? | #11 (full dataset), and through it every full training run |
| #23 | Is the hand-authored evaluation set acceptable? | #24 (the comparison report) |

## The longest chains

With #6 done, two chains of eight issues remain. Both start at #7 and end at #24:

- **Data:** #7 → #8 → #9 → #10 → #11 → #20 → #21 → #24
- **Model:** #7 → #15 → #16 → #17 → #19 → #20 → #21 → #24

They meet at #20, the first full training run, which needs both the full dataset (#11) and the smoke test (#19). The second full run (#21) also needs the finished training renderer (#14).

## After this spec

The spec stops at the comparison report. Left for the next spec: the interactive native app in a real window. Outside this spec altogether: networks that paint pixels (B, Neural Raw and C, Neural Exact Text), any recording of real use, platforms other than macOS 27 on Apple silicon, and any claim about design taste, usability, accessibility or production readiness.

## Known limits that later issues must deal with

These come from the S1 and S2 records and are not yet assigned beyond what is noted:

- **Nothing scrolls**, and a screen holds at most 32 bound elements (21 list rows). The generator must stay inside that or the limit must rise.
- **Text fit is unchecked** until #8.
- **Roomier presets need larger windows.** The generator has to pick window sizes with the preset in mind (#7, #8).
- **Whether each preset looks intentional** is judged at #9 and #10.
- **The cost of the picture-based training step is unknown** until #18 measures it.
