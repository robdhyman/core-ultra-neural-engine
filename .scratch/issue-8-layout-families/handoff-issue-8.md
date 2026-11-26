# Hand-off: issue #8, layout families, validators and the stress-test set

Written 2026-11-26 by the session that implemented issue #8, on branch `claude/issue-8-layout-families-6a509e`, and rewritten the same day after you sent the issue back. The branch is rebased onto `main` at `a2836bd` (issue #32). Nothing was pushed, no pull request was opened and nothing was merged.

The full account is the issue 8 section of [records/milestones/S2.md](../../records/milestones/S2.md). This note is what to look at first.

## What changed when the issue came back

You asked for grouping and alignment to vary on their own. They are design factors now, the sixth and seventh:

- **Grouping** is which elements share a container in the scene. `parts`: one container for each part of the workspace. `tasks`: the toolbar's elements in two containers with a divider between them. `sheet`: the list and the editor on one panel with a divider between them.
- **Alignment** is where an element narrower than its room is put. `justified`: the toolbar's elements at both ends of a bar, or as wide as a rail. `start`: packed from the left. `centre`: centred, along with the list's heading, the label of an empty list and the editor's revision.

Both are declared in a new layout configuration, `configs/layout/v3.json`, drawn by the reference layout, sampled in the eight families, given to the scene model as inputs, and read back off every scene's boxes and tree by the tests. The dataset is `configs/data/families-v2.json`. Layout version 2 and version 1 of the families dataset stay as committed and are superseded.

The scene schema did not change. One consequence of that is a limit: alignment moves boxes, never the text inside a box. A button's text is always centred and every other text starts at the left, because where text sits in its box is the runtime renderer's rule and not a scene value. Changing that is a change to the scene schema, which is your decision; I did not need it to make alignment vary, so I have not asked.

## See it

![One application state in each of the eight layout families](families.png)

`families.png` is one application state in each of the eight layout families of version 3, at 1120 by 630, the visual presets taken in turn. It was drawn for this note by a throwaway script and is not evidence; the evidence is the dataset and its tests.

```bash
uv run core-ultra data generate --config configs/data/families-v2.json
```

writes 358 records and their images to `artifacts/datasets/families-v2/` (about eight seconds, 28 MB, git-ignored), and the 20 stress tests with their pictures to `artifacts/datasets/families-v2/stress/`.

## What landing it changes for you

- **`artifacts/datasets/tiny-v1/` on this Mac was written by generator version 1.** `data check` on that folder will now report every record as different, because a record lists six validators where it listed two. The model inputs and targets are identical, hash for hash, and the committed tiny manifest was not rewritten. To have a tiny dataset that passes `data check`, generate it into another folder with `--out`.
- **The scene model now has up to seven design factors to take**, not five. The tiny dataset still has five. The S0 placeholder model was measured with five and is untouched.

## Decisions I made that you may want to overrule

Each is recorded with its reason under "Decisions" in the S2 record. The ones closest to design:

1. **The eight families.** Which 8 of the 2 187 combinations are sampled is a preference, declared in `configs/layout/v3.json`. Roomy never goes with tight, compact never with loose, and no other factor fixes the grouping or the alignment.
2. **The three groupings and the three alignments**, and that one alignment holds for the whole workspace. Right alignment is out of scope. Start and justified differ in the toolbar only; in the list and the editor only centre looks different, because justified has to stay what the tiny dataset was drawn in.
3. **The scene model is given seven design factors**, where the spec's table of inputs names five. Two designs that differ only in grouping or alignment are both valid, so the difference has to be an input.
4. **The two groups of `tasks` are seen by the divider between them.** Their containers are drawn in the toolbar's own fill. No token was added to DESIGN.md.
5. **The notification only sits along the lower edge.** Along the top it covered the title field, and the validators rejected it.
6. **Density is 0.85, 1 and 1.15 on heights; spacing is 0.75, 1 and 1.25 on distances.** Type size does not change with density.
7. **The rail's width** is the widest filter field plus a margin either side.
8. **A coverage gap is reported and does not fail the command.**

None of these blocks issue #9. The pilot gallery is where they are best judged.

## Review

Sub-agents reviewed the work twice, once against the repository's standards and once against the issue each time. The first review found that two validators were enforcing taste (padding around text, and one container for each part of the workspace); both were removed. The second, on the grouping and alignment work, found that a record whose inputs left out the two new factors still passed the record rules; that is fixed. The S2 record lists everything the reviews found and what was done about each.
