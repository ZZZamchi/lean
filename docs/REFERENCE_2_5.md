# 2/5 实验参考（上传后本仓库即 goedel_EXPERIMENT，此处为当时设置与情况）

以下为 **2025-02-05** 在本仓库（[ZZZamchi/goedel_EXPERIMENT](https://github.com/ZZZamchi/goedel_EXPERIMENT)）上的实验设置与结果，供后续实验对照，**请勿删除或覆盖**。

## 2/5 结果位置

- **结果目录**：`results/run_20260205_085845/`
- **Pass@32**：91.80%（通过问题数 224/244，通过样本数 4883/7808）
- 本仓库中 **round_1 参考**：`results/minif2f/round_1/` 仅存 `pass_at_32_summary.txt`（0.9180）与本 README，完整 2/5 数据仍以 `results/run_20260205_085845/` 为准。

## 2/5 时的主要设置

| 项目 | 设置 |
|------|------|
| 入口脚本 | `scripts/pipeline.sh`、`scripts/run_dataset.sh`（如 `run_dataset.sh minif2f --gpu 4 --cpu 128 --n 32`） |
| 输出目录 | `results/run_YYYYMMDD_HHMMSS/`（单次 run 一个时间戳目录） |
| 编译 | `src/compile.py` + `lean_compiler`（REPL），handle 去掉 import/set_option/open 后发纯定理，env=0 |
| Lean / mathlib4 | Lean 4.9，mathlib4 子模块 @ 2f65ba7（xinhjBrant/mathlib4） |
| 配置 | `config/env.sh`、`DATA_PATH`、`GPUS`、`CPUS`、`NUM_SAMPLES_INITIAL`、`COMPILE_TIMEOUT` 等 |

## 与当前 Zam 结果的对应关系

- **round_1** = 2/5 参考（仅 Pass@32 数值，数据在 `results/run_20260205_085845/`）。
- **round_2 / round_3** = 本次两轮推理结果，存放在 `results/minif2f/round_2`、`round_3`；编译未完成（round_2 已跑但全 0，round_3 未跑）。详见 `docs/README.md`、`REMAINING_WORK.md`。

后续实验若需复现 2/5 或对照环境，请以 **本仓库** `results/run_20260205_085845/` 及上述设置为准。
