#!/usr/bin/env python3
"""
小规模验证：在「baseline 下该题 32 条全未 pass」的题中，选出子题侧 DeepSeek/Goedel
已有编译通过的题；每题只取 1 条样本（优先 _g0），用 hybrid 回填后编译，看有几题由败转通。

不跑新推理；依赖现有子题编译结果，现场调用 minif2f_build_hybrid_repaired_codes.py。

口径:
  - lift_sample_fail（默认）: 该条样本 baseline 未 pass，且 manifest 中对应子题在 DS/GO 侧有编译通过；
    适合「20 道失败样本能否救回几道」（不要求整题 32 条全挂）。
  - fail_all_at_k: 整题在前 k 条样本上 baseline 全无 pass，再与子题 lift 求交（很严，通常极少）。

用法:
  python3 scripts/minif2f_subproblem_smoke_lift.py --n_problems 20 --run_compile
  python3 scripts/minif2f_subproblem_smoke_lift.py --n_problems 20   # 只写 JSON，不编译
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def compile_row_subproblem_key(problem_id: str) -> str:
    return re.sub(r"_g\d+$", "", str(problem_id or ""))


def read_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_complete(row) -> bool:
    """True only when compilation passes WITHOUT sorry."""
    cr = row.get("compilation_result") or {}
    return bool(cr.get("complete"))


def baseline_bases_all_fail_pass(baseline_rows: list, k: int) -> Set[str]:
    """每题只看前 k 条样本：若全无 complete 则纳入。"""
    by: Dict[str, List[bool]] = {}
    for r in baseline_rows:
        pid = str(r.get("problem_id") or r.get("name") or "")
        if not pid:
            continue
        b = base_id(pid)
        by.setdefault(b, []).append(_is_complete(r))
    out = set()
    for b, flags in by.items():
        flags = flags[:k]
        if flags and not any(flags):
            out.add(b)
    return out


def collect_passing_sub_keys(sub_comp: list) -> Set[str]:
    keys = set()
    for r in sub_comp:
        if not _is_complete(r):
            continue
        pid = r.get("problem_id") or ""
        sk = compile_row_subproblem_key(str(pid))
        if sk:
            keys.add(sk)
    return keys


def bases_with_sub_lift(manifest: list, ds_ok: Set[str], go_ok: Set[str]) -> Set[str]:
    bases = set()
    for m in manifest:
        sid = m.get("subproblem_id")
        if not sid:
            continue
        if sid not in ds_ok and sid not in go_ok:
            continue
        pb = m.get("problem_base")
        if pb:
            bases.add(str(pb))
    return bases


def pick_pid_per_base_with_sub_lift(
    manifest: list, bases: List[str], ds_ok: Set[str], go_ok: Set[str]
) -> Dict[str, str]:
    """
    每道 base 选一个 problem_id：该样本在 manifest 中有子题且 DS/GO 子题编译通过，
    保证 hybrid 回填会改到这一行（避免盲选 _g0 却无子题）。
    """
    out: Dict[str, str] = {}
    for b in bases:
        cands: List[str] = []
        for m in manifest:
            if str(m.get("problem_base") or "") != b:
                continue
            sid = m.get("subproblem_id")
            if not sid or (sid not in ds_ok and sid not in go_ok):
                continue
            pid = str(m.get("problem_id") or "")
            if pid:
                cands.append(pid)
        if cands:
            out[b] = sorted(set(cands))[0]
    return out


def filter_rows_by_pid(codes: list, pids: Set[str]) -> list:
    return [dict(r) for r in codes if str(r.get("problem_id") or r.get("name") or "") in pids]


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke test hybrid lift on N failed bases, 1 sample each.")
    ap.add_argument("--round_dir", default="results/minif2f/round_2")
    ap.add_argument("--mvp_dir", default="results/minif2f/round_2/subproblem_mvp")
    ap.add_argument(
        "--manifest",
        default=None,
        help="子题 manifest（默认优先 subproblem_manifest_raw.json，否则 subproblem_manifest_goal.json）",
    )
    ap.add_argument("--n_problems", type=int, default=20)
    ap.add_argument("--k", type=int, default=32, help="fail_all_at_k 模式下前 k 条样本")
    ap.add_argument(
        "--criterion",
        choices=("lift_sample_fail", "fail_all_at_k"),
        default="lift_sample_fail",
        help="选题口径（默认 lift_sample_fail 便于凑满 n 做 smoke）",
    )
    ap.add_argument(
        "--run_compile",
        action="store_true",
        help="调用 compile_by_chunks 编译筛选后的 hybrid 回填 JSON",
    )
    ap.add_argument("--compile_cpu", type=int, default=8)
    ap.add_argument("--compile_timeout", type=int, default=180)
    ap.add_argument(
        "--reeval_abnormal",
        action="store_true",
        help="传给 compile_by_chunks --reeval-abnormal",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    round_dir = Path(args.round_dir)
    mvp_dir = Path(args.mvp_dir)
    baseline_path = round_dir / "code_compilation_repl.json"
    orig_codes_path = round_dir / "to_inference_codes.json"
    if args.manifest:
        manifest_path = Path(args.manifest)
    else:
        raw_m = mvp_dir / "subproblem_manifest_raw.json"
        goal_m = mvp_dir / "subproblem_manifest_goal.json"
        manifest_path = raw_m if raw_m.is_file() else goal_m
    ds_path = mvp_dir / "deepseek" / "code_compilation_repl.json"
    go_path = mvp_dir / "goedel" / "code_compilation_repl.json"
    router_path = mvp_dir / "router_scores.json"

    for p in (baseline_path, orig_codes_path, manifest_path, ds_path, go_path):
        if not p.is_file():
            print(f"Missing required file: {p}", file=sys.stderr)
            sys.exit(1)

    baseline = read_json(baseline_path)
    orig_codes = read_json(orig_codes_path)
    manifest = read_json(manifest_path)
    ds_sub = read_json(ds_path)
    go_sub = read_json(go_path)

    ds_ok = collect_passing_sub_keys(ds_sub)
    go_ok = collect_passing_sub_keys(go_sub)
    by_pid_baseline = {str(r.get("problem_id") or r.get("name")): r for r in baseline}

    if args.criterion == "fail_all_at_k":
        fail_all = baseline_bases_all_fail_pass(baseline, args.k)
        liftable_bases = bases_with_sub_lift(manifest, ds_ok, go_ok) & fail_all
        ordered = sorted(liftable_bases)
        chosen_bases = ordered[: args.n_problems]
        base_to_pid = pick_pid_per_base_with_sub_lift(manifest, chosen_bases, ds_ok, go_ok)
    else:
        # 每条 manifest 记录：子题过 + 该样本 baseline 未 pass
        base_to_pid_cand: Dict[str, str] = {}
        for m in manifest:
            sid = m.get("subproblem_id")
            if not sid or (sid not in ds_ok and sid not in go_ok):
                continue
            pid = str(m.get("problem_id") or "")
            if not pid:
                continue
            br = by_pid_baseline.get(pid, {})
            if _is_complete(br):
                continue
            b = str(m.get("problem_base") or base_id(pid))
            if b not in base_to_pid_cand or pid < base_to_pid_cand[b]:
                base_to_pid_cand[b] = pid
        ordered = sorted(base_to_pid_cand.keys())
        chosen_bases = ordered[: args.n_problems]
        base_to_pid = {b: base_to_pid_cand[b] for b in chosen_bases}

    if len(chosen_bases) < args.n_problems:
        print(
            f"Warning: only {len(chosen_bases)} bases match criterion={args.criterion}; "
            f"requested {args.n_problems}.",
            file=sys.stderr,
        )
    pids = set(base_to_pid.values())
    if len(pids) < len(chosen_bases):
        print(
            f"Warning: missing codes rows for some bases; have {len(pids)} pids for {len(chosen_bases)} bases.",
            file=sys.stderr,
        )

    out_dir = mvp_dir / f"_smoke_lift_{args.n_problems}"
    out_dir.mkdir(parents=True, exist_ok=True)

    hybrid_full = out_dir / "repaired_hybrid_full.json"
    hybrid_args = [
        sys.executable,
        str(root / "scripts" / "minif2f_build_hybrid_repaired_codes.py"),
        "--input_manifest",
        str(manifest_path),
        "--deepseek_sub_compile",
        str(ds_path),
        "--goedel_sub_compile",
        str(go_path),
        "--input_original_codes",
        str(orig_codes_path),
        "--baseline_compile",
        str(baseline_path),
        "--output_repaired_codes",
        str(hybrid_full),
    ]
    if router_path.is_file():
        hybrid_args += ["--router_scores", str(router_path)]
    print("Building hybrid repaired (full round)...", flush=True)
    subprocess.run(hybrid_args, check=True, cwd=str(root))

    full_rep = read_json(hybrid_full)
    by_pid = {str(r.get("problem_id") or r.get("name")): r for r in full_rep}
    by_base_comp = {str(r.get("problem_id") or r.get("name")): r for r in baseline}

    changed = 0
    for b, pid in base_to_pid.items():
        o = next((r for r in orig_codes if str(r.get("problem_id") or r.get("name")) == pid), None)
        r = by_pid.get(pid)
        if o and r and (o.get("full_code") or "") != (r.get("full_code") or ""):
            changed += 1

    smoke_codes = filter_rows_by_pid(full_rep, pids)
    smoke_path = out_dir / "smoke_hybrid_repaired.json"
    with open(smoke_path, "w", encoding="utf-8") as f:
        json.dump(smoke_codes, f, ensure_ascii=False, indent=2)

    meta = {
        "criterion": args.criterion,
        "k": args.k,
        "n_requested": args.n_problems,
        "chosen_bases": chosen_bases,
        "sample_pid_by_base": base_to_pid,
        "hybrid_full_code_changed_among_samples": changed,
        "smoke_rows": len(smoke_codes),
        "paths": {"smoke_codes": str(smoke_path), "compile_out": str(out_dir / "smoke_hybrid_compiled.json")},
    }
    if args.criterion == "fail_all_at_k":
        fa = baseline_bases_all_fail_pass(baseline, args.k)
        meta["fail_all_at_k_bases"] = len(fa)
        meta["liftable_fail_all_bases"] = len(fa & bases_with_sub_lift(manifest, ds_ok, go_ok))
    with open(out_dir / "smoke_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Chosen {len(chosen_bases)} bases, {len(smoke_codes)} rows -> {smoke_path}")
    print(f"Among chosen samples, full_code differs from orig in {changed} rows (hybrid backfill).")

    compile_out = out_dir / "smoke_hybrid_compiled.json"
    if not args.run_compile:
        print("Skip compile (pass --run_compile). Then compare passes vs baseline on sample pids.")
        return

    cargs = [
        sys.executable,
        str(root / "scripts" / "compile_by_chunks.py"),
        "--input_path",
        str(smoke_path),
        "--output_path",
        str(compile_out),
        "--chunk_size",
        str(max(1, len(smoke_codes))),
        "--cpu",
        str(args.compile_cpu),
        "--timeout",
        str(args.compile_timeout),
        "--force",
    ]
    if args.reeval_abnormal:
        cargs.append("--reeval-abnormal")
    print("Running compile_by_chunks...", " ".join(cargs[-8:]), flush=True)
    subprocess.run(cargs, check=True, cwd=str(root))

    compiled = read_json(compile_out)
    by_new = {str(r.get("problem_id") or r.get("name")): r for r in compiled}

    lifted_problems = 0
    still_fail = 0
    baseline_was_pass = 0
    detail: List[Tuple[str, str, bool, bool]] = []

    for b, pid in base_to_pid.items():
        if pid not in pids:
            continue
        br = by_base_comp.get(pid, {})
        nr = by_new.get(pid, {})
        bp = _is_complete(br)
        np = _is_complete(nr)
        detail.append((b, pid, bp, np))
        if bp:
            baseline_was_pass += 1
        elif np:
            lifted_problems += 1
        else:
            still_fail += 1

    meta["compile"] = {
        "lifted_problems_baseline_fail_to_pass": lifted_problems,
        "still_fail": still_fail,
        "baseline_pass_on_sample": baseline_was_pass,
        "detail_base_pid_baseline_pass_repaired_pass": [
            {"base": b, "pid": pid, "baseline_pass": bp, "repaired_pass": np} for b, pid, bp, np in detail
        ],
    }
    with open(out_dir / "smoke_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(
        f"\n=== Smoke result (single sample per problem, baseline.pass) ===\n"
        f"Problems with baseline fail -> repaired pass: {lifted_problems} / {len(pids)}\n"
        f"Still fail after repair: {still_fail}\n"
        f"(Unexpected) baseline already pass on sample: {baseline_was_pass}"
    )
    if lifted_problems >= 1:
        print("PASS smoke criterion: at least 1 problem lifted.")
    else:
        print("FAIL smoke criterion: 0 problems lifted; do not scale up yet.")
        sys.exit(2)
    if args.criterion == "lift_sample_fail":
        print(
            "\nNote: lift_sample_fail 选取的是「该样本 baseline 挂 + 子题已有一条编译过」的子集；"
            "在此子集上 hybrid 回填往往接近 100% 救回。整轮 pass@32 增益仍取决于全量中有多少题落在该子集。"
        )


if __name__ == "__main__":
    main()
