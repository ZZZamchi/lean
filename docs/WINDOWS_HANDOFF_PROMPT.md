# Windows Native Handoff Prompt (No WSL)

Use this prompt on a fresh Windows machine where nothing is preinstalled.

## Goal

1. Run full FATE-H (1..100) in stable batches.
2. Reduce API-timeout noise by rerunning timeout-like items (`attempts == 0`).
3. Report final overall `complete` rate and whether it exceeds 10%.
4. Do not do per-problem manual repair loops in this stage.

## Constraints

- Use Windows native PowerShell only (no WSL).
- Treat machine as empty: no Python env, no repo, no benchmark data.
- Detect missing dependencies first, then install.
- Keep model/strategy fixed for comparability.

## Inputs to Ask User

- `REPO_MAIN_URL` (project repo, contains `prover.run`)
- `REPO_BENCH_URL` (benchmark repo, contains `FATE-H.json`)
- `OPENAI_API_KEY`
- Optional:
  - `API_BASE_URL` (default `https://api.ofox.ai/v1`)
  - `API_MODEL` (default `anthropic/claude-opus-4.7`)
  - `WORKDIR` (default `D:\ml\zam`)

## Required Steps

### 1) Environment detection

Run and print outputs:

- `$PSVersionTable`
- `[System.Environment]::OSVersion.VersionString`
- `git --version`
- `python --version`
- `py --version`
- `pip --version`
- `nvidia-smi` (if available)
- `Test-NetConnection github.com -Port 443`
- `Test-NetConnection api.ofox.ai -Port 443`

If missing, install with `winget`:

- Git: `winget install --id Git.Git -e`
- Python: `winget install --id Python.Python.3.11 -e`

### 2) Clone repos and locate dataset

- Create workdir, clone main repo and benchmark repo.
- Ensure final dataset path resolves to:
  - `<bench-root>\benchmarks\fate\FATE-H\FATE-H.json`
- If path differs, search recursively for `FATE-H.json` and store resolved path.

### 3) Python environment

Inside main repo root:

- `py -3.11 -m venv .venv`
- `.\.venv\Scripts\Activate.ps1`
- `python -m pip install --upgrade pip setuptools wheel`

Install dependencies by probing in order:

1. `requirements.txt` -> `pip install -r requirements.txt`
2. `pyproject.toml` -> `pip install -e .`
3. fallback: read repo README and execute documented install commands.

Sanity check:

- `python -m prover.run -h` must succeed.

### 4) Run strategy (fixed)

Batch plan:

- `1-20`, `21-40`, `41-60`, `61-80`, `81-100`

Main run params:

- `api-timeout-s=90`
- `api-max-retries=2`

Timeout-rerun params:

- `api-timeout-s=120`
- `api-max-retries=3`

Shared params:

- backend: `openai_compat`
- model: `anthropic/claude-opus-4.7`
- strategy: `draft_formalize + sketch-first`
- `--draft-sketch-samples 3`
- `--draft-min-sketch-lemmas 3`
- `--draft-samples 1`
- `--formalize-samples 6`
- `--draft-rounds 4`
- `--draft-repair-steps 8`
- `--draft-sorry-candidates 10`
- `--draft-feedback-chars 3000`
- `--max-tokens 4096`
- `--temperature 0.15`
- `--verifier-timeout 300`
- `--mathlib-path mathlib4`

For each batch:

1. Run main batch.
2. Parse `proof_results.json`, collect `problem_id` where `attempts == 0`.
3. If non-empty, run timeout-rerun on those IDs.
4. For batch final view, prefer rerun record for overlapped IDs.

### 5) Reporting requirements

Per batch report:

- `n`, `complete`, `pass`
- `attempts=0` count (main run)
- rerun recovered `complete` and `pass` counts

Final full 100 report:

- overall `complete` / rate
- overall `pass` / rate
- timeout-like share
- net gain from timeout-rerun
- whether `complete_rate >= 10%`

## Optional helper script

If available in repo, prefer using:

- `scripts/windows/run_fate_h_windows.ps1`

