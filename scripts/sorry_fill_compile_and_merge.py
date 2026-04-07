#!/usr/bin/env python3
"""
Compile sorry-goal inference outputs, then merge successful proofs back into
the original sorry-containing baseline proofs. Report which problems are newly solved.
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


def run_compile(input_path, output_path, cpu=16, timeout=120, chunk_size=500):
    """Run compile_by_chunks.py on the input."""
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
    print(f"  Compiling {input_path} ...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 3)
    if result.returncode != 0:
        print(f"  Compile failed: {result.stderr[-500:]}")
        return False
    print(f"  Done: {output_path}")
    return True


def analyze_results(compiled_path, failed_bids):
    """Check which problems got complete proofs."""
    compiled = load(compiled_path)
    
    newly_solved = defaultdict(list)
    for r in compiled:
        cr = r.get("compilation_result") or {}
        if cr.get("complete"):
            pid = r.get("problem_id", "")
            bid = pid.split("__")[0] if "__" in pid else base_id(pid)
            if bid in failed_bids:
                newly_solved[bid].append({
                    "problem_id": pid,
                    "code": r.get("code", ""),
                })
    
    return newly_solved


def merge_back_to_baseline(
    baseline_path, sorry_proofs_meta, newly_solved, output_path
):
    """For each newly solved problem, replace a sorry proof in baseline with the complete one."""
    baseline = load(baseline_path)
    
    merged = list(baseline)
    replacements = 0
    
    for bid, solutions in newly_solved.items():
        if not solutions:
            continue
        best = solutions[0]
        meta = sorry_proofs_meta.get(bid)
        if not meta:
            continue
        
        for i, r in enumerate(merged):
            if r.get("problem_id") == meta["original_pid"]:
                new_r = dict(r)
                new_r["code"] = best["code"]
                new_r["compilation_result"] = {"pass": True, "complete": True, "sorries": [], "errors": []}
                merged[i] = new_r
                replacements += 1
                break
    
    with open(output_path, "w") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(f"Merged {replacements} complete proofs into baseline → {output_path}")
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inference_dir", required=True, help="Dir with to_inference_codes.json")
    ap.add_argument("--baseline", default="results/minif2f/round_2/code_compilation_repl.json")
    ap.add_argument("--sorry_goals_jsonl", 
                     default="results/minif2f/round_2/subproblem_mvp/_sorry_goals_for_inference.jsonl")
    ap.add_argument("--cpu", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--output_dir", default=None)
    args = ap.parse_args()
    
    os.chdir(Path(__file__).resolve().parent.parent)
    
    baseline = load(args.baseline)
    by_bid = defaultdict(list)
    for r in baseline:
        cr = r.get("compilation_result") or {}
        by_bid[base_id(str(r.get("problem_id", "")))].append(r)
    failed_bids = {bid for bid, rows in by_bid.items()
                   if not any((r.get("compilation_result") or {}).get("complete") for r in rows)}
    
    print(f"Baseline: {len(baseline)} samples, {len(failed_bids)} failed problems")
    
    sorry_meta = {}
    with open(args.sorry_goals_jsonl) as f:
        for line in f:
            d = json.loads(line)
            bid = d.get("_base_problem", "")
            if bid and bid not in sorry_meta:
                sorry_meta[bid] = {
                    "original_pid": d.get("_original_pid", ""),
                    "sorry_goal": d.get("_sorry_goal", ""),
                }
    
    inf_codes = os.path.join(args.inference_dir, "to_inference_codes.json")
    if not os.path.exists(inf_codes):
        print(f"Error: {inf_codes} not found. Inference not complete?")
        sys.exit(1)
    
    output_dir = args.output_dir or args.inference_dir
    compiled_path = os.path.join(output_dir, "code_compilation_repl.json")
    
    if not os.path.exists(compiled_path):
        run_compile(inf_codes, compiled_path, args.cpu, args.timeout)
    
    if not os.path.exists(compiled_path):
        print("Compilation failed!")
        sys.exit(1)
    
    newly_solved = analyze_results(compiled_path, failed_bids)
    
    print(f"\n=== Results ===")
    print(f"Newly solved: {len(newly_solved)} problems")
    for bid in sorted(newly_solved):
        n = len(newly_solved[bid])
        print(f"  {bid}: {n} complete proofs")
    
    if newly_solved:
        merged_path = os.path.join(output_dir, "baseline_with_sorry_fills.json")
        merge_back_to_baseline(args.baseline, sorry_meta, newly_solved, merged_path)
    
    return len(newly_solved)


if __name__ == "__main__":
    main()
