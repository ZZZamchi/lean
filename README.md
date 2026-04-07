# Lean 4 Proof Search Framework

Multi-strategy proof search engine for Lean 4 formal theorem proving, with support for cross-model sorry-gap filling.

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

dataset/                   # Benchmark datasets (JSONL/JSON)
config/                    # Environment config (env.sh)
scripts/                   # Utility scripts (inference, compilation)
results/                   # Experiment outputs
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
