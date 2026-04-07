#!/usr/bin/env python3
"""
Generate visualization charts for proof search results.

Usage:
  python -m prover.visualize                          # auto-discover results
  python -m prover.visualize --output-dir results/figures
"""
import argparse
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def pass_at_k(n: int, c: int, k: int) -> float:
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


def load_old_baseline(path: str, valid_pids: set | None = None) -> dict:
    """Load old pipeline code_compilation_repl.json and compute metrics."""
    with open(path) as f:
        data = json.load(f)
    by_pid = defaultdict(lambda: {"n": 0, "c": 0, "s": 0, "err": 0})
    for r in data:
        pid = re.sub(r"_g\d+$", "", str(r.get("problem_id", "")))
        if valid_pids and pid not in valid_pids:
            continue
        cr = r.get("compilation_result") or {}
        by_pid[pid]["n"] += 1
        if cr.get("complete"):
            by_pid[pid]["c"] += 1
        elif cr.get("pass") and not cr.get("complete"):
            by_pid[pid]["s"] += 1
        else:
            by_pid[pid]["err"] += 1
    return dict(by_pid)


def load_prover_results(path: str) -> dict:
    """Load prover framework proof_results.json."""
    with open(path) as f:
        data = json.load(f)
    by_pid = defaultdict(lambda: {"n": 0, "c": 0, "s": 0, "err": 0})
    for r in data:
        pid = r.get("problem_id", "")
        by_pid[pid]["n"] = r.get("attempts", 1)
        if r.get("complete"):
            by_pid[pid]["c"] = 1
        elif r.get("code", "") and "sorry" in r.get("code", ""):
            by_pid[pid]["s"] = 1
        else:
            by_pid[pid]["err"] = 1
    return dict(by_pid)


def compute_metrics(by_pid: dict) -> dict:
    total = len(by_pid)
    solved = sum(1 for d in by_pid.values() if d["c"] > 0)
    sorry = sum(1 for d in by_pid.values() if d["c"] == 0 and d["s"] > 0)
    error = sum(1 for d in by_pid.values() if d["c"] == 0 and d["s"] == 0)
    p32 = (
        sum(pass_at_k(d["n"], d["c"], min(32, d["n"])) for d in by_pid.values()) / total
        if total
        else 0
    )
    return {
        "total": total,
        "solved": solved,
        "sorry": sorry,
        "error": error,
        "pass_at_32": p32,
    }


def get_valid_pids(dataset_path: str) -> set:
    with open(dataset_path) as f:
        return {
            json.loads(l).get("problem_id", "")
            for l in f
            if l.strip() and json.loads(l).get("split") == "valid"
        }


def plot_pass_at_32_comparison(results: dict, output_path: str):
    """Bar chart comparing pass@32 across configurations."""
    fig, ax = plt.subplots(figsize=(12, 6))
    names = list(results.keys())
    values = [results[n]["pass_at_32"] * 100 for n in names]
    colors = plt.cm.Set2(np.linspace(0, 1, len(names)))

    bars = ax.bar(range(len(names)), values, color=colors, edgecolor="black", linewidth=0.5)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("Pass@32 (%)", fontsize=12)
    ax.set_title("Pass@32 Comparison Across Models and Strategies", fontsize=14)
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Saved: {output_path}")


