#!/usr/bin/env python3
"""统一计算各 benchmark 的 Pass@32 并写入 results/pass_at_32_summary.md。
会更新各目录下的 pass_at_32_rounds.txt / pass_at_32_summary.txt，再生成汇总 Markdown。
用法: python3 scripts/report_pass_at_32.py
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ZAM_LEAN = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

import calculate_pass_at_k
import compute_pass_at_32_v2s_v2c

K = 32
SUMMARY_MD = os.path.join(ZAM_LEAN, "results", "pass_at_32_summary.md")


def _read_minif2f_round(path: str) -> float | None:
    """读取 round 目录下 pass_at_32_summary.txt 中的 Pass@32。"""
    f = os.path.join(path, "pass_at_32_summary.txt")
    if not os.path.isfile(f):
        return None
    try:
        with open(f) as fp:
            for line in fp:
                if "Pass@" in line and ":" in line:
                    return float(line.split(":")[-1].strip())
    except (ValueError, OSError):
        pass
    return None


def _ensure_minif2f_pass_at_32():
    """若 round_2/round_3 有 code_compilation_repl.json 但无 summary，则计算并写入。"""
    for r in ("round_2", "round_3"):
        repl = os.path.join(ZAM_LEAN, "results", "minif2f", r, "code_compilation_repl.json")
        if os.path.isfile(repl):
            p = _read_minif2f_round(os.path.join(ZAM_LEAN, "results", "minif2f", r))
            if p is None:
                p = calculate_pass_at_k.pass_at_k(repl, K)
                out = os.path.join(ZAM_LEAN, "results", "minif2f", r, "pass_at_32_summary.txt")
                with open(out, "w") as f:
                    f.write(f"Pass@{K}: {p:.4f}\n")
                print(f"  minif2f/{r} Pass@{K}: {p:.4f} (wrote {out})", file=sys.stderr)


PUTNAM_TOTAL = 672


def _collect_putnambench() -> tuple[float | None, int | None]:
    """Putnam 单表 Pass@32 与通过题目数。返回 (Pass@32, 通过题数)。"""
    path = os.path.join(ZAM_LEAN, "results", "putnambench", "code_compilation_repl.json")
    if not os.path.isfile(path):
        return None, None
    with open(path) as f:
        records = json.load(f)
    from collections import defaultdict
    by_problem = defaultdict(list)
    for r in records:
        pid = r.get("problem_id") or r.get("name") or ""
        if isinstance(pid, str) and "_g" in pid:
            pid = pid.rsplit("_g", 1)[0]
        cr = r.get("compilation_result") or {}
        passed = cr.get("complete") or False
        by_problem[pid].append(passed)
    n_total = len(by_problem)
    n_passed = sum(1 for probs in by_problem.values() if any(probs[:K]))
    p = n_passed / n_total if n_total else 0.0
    out = os.path.join(ZAM_LEAN, "results", "putnambench", "pass_at_32_rounds.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Pass@32 (putnambench, {PUTNAM_TOTAL} problems)\n")
        f.write(f"round_0 Pass@32: {p:.4f}\n")
        f.write(f"通过题目数: {n_passed}\n")
    return p, n_passed


def main():
    os.chdir(ZAM_LEAN)
    lines = [
        "# Pass@32 汇总",
        "",
        "> 由 `python3 scripts/report_pass_at_32.py` 生成",
        "",
    ]

    # minif2f round_2 / round_3
    _ensure_minif2f_pass_at_32()
    p2 = _read_minif2f_round(os.path.join(ZAM_LEAN, "results", "minif2f", "round_2"))
    p3 = _read_minif2f_round(os.path.join(ZAM_LEAN, "results", "minif2f", "round_3"))
    if p2 is not None or p3 is not None:
        lines.append("## minif2f (round_2 / round_3)")
        lines.append("")
        lines.append("| Benchmark | Pass@32 |")
        lines.append("|-----------|---------|")
        if p2 is not None:
            lines.append(f"| minif2f round_2 | **{p2:.4f}** |")
        if p3 is not None:
            lines.append(f"| minif2f round_3 | **{p3:.4f}** |")
        if p2 is not None and p3 is not None:
            lines.append(f"| average(round_2, round_3) | {(p2 + p3) / 2:.4f} |")
        lines.append("")
        lines.append("")

    # v2s / v2c：计算并写 pass_at_32_rounds.txt，再用于汇总
    for bench in ("minif2f_v2s", "minif2f_v2c"):
        bench_dir = os.path.join(ZAM_LEAN, "results", bench)
        if not os.path.isdir(bench_dir) or not os.path.isfile(os.path.join(bench_dir, "code_compilation_repl.json")):
            continue
        results = compute_pass_at_32_v2s_v2c.compute_rounds(bench_dir)
        if not results:
            continue
        out_path = os.path.join(bench_dir, "pass_at_32_rounds.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            if results and ("244 valid" in results[0][0] or "244 test" in results[0][0]):
                f.write("# Pass@32: 244 valid, 244 test, 488 all (v2s/v2c)\n")
            for name, p in results:
                f.write(f"{name} Pass@32: {p:.4f}\n")
            names = [n for n, _ in results]
            if len(results) >= 2 and "either_round" not in names and ("244 valid" in str(names) or "244 test" in str(names)):
                p_valid = next((p for n, p in results if "244 valid" in n), None)
                p_test = next((p for n, p in results if "244 test" in n), None)
                if p_valid is not None and p_test is not None:
                    f.write(f"average Pass@32 (valid+test): {(p_valid + p_test) / 2:.4f}\n")
            elif len(results) > 1 and "either_round" not in names:
                f.write(f"average Pass@32: {sum(p for _, p in results) / len(results):.4f}\n")
        rows = [(n.replace("round_0 ", "").strip(), p) for n, p in results]
        if rows:
            lines.append(f"## {bench}")
            lines.append("")
            lines.append("| 划分 | Pass@32 |")
            lines.append("|------|---------|")
            for label, val in rows:
                lines.append(f"| {label} | **{val:.4f}** |")
            lines.append("")
            lines.append("")

    # putnambench（按通过题数）
    p_putnam, n_putnam_passed = _collect_putnambench()
    if p_putnam is not None:
        lines.append(f"## putnambench ({PUTNAM_TOTAL} 题)")
        lines.append("")
        lines.append("| 划分 | Pass@32 | 通过题目数 |")
        lines.append("|------|---------|------------|")
        n_str = str(n_putnam_passed) if n_putnam_passed is not None else "—"
        lines.append(f"| round_0 | **{p_putnam:.4f}** | {n_str} |")
        lines.append("")
        lines.append("")

    # proofnet（推理 3 轮：round_0 / _corr1 / _corr2，取平均）
    proofnet_dir = os.path.join(ZAM_LEAN, "results", "proofnet")
    repl0 = os.path.join(proofnet_dir, "code_compilation_repl.json")
    repl1 = os.path.join(proofnet_dir, "code_compilation_repl_corr1.json")
    repl2 = os.path.join(proofnet_dir, "code_compilation_repl_corr2.json")
    if os.path.isfile(repl0):
        p0 = calculate_pass_at_k.pass_at_k(repl0, K)
        results_proofnet = [("round_0", p0)]
        if os.path.isfile(repl1):
            p1 = calculate_pass_at_k.pass_at_k(repl1, K)
            results_proofnet.append(("round_1", p1))
        if os.path.isfile(repl2):
            p2 = calculate_pass_at_k.pass_at_k(repl2, K)
            results_proofnet.append(("round_2", p2))
        avg = sum(p for _, p in results_proofnet) / len(results_proofnet)
        out_path = os.path.join(proofnet_dir, "pass_at_32_rounds.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# Pass@32 (proofnet, 3 rounds average)\n")
            for name, p in results_proofnet:
                f.write(f"{name} Pass@32: {p:.4f}\n")
            f.write(f"average Pass@32 (3 rounds): {avg:.4f}\n")
        lines.append("## proofnet")
        lines.append("")
        lines.append("| 划分 | Pass@32 |")
        lines.append("|------|---------|")
        for label, val in results_proofnet:
            lines.append(f"| {label} | **{val:.4f}** |")
        lines.append(f"| average (3 轮) | **{avg:.4f}** |")
        lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*各 benchmark 明细: results/<bench>/pass_at_32_rounds.txt 或 round_*/pass_at_32_summary.txt*")
    lines.append("")

    with open(SUMMARY_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {SUMMARY_MD}", file=sys.stderr)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
