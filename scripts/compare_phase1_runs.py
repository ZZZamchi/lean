#!/usr/bin/env python3
"""Compare two Phase1-style proof_results.json files (e.g. 16K vs 32K on unsolved39).

Writes:
  results/experiments/phase1_compare_16k_32k.json
  results/experiments/phase1_compare_16k_32k.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "results" / "experiments"


def load_map(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Invalid JSON {path}: {e}", file=sys.stderr)
        return {}
    return {r["problem_id"]: r for r in data if isinstance(r, dict) and r.get("problem_id")}


def main() -> int:
    p16 = EXP / "phase1_official_16k" / "proof_results.json"
    p32 = EXP / "phase1_official_32k" / "proof_results.json"
    if len(sys.argv) >= 3:
        p16 = Path(sys.argv[1])
        p32 = Path(sys.argv[2])

    m16 = load_map(p16)
    m32 = load_map(p32)
    all_ids = sorted(set(m16) | set(m32))

    rows = []
    upgraded = downgraded = 0
    for pid in all_ids:
        a, b = m16.get(pid), m32.get(pid)
        ca = bool(a and a.get("complete"))
        cb = bool(b and b.get("complete"))
        row = {
            "problem_id": pid,
            "complete_16k": ca,
            "complete_32k": cb,
            "agree": ca == cb,
        }
        if a and "sc" in a:
            row["sc_rounds_16k"] = a.get("sc", 0)
        if b and "self_correction_rounds" in b:
            row["sc_rounds_32k"] = b.get("self_correction_rounds", 0)
        rows.append(row)
        if ca and not cb:
            downgraded += 1
        elif not ca and cb:
            upgraded += 1

    out_j = EXP / "phase1_compare_16k_32k.json"
    summary = {
        "path_16k": str(p16),
        "path_32k": str(p32),
        "n_ids": len(all_ids),
        "complete_16k": sum(1 for r in rows if r["complete_16k"]),
        "complete_32k": sum(1 for r in rows if r["complete_32k"]),
        "newly_solved_by_32k_vs_16k": upgraded,
        "lost_by_32k_vs_16k": downgraded,
        "rows": rows,
    }
    EXP.mkdir(parents=True, exist_ok=True)
    out_j.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    out_md = EXP / "phase1_compare_16k_32k.md"
    lines = [
        "# Phase1 16K vs 32K (per-problem)",
        "",
        f"- 16K file: `{p16}` ({len(m16)} records)",
        f"- 32K file: `{p32}` ({len(m32)} records)",
        f"- Joined ids: **{len(all_ids)}**",
        f"- Complete 16K: **{summary['complete_16k']}**",
        f"- Complete 32K: **{summary['complete_32k']}**",
        f"- New complete only in 32K row (vs 16K): **{upgraded}**",
        f"- Complete in 16K but not 32K: **{downgraded}**",
        "",
        "| problem_id | 16K | 32K |",
        "|------------|-----|-----|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['problem_id']}` | {'Y' if r['complete_16k'] else 'N'} | "
            f"{'Y' if r['complete_32k'] else 'N'} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {out_j}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
