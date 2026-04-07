#!/usr/bin/env python3
"""
根据子问题尝试结果估计模型能力系数，并输出简单路由分数。
"""
import argparse
import json
import os
import re
from collections import defaultdict


def error_type(sig):
    if not sig:
        return "unknown"
    m = (sig.get("message") or "").lower()
    if "type mismatch" in m:
        return "type_mismatch"
    if "unsolved goals" in m:
        return "unsolved_goals"
    if "rewrite" in m or "rw" in m:
        return "rewrite"
    return "other"


def goal_bin(target: str):
    n = len(target or "")
    if n < 80:
        return "short"
    if n < 240:
        return "medium"
    return "long"


def normalize_compile_problem_id(pid: str) -> str:
    """Align compile JSON `problem_id` (…_gK) with manifest `subproblem_id`."""
    return re.sub(r"_g\d+$", "", str(pid or ""))


def main():
    ap = argparse.ArgumentParser(description="Compute model capability coefficients and router scores.")
    ap.add_argument("--input_manifest", required=True)
    ap.add_argument("--input_model_compiles", nargs="+", required=True, help="model=path_to_compile_json")
    ap.add_argument("--output_json", required=True)
    args = ap.parse_args()

    with open(args.input_manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    feat = {}
    for m in manifest:
        sid = m.get("subproblem_id")
        if not sid:
            continue
        sig = m.get("error_signature") or {}
        goal = (m.get("goal_state") or {}).get("target", "")
        feat[sid] = {
            "error_type": error_type(sig),
            "goal_bin": goal_bin(goal),
        }

    model_stats = {}
    for item in args.input_model_compiles:
        if "=" not in item:
            raise ValueError("input_model_compiles format must be model=path")
        model, path = item.split("=", 1)
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        by_err = defaultdict(lambda: [0, 0])  # succ,total
        by_goal = defaultdict(lambda: [0, 0])
        latency = []
        for r in rows:
            sid = normalize_compile_problem_id(r.get("problem_id") or "")
            if not sid or sid not in feat:
                continue
            ok = bool((r.get("compilation_result") or {}).get("complete"))
            et = feat[sid]["error_type"]
            gb = feat[sid]["goal_bin"]
            by_err[et][1] += 1
            by_goal[gb][1] += 1
            if ok:
                by_err[et][0] += 1
                by_goal[gb][0] += 1
            vt = r.get("verify_time")
            if isinstance(vt, (int, float)):
                latency.append(float(vt))
        model_stats[model] = {
            "succ_rate_error_type": {k: (v[0] / v[1] if v[1] else 0.0) for k, v in by_err.items()},
            "succ_rate_goal_bin": {k: (v[0] / v[1] if v[1] else 0.0) for k, v in by_goal.items()},
            "avg_latency": (sum(latency) / len(latency) if latency else None),
            "token_cost": None,
        }

    # 为每个子问题给出主模型推荐
    routing = {}
    for sid, f in feat.items():
        best_model, best_score = None, -1.0
        for model, st in model_stats.items():
            p1 = st["succ_rate_error_type"].get(f["error_type"], 0.0)
            p2 = st["succ_rate_goal_bin"].get(f["goal_bin"], 0.0)
            p = 0.6 * p1 + 0.4 * p2
            lat = st["avg_latency"] or 1.0
            score = p / max(lat, 1e-6)
            if score > best_score:
                best_score = score
                best_model = model
        routing[sid] = {"recommended_model": best_model, "score": best_score, "features": f}

    out = {"model_capability": model_stats, "routing": routing}
    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote router coefficients: {args.output_json}")


if __name__ == "__main__":
    main()
