# Fonts and assets

Every font and asset in this repository, with its source, licence and attribution. A test (`tests/test_design.py`) fails when a font or image asset is added without being recorded here, or when a recorded file's hash changes.

The design itself (`DESIGN.md`, `configs/design/v1.json` and the four visual presets) is original work written for this project. No value in it was taken from Refero, from any other design collection, or from an existing product, brand or screenshot.

## Inter

The one font all text is drawn in.

| | |
| --- | --- |
| File | `src/core_ultra/assets/fonts/inter/Inter[opsz,wght].ttf` |
| SHA-256 | `29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031` |
| Size | 876,576 bytes |
| Version | 4.001 |
| Designer | Rasmus Andersson |
| Copyright | Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter) |
| Licence | SIL Open Font License, Version 1.1 |
| Licence text | `src/core_ultra/assets/fonts/inter/OFL.txt`, SHA-256 `5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57` |
| Retrieved from | https://github.com/google/fonts/tree/0b58fb370093f9a9f4ff785d94405710b79de67c/ofl/inter on 2026-11-25 |
| Upstream | https://github.com/rsms/inter/commit/66647c0bbbe41a850d79d9c76fb13add3378940f |

The file is unmodified. The licence allows the font to be used, embedded and redistributed, including with software, as long as the copyright notice and the licence travel with it; they do, in `OFL.txt` beside the font. The licence declares no Reserved Font Name.

How it is used: it is a variable font with a weight axis (100 to 900) and an optical size axis (14 to 32). The weight axis is set to the type weight rounded to the nearest hundred. The optical size axis is pinned at 16. `src/core_ultra/typography.py` says why. Rob chose Inter on 2026-11-25.

A machine may have its own copy of Inter installed. The copy in this repository is the only one drawn with: the face Qt selects is compared with this file, and another version is refused.

## Images

The PNG files under `records/` are drawn by this project's own runtime renderer from this project's own scenes. They contain no third-party material other than text set in Inter.
