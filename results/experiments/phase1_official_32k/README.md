# Phase1 official 32K (39 unsolved miniF2F valid)

**Purpose:** Same problem list as `phase1_official_16k`, but `max_tokens` / `max_model_len` = 32768 and runner `experiments/phase1_official_config.py`.

## Run (resumable)

```bash
cd /path/to/lean
# Uses default output-dir phase1_official_32k; skips problems already complete in proof_results.json
python3 experiments/phase1_official_config.py --gpus 0,1 --resume \
  --output-dir phase1_official_32k --self-correction 2 --samples 32
```

- First run: omit `--resume` or start with empty `proof_results.json` (`[]`).
- After crash: re-run with `--resume` to skip `complete: true` rows.
- Force full re-run: `--resume --force`.

## After completion

```bash
python3 scripts/compare_phase1_runs.py
# -> results/experiments/phase1_compare_16k_32k.{json,md}
```

`run_meta.json` is overwritten at each invocation with start-time and CLI snapshot.
