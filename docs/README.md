# Zam 实验说明

## 1. 生成文件存放位置

| 目录 | 说明 |
|------|------|
| `results/minif2f/round_1/` | **2/5 参考**：仅 `pass_at_32_summary.txt`（Pass@32 91.80%）；2/5 完整数据在本仓库 `results/run_20260205_085845/`，**2/5 设置与情况**见 [docs/REFERENCE_2_5.md](REFERENCE_2_5.md)（上传后本仓库即 goedel_EXPERIMENT） |
| `results/minif2f/round_2/` | **本次第一轮**：`to_inference_codes.json`、`full_records.json`；已有 `code_compilation_repl.json`、`pass_at_32_summary.txt`（见下） |
| `results/minif2f/round_3/` | **本次第二轮**：`to_inference_codes.json`、`full_records.json`、`inference.log`；**无** `code_compilation_repl.json`（编译未跑） |

推理结果主字段：`to_inference_codes.json` 中每条含 `full_code`（完整 Lean 4 代码），可被 `src/compile.py` 的 `handle()` 去 import/set_option/open 后送 REPL 编译。

## 2. 编译状态

- **round_2**：已跑过编译，**Pass@32 = 0**（全部未通过，错误以 expected token / unknown constant 等为主）。编译流程与当前 Zam 代码一致（init + env 增量）。
- **round_3**：**编译未完成**，尚未生成 `code_compilation_repl.json`。后续需研究如何对生成文件正确编译后再跑。
- 当前环境下 REPL 对「init 后 env=0 + 纯定理」返回大量错误，与 2/5 实验（91.80%）形成对比，差异更可能来自**运行环境**（Lean/mathlib4 版本、cwd、构建等）。

## 3. 与 [goedel_EXPERIMENT](https://github.com/ZZZamchi/goedel_EXPERIMENT) 的差异

| 项目 | goedel_EXPERIMENT | Zam |
|------|-------------------|-----|
| 入口 | `scripts/pipeline.sh`、`run_dataset.sh`，结果 `results/run_YYYYMMDD_HHMMSS/` | 原为 `run_minif2f.sh` → `run_two_rounds.sh`，结果 `results/minif2f/round_2`、`round_3` |
| 轮次 | 单次 run 时间戳目录 | 固定 round_1(2/5 参考)、round_2、round_3 |
| 脚本 | `pipeline.sh`、`dataset_config.sh`、`monitor_both_experiments.sh`、`validate_dataset.py` 等 | 已精简：保留 `pipeline.sh`、`calculate_pass_at_k.py`、`compute_average_pass_at_k.py` |
| 编译 | 同 REPL + handle 纯定理，2/5 取得 Pass@32 91.80% | 同逻辑，当前环境 Pass@32 全 0，编译待后续研究 |

代码逻辑（`compile.py` handle、`repl_scheduler` init+env）与 2/5 对齐；差异主要在**目录与脚本组织**及**当前编译环境**未通过。

## 4. 保留脚本

- `scripts/calculate_pass_at_k.py <code_compilation_repl.json> [k]`：单轮 Pass@k，写入该目录下 `pass_at_32_summary.txt`。
- `scripts/compute_average_pass_at_k.py [out_dir]`：读 `out_dir` 下 round_1/2/3 的 `pass_at_32_summary.txt`，写 `out_dir/average_pass_at_32.txt`（含 round_1/2/3 及 average(round_2, round_3)）。默认 `out_dir=results/minif2f`。
- `scripts/pipeline.sh`：通用推理+编译+总结流水线（可配置时间戳输出目录）。

## 5. 计算三轮平均 Pass@32 的剩余工作

见项目根目录 **REMAINING_WORK.md**。
