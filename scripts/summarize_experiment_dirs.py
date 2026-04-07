#!/usr/bin/env python3
"""Print complete/total for each results/experiments/*/proof_results.json."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "results" / "experiments"


def main() -> int:
    rows = []
    for path in sorted(EXP.glob("*/proof_results.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        n = len(data) if isinstance(data, list) else 0
        c = sum(1 for x in data if isinstance(x, dict) and x.get("complete"))
        rows.append((path.parent.name, c, n, path))
    for name, c, n, _ in rows:
        pct = 100.0 * c / n if n else 0.0
        print(f"{name:40s}  {c:3d}/{n:3d}  ({pct:5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
