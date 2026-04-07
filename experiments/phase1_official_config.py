#!/usr/bin/env python3
"""
Phase 1: Goedel-8B with official-style config on minif2f_unsolved39 (39 problems).

Features:
  - Chat template, Goedel proof-plan prompt, optional self-correction
  - --output-dir under results/experiments/ (default phase1_official_32k)
  - --resume: load proof_results.json, skip problems already complete (unless --force)
  - --max-problems N: only first N problems (for ablation / smoke tests)
  - --max-tokens / --max-model-len / --no-chat for ablations
  - Writes run_meta.json at start

Usage:
  python3 experiments/phase1_official_config.py --gpus 0,1 --samples 32 --self-correction 2
  python3 experiments/phase1_official_config.py --gpus 0,1 --resume --output-dir phase1_official_32k
  python3 experiments/phase1_official_config.py --gpus 0,1 --max-problems 3 --output-dir _smoke_phase1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOEDEL_PROMPT = """\
Complete the following Lean 4 code:

```lean4
{formal_statement}```

Before producing the Lean 4 code to formally prove the given theorem, provide a detailed proof plan outlining the main proof steps and strategies.
The plan should highlight key ideas, intermediate lemmas, and proof structures that will guide the construction of the final formal proof."""

SELF_CORRECTION_PROMPT = """\
The following Lean 4 proof attempt failed compilation:

```lean4
{failed_code}
```

The Lean compiler reported the following errors:
```
{error_messages}
```

Please fix the proof. First analyze what went wrong, then provide a corrected complete proof.

