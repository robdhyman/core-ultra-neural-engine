---
status: accepted
---

# The trained network writes a scene, not pixels

Decided by Rob on 2026-11-24. The first spec (issue 1) had a trained network paint every application pixel. The primary pre-alpha approach is now a scene model: the network predicts an editable scene (elements, geometry, style, states) and deterministic code draws it as vectors. Vectors are cheaper to produce, hold still between frames and scale to any resolution; text and hit targets become exact because drawing and hit testing read the same validated scene. The pixel-model spec is preserved as a deferred baseline (B, Neural Raw and C, Neural Exact Text), not deleted.

## Considered Options

- **Run both tracks.** Keeps the "network paints the pixels" claim, and roughly doubles training and evaluation work on one 16 GB Mac.
- **Export scene data only.** Least change, and no scene model would be trained by the M3 exit.

## Consequences

- The project's headline changes from "the network produces the pixels" to "the network writes the scene". Proof that the result is neural must now rest on the predicted scene values, since every pixel is drawn by deterministic code in every mode.
- No published differentiable renderer covers rounded rectangles, text and shadows (`docs/research/scene-models-2026-11.md`, section 4), so the training renderer is written here and its gradients are verified before training is scaled.
- No published system matches this design (same file, sections 1 to 3). Training time and memory are measured on this hardware, never inferred from related papers.
- The core experiment is a comparison: the same small model trained on structure loss alone, and on structure loss plus render loss, judged on held-out layout families. The structure-only baseline is kept even if the combined approach becomes primary.
