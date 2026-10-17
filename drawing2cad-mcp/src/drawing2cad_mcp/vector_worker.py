"""Run internal vector analysis in an isolated process.

PdfService supplies a permitted snapshot and a temporary result path.
This module is an implementation detail, not a separate command-line product.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("Vector worker requires a snapshot and a result path.", file=sys.stderr)
        return 2
    from .vector import extract
    from .vector.export import to_dict

    try:
        data = to_dict(extract(Path(sys.argv[1])))
        Path(sys.argv[2]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
