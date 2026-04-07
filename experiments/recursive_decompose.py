#!/usr/bin/env python3
"""
Recursive sorry-goal decomposition (Round 3).

Takes pass-but-not-complete samples from Round 2 sorry-goal experiments,
extracts the NEW sub-goals (not trivial, not circular), formats them as
independent theorems, and creates a dataset for the next round of proving.
"""
import json
import os
import re
import sys
from collections import defaultdict

MANIFEST = "results/minif2f/round_2/subproblem_mvp/_sorry_goals_for_inference.jsonl"
GOEDEL_RESULTS = "results/minif2f/round_2/subproblem_mvp/sorry_goal_goedel/code_compilation_repl.json"
OUTPUT_DIR = "results/experiments/recursive_round3"
PREAMBLE = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n"


def get_base_pid(pid):
    return re.sub(r'_g\d+$', '', pid)


def goal_to_theorem(goal_text, theorem_name):
    """Convert a goal state to an independent theorem statement."""
    lines = goal_text.strip().split('\n')
    hypotheses = []
    conclusion = ""

    for line in lines:
        line = line.strip()
        if line.startswith('⊢'):
            conclusion = line[1:].strip()
        elif ':' in line and not line.startswith('case'):
            parts = line.split(':', 1)
            var_name = parts[0].strip()
            var_type = parts[1].strip()
            hypotheses.append(f"({var_name} : {var_type})")

    if not conclusion:
        return None

    hyps_str = " ".join(hypotheses)
    return f"theorem {theorem_name} {hyps_str} : {conclusion} := by sorry"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sorry_goals = {}
    with open(MANIFEST) as f:
        for line in f:
            g = json.loads(line)
            sorry_goals[g["problem_id"]] = g

    with open(GOEDEL_RESULTS) as f:
        goedel_results = json.load(f)

    goal_samples = defaultdict(list)
    for entry in goedel_results:
        goal_pid = get_base_pid(entry["problem_id"])
        goal_samples[goal_pid].append(entry)

    solved = {gid for gid, samps in goal_samples.items()
              if any(s["compilation_result"].get("complete", False) for s in samps)}
    unsolved = set(sorry_goals.keys()) - solved

    new_goals = []
    seen = set()
    proof_map = {}  # parent_goal -> list of (proof_code, [subgoal_ids])

    for gid in sorted(unsolved):
        samples = goal_samples.get(gid, [])
        pass_samples = [s for s in samples
                        if s["compilation_result"].get("pass", False)
                        and not s["compilation_result"].get("complete", False)]

        info = sorry_goals.get(gid, {})
        orig_goal = info.get("_sorry_goal", "")
        orig_conclusion = orig_goal.split("⊢")[-1].strip() if "⊢" in orig_goal else ""
        base_problem = info.get("_base_problem", "")

        for si, s in enumerate(pass_samples[:5]):
            code = s.get("code", "")
            sorries = s["compilation_result"].get("sorries", [])
            subgoal_ids = []

            for gi, sorry in enumerate(sorries):
                goal_text = sorry.get("goal", "")
                if not goal_text or "⊢" not in goal_text:
                    continue

                conclusion = goal_text.split("⊢")[-1].strip()

                hyps = goal_text.split("⊢")[0]
                is_trivial = any(
                    line.strip().split(":", 1)[-1].strip() == conclusion
                    for line in hyps.split("\n")
                    if ":" in line
                )
                is_circular = (conclusion == orig_conclusion)

                subgoal_id = f"r3_{gid}_s{si}_g{gi}"
                category = "trivial" if is_trivial else ("circular" if is_circular else "new")

                theorem_stmt = goal_to_theorem(goal_text, subgoal_id)
                if not theorem_stmt:
                    continue

                goal_key = f"{gid}|{conclusion[:100]}"
                is_duplicate = goal_key in seen
                if not is_duplicate:
                    seen.add(goal_key)

                entry = {
                    "problem_id": subgoal_id,
                    "name": subgoal_id,
                    "lean4_code": f"{PREAMBLE}{theorem_stmt}",
                    "formal_statement": f"{PREAMBLE}{theorem_stmt}",
                    "informal_prefix": "",
                    "split": "none",
                    "_parent_goal": gid,
                    "_base_problem": base_problem,
                    "_sorry_goal": goal_text,
                    "_category": category,
                    "_sample_idx": si,
                    "_goal_idx": gi,
                    "_is_duplicate": is_duplicate,
                }
                new_goals.append(entry)
                subgoal_ids.append(subgoal_id)

            if subgoal_ids:
                proof_map.setdefault(gid, []).append({
                    "sample_idx": si,
                    "code": code,
                    "subgoal_ids": subgoal_ids,
                })

    stats = defaultdict(int)
    for g in new_goals:
        stats[g["_category"]] += 1
        if not g["_is_duplicate"]:
            stats[f"{g['_category']}_unique"] += 1

    print(f"Total new sub-goals: {len(new_goals)}")
    print(f"  new: {stats['new']} (unique: {stats.get('new_unique', 0)})")
    print(f"  trivial: {stats['trivial']} (unique: {stats.get('trivial_unique', 0)})")
    print(f"  circular: {stats['circular']} (unique: {stats.get('circular_unique', 0)})")
    print()

    unique_new = [g for g in new_goals if g["_category"] == "new" and not g["_is_duplicate"]]
    print(f"Unique NEW sub-goals for inference: {len(unique_new)}")

    manifest_path = os.path.join(OUTPUT_DIR, "round3_subgoals.jsonl")
    with open(manifest_path, "w") as f:
        for g in unique_new:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"Manifest written to {manifest_path}")

    dataset_path = os.path.join(OUTPUT_DIR, "round3_dataset.jsonl")
    with open(dataset_path, "w") as f:
        for g in unique_new:
            f.write(json.dumps({
                "problem_id": g["problem_id"],
                "name": g["name"],
                "lean4_code": g["lean4_code"],
                "formal_statement": g["formal_statement"],
                "informal_prefix": "",
                "split": "valid",
            }, ensure_ascii=False) + "\n")
    print(f"Dataset written to {dataset_path}")

    map_path = os.path.join(OUTPUT_DIR, "proof_map.json")
    with open(map_path, "w") as f:
        json.dump(proof_map, f, indent=2, ensure_ascii=False)
    print(f"Proof map written to {map_path}")

    by_parent = defaultdict(list)
    for g in unique_new:
        by_parent[g["_parent_goal"]].append(g)

    print(f"\nBreakdown by parent goal:")
    for parent, subs in sorted(by_parent.items(), key=lambda x: -len(x[1])):
        base = sorry_goals[parent]["_base_problem"]
        print(f"  {parent} ({base}): {len(subs)} unique new sub-goals")
        for s in subs[:2]:
            concl = s["_sorry_goal"].split("⊢")[-1].strip()[:80]
            print(f"    ⊢ {concl}")


if __name__ == "__main__":
    main()
