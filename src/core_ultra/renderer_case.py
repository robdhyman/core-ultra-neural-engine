"""Draw a check configuration's scenes on the Apple GPU path in this process.

`renderer_check` starts a fresh interpreter for this
(`python -m core_ultra.renderer_case RESULT_PATH`, the case as JSON on stdin),
because whether an unsupported operation stops the run or falls back to the
CPU, and whether PyTorch's profiler logs, are decided when PyTorch starts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    from core_ultra import renderer_check

    case = json.loads(sys.stdin.read())
    try:
        result = renderer_check.apple_gpu_case(case)
    except Exception as error:  # the parent reports whatever stopped the run
        message = str(error).splitlines()[0] if str(error) else ""
        result = {"ok": False, "error": {"type": type(error).__name__, "message": message.replace(str(Path.home()), "~")}}
    Path(sys.argv[1]).write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
