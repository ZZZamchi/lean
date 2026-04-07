#!/usr/bin/env python3
"""
Generate cross-dataset comparison report from proof_results.json files.

Usage:
  python -m prover.generate_report                    # auto-discover all results
  python -m prover.generate_report --results-dir results/prover  # specify dir
"""
import argparse
import json
import os
import sys
from pathlib import Path

from .evaluate import cross_dataset_report, evaluate_results, print_report


def discover_results(results_dir: str) -> dict[str, str]:
    """Find all proof_results.json files in subdirectories."""
    found = {}
    base = Path(results_dir)
    if not base.exists():
        return found
    for child in sorted(base.iterdir()):
        if child.is_dir():
            result_file = child / "proof_results.json"
            if result_file.exists():
                found[child.name] = str(result_file)
    return found


def load_and_evaluate(path: str) -> dict:
    """Load results and compute metrics, handling partial results."""
    try:
        metrics = evaluate_results(path, k_values=[1, 8, 32])
        return metrics
    except Exception as e:
        print(f"  Warning: Failed to evaluate {path}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Cross-dataset evaluation report")
    parser.add_argument("--results-dir", default="results/prover",
                        help="Directory containing dataset result folders")
    parser.add_argument("--output", default=None,
                        help="Save report to file (default: print to stdout)")
    parser.add_argument("--json-output", default=None,
                        help="Save metrics as JSON")
    args = parser.parse_args()

    discovered = discover_results(args.results_dir)
    if not discovered:
        print(f"No results found in {args.results_dir}/")
        sys.exit(1)

    print(f"Found {len(discovered)} result sets:\n")
    all_metrics = {}

    for ds_name, path in discovered.items():
        with open(path) as f:
            data = json.load(f)
        n_problems = len(data)
        n_solved = sum(1 for r in data if r.get("complete"))

        metrics = load_and_evaluate(path)
        if metrics:
            all_metrics[ds_name] = metrics
            status = f"{n_solved}/{n_problems} solved"
            running = " (still running)" if n_problems < 10 else ""
            print(f"  {ds_name}: {status}{running}")

    if not all_metrics:
        print("No valid results to report.")
        sys.exit(1)

    print()
    for ds_name, metrics in all_metrics.items():
        print_report(metrics, dataset_name=ds_name)

    if len(all_metrics) > 1:
        report = cross_dataset_report(all_metrics)
        print(report)

        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"\nReport saved to {args.output}")

    if args.json_output:
        serializable = {}
        for ds, m in all_metrics.items():
            serializable[ds] = {
                "total": m["total"],
                "solved": m["solved"],
                "solve_rate": m["solve_rate"],
                "pass_at_k": {str(k): v for k, v in m.get("pass_at_k", {}).items()},
            }
        with open(args.json_output, "w") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        print(f"Metrics saved to {args.json_output}")


if __name__ == "__main__":
    main()