def plot_failure_mode_comparison(goedel_metrics: dict, deepseek_metrics: dict, output_path: str):
    """Stacked bar chart showing failure mode distribution."""
    fig, ax = plt.subplots(figsize=(8, 6))
    models = ["Goedel-8B", "DeepSeek-7B"]
    solved = [goedel_metrics["solved"], deepseek_metrics["solved"]]
    sorry = [goedel_metrics["sorry"], deepseek_metrics["sorry"]]
    error = [goedel_metrics["error"], deepseek_metrics["error"]]

    x = np.arange(len(models))
    w = 0.5
    ax.bar(x, solved, w, label="Solved", color="#4CAF50")
    ax.bar(x, sorry, w, bottom=solved, label="Sorry (near-miss)", color="#FF9800")
    ax.bar(
        x, error, w,
        bottom=[s + sr for s, sr in zip(solved, sorry)],
        label="Error", color="#F44336",
    )

    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=12)
    ax.set_ylabel("Number of Problems", fontsize=12)
    ax.set_title("Failure Mode Distribution: miniF2F Valid (244 problems)", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    for i, model in enumerate(models):
        total = solved[i] + sorry[i] + error[i]
        ax.text(i, total + 2, f"pass@32={[goedel_metrics, deepseek_metrics][i]['pass_at_32']*100:.1f}%",
                ha="center", fontsize=10, fontweight="bold")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Saved: {output_path}")


def plot_cross_dataset(dataset_results: dict, output_path: str):
    """Bar chart for cross-dataset comparison."""
    fig, ax = plt.subplots(figsize=(10, 6))
    names = list(dataset_results.keys())
    values = [dataset_results[n]["pass_at_32"] * 100 for n in names]
    totals = [dataset_results[n]["total"] for n in names]

    colors = ["#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0"]
    bars = ax.bar(range(len(names)), values, color=colors[: len(names)], edgecolor="black", linewidth=0.5)

    ax.set_xticks(range(len(names)))
    labels = [f"{n}\n({totals[i]} problems)" for i, n in enumerate(names)]
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Pass@32 (%)", fontsize=12)
    ax.set_title("Goedel-8B Performance Across Datasets", fontsize=14)
    ax.set_ylim(0, 100)
    ax.grid(axis="y", alpha=0.3)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Saved: {output_path}")


def plot_nearmiss_delta(baseline_results: dict, nearmiss_results: dict, output_path: str):
    """Grouped bar chart showing baseline vs NearMiss improvement."""
    fig, ax = plt.subplots(figsize=(10, 6))
    configs = list(baseline_results.keys())
    baselines = [baseline_results[c] * 100 for c in configs]
    nearmiss = [nearmiss_results.get(c, baseline_results[c]) * 100 for c in configs]

    x = np.arange(len(configs))
    w = 0.35
    bars1 = ax.bar(x - w / 2, baselines, w, label="Baseline", color="#90CAF9", edgecolor="black", linewidth=0.5)
    bars2 = ax.bar(x + w / 2, nearmiss, w, label="+ NearMiss", color="#2196F3", edgecolor="black", linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(configs, rotation=15, ha="right", fontsize=9)
    ax.set_ylabel("Pass@32 (%)", fontsize=12)
    ax.set_title("NearMiss Sorry Filling: Baseline vs Improved", fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)

    for b1, b2, bv, nv in zip(bars1, bars2, baselines, nearmiss):
        delta = nv - bv
        if abs(delta) > 0.05:
            ax.annotate(
                f"+{delta:.1f}%",
                xy=(b2.get_x() + b2.get_width() / 2, nv),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
                color="green" if delta > 0 else "red",
            )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate visualization charts")
    parser.add_argument("--output-dir", default="results/figures")
    parser.add_argument("--dataset-path", default="dataset/minif2f.jsonl")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    base = Path(__file__).resolve().parent.parent
    print("Generating charts...\n")

    valid_pids = get_valid_pids(args.dataset_path)

    goedel_baseline = load_old_baseline(
        str(base / "results/minif2f/round_2/code_compilation_repl.json")
    )
    deepseek_baseline = load_old_baseline(
        str(base / "results/deepseek_prover_v2_minif2f/code_compilation_repl.json"),
        valid_pids,
    )
    g_metrics = compute_metrics(goedel_baseline)
    d_metrics = compute_metrics(deepseek_baseline)

    g_solved = {pid for pid, d in goedel_baseline.items() if d["c"] > 0}
    d_solved = {pid for pid, d in deepseek_baseline.items() if d["c"] > 0}
    oracle_p32 = len(g_solved | d_solved) / 244

    all_results = {
        "Goedel-8B\n(baseline)": g_metrics,
        "DeepSeek-7B\n(baseline)": d_metrics,
    }

    nearmiss_dirs = {
        "E1: Goedel+DeepSeek": "minif2f_valid_goedel_base_deepseek_fill",
        "E2: Goedel+Goedel": "minif2f_valid_goedel_base_goedel_fill",
        "E3: DeepSeek+Goedel": "minif2f_valid_deepseek_base_goedel_fill",
    }

    for label, dirname in nearmiss_dirs.items():
        path = base / "results" / "prover" / dirname / "proof_results.json"
        if path.exists():
            nm_data = load_prover_results(str(path))
            nm_metrics = compute_metrics(nm_data)
            all_results[label] = nm_metrics

    all_results["Oracle\nEnsemble"] = {
        "total": 244,
        "solved": len(g_solved | d_solved),
        "sorry": 0,
        "error": 244 - len(g_solved | d_solved),
        "pass_at_32": oracle_p32,
    }

    plot_pass_at_32_comparison(all_results, os.path.join(args.output_dir, "pass_at_32_comparison.png"))
    plot_failure_mode_comparison(g_metrics, d_metrics, os.path.join(args.output_dir, "failure_mode_comparison.png"))

    cross_ds = {}
    cross_ds["miniF2F\nvalid"] = g_metrics
    for name, path in [
        ("PutnamBench", "results/prover/putnambench_goedel8b/proof_results.json"),
        ("FATE-M", "results/prover/fate_m_goedel8b/proof_results.json"),
        ("FATE-H", "results/prover/fate_h_goedel8b/proof_results.json"),
    ]:
        full = base / path
        if full.exists():
            cross_ds[name] = compute_metrics(load_prover_results(str(full)))

    if len(cross_ds) > 1:
        plot_cross_dataset(cross_ds, os.path.join(args.output_dir, "cross_dataset_comparison.png"))

    putnam_baseline_path = base / "results/prover/putnambench_goedel8b/proof_results.json"
    putnam_nearmiss_path = base / "results/prover/putnambench_nearmiss_merged/proof_results.json"

    baseline_p32 = {}
    nearmiss_p32 = {}

    if putnam_baseline_path.exists():
        pb = load_prover_results(str(putnam_baseline_path))
        pb_m = compute_metrics(pb)
        pb_solved = {pid for pid, d in pb.items() if d["c"] > 0}
        baseline_p32["Putnam\n(Goedel-8B)"] = pb_m["pass_at_32"]

        if putnam_nearmiss_path.exists():
            pn = load_prover_results(str(putnam_nearmiss_path))
            pn_solved = {pid for pid, d in pn.items() if d["c"] > 0}
            combined = pb_solved | pn_solved
            nearmiss_p32["Putnam\n(Goedel-8B)"] = len(combined) / pb_m["total"] if pb_m["total"] else 0
        else:
            nearmiss_p32["Putnam\n(Goedel-8B)"] = pb_m["pass_at_32"]

    baseline_p32["miniF2F\n(Goedel-8B)"] = g_metrics["pass_at_32"]
    nearmiss_p32["miniF2F\n(Goedel-8B)"] = g_metrics["pass_at_32"]

    if baseline_p32:
        plot_nearmiss_delta(baseline_p32, nearmiss_p32, os.path.join(args.output_dir, "nearmiss_delta.png"))

    print("\nDone!")


if __name__ == "__main__":
    main()
