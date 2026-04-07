"""
Unified evaluation metrics across benchmarks.
"""
import json
import math
from collections import defaultdict
from typing import Optional


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator for pass@k (from the Codex paper)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


def evaluate_results(
    results_path: str,
    k_values: list[int] | None = None,
) -> dict:
    """
    Compute evaluation metrics from proof_results.json.

    Returns dict with:
    - total: number of problems
    - solved: number with complete proof
    - solve_rate: solved/total
    - pass_at_k: for each k
    - by_strategy: breakdown by strategy
    """
    with open(results_path) as f:
        results = json.load(f)

    if k_values is None:
        k_values = [1, 8, 32]

    total = len(results)
    solved = sum(1 for r in results if r.get("complete"))

    by_strategy = defaultdict(lambda: {"total": 0, "solved": 0})
    by_problem = defaultdict(lambda: {"n": 0, "c": 0})

    for r in results:
        s = r.get("strategy", "unknown")
        by_strategy[s]["total"] += 1
        if r.get("complete"):
            by_strategy[s]["solved"] += 1

        pid = r["problem_id"]
        by_problem[pid]["n"] = r.get("attempts", 1)
        if r.get("complete"):
            by_problem[pid]["c"] = 1

    pass_at = {}
    for k in k_values:
        scores = [pass_at_k(d["n"], d["c"], min(k, d["n"])) for d in by_problem.values()]
        pass_at[k] = sum(scores) / len(scores) if scores else 0.0

    return {
        "total": total,
        "solved": solved,
        "solve_rate": solved / total if total else 0,
        "pass_at_k": pass_at,
        "by_strategy": dict(by_strategy),
    }


def evaluate_compilation_results(
    results_path: str,
    k_values: list[int] | None = None,
) -> dict:
    """
    Evaluate from compilation result format (code_compilation_repl.json).
    Groups by base problem_id (strips _gN suffix).
    """
    import re
    with open(results_path) as f:
        results = json.load(f)

    if k_values is None:
        k_values = [1, 8, 32, 64]

    by_problem = defaultdict(lambda: {"n": 0, "c": 0, "sorry_count": 0, "error_count": 0})

    for r in results:
        pid = str(r.get("problem_id", ""))
        base_pid = re.sub(r"_g\d+$", "", pid)
        cr = r.get("compilation_result") or {}

        by_problem[base_pid]["n"] += 1
        if cr.get("complete"):
            by_problem[base_pid]["c"] += 1
        elif cr.get("pass") and not cr.get("complete"):
            by_problem[base_pid]["sorry_count"] += 1
        else:
            by_problem[base_pid]["error_count"] += 1

    total = len(by_problem)
    solved = sum(1 for d in by_problem.values() if d["c"] > 0)
    with_sorry = sum(1 for d in by_problem.values() if d["c"] == 0 and d["sorry_count"] > 0)

    pass_at = {}
    for k in k_values:
        scores = [pass_at_k(d["n"], d["c"], min(k, d["n"])) for d in by_problem.values()]
        pass_at[k] = sum(scores) / len(scores) if scores else 0.0

    return {
        "total": total,
        "solved": solved,
        "solve_rate": solved / total if total else 0,
        "with_sorry_only": with_sorry,
        "pure_error": total - solved - with_sorry,
        "pass_at_k": pass_at,
        "per_problem": dict(by_problem),
    }


def cross_dataset_report(
    dataset_results: dict[str, dict],
) -> str:
    """Generate a comparative report across multiple datasets."""
    lines = ["=" * 70, "CROSS-DATASET EVALUATION REPORT", "=" * 70, ""]

    header = f"{'Dataset':<20} {'Total':>6} {'Solved':>7} {'Rate':>8}"
    k_vals = set()
    for m in dataset_results.values():
        k_vals.update(m.get("pass_at_k", {}).keys())
    for k in sorted(k_vals):
        header += f" {'p@'+str(k):>7}"
    lines.append(header)
    lines.append("-" * len(header))

    for ds_name, metrics in dataset_results.items():
        row = f"{ds_name:<20} {metrics['total']:>6} {metrics['solved']:>7} {100*metrics['solve_rate']:>7.1f}%"
        for k in sorted(k_vals):
            v = metrics.get("pass_at_k", {}).get(k, 0)
            row += f" {100*v:>6.1f}%"
        lines.append(row)

    lines.append("-" * len(header))

    total_problems = sum(m["total"] for m in dataset_results.values())
    total_solved = sum(m["solved"] for m in dataset_results.values())
    rate = total_solved / total_problems if total_problems else 0
    overall = f"{'TOTAL':<20} {total_problems:>6} {total_solved:>7} {100*rate:>7.1f}%"
    lines.append(overall)

    lines.append("")
    lines.append("Difficulty Breakdown:")
    for ds_name, metrics in dataset_results.items():
        ws = metrics.get("with_sorry_only", 0)
        pe = metrics.get("pure_error", 0)
        if ws or pe:
            lines.append(f"  {ds_name}: {ws} near-miss (sorry), {pe} pure error")

    return "\n".join(lines)


def print_report(metrics: dict, dataset_name: str = ""):
    header = f"=== Evaluation: {dataset_name} ===" if dataset_name else "=== Evaluation ==="
    print(header)
    print(f"  Total problems: {metrics['total']}")
    print(f"  Solved:         {metrics['solved']} ({100*metrics['solve_rate']:.1f}%)")
    if "with_sorry_only" in metrics:
        print(f"  Near-miss:      {metrics['with_sorry_only']} (sorry only)")
        print(f"  Pure error:     {metrics['pure_error']}")
    print()
    for k, v in metrics.get("pass_at_k", {}).items():
        print(f"  pass@{k}: {100*v:.1f}%")
    print()
    if metrics.get("by_strategy"):
        print("  By strategy:")
        for s, d in metrics["by_strategy"].items():
            rate = d["solved"] / d["total"] * 100 if d["total"] else 0
            print(f"    {s}: {d['solved']}/{d['total']} ({rate:.1f}%)")
    print()
