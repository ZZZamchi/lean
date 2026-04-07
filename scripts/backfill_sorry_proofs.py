#!/usr/bin/env python3
"""
Backfill sorry-goal proofs into original sorry-containing proofs.
For each original proof with sorry gaps:
  1. Map each sorry position to its sorry-goal theorem
  2. Extract the proof body from the complete sorry-goal proof
  3. Replace sorry in the original proof
  4. Compile to verify completeness
"""
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def load(p):
    with open(p) as f:
        return json.load(f)


def base_id(pid):
    return re.sub(r"_g\d+$", "", str(pid or ""))


def extract_proof_body(code: str) -> str:
    """Extract the proof body from a complete theorem (after ':= by')."""
    m = re.search(r":=\s*by\b(.*)", code, re.DOTALL)
    if m:
        body = m.group(1).strip()
        if body == "sorry":
            return ""
        return body
    return ""


def main():
    os.chdir(Path(__file__).resolve().parent.parent)

    # 1) Load sorry goals mapping
    sorry_map = {}  # sorry_pid -> {base, original_pid, sorry_goal, sorry_index}
    base_sorry_pids = defaultdict(list)  # base_problem -> [sorry_pids in order]
    with open("results/minif2f/round_2/subproblem_mvp/_sorry_goals_for_inference.jsonl") as f:
        for line in f:
            d = json.loads(line)
            spid = d["problem_id"]
            base = d.get("_base_problem", "")
            sorry_map[spid] = {
                "base": base,
                "original_pid": d.get("_original_pid", ""),
                "sorry_goal": d.get("_sorry_goal", ""),
            }
            base_sorry_pids[base].append(spid)

    # 2) Load baseline
    baseline = load("results/minif2f/round_2/code_compilation_repl.json")
    by_bid = defaultdict(list)
    for r in baseline:
        bid = base_id(str(r.get("problem_id", "")))
        by_bid[bid].append(r)
    failed_bids = {bid for bid, rows in by_bid.items()
                   if not any((rr.get("compilation_result") or {}).get("complete") for rr in rows)}

    # 3) Load complete sorry-goal proofs (best per sorry_pid)
    best_proof = {}  # sorry_pid -> code
    for path in [
        "results/minif2f/round_2/subproblem_mvp/sorry_goal_goedel/code_compilation_repl.json",
        "results/minif2f/round_2/subproblem_mvp/sorry_goal_kimina/code_compilation_repl.json",
    ]:
        if not os.path.exists(path):
            continue
        data = load(path)
        for d in data:
            cr = d.get("compilation_result") or {}
            if cr.get("complete"):
                pid = str(d.get("problem_id", ""))
                spid = re.sub(r"_g\d+$", "", pid)
                code = d.get("code", "")
                if spid not in best_proof and code:
                    best_proof[spid] = code

    # 4) For each failed base problem, check coverage
    print(f"Failed problems: {len(failed_bids)}")
    print(f"Sorry-goal proofs available: {len(best_proof)}")
    print()

    candidates = []
    for base in sorted(failed_bids):
        spids = base_sorry_pids.get(base, [])
        if not spids:
            continue
        solved = [s for s in spids if s in best_proof]
        total = len(spids)

        # Find the original sorry proof
        original_pid = sorry_map[spids[0]]["original_pid"]
        original_proof = None
        for r in by_bid.get(base, []):
            if str(r.get("problem_id", "")) == original_pid:
                cr = r.get("compilation_result") or {}
                if cr.get("pass") and not cr.get("complete"):
                    original_proof = r
                    break

        status = "ALL_SOLVED" if len(solved) == total else f"{len(solved)}/{total}"
        print(f"  {base}: {status} sorry goals, original_pid={original_pid}, has_proof={'YES' if original_proof else 'NO'}")

        if len(solved) == total and original_proof:
            # Extract proof bodies for each sorry goal
            bodies = []
            for spid in spids:
                body = extract_proof_body(best_proof[spid])
                bodies.append(body)
                print(f"    {spid}: body={body[:80]}...")

            # Build backfilled code
            code = original_proof.get("code", "")
            filled = code
            for body in bodies:
                if body:
                    filled = filled.replace("sorry", body, 1)
                else:
                    print(f"    WARNING: empty proof body for {spid}")

            candidates.append({
                "problem_id": f"{base}_backfilled",
                "origin_problem_id": base,
                "code": filled,
                "full_code": filled,
            })
            print(f"    -> Backfilled code ready ({len(filled)} chars)")

    print(f"\nTotal backfill candidates: {len(candidates)}")

    if candidates:
        out_path = "results/minif2f/round_2/subproblem_mvp/_backfill_to_compile.json"
        with open(out_path, "w") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
        print(f"Written to {out_path}")

        # Also output in the format compile_by_chunks expects
        compile_input = []
        for c in candidates:
            compile_input.append({
                "problem_id": c["problem_id"],
                "full_code": c["full_code"],
            })
        compile_path = "results/minif2f/round_2/subproblem_mvp/_backfill_inference_codes.json"
        with open(compile_path, "w") as f:
            json.dump(compile_input, f, indent=2, ensure_ascii=False)
        print(f"Compile input: {compile_path}")

    return len(candidates)


if __name__ == "__main__":
    main()
