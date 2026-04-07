#!/usr/bin/env python3
"""
Targeted attack on 14 near-miss hard sub-goals using multiple prompt strategies.

Each sub-goal is tried with different prompt variants:
  - standard: bare theorem (baseline, same as original)
  - hinted: mathematical insight as Lean comment
  - tactic: suggested Lean tactics as comment
  - skeleton: proof skeleton with sorry for sub-steps

Runs Goedel-8B, verifies via Lean REPL, reports which goals are newly solved.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prover.config import ModelConfig, ProverConfig, VerifierConfig
from prover.model import ProverModel
from prover.verifier import LeanVerifier

MANIFEST_PATH = "results/minif2f/round_2/subproblem_mvp/_sorry_goals_for_inference.jsonl"

HINTS = {
    "sorry_fill_amc12b_2002_p4_g0": {
        "hinted": (
            "-- Hint: 1/2 + 1/3 + 1/7 = 41/42. For 41/42 + 1/n to be integer,\n"
            "-- n must divide 42. Check: only n=42 gives integer sum.\n"
            "-- Try: unfold Rat arithmetic, use omega or interval_cases on divisors."
        ),
        "tactic": (
            "-- Strategy: Use Rat.add_den_dvd or unfold /. to reduce to divisibility.\n"
            "-- Try: simp [Rat.mk_eq_divInt] then omega, or native_decide."
        ),
    },
    "sorry_fill_imo_1982_p1_g0": {
        "hinted": (
            "-- Hint: f is nearly additive with f(m+n) = f(m)+f(n) or f(m)+f(n)+1.\n"
            "-- From f(2)=0 and f(3)>=1, deduce f(3)=1. Then f(n) = floor(n/3).\n"
            "-- Key: show f(3k)=k by induction using near-additivity.\n"
            "-- Then f(1982) = f(3*660+2) = 660+f(2) = 660."
        ),
        "tactic": (
            "-- Strategy: First prove f(1)=0 from f(2)=0 and near-additivity.\n"
            "-- Then f(3)=1, f(6)=2, ..., f(3k)=k by strong induction.\n"
            "-- Use h3 to confirm, then compute f(1982) = f(1980+2) = 660+0 = 660."
        ),
    },
    "sorry_fill_aime_1984_p7_g0": {
        "hinted": (
            "-- Hint: For n>=1000, f(n)=n-3. For n<1000, f(n)=f(f(n+5)).\n"
            "-- Key insight: for n in [997,999], f cycles with values 997,998,999.\n"
            "-- Since 84 mod 4 = 0, tracing the recursion gives f(84) = 997.\n"
            "-- Approach: build a chain of equalities using h0 and h1."
        ),
        "tactic": (
            "-- Strategy: prove helper lemmas:\n"
            "-- have h997 : f 997 = 997 (trace through f(997)=f(f(1002))=f(999)=...)\n"
            "-- Then show f(n) = f(n+12) for n < 988 by unwinding the recursion.\n"
            "-- Since 84 = 997 - 913 and 913 = 76*12+1, reduce to f(84+12k)=997."
        ),
    },
    "sorry_fill_imo_1968_p5_1_g0": {
        "hinted": (
            "-- Hint: Apply h1 at x and at (x+a) to get f(x+2a).\n"
            "-- Then apply twice more to get f(x+4a).\n"
            "-- Show f(x+4a) = f(x) by algebraic simplification.\n"
            "-- Use b = 4*a. Start with: refine ⟨4*a, by linarith, ?_⟩"
        ),
        "tactic": (
            "-- Strategy: exact ⟨4*a, by linarith, fun x => by\n"
            "--   have h2 := h1 x; have h3 := h1 (x+a)\n"
            "--   have h4 := h1 (x+2*a); have h5 := h1 (x+3*a)\n"
            "--   ring_nf at *; nlinarith [sq_nonneg (f x), sq_nonneg (f(x+a))]⟩"
        ),
    },
    "sorry_fill_imo_1977_p6_g0": {
        "hinted": (
            "-- Hint: Step 1: f is strictly increasing (from f(f(n)) < f(n+1) and f > 0).\n"
            "-- Step 2: f(n) >= n for all n>0 by strong induction.\n"
            "-- Step 3: f(n) <= n: if f(n)>=n+1, then f(f(n))>=f(n+1), contradicting h1.\n"
            "-- Combine steps 2&3: f(n) = n."
        ),
        "tactic": (
            "-- Strategy: First prove f is strictly monotone:\n"
            "-- have mono : StrictMono f := by ...\n"
            "-- Then: have ge : ∀ n, 0 < n → n ≤ f n := by intro n hn; induction n with ...\n"
            "-- Then: have le : ∀ n, 0 < n → f n ≤ n := by intro n hn; by_contra h; push_neg at h; ...\n"
            "-- Finally: intro n hn; exact Nat.le_antisymm (le n hn) (ge n hn)"
        ),
    },
    "sorry_fill_imo_1997_p5_g0": {
        "hinted": (
            "-- Hint: Case split on y.\n"
            "-- y=1: x^1 = 1 → x=1.\n"
            "-- y=2: x^4 = 2^x → check x=16 works (16^4 = 65536 = 2^16).\n"
            "-- y=3: x^9 = 3^x → check x=27 works (27^9 = 3^27).\n"
            "-- y>=4: show no solution. If x=y^a then a*y^2 = y^a, so a = y^(a-2).\n"
            "-- For y>=4 and a>=2: y^(a-2) > a, contradiction."
        ),
        "tactic": (
            "-- Strategy: rcases h0 with ⟨hx, hy⟩\n"
            "-- Use interval_cases y for small values, then contradiction for y >= 4.\n"
            "-- Key: for y=1, h1 gives x^1=1, so x=1.\n"
            "-- For y=2, x^4=2^x. Show x=16 by bounding.\n"
            "-- For y>=4: use Nat.pow_lt_pow to show no solution exists."
        ),
    },
    "sorry_fill_numbertheory_fxeq4powxp6powxp9powx_f2powmdvdf2pown_g0": {
        "hinted": (
            "-- Hint: f(x) = 4^x + 6^x + 9^x = (2^x + 3^x)^2 - 6^x.\n"
            "-- Key algebraic identity: f(2x) = f(x) * (4^x - 6^x + 9^x).\n"
            "-- Proof: f(2x) = 16^x + 36^x + 81^x\n"
            "--   = (4^x+6^x+9^x)(4^x-6^x+9^x) + 2*36^x - 2*36^x = f(x)*g(x).\n"
            "-- So f(2^m) | f(2^(m+1)) | ... | f(2^n) by induction on n-m."
        ),
        "tactic": (
            "-- Strategy: induction on n-m.\n"
            "-- Base: m=n, trivially divides.\n"
            "-- Step: show f(2x) is divisible by f(x) using the identity\n"
            "--   f(2x) = (4^x)^2 + (6^x)^2 + (9^x)^2\n"
            "--        = (4^x+6^x+9^x)^2 - 2*(24^x + 36^x + 54^x)\n"
            "-- Then simplify the remainder terms."
        ),
    },
    "sorry_fill_amc12a_2008_p25_g0": {
        "hinted": (
            "-- Hint: Define c(n) = a(n) + b(n)*I as a complex number.\n"
            "-- Then c(n+1) = (sqrt(3) + I) * c(n), which is multiplication by 2*exp(I*pi/6).\n"
            "-- So |c(n)| = 2^(n-1) * |c(1)| and c(100) = 2 + 4*I.\n"
            "-- a(1)+b(1) = (a(100)+b(100)) / 2^99 * correction = 6/2^99 after angle analysis.\n"
            "-- Actually a(1)+b(1) = 1/2^98."
        ),
    },
    "sorry_fill_amc12a_2021_p12_g0": {
        "hinted": (
            "-- Hint: All roots are positive integers (from h1). By Vieta's:\n"
            "-- Sum of roots = 10, product of roots = 16.\n"
            "-- List all multisets of 6 positive integers summing to 10:\n"
            "-- Check that none has product exactly 16.\n"
            "-- Therefore the hypotheses are contradictory → False."
        ),
        "tactic": (
            "-- Strategy: suffices h : ¬∃ (roots : Multiset ℕ), roots.card = 6 ∧\n"
            "--   (∀ r ∈ roots, 0 < r) ∧ roots.sum = 10 ∧ roots.prod = 16 by ...\n"
            "-- Or: construct a specific z that violates h1, e.g. a non-integer root."
        ),
    },
    "sorry_fill_aime_1999_p11_g0": {
        "hinted": (
            "-- Hint: sum_{k=1}^{35} sin(5k*pi/180) = sin(5*pi/180)*...\n"
            "-- Use telescoping product formula for sum of sines:\n"
            "-- sum = sin(n*d/2) * sin((n+1)*d/2) / sin(d/2) with d=5*pi/180, n=35.\n"
            "-- This gives tan(87.5 degrees) = tan(175/2 degrees).\n"
            "-- So m = 175/2, den + num = 2 + 175 = 177."
        ),
    },
    "sorry_fill_amc12a_2020_p25_g0": {
        "hinted": (
            "-- Hint: floor(x)*(x - floor(x)) = a*x^2.\n"
            "-- For each integer n, in the interval [n, n+1): n*(x-n) = a*x^2.\n"
            "-- This gives x = (n ± sqrt(n^2 - 4an^2)) / (2a).\n"
            "-- Sum over all valid n gives sum = 420, determining a.\n"
            "-- Then a.den + a.num = 929."
        ),
    },
    "sorry_fill_amc12a_2020_p9_g0": {
        "hinted": (
            "-- Hint: tan(2x) = cos(x/2) in [0, 2*pi].\n"
            "-- Rewrite: sin(2x)/cos(2x) = cos(x/2).\n"
            "-- Exclude x where cos(2x)=0: x = pi/4, 3pi/4, 5pi/4, 7pi/4.\n"
            "-- Count solutions graphically: there are exactly 5 intersections."
        ),
    },
    "sorry_fill_amc12b_2021_p13_g0": {
        "hinted": (
            "-- Hint: 1 - 3*sin(x) + 5*cos(3x) = 0 in (0, 2*pi].\n"
            "-- Expand cos(3x) = 4cos^3(x) - 3cos(x) and use sin^2+cos^2=1.\n"
            "-- This becomes a polynomial in sin(x) and cos(x).\n"
            "-- Count roots: exactly 6 solutions in the given interval."
        ),
    },
    "sorry_fill_imo_1969_p2_g0": {
        "hinted": (
            "-- Hint: y(x) = sum cos(a_i + x)/2^i.\n"
            "-- |y(x)| <= sum 1/2^i < 2 for any x.\n"
            "-- y(m)=0 and y(n)=0 means the function vanishes at both points.\n"
            "-- The function is a finite trigonometric polynomial.\n"
            "-- Show m-n must be a multiple of pi using the structure of the sum."
        ),
    },
}


def load_hard_subgoals():
    """Load the 14 hard sub-goals from the manifest, attach hints."""
    goals = {}
    with open(MANIFEST_PATH) as f:
        for line in f:
            g = json.loads(line)
            gid = g["problem_id"]
            if gid in HINTS:
                goals[gid] = {
                    "base": g["_base_problem"],
                    "lean4_code": g["lean4_code"],
                    "formal_statement": g["formal_statement"],
                    "goal_text": g["_sorry_goal"],
                    "hints": HINTS[gid],
                }
    return goals


HARD_SUBGOALS = None  # loaded at runtime

def create_prompt_variants(goal_id, info):
    """Create multiple prompt variants for a sub-goal."""
    code = info["lean4_code"]
    variants = {}

    variants["standard"] = f"Complete the following Lean 4 code:\n\n```lean4\n{code}\n```"

    for hint_name, hint_text in info.get("hints", {}).items():
        parts = code.split("\ntheorem")
        if len(parts) >= 2:
            hinted_code = parts[0] + "\n" + hint_text + "\ntheorem" + parts[1]
        else:
            hinted_code = hint_text + "\n" + code
        variants[hint_name] = f"Complete the following Lean 4 code:\n\n```lean4\n{hinted_code}\n```"

    return variants


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpus", default="2,3")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--output-dir", default="results/experiments/hard_subgoals_v1")
    parser.add_argument("--dry-run", action="store_true", help="Just print prompts, don't run")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    hard_subgoals = load_hard_subgoals()
    print(f"Loaded {len(hard_subgoals)} hard sub-goals with hints")

    all_tasks = []
    for goal_id, info in hard_subgoals.items():
        variants = create_prompt_variants(goal_id, info)
        for vname, prompt in variants.items():
            all_tasks.append({
                "goal_id": goal_id,
                "base_problem": info["base"],
                "variant": vname,
                "prompt": prompt,
                "lean4_code": info["lean4_code"],
            })

    print(f"Total tasks: {len(all_tasks)} ({len(hard_subgoals)} goals × variants)")

    if args.dry_run:
        for t in all_tasks:
            print(f"\n{'='*60}")
            print(f"Goal: {t['goal_id']} | Variant: {t['variant']}")
            print(f"{'='*60}")
            print(t["prompt"][:600])
        return

    config = ProverConfig(
        model=ModelConfig(
            model_path="Goedel-LM/Goedel-Prover-V2-8B",
            tensor_parallel_size=2,
            max_model_len=args.max_model_len,
            max_tokens=args.max_tokens,
            temperature=1.0,
            gpu_memory_utilization=0.90,
            use_chat_template=True,
        ),
        verifier=VerifierConfig(),
        cuda_devices=args.gpus,
    )

    print("Loading model...")
    model = ProverModel(config.model, config.cuda_devices)
    model.load()

    print("Starting verifier...")
    verifier = LeanVerifier(config.verifier)
    verifier.start()

    results = []
    solved_goals = set()
    total_tasks = len(all_tasks)

    try:
        for i, task in enumerate(all_tasks):
            goal_id = task["goal_id"]
            variant = task["variant"]
            print(f"\n[{i+1}/{total_tasks}] {goal_id} ({variant})")

            if goal_id in solved_goals:
                print(f"  Already solved, skipping")
                continue

            t0 = time.time()
            raw_outputs = model.generate_single(
                task["prompt"],
                n=args.samples,
                temperature=1.0,
                chat=config.model.use_chat_template,
            )
            gen_time = time.time() - t0

            n_extracted = 0
            n_pass = 0
            n_complete = 0
            best_code = None
            best_sorries = 999

            for raw in raw_outputs:
                extracted = model.extract_lean_code(raw)
                if not extracted:
                    continue
                n_extracted += 1

                if "theorem" in extracted and ":= by" in extracted:
                    code = extracted
                else:
                    lean4 = task["lean4_code"]
                    header = lean4.split(":= by")[0].strip() + " := by"
                    code = f"{header}\n  {extracted}"

                result = verifier.verify(code)

                if result.complete:
                    n_complete += 1
                    solved_goals.add(goal_id)
                    best_code = code
                    print(f"  *** SOLVED! *** variant={variant}")
                    break

                if result.success:
                    n_pass += 1
                    n_sorries = len(result.sorries) if result.sorries else 0
                    if n_sorries < best_sorries:
                        best_sorries = n_sorries
                        best_code = code

            task_result = {
                "goal_id": goal_id,
                "base_problem": task["base_problem"],
                "variant": variant,
                "n_samples": args.samples,
                "n_extracted": n_extracted,
                "n_pass": n_pass,
                "n_complete": n_complete,
                "solved": goal_id in solved_goals,
                "gen_time": round(gen_time, 1),
                "best_code": best_code,
            }
            results.append(task_result)

            status = "SOLVED" if n_complete > 0 else f"pass={n_pass}/{n_extracted}"
            print(f"  {status} ({gen_time:.1f}s)")

            with open(os.path.join(args.output_dir, "results.json"), "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    finally:
        verifier.stop()

    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(solved_goals)}/{len(hard_subgoals)} hard sub-goals solved")
    for gid in sorted(solved_goals):
        print(f"  ✓ {gid}")
    print(f"Results saved to {args.output_dir}/results.json")


if __name__ == "__main__":
    main()
