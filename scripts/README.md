# 脚本说明

所有脚本从仓库根目录 `Zam/lean` 运行（`bash scripts/xxx.sh`、`python3 scripts/xxx.py`）。

## minif2f 子问题 MVP（单一入口）

| 命令 | 说明 |
|------|------|
| `bash scripts/minif2f_subproblem_mvp.sh help` | 查看子命令与 GPU 环境变量说明 |
| `bash scripts/minif2f_subproblem_mvp.sh full` | 全流程（抽 sorry → 推理 → 编译 → 回填 → repaired 编译 → 报告） |
| `bash scripts/minif2f_subproblem_mvp.sh analyze` | 失败挖掘 + 子题归因 + `mvp_experiment_conclusion.md` |
| `bash scripts/minif2f_subproblem_mvp.sh smoke` | 子题小样本编译自测（需已有 `deepseek/to_inference_codes.json`） |
| `bash scripts/minif2f_subproblem_mvp.sh failed-only` | failed-only 子集编译 + merge + router + 报告 |
| `SMOKE_LIFT_N=28 bash scripts/minif2f_subproblem_mvp.sh smoke-lift` | 小规模 hybrid 验证（默认带 Lean 编译）；`SMOKE_LIFT_SKIP_COMPILE=1` 仅写 JSON |
| `bash scripts/minif2f_subproblem_mvp.sh mini` | 前 N 行小推理闭环（需 GPU） |
| `bash scripts/minif2f_subproblem_mvp.sh extend` | 需先 `export MVP_DIR=...` 独立目录再跑 `full` |

**GPU**：设置 `CUDA_VISIBLE_DEVICES`（逗号分隔设备号）与 `GPUS`（张量并行数，通常等于设备个数）。未设置 `GPUS` 时按设备列表长度自动推断；均未设置时默认 `2,3,6,7` 与 `GPUS=4`。

兼容：`bash scripts/run_minif2f_subproblem_mvp.sh` 等同于 `minif2f_subproblem_mvp.sh full`。

## Putnam / FATE 子题（离线扫描与抽取）

| 命令 | 说明 |
|------|------|
| `bash scripts/bench_subproblem_mvp.sh scan-all` | 各 benchmark `subproblem_lift_scan.json`（Pass@32 complete、全挂题、可切块数、FATE 跨模型） |
| `bash scripts/bench_subproblem_mvp.sh extract-putnam` | 从 Putnam 抽 sorry 子题；默认 `MAX_SUBPROBLEMS=600`，`--use_not_complete_as_fail` + 按题去重 |
| `bash scripts/bench_subproblem_mvp.sh extract-fate-ds` / `extract-fate-go` | FATE 子题清单（输出在对应 `results/fate_*/subproblem_mvp/`） |

**小规模验证（先跑再扩）：** `python3 scripts/minif2f_subproblem_smoke_lift.py --n_problems 20 --run_compile --reeval_abnormal`  
默认口径 `lift_sample_fail`（baseline 该条样本未过 + 子题 DS/GO 已过）；`--criterion fail_all_at_k` 更严（整题 k 条全挂 ∩ 子题可过，通常极少）。

Python：`python3 scripts/bench_subproblem_lift_scan.py --preset putnambench`；`minif2f_extract_sorry_subproblems.py` 新增 `--dedupe_problem_base`、`--max_subproblems`、`--use_not_complete_as_fail`。

后续推理/编译可：`export ROUND_DIR=results/putnambench MVP_DIR=results/putnambench/subproblem_mvp` 后接 `minif2f_subproblem_mvp.sh` 中 extract-goal 之后的步骤（或手写 `inference.py` + `compile_by_chunks`）。

## 其他

| 脚本 | 说明 |
|------|------|
| **run_compile_32_with_memory_guard.sh** | 分块编译 + 内存监控；`COMPILE_BENCH=putnambench\|minif2f_v2s\|...` |
| **compile_by_chunks.py** | 分块编译并合并；`--chunk_index`、`SUBCHUNK_*`、`--force` |
| **auto_fix_oom_chunk.py** | OOM 后加异常题、删不完整块 |
| **pipeline.sh** | 多 benchmark 推理/编译入口 |
| **report_pass_at_32.py** | 汇总 Pass@32，写 `results/pass_at_32_summary.md` |
| **check_compile_status.py** | 编译进度与 ETA |

完整脚本列表与用法见 **docs/编译与运行说明.md** 与 **docs/README.md**。

---

**已合并删除（历史）**：`run_subproblem_mvp_smoke.sh`、`run_subproblem_mvp_mini_infer.sh`、`subproblem_mvp_extend.sh`、`subproblem_mvp_extend_env.example`、`run_subproblem_mvp_failed_only.sh`、`minif2f_mvp_run_all_analysis.sh` 的功能并入 `minif2f_subproblem_mvp.sh` 子命令；`results/logs/minif2f_subproblem_mvp/` 下诊断用 `*.txt`、重复 `pid`、旧 `nohup` 小日志已清理，保留主流水线日志。
