# 仓库结构说明

## 顶层目录（本研究相关）

| 路径 | 作用 |
|------|------|
| `prover/` | Lean 4 **证明搜索框架**（vLLM + REPL）：`run.py`、`engine.py`、`strategies/`、`docs/`（论文与技术报告） |
| `src/` | **Goedel 风格批量推理**（`inference.py`、`utils.py`）：`correction_round`、与 `compile_by_chunks` 等衔接 |
| `scripts/` | 编译分块、Pass@32 汇总、minif2f 子问题 MVP、Putnam/FATE 工具链 |
| `dataset/` | 常用 JSONL 子集（如 `minif2f.jsonl`、`minif2f_unsolved39.jsonl`） |
| `data/` | miniF2F v2 等额外数据 |
| `results/` | 所有实验输出（`proof_results.json`、`code_compilation_repl.json`、日志） |
| `experiments/` | 一次性实验脚本（如 `phase1_official_config.py`） |
| `config/` | 环境变量示例（如 `env.sh`） |

## 大型上游依赖（勿当「本仓库代码」阅读）

| 路径 | 说明 |
|------|------|
| `mathlib4/` | **Lean Mathlib 上游**；体积大、与论文工程解耦，日常只需 `lake build`。 |

## 结果文件约定

- **`proof_results.json`**：`prover` 或实验脚本写的逐题结果（`complete`、`attempts`、`strategy` 等）。  
- **`to_inference_codes.json`**：`inference.py` 输出，供后续 REPL 编译。  
- 汇总脚本：`python3 scripts/report_pass_at_32.py`（见 `scripts/README.md`）。
