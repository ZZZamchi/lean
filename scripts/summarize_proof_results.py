#!/usr/bin/env python3
"""Scan results/prover/*/proof_results.json and emit JSON summary for tooling.

Cross-benchmark figures in the paper use \\Logged* macros in paper_full.tex (edited by hand).
This script no longer writes generated_benchmark_stats.tex.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROVER = ROOT / "results" / "prover"
OUT_JSON = PROVER / "_summary" / "proof_results_summary.json"


def main() -> int:
    rows = []
    for path in sorted(PROVER.glob("*/proof_results.json")):
        data = json.loads(path.read_text())
        folder = path.parent.name
        n = len(data)
        complete = sum(1 for x in data if x.get("complete"))
        pct = (100.0 * complete / n) if n else 0.0
        rows.append(
            {
                "folder": folder,
                "n_problems": n,
                "n_complete": complete,
                "pass_rate_pct": round(pct, 2),
            }
        )

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, indent=2) + "\n")

    print(f"Wrote {OUT_JSON} ({len(rows)} runs)")
    print("Update \\Logged* macros in prover/docs/latex/paper_full.tex when publishing new numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
