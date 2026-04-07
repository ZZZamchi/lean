# Lean 4 Proof Search Framework

Multi-strategy proof search engine for Lean 4 formal theorem proving, with support for cross-model sorry-gap filling.

## Documentation

| 资源 | 说明 |
|------|------|
| **[docs/README.md](docs/README.md)** | 文档索引（技术报告、脚本、评测说明） |
| **[docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md)** | 顶层目录与 `results/` 约定 |
| **[docs/GOEDEL_V2_EVALUATION.md](docs/GOEDEL_V2_EVALUATION.md)** | **Goedel-V2 8B/32B 与论文 pass@ 对齐**（为何本地 32B 远低于 ~90%） |
| **[prover/docs/technical_report.md](prover/docs/technical_report.md)** | 实验结果与 Phase1 / 32B 快照 |

## Quick Start

```bash
# Environment
conda env create -f goedelv2.yml
cd mathlib4 && lake build && cd ..

# Run proof search on miniF2F
python -m prover.run --dataset minif2f --split test \
  --model Goedel-LM/Goedel-Prover-V2-8B --tp 2 --gpus 0,1 \
  --strategies whole_proof --samples 32

# Cross-model sorry filling
python -m prover.run --dataset minif2f --split valid \
  --model deepseek-ai/DeepSeek-Prover-V2-7B --tp 2 --gpus 0,1 \
  --strategies near_miss \
  --baseline-results results/minif2f/round_2/code_compilation_repl.json

# Generate charts
python -m prover.visualize --output-dir results/figures

# Goedel-V2-32B（对齐官方协议：chat 开启 + 大 token；勿用 --no-chat）
python -m prover.run --dataset minif2f --split valid \
  --model Goedel-LM/Goedel-Prover-V2-32B --tp 2 --gpus 0,1 \
  --strategies whole_proof --samples 32 \
  --max-tokens 32768 --max-model-len 40960
```

## Project Structure

```
prover/                    # Core framework
├── run.py                 # CLI entry point
├── engine.py              # Proof search orchestrator
├── model.py               # vLLM inference wrapper
├── verifier.py            # Lean REPL manager
├── datasets.py            # Unified dataset loader
├── evaluate.py            # Metrics (pass@k)
├── prompts.py             # Prompt templates
├── config.py              # Configuration dataclasses
├── visualize.py           # Chart generation
├── strategies/
│   ├── whole_proof.py     # Full proof generation
│   ├── stepwise.py        # Tactic-by-tactic search
│   ├── refinement.py      # Error-guided self-correction
│   └── near_miss.py       # Sorry-gap filling
└── docs/
    ├── academic_report.md # Research methodology report
    └── technical_report.md# Technical implementation report

dataset/                   # Benchmark JSONL 子集（minif2f、unsolved39 等）
data/                      # miniF2F v2 等扩展数据
config/                    # Environment config (env.sh)
scripts/                   # 编译分块、Pass@32 汇总、MVP 流水线（见 scripts/README.md）
src/                       # Goedel 风格 inference.py（多轮 correction_round）
results/                   # 实验输出（proof_results、编译 JSON、日志）
docs/                      # 仓库导航与 Goedel 评测说明
experiments/               # 一次性实验（如 phase1_official_config.py）
mathlib4/                  # Mathlib 上游（勿与 prover 代码混淆）
```

## Strategies

| Strategy | Description |
|----------|-------------|
| `whole_proof` | Generate complete proofs, verify via REPL |
| `stepwise` | Tactic-by-tactic search with goal state feedback |
| `refinement` | Error-classified iterative self-correction |
| `near_miss` | Fill sorry gaps using context-aware prompts |

Strategies can be composed in a **cascade** where each passes intermediate results to the next.

## Supported Datasets

`minif2f`, `putnambench`, `proofnet`, `fate_h`, `fate_m`, `fate_x`

## Key Features

- **Cross-model sorry filling**: Use Model A's proof skeleton + Model B's tactic generation
- **Robust REPL integration**: Process-group kill on timeout, automatic restart
- **Dataset sharding**: `--shard-id` / `--num-shards` for parallel experiments
- **Incremental results**: Resume interrupted experiments with `--resume`
