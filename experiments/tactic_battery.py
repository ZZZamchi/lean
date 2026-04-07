#!/usr/bin/env python3
"""
Tactic battery: try a suite of automated Lean tactics on all unsolved sorry sub-goals.

No LLM needed - just Lean REPL + built-in search tactics.
Tactics tried (in order):
  assumption, exact?, omega, norm_num, simp, decide, ring, aesop, linarith, tauto
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prover.config import VerifierConfig
from prover.verifier import LeanVerifier

MANIFEST = "results/minif2f/round_2/subproblem_mvp/_sorry_goals_for_inference.jsonl"
GOEDEL_RESULTS = "results/minif2f/round_2/subproblem_mvp/sorry_goal_goedel/code_compilation_repl.json"

TACTIC_BATTERY = [
    "assumption",
    "trivial",
    "tauto",
    "omega",
    "norm_num",
    "simp",
    "ring",
    "linarith",
    "positivity",
    "decide",
    "aesop",
    "norm_num [Rat.add_def, Rat.mk_eq_divInt]",
    "simp only [Rat.add_def, Rat.mk_eq_divInt]; omega",
    "exact?",
]


def load_unsolved_goals():
    """Load sorry sub-goals not solved by any model."""
    import re
    from collections import defaultdict

    def get_base_pid(pid):
        return re.sub(r'_g\d+$', '', pid)

    goals = {}
    with open(MANIFEST) as f:
        for line in f:
            g = json.loads(line)
            goals[g["problem_id"]] = g

    with open(GOEDEL_RESULTS) as f:
        results = json.load(f)

    goal_samples = defaultdict(list)
    for entry in results:
        goal_pid = get_base_pid(entry["problem_id"])
        goal_samples[goal_pid].append(entry)

    solved = set()
    for gid, samples in goal_samples.items():
        if any(s["compilation_result"].get("complete", False) for s in samples):
            solved.add(gid)

    unsolved = {gid: info for gid, info in goals.items() if gid not in solved}
    return unsolved


def try_tactic(verifier, lean4_code, tactic):
    """Replace 'sorry' with a tactic and verify."""
    code = lean4_code.replace(":= by sorry", f":= by\n  {tactic}")
    if ":= by sorry" in code:
        code = code.replace("by sorry", f"by\n  {tactic}")
    if "sorry" in code:
        code = code.replace("sorry", tactic)

    try:
        result = verifier.verify(code)
        return result.complete, result
    except Exception as e:
        return False, str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", default="results/experiments/tactic_battery_results.json")
    args = parser.parse_args()

    unsolved = load_unsolved_goals()
    print(f"Unsolved sub-goals: {len(unsolved)}")

    print("Starting Lean verifier...")
    verifier = LeanVerifier(VerifierConfig(timeout=args.timeout))
    verifier.start()

    results = []
    newly_solved = []

    try:
        for i, (gid, info) in enumerate(sorted(unsolved.items())):
            print(f"\n[{i+1}/{len(unsolved)}] {gid}")
            print(f"  Base: {info['_base_problem']}")
            goal_text = info['_sorry_goal']
            conclusion = goal_text.split('⊢')[-1].strip()[:80] if '⊢' in goal_text else '?'
            print(f"  Goal: ...⊢ {conclusion}")

            solved_by = None
            for tactic in TACTIC_BATTERY:
                t0 = time.time()
                try:
                    success, res = try_tactic(verifier, info["lean4_code"], tactic)
                except Exception as e:
                    print(f"    {tactic}: ERROR ({e})")
                    verifier.stop()
                    time.sleep(1)
                    verifier.start()
                    continue
                elapsed = time.time() - t0

                if success:
                    print(f"    {tactic}: *** SOLVED *** ({elapsed:.1f}s)")
                    solved_by = tactic
                    break
                else:
                    status = "pass" if (hasattr(res, 'success') and res.success) else "fail"
                    print(f"    {tactic}: {status} ({elapsed:.1f}s)")

                if tactic == "exact?" and elapsed > 20:
                    print(f"    (skipping remaining slow tactics)")
                    break

            result = {
                "goal_id": gid,
                "base_problem": info["_base_problem"],
                "solved": solved_by is not None,
                "solved_by": solved_by,
                "goal_conclusion": conclusion,
            }
            results.append(result)

            if solved_by:
                newly_solved.append((gid, solved_by))

            os.makedirs(os.path.dirname(args.output), exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    finally:
        verifier.stop()

    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(newly_solved)}/{len(unsolved)} solved by tactic battery")
    for gid, tactic in newly_solved:
        print(f"  ✓ {gid} → {tactic}")

    if not newly_solved:
        print("  (none solved)")


if __name__ == "__main__":
    main()
