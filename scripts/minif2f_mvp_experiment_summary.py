#!/usr/bin/env python3
"""
在不重新跑编译的前提下，整合 minif2f 子问题 MVP 已有产物，输出实验结论文本。

依赖：baseline to_inference_codes、repaired_from_{deepseek,goedel}.json、
      merged 编译 JSON、子问题侧 code_compilation_repl.json、manifest_goal、
      可选 failed_only JSON。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


def base_id(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_complete(row) -> bool:
    """True only when compilation passes WITHOUT sorry (complete=True)."""
    cr = row.get("compilation_result") or {}
    return bool(cr.get("complete"))


def pass_stats(rows: list) -> dict:
    sample_pass = sum(1 for r in rows if _is_complete(r))
    groups: dict[str, bool] = {}
    for r in rows:
        pid = r.get("problem_id") or r.get("name")
        b = base_id(str(pid))
        groups.setdefault(b, False)
        if _is_complete(r):
            groups[b] = True
    prob_pass = sum(1 for v in groups.values() if v)
    n = len(rows)
    g = len(groups)
    return {
        "samples_total": n,
        "samples_pass": sample_pass,
        "sample_pass_rate": (sample_pass / n if n else 0.0),
        "problems_total": g,
        "problems_pass_at_32": prob_pass,
        "pass_at_32": (prob_pass / g if g else 0.0),
    }


def count_code_diff(orig: list, rep: list) -> int:
    n = 0
    for a, b in zip(orig, rep):
        if (a.get("full_code") or "") != (b.get("full_code") or ""):
            n += 1
    return n


def normalize_compile_pid(pid: str) -> str:
    return re.sub(r"_g\d+$", "", str(pid or ""))


def manifest_compile_join(manifest: list, compile_rows: list) -> tuple[int, int, int]:
    m_ids = {m.get("subproblem_id") for m in manifest if m.get("subproblem_id")}
    c_ids = {normalize_compile_pid(r.get("problem_id") or "") for r in compile_rows if r.get("problem_id")}
    c_ids.discard("")
    return len(m_ids), len(c_ids), len(m_ids & c_ids)


def main() -> None:
    ap = argparse.ArgumentParser(description="Integrate MVP artifacts into a conclusion markdown.")
    ap.add_argument(
        "--mvp_dir",
        default="results/minif2f/round_2/subproblem_mvp",
        help="subproblem_mvp directory",
    )
    ap.add_argument(
        "--round_dir",
        default="results/minif2f/round_2",
        help="round directory (baseline codes/compile)",
    )
    ap.add_argument("--output_md", default=None, help="default: <mvp_dir>/mvp_experiment_conclusion.md")
    args = ap.parse_args()

    mvp = Path(args.mvp_dir)
    rnd = Path(args.round_dir)
    out_md = Path(args.output_md) if args.output_md else mvp / "mvp_experiment_conclusion.md"

    orig_codes = read_json(rnd / "to_inference_codes.json")
    baseline_comp = read_json(rnd / "code_compilation_repl.json")
    rep_ds = read_json(mvp / "repaired_from_deepseek.json")
    rep_go = read_json(mvp / "repaired_from_goedel.json")
    merged_ds = read_json(mvp / "repaired_from_deepseek_compiled_merged.json")
    merged_go = read_json(mvp / "repaired_from_goedel_compiled_merged.json")

    manifest = read_json(mvp / "subproblem_manifest_goal.json")
    ds_sub = read_json(mvp / "deepseek" / "code_compilation_repl.json")
    go_sub = read_json(mvp / "goedel" / "code_compilation_repl.json")

    router_path = mvp / "router_scores.json"
    router_note = ""
    if router_path.is_file():
        router = read_json(router_path)
        mc = router.get("model_capability") or {}
        empty = all(
            not (v.get("succ_rate_error_type") or {}) and not (v.get("succ_rate_goal_bin") or {})
            for v in mc.values()
        )
        if empty:
            router_note = (
                "当前 `router_scores.json` 中 `model_capability` 为空："
                "子问题编译 JSON 的 `problem_id` 与 manifest 的 `subproblem_id` **无交集**，"
                "路由统计无法按子问题聚合。"
            )
        else:
            router_note = "已写入模型按错误类型 / goal 分桶的成功率（见 `router_scores.json`）。"

    mlen, clen, inter = manifest_compile_join(manifest, ds_sub)
    diff_ds = count_code_diff(orig_codes, rep_ds)
    diff_go = count_code_diff(orig_codes, rep_go)

    b = pass_stats(baseline_comp)
    d = pass_stats(merged_ds)
    g = pass_stats(merged_go)
    merged_hy_path = mvp / "repaired_from_hybrid_compiled_merged.json"
    h_stats = pass_stats(read_json(merged_hy_path)) if merged_hy_path.is_file() else None

    fo_path = mvp / "repaired_from_deepseek_failed_only.json"
    subset_lines = []
    if fo_path.is_file():
        fo = read_json(fo_path)
        fo_ids = {r.get("problem_id") or r.get("name") for r in fo}
        subset_bases = {base_id(str(x)) for x in fo_ids}
        n_sub = len(subset_bases)

        def sample_pass_in(rows: list, idset: set) -> tuple[int, int]:
            sub = [r for r in rows if (r.get("problem_id") or r.get("name")) in idset]
            sp = sum(1 for r in sub if _is_complete(r))
            return len(sub), sp

        tot_b, pb = sample_pass_in(baseline_comp, fo_ids)
        tot_d, pd = sample_pass_in(merged_ds, fo_ids)
        tot_g, pg = sample_pass_in(merged_go, fo_ids)
        subset_lines = [
            "",
            "## 三、baseline pass@32 失败子集（failed-only，未做全量重编）",
            "",
            f"- 子集样本行数：{len(fo)}；对应 **{n_sub}** 个 base 题（pass@32 全败的题）。",
            f"- 该子集上 sample 通过率：baseline {pb}/{tot_b}；DeepSeek merged {pd}/{tot_d}；Goedel merged {pg}/{tot_g}。",
            "",
        ]

    lines = [
        "# minif2f 子问题 MVP：实验结论（基于现有产物整合）",
        "",
        "本说明在**不重新跑全量编译**的前提下，汇总当前目录下已有 JSON / 日志所支持的事实判断。",
        "",
        "## 一、端到端指标（merged 编译 vs baseline）",
        "",
        "| 方案 | sample pass rate | pass@32 |",
        "|---|---:|---:|",
        f"| baseline | {b['sample_pass_rate']:.4f} | {b['pass_at_32']:.4f} |",
        f"| repaired merged (deepseek) | {d['sample_pass_rate']:.4f} | {d['pass_at_32']:.4f} |",
        f"| repaired merged (goedel) | {g['sample_pass_rate']:.4f} | {g['pass_at_32']:.4f} |",
    ]
    if h_stats is not None:
        lines.append(
            f"| repaired merged (hybrid) | {h_stats['sample_pass_rate']:.4f} | {h_stats['pass_at_32']:.4f} |"
        )
    delta_hy = (
        f"，Hybrid **{h_stats['pass_at_32'] - b['pass_at_32']:+.4f}**" if h_stats is not None else ""
    )
    lines.extend(
        [
            "",
            f"- 相对 baseline 的 pass@32 变化：DeepSeek **{d['pass_at_32'] - b['pass_at_32']:+.4f}**，"
            f"Goedel **{g['pass_at_32'] - b['pass_at_32']:+.4f}**{delta_hy}。",
            "",
            "## 二、为何与 baseline 一致：回填未生效",
            "",
            f"- `subproblem_manifest_goal.json` 条目数：**{len(manifest)}**",
            f"- 子问题侧编译：`deepseek` **{len(ds_sub)}** 行，`goedel` **{len(go_sub)}** 行；"
            f" manifest `subproblem_id` 与 compile `problem_id` **交集 {inter}**（manifest 唯一 id {mlen}，compile 唯一 id {clen}）。",
            f"- `minif2f_build_repaired_codes.py` 用 compile 行的 `problem_id` 作为 key 去对齐 manifest 的 `subproblem_id`；**无对齐则不会回填**。",
            "- `minif2f_subproblem_mvp.sh` 中对该脚本传入 `--baseline_compile`（整轮 `ORIG_COMP`）时：**baseline 已编译通过的 `problem_id` 不再被子题补丁覆盖** `full_code`。",
            "- **去抖动报告**：`bash scripts/minif2f_subproblem_mvp.sh report-debiased` 生成 `mvp_report_debiased.md`（`minif2f_merge_compile_debiased.py`：未改 `full_code` 的行沿用 baseline 的 `compilation_result`）。",
            "- **可选回填策略**（环境变量）：`MVP_FILL_ONLY_BASE_ALL_FAIL=1` 时仅对 baseline 下该题 32 条全败的 `base_id` 回填；`MVP_PICK_SHORTEST_PASSING=1` 时子题多通过取最短 `code`。",
            f"- 与 `to_inference_codes.json` 相比，`repaired_from_deepseek.json` **有 {diff_ds} 行** `full_code` 不同；`repaired_from_goedel.json` **有 {diff_go} 行** 不同。",
            "",
            "若 merged 与 baseline 指标仍完全相同，多为 **abnormal 跳过未重编** 或回填未触达；"
            "若已开启 `MVP_COMPILE_REEVAL_ABNORMAL=1` 并跑 hybrid，则以**第一节表格**为准。",
            "",
            f"### 路由系数\n\n{router_note}",
            "",
            "### 子问题尝试编译",
            "",
            f"- DeepSeek 子问题：{sum(1 for r in ds_sub if _is_complete(r))}/{len(ds_sub)} 通过（complete，无 sorry）。",
            f"- Goedel 子问题：{sum(1 for r in go_sub if _is_complete(r))}/{len(go_sub)} 通过（complete，无 sorry）。",
            "",
        ]
    )
    smoke_dirs = sorted(mvp.glob("_smoke_lift_*"))
    if smoke_dirs:
        lines.extend(["", "### smoke-lift（小规模 hybrid 验证）", ""])
        lines.append(
            "由 `minif2f_subproblem_smoke_lift.py` 或 `bash scripts/minif2f_subproblem_mvp.sh smoke-lift`；"
            "默认 `lift_sample_fail` 口径。"
        )
        lines.append("")
        for d in smoke_dirs[-5:]:
            meta_path = d / "smoke_meta.json"
            if not meta_path.is_file():
                continue
            sm = read_json(meta_path)
            comp = sm.get("compile") or {}
            lifted = comp.get("lifted_problems_baseline_fail_to_pass")
            nrows = sm.get("smoke_rows")
            crit = sm.get("criterion", "")
            if lifted is not None and nrows is not None:
                lines.append(
                    f"- `{d.name}`：criterion={crit}，样本 {nrows} 行，baseline 挂→repair pass **{lifted}/{nrows}**。"
                )
            else:
                lines.append(f"- `{d.name}`：已写 meta（未完成编译或旧格式）。")
        lines.append("")
    lines.extend(subset_lines)

    fail_an = mvp / "subproblem_compile_failure_analysis.json"
    if fail_an.is_file():
        fa = read_json(fail_an)
        lines.extend(
            [
                "## 四、子问题编译失败归因（`subproblem_compile_failure_analysis.json`）",
                "",
            ]
        )
        for model, block in (fa.get("models") or {}).items():
            fk = block.get("fail_kinds") or {}
            lines.append(f"- **{model}**：{block.get('rows', 0)} 行；失败类型分布：{fk}。")
        lines.append(
            "- 若几乎全部为 `repl_pexpect_eof`：属 REPL/pexpect 环境问题，而非模型证明「搜索过重」；"
            "请在 `minif2f_subproblem_mvp.sh`（或 `run_minif2f_subproblem_mvp.sh`）已导出的 `REPL_PEXPECT_MAXREAD` / `IMPORT_TIMEOUT` 下重编子题。"
        )
        lines.append("")

    lines.extend(
        [
            "## 五、结论摘要",
            "",
            "1. 若 `mvp_report.md` 中 repaired 与 baseline 仍完全一致，常见原因是 **abnormal 题被跳过未重编**；可设 `MVP_COMPILE_REEVAL_ABNORMAL=1` 再跑 failed-only / hybrid-failed-only。",
            "2. **hybrid**（`repaired_from_hybrid` + 子集重编 + merge）在复检 abnormal 后可在 pass@32 上出现小幅正增益；详见当前 `mvp_report.md`。",
            "3. 子题 manifest 与 compile `problem_id` 需对齐；`subproblem_manifest_raw.json` 覆盖远大于 `subproblem_manifest_goal.json`，hybrid 回填依赖与 DS/GO 子题编译的 join。",
            "4. failed-only 仅重编失败子集；smoke-lift 用于在扩大规模前验证 hybrid 链路（见上节 `_smoke_lift_*`）。",
            "",
        ]
    )

    os.makedirs(out_md.parent, exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote: {out_md}")


if __name__ == "__main__":
    main()
