#!/usr/bin/env python3
"""
Deterministic proof sketch for AIME 1984 p7 Round-3 subgoals whose conclusion is
  f k = f (f (k+5))  with k < 1000
using only h₁ (the recursion rule) and norm_num/simpa — same pattern as Goedel-8B
solutions for g0–g2.

Run from repo root: python experiments/round3_aime_h1_template.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOAL_TAIL = re.compile(
    r":\s*f\s+(-?\d+)\s*=\s*f\s*\(\s*f\s+(-?\d+)\s*\)\s*:=\s*by\s*sorry\s*$",
    re.MULTILINE | re.DOTALL,
)


def build_proof(k: int, k2: int) -> str | None:
    if k + 5 != k2:
        return None
    if not (-1000 < k < 1000):
        return None
    return f"""  have step_lt : ({k} : ℤ) < 1000 := by norm_num
  have step_rec : f {k} = f (f ({k} + 5)) := h₁ {k} step_lt
  have step_res : f {k} = f (f {k2}) := by
    norm_num at step_rec ⊢
    <;> simpa using step_rec
  exact step_res"""


def try_fill(lean4_code: str) -> tuple[str | None, str | None]:
    m = GOAL_TAIL.search(lean4_code)
    if not m:
        return None, "goal tail not f k = f (f k2)"
    k, k2 = int(m.group(1)), int(m.group(2))
    body = build_proof(k, k2)
    if body is None:
        return None, f"k+5!=k2 or bound: {k},{k2}"
    filled = lean4_code.replace(":= by sorry", ":= by\n" + body, 1)
    return filled, None


def main() -> int:
    from prover.strategies.base import ProofStrategy
    from prover.verifier import LeanVerifier
    from prover.config import VerifierConfig

    jl = ROOT / "results/experiments/recursive_round3/round3_subgoals.jsonl"
    pr = ROOT / "results/experiments/recursive_round3/goedel_8b/proof_results.json"
    done = set()
    if pr.is_file():
        with open(pr) as f:
            for row in json.load(f):
                if row.get("complete"):
                    done.add(row["problem_id"])

    v = LeanVerifier(VerifierConfig())
    v.start()
    ok = 0
    skip = 0
    fail = 0
    try:
        for line in jl.read_text().splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            pid = o["problem_id"]
            if "aime_1984_p7" not in pid:
                continue
            if pid in done:
                skip += 1
                continue
            code = o.get("lean4_code") or o.get("formal_statement", "")
            filled, err = try_fill(code)
            if filled is None:
                print(f"[skip] {pid}: {err}")
                skip += 1
                continue
            r = v.verify(ProofStrategy.strip_imports(filled))
            if r.success and r.complete:
                print(f"[OK] {pid}")
                ok += 1
            else:
                print(f"[FAIL] {pid} success={r.success} complete={r.complete} err={r.errors[:1]}")
                fail += 1
    finally:
        v.stop()

    print(f"\nSummary: template_ok={ok}, skip_or_no_pattern={skip}, verify_fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
