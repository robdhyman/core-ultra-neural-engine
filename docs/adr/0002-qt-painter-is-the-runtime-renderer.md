---
status: accepted
---

# Qt's painter, off screen, is the runtime renderer

Decided by Claude on 2026-11-25, in issue 4. The spec named Qt's painter (PySide6 without QtWebEngine) as the starting choice for the runtime renderer and asked for it to be confirmed or replaced once a scene had been drawn. It is confirmed.

What was checked on the tested platform, with PySide6-Essentials 6.12.0:

- **No window.** Qt runs on its `offscreen` platform; a frame is drawn into an image and the process has no window at any point.
- **Vectors.** Rounded rectangles are filled painter paths. Text is shaped by Qt's text layout (HarfBuzz) and drawn as filled glyph outlines, so a scene drawn at scale 3.5 has edges as sharp as at scale 1.
- **Exact text.** The glyph outlines agree with Qt's own text-to-path (`QPainterPath.addText`) for the same string to within 0.2% of the ink at three scales, and the same comparison tells one accent from another. Ligatures and accents are shaped. A character the font lacks is refused.
- **One shape for drawing and hitting.** A hit test asks the same painter path that was filled whether it contains the point.
- **No browser engine.** PySide6-Essentials does not contain QtWebEngine; that lives in PySide6-Addons, which is not installed. After a frame is drawn the process has loaded QtCore, QtGui and QtDBus and no WebEngine, WebKit or Chromium library.

## Considered Options

None of these was built or run; they were set aside on what is known of them.

- **Skia (skia-python).** It would be a second graphics stack next to the Qt one the later native host needs for its window.
- **Cairo with Pango.** Needs system libraries outside the locked Python environment.
- **Core Graphics and Core Text through PyObjC.** No extra download, and tied to macOS for good.

## Consequences

- The project depends on `PySide6-Essentials`, never on `PySide6`, which would pull in PySide6-Addons and with it QtWebEngine. A test fails if either is installed.
- The Qt libraries add about 350 MB to the environment.
- The later native host can paint the same scenes with the same code in a real window.
- Text is drawn from glyph outlines without hinting, so it is the same shape at every scale. It is lighter than Qt's ordinary `drawText`: 14% less ink for one 15-unit line in the one comparison made.
- The doctor report now lists the Qt dependency, so its environment id differs from the one in the S0 records. Those records are unchanged.