```lean4
{formal_statement}```"""


def assemble_code(header, extracted, strip_imports_fn):
    if "theorem" in extracted and ":= by" in extracted:
        return strip_imports_fn(extracted)
    if extracted.strip().startswith("by"):
        return f"{header.rstrip()}\n{extracted}"
    return f"{header}\n  {extracted}"


def _git_rev() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_run_meta(
    out_dir: Path,
    *,
    gpus: str,
    samples: int,
    self_correction_rounds: int,
    max_tokens: int,
    max_model_len: int,
    use_chat: bool,
    resume: bool,
    force: bool,
    max_problems: int | None,
    output_dir_name: str,
    dataset_key: str,
) -> None:
    meta = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_rev": _git_rev(),
        "cuda_visible_devices": gpus,
        "samples_per_problem": samples,
        "self_correction_rounds": self_correction_rounds,
        "max_tokens": max_tokens,
        "max_model_len": max_model_len,
        "use_chat_template": use_chat,
        "resume": resume,
        "force_rerun_complete": force,
        "max_problems": max_problems,
        "dataset": dataset_key,
        "output_dir": output_dir_name,
    }
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def load_existing_by_id(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {r["problem_id"]: r for r in data if isinstance(r, dict) and r.get("problem_id")}


def save_results(out_dir: Path, results: list) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "proof_results.json"
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def run_official(
    gpus: str,
    samples: int = 32,
    self_correction_rounds: int = 0,
    output_subdir: str = "phase1_official_32k",
    resume: bool = False,
    force: bool = False,
    max_problems: int | None = None,
    max_tokens: int = 32768,
    max_model_len: int = 32768,
    use_chat: bool = True,
    dataset_key: str = "minif2f_unsolved39",
) -> None:
    from prover.config import ModelConfig, VerifierConfig
    from prover.datasets import load_dataset
    from prover.model import ProverModel
    from prover.strategies.base import ProofStrategy
    from prover.verifier import LeanVerifier

    out_dir = ROOT / "results" / "experiments" / output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "proof_results.json"

    write_run_meta(
        out_dir,
        gpus=gpus,
        samples=samples,
        self_correction_rounds=self_correction_rounds,
        max_tokens=max_tokens,
        max_model_len=max_model_len,
        use_chat=use_chat,
        resume=resume,
        force=force,
        max_problems=max_problems,
        output_dir_name=output_subdir,
        dataset_key=dataset_key,
    )

    existing = load_existing_by_id(results_path) if resume else {}

    mcfg = ModelConfig(
        model_path="Goedel-LM/Goedel-Prover-V2-8B",
        tensor_parallel_size=2,
        max_model_len=max_model_len,
        max_tokens=max_tokens,
        temperature=1.0,
        top_p=0.95,
        gpu_memory_utilization=0.92,
        use_chat_template=use_chat,
    )

    os.environ["CUDA_VISIBLE_DEVICES"] = gpus
    model = ProverModel(mcfg, cuda_devices=gpus)
    model.load()

    verifier = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))
    verifier.start()

    problems = list(load_dataset(dataset_key))
    if max_problems is not None:
        problems = problems[: max(0, max_problems)]

    results: list = []
    batch_size = 4

    try:
        for idx, prob in enumerate(problems):
            t0 = time.time()
            pid = prob.problem_id
            print(f"\n[{idx+1}/{len(problems)}] {pid}")

            if (
                resume
                and pid in existing
                and existing[pid].get("complete")
                and not force
            ):
                print("  [SKIP] already complete (resume)")
                results.append(existing[pid])
                save_results(out_dir, results)
                continue

            stmt = prob.lean4_code
            header = ProofStrategy.strip_imports(prob.theorem_header)
            prompt = GOEDEL_PROMPT.format(formal_statement=stmt)

            attempt = {
                "problem_id": pid,
                "complete": False,
                "attempts": 0,
                "strategy": "phase1_official",
                "code": "",
                "self_correction_rounds": 0,
                "max_tokens": max_tokens,
                "use_chat": use_chat,
            }
            best_error_code = None
            best_error_msg = None

            for batch_start in range(0, samples, batch_size):
                batch_n = min(batch_size, samples - batch_start)
                batch_out = model.generate_single(
                    prompt,
                    n=batch_n,
                    temperature=1.0,
                    max_tokens=max_tokens,
                    chat=use_chat,
                )

                for raw in batch_out:
                    extracted = model.extract_lean_code(raw)
                    if not extracted:
                        continue
                    code = assemble_code(header, extracted, ProofStrategy.strip_imports)
                    attempt["attempts"] += 1
                    r = verifier.verify(code)

                    if r.complete:
                        attempt["complete"] = True
                        attempt["code"] = code
                        break

                    if r.success and not r.complete and best_error_code is None:
                        best_error_code = code
                        best_error_msg = "; ".join(
                            s.get("goal", "")[:100] for s in r.sorries[:3]
                        )
                    elif r.errors and best_error_code is None:
                        best_error_code = code
                        best_error_msg = "; ".join(
                            e.get("data", "")[:100] for e in r.errors[:3]
                        )

                if attempt["complete"]:
                    break

            if not attempt["complete"] and self_correction_rounds > 0 and best_error_code:
                for sc_round in range(1, self_correction_rounds + 1):
                    print(f"  Self-correction round {sc_round}...")
                    sc_prompt = SELF_CORRECTION_PROMPT.format(
                        failed_code=best_error_code,
                        error_messages=best_error_msg or "unknown error",
                        formal_statement=stmt,
                    )
                    sc_n = min(samples // 2, 8)
                    sc_outputs = model.generate_single(
                        sc_prompt,
                        n=sc_n,
                        temperature=0.8,
                        max_tokens=max_tokens,
                        chat=use_chat,
                    )
                    for raw in sc_outputs:
                        extracted = model.extract_lean_code(raw)
                        if not extracted:
                            continue
                        code = assemble_code(
                            header, extracted, ProofStrategy.strip_imports
                        )
                        attempt["attempts"] += 1
                        r = verifier.verify(code)
                        if r.complete:
                            attempt["complete"] = True
                            attempt["code"] = code
                            attempt["self_correction_rounds"] = sc_round
                            break
                        if r.errors:
                            best_error_code = code
                            best_error_msg = "; ".join(
                                e.get("data", "")[:100] for e in r.errors[:3]
                            )
                    if attempt["complete"]:
                        break

            elapsed = time.time() - t0
            attempt["elapsed"] = round(elapsed, 1)

            if attempt["complete"]:
                sc_info = (
                    f" (SC round {attempt['self_correction_rounds']})"
                    if attempt["self_correction_rounds"] > 0
                    else ""
                )
                print(
                    f"  [SOLVED] in {elapsed:.1f}s, {attempt['attempts']} attempts{sc_info}"
                )
            else:
                print(f"  [FAIL] in {elapsed:.1f}s, {attempt['attempts']} attempts")

            results.append(attempt)
            save_results(out_dir, results)

    finally:
        verifier.stop()

    total_complete = sum(1 for r in results if r.get("complete"))
    print(f"\n{'='*60}")
    print(
        f"Phase 1 ({output_subdir}): {total_complete}/{len(results)} complete in proof_results.json"
    )
    print("Baseline pass@64 slice: 205/244 = 84.0%; +1 on 39-set already from 16K (mathd_algebra_320).")
    solved_pids = [r["problem_id"] for r in results if r.get("complete")]
    if solved_pids:
        print(f"Solved ids: {solved_pids}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gpus", type=str, default="2,3")
    p.add_argument("--samples", type=int, default=32)
    p.add_argument("--self-correction", type=int, default=2, dest="self_correction")
    p.add_argument(
        "--output-dir",
        type=str,
        default="phase1_official_32k",
        help="Subdirectory under results/experiments/",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Load proof_results.json; skip problems with complete=True unless --force",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if already complete (with --resume)",
    )
    p.add_argument(
        "--max-problems",
        type=int,
        default=None,
        help="Only first N problems from minif2f_unsolved39",
    )
    p.add_argument("--max-tokens", type=int, default=32768)
    p.add_argument("--max-model-len", type=int, default=None)
    p.add_argument(
        "--no-chat",
        action="store_true",
        help="Disable chat template (ablation)",
    )
    p.add_argument(
        "--dataset",
        type=str,
        default="minif2f_unsolved39",
        help="Registry key in prover.datasets (e.g. minif2f_ablation_slice10)",
    )
    args = p.parse_args()
    mlen = args.max_model_len if args.max_model_len is not None else args.max_tokens
    run_official(
        args.gpus,
        args.samples,
        args.self_correction,
        output_subdir=args.output_dir,
        resume=args.resume,
        force=args.force,
        max_problems=args.max_problems,
        max_tokens=args.max_tokens,
        max_model_len=mlen,
        use_chat=not args.no_chat,
        dataset_key=args.dataset,
    )


if __name__ == "__main__":
    main()
