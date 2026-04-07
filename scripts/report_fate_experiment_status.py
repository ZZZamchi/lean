#!/usr/bin/env python3
"""
Summarize FATE-related proof_results.json and auxiliary result dirs.
Run: python3 scripts/report_fate_experiment_status.py
Writes: results/prover/fate_experiment_status.txt
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROVER = REPO / "results" / "prover"
OUT = PROVER / "fate_experiment_status.txt"


def count_json(path: Path) -> tuple[int, int, float] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return (-1, -1, 0.0)
    if not isinstance(data, list):
        return None
    n = len(data)
    ok = sum(1 for r in data if isinstance(r, dict) and r.get("complete") is True)
    pct = 100.0 * ok / n if n else 0.0
    return n, ok, pct


def main() -> None:
    lines = [
        f"# FATE experiment status (auto) — {datetime.utcnow().isoformat()}Z",
        "",
    ]
    candidates = sorted(PROVER.glob("fate*/proof_results.json"))
    if not candidates:
        lines.append("No results/prover/fate*/proof_results.json found.")
    for p in candidates:
        rel = p.relative_to(REPO)
        st = count_json(p)
        if st is None:
            lines.append(f"{rel}: (skip)")
            continue
        if st[0] < 0:
            lines.append(f"{rel}: JSON parse error")
            continue
        n, ok, pct = st
        mtime = datetime.utcfromtimestamp(p.stat().st_mtime).isoformat() + "Z"
        lines.append(f"{rel}: N={n} complete={ok} ({pct:.2f}%) mtime={mtime}")

    # Auxiliary dirs (subproblem / REPL chunks) — presence only
    extra = [
        REPO / "results" / "fate_h_goedel_gpu67",
        REPO / "results" / "fate_h_deepseek_gpu12",
    ]
    lines.append("")
    lines.append("## Auxiliary dirs (not whole-proof pass rates)")
    for d in extra:
        if d.is_dir():
            n_json = sum(1 for _ in d.rglob("*.json"))
            lines.append(f"{d.relative_to(REPO)}: exists, ~{n_json} json files under tree")
        else:
            lines.append(f"{d.relative_to(REPO)}: missing")

    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
