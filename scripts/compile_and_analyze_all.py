#!/usr/bin/env python3
"""
Compile all inference outputs and analyze which of the 41 failed problems are newly solved.
Handles both 'sorry goal' inference and 'whole problem' inference.
"""
import argparse
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


def run_compile(input_path, output_path, cpu=16, timeout=300, chunk_size=500):
    cmd = [
        "python3", "scripts/compile_by_chunks.py",
        "--input_path", input_path,
        "--output_path", output_path,
        "--chunk_size", str(chunk_size),
        "--cpu", str(cpu),
        "--timeout", str(timeout),
        "--force",
        "--reeval-abnormal",
    ]
    print(f"  Compiling {input_path} -> {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 5)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr[-1000:]}")
        return False
    print(f"  OK")
    return True


def analyze_dir(inference_dir, failed_bids, label=""):
    """Compile and analyze one inference output directory."""
    inf_codes = os.path.join(inference_dir, "to_inference_codes.json")
    if not os.path.exists(inf_codes):
        print(f"  [{label}] to_inference_codes.json not found — skipping")
        return {}

    compiled_path = os.path.join(inference_dir, "code_compilation_repl.json")
    if not os.path.exists(compiled_path):
        ok = run_compile(inf_codes, compiled_path)
        if not ok:
            return {}

    compiled = load(compiled_path)
    total = len(compiled)
    n_complete = 0
    newly_solved = defaultdict(list)

    for r in compiled:
        cr = r.get("compilation_result") or {}
        if cr.get("complete"):
            n_complete += 1
            pid = str(r.get("problem_id", ""))
            origin = str(r.get("origin_problem_id", ""))
            bid = origin if origin else base_id(pid)
            bid = bid.split("__")[0] if "__" in bid else base_id(bid)
            if bid in failed_bids:
                newly_solved[bid].append({
                    "problem_id": pid,
                    "code": r.get("full_code") or r.get("code", ""),
                })

    print(f"  [{label}] {total} samples, {n_complete} complete, {len(newly_solved)} newly-solved problems from the 41 failed")
    return dict(newly_solved)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="results/minif2f/round_2/code_compilation_repl.json")
    ap.add_argument("--dirs", nargs="+", required=True,
                    help="label:path pairs, e.g. goedel_sorry:results/.../sorry_goal_goedel")
    ap.add_argument("--cpu", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    os.chdir(Path(__file__).resolve().parent.parent)

    baseline = load(args.baseline)
    by_bid = defaultdict(list)
    for r in baseline:
        by_bid[base_id(str(r.get("problem_id", "")))].append(r)
    failed_bids = {bid for bid, rows in by_bid.items()
                   if not any((rr.get("compilation_result") or {}).get("complete") for rr in rows)}

    print(f"Baseline: {len(baseline)} samples, {len(failed_bids)} failed problems\n")

    all_solved = defaultdict(list)
    for entry in args.dirs:
        if ":" in entry:
            label, path = entry.split(":", 1)
        else:
            label = os.path.basename(entry.rstrip("/"))
            path = entry
        if not os.path.isdir(path):
            print(f"  [{label}] directory not found — skipping")
            continue
        solved = analyze_dir(path, failed_bids, label)
        for bid, proofs in solved.items():
            all_solved[bid].extend(proofs)

    print(f"\n{'='*60}")
    print(f"TOTAL newly solved (from 41 failed): {len(all_solved)} problems")
    for bid in sorted(all_solved):
        n = len(all_solved[bid])
        print(f"  {bid}: {n} complete proof(s)")

    if all_solved:
        out = {}
        for bid, proofs in all_solved.items():
            out[bid] = proofs[0]["code"]
        outpath = "results/minif2f/round_2/subproblem_mvp/_newly_solved_from_inference.json"
        with open(outpath, "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nBest proofs saved to {outpath}")

    return len(all_solved)


if __name__ == "__main__":
    main()
