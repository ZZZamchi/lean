#!/usr/bin/env python3
"""
Take sorry-containing proofs from baseline, try replacing sorry with common tactics,
compile, and report which replacements produce complete proofs.

Small-scale experiment to test whether tactic brute-force can close sorry gaps.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Tuple


TACTICS_TO_TRY = [
    "omega",
    "norm_num",
    "simp",
    "decide",
    "native_decide",
    "ring",
    "linarith",
    "positivity",
    "exact?",
    "aesop",
    "tauto",
    "trivial",
    "norm_num [Finset.sum, Finset.prod]",
    "simp only [Finset.sum, Finset.prod, Finset.card]",
    "simp [Nat.Prime]",
]


def load_json(p):
    with open(p) as f:
        return json.load(f)


def base_id(pid):
    return re.sub(r"_g\d+$", "", str(pid or ""))


def find_sorry_proofs(baseline, target_bids=None, max_sorry=2, max_per_bid=2):
    """Find samples with sorry that are candidates for tactic replacement."""
    from collections import defaultdict
    by_bid = defaultdict(list)
    for r in baseline:
        cr = r.get("compilation_result") or {}
        if not cr.get("pass"):
            continue
        if cr.get("complete"):
            continue
        sorries = cr.get("sorries", [])
        if not sorries or len(sorries) > max_sorry:
            continue
        bid = base_id(r["problem_id"])
        if target_bids and bid not in target_bids:
            continue
        by_bid[bid].append(r)

    result = []
    for bid in sorted(by_bid):
        candidates = sorted(by_bid[bid], key=lambda r: len(r.get("compilation_result", {}).get("sorries", [])))
        for r in candidates[:max_per_bid]:
            result.append(r)
    return result


def make_variants(code: str, sorries_info: list) -> List[Tuple[str, str]]:
    """Generate code variants by replacing sorry with tactics.

    Strategy: replace ALL sorry occurrences with the same tactic first,
    then try per-sorry if there are multiple.
    """
    variants = []

    for tactic in TACTICS_TO_TRY:
        new_code = code.replace("sorry", tactic)
        variants.append((f"all_sorry→{tactic}", new_code))

    if code.count("sorry") == 1:
        return variants

    sorry_positions = [m.start() for m in re.finditer(r'\bsorry\b', code)]
    if len(sorry_positions) <= 3:
        for i, pos in enumerate(sorry_positions):
            for tactic in TACTICS_TO_TRY[:8]:
                new_code = code[:pos] + tactic + code[pos + 5:]
                variants.append((f"sorry[{i}]→{tactic}", new_code))

    return variants


def compile_one(code: str, env: str, repl_path: str, timeout: int = 120) -> dict:
    """Compile a single proof using the Lean REPL."""
    import tempfile
    payload = json.dumps([{"cmd": code, "env": env}])
    try:
        result = subprocess.run(
            ["python3", "scripts/compile_lean_repl.py",
             "--code", code, "--env", env],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="results/minif2f/round_2/code_compilation_repl.json")
    ap.add_argument("--problems", nargs="*", help="specific base_ids to try")
    ap.add_argument("--max_sorry", type=int, default=2)
    ap.add_argument("--max_per_bid", type=int, default=1)
    ap.add_argument("--output", default="results/minif2f/round_2/subproblem_mvp/_sorry_fill_experiments.json")
    ap.add_argument("--compile_timeout", type=int, default=120)
    ap.add_argument("--dry_run", action="store_true", help="Just show variants, don't compile")
    args = ap.parse_args()

    os.chdir(Path(__file__).resolve().parent.parent)
    baseline = load_json(args.baseline)
    target = set(args.problems) if args.problems else None
    candidates = find_sorry_proofs(baseline, target, args.max_sorry, args.max_per_bid)

    print(f"Found {len(candidates)} sorry-proof candidates")

    all_results = []
    for r in candidates:
        pid = r["problem_id"]
        bid = base_id(pid)
        code = r.get("code", "")
        env = r.get("env", "")
        cr = r.get("compilation_result") or {}
        sorries = cr.get("sorries", [])

        print(f"\n{'='*60}")
        print(f"Problem: {bid} ({pid})")
        print(f"  code_len={len(code)}, sorry_count={len(sorries)}")
        for i, s in enumerate(sorries):
            goal = s.get("goal", "")
            print(f"  sorry[{i}] goal: {goal[:150]}")

        variants = make_variants(code, sorries)
        print(f"  Trying {len(variants)} tactic variants...")

        if args.dry_run:
            all_results.append({
                "problem_id": pid,
                "base_id": bid,
                "n_sorry": len(sorries),
                "n_variants": len(variants),
                "goals": [s.get("goal", "")[:200] for s in sorries],
            })
            continue

        for label, new_code in variants:
            row = {
                "code": new_code,
                "env": env,
                "problem_id": pid,
                "name": pid,
            }
            row_path = Path(args.output).parent / "_sorry_fill_tmp.json"
            with open(row_path, "w") as f:
                json.dump([row], f)

            compile_result = subprocess.run(
                ["python3", "scripts/compile_by_chunks.py",
                 "--input_path", str(row_path),
                 "--output_path", str(row_path.with_suffix(".compiled.json")),
                 "--chunk_size", "1",
                 "--cpu", "1",
                 "--timeout", str(args.compile_timeout),
                 "--force"],
                capture_output=True, text=True, timeout=args.compile_timeout + 30,
                cwd=str(Path(__file__).resolve().parent.parent),
            )

            compiled = []
            compiled_path = row_path.with_suffix(".compiled.json")
            if compiled_path.exists():
                compiled = load_json(compiled_path)

            if compiled:
                comp_r = compiled[0].get("compilation_result", {})
                is_pass = bool(comp_r.get("pass"))
                is_complete = bool(comp_r.get("complete"))
                n_sorry = len(comp_r.get("sorries", []))
                n_err = len(comp_r.get("errors", []))
            else:
                is_pass = False
                is_complete = False
                n_sorry = -1
                n_err = -1

            status = "COMPLETE" if is_complete else ("pass+sorry" if is_pass else "fail")
            if is_complete:
                print(f"  *** {label} => COMPLETE! ***")
            elif is_pass and n_sorry == 0:
                print(f"  *** {label} => PASS (no sorry, but not complete?) ***")

            entry = {
                "problem_id": pid, "base_id": bid,
                "variant": label, "status": status,
                "pass": is_pass, "complete": is_complete,
                "n_sorry": n_sorry, "n_errors": n_err,
            }
            all_results.append(entry)

            if is_complete:
                entry["code"] = new_code
                print(f"  Found complete proof! Stopping search for {bid}.")
                break

    os.makedirs(Path(args.output).parent, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(all_results)} results to {args.output}")

    n_complete = sum(1 for r in all_results if r.get("complete"))
    n_bids = len(set(r.get("base_id") for r in all_results if r.get("complete")))
    print(f"Complete proofs found: {n_complete} ({n_bids} unique problems)")


if __name__ == "__main__":
    main()
