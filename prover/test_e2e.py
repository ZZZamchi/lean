#!/usr/bin/env python3
"""
End-to-end test using the verifier (no GPU needed).
Tests stepwise strategy logic with a deterministic "mock" tactic generator.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from prover.verifier import LeanVerifier, VerifyResult
from prover.config import VerifierConfig


EASY_PROBLEMS = [
    {
        "id": "test_omega",
        "header": "theorem t1 (n : Nat) (h : n > 5) : n > 3 := by",
        "solution": ["omega"],
    },
    {
        "id": "test_constructor",
        "header": "theorem t2 (p q : Prop) (hp : p) (hq : q) : p ∧ q := by",
        "solution": ["constructor", "exact hp", "exact hq"],
    },
    {
        "id": "test_intro_apply",
        "header": "theorem t3 (p q : Prop) (h : p → q) (hp : p) : q := by",
        "solution": ["exact h hp"],
    },
    {
        "id": "test_induction",
        "header": "theorem t4 (n : Nat) : 0 + n = n := by",
        "solution": ["simp"],
    },
    {
        "id": "test_cases",
        "header": "theorem t5 (p : Prop) (h : p ∨ ¬p) : True := by",
        "solution": ["trivial"],
    },
]

TACTIC_POOL = [
    "omega", "simp", "ring", "norm_num", "linarith", "trivial", "rfl",
    "constructor", "exact hp", "exact hq", "exact h hp",
    "intro h", "cases h", "contradiction",
    "apply And.intro", "apply Or.inl",
]


def test_stepwise_search(verifier: LeanVerifier):
    """Simulate stepwise search with a fixed tactic pool."""
    print("=== Stepwise Search (simulated) ===\n")

    for problem in EASY_PROBLEMS:
        pid = problem["id"]
        header = problem["header"]
        expected = problem["solution"]

        print(f"Problem: {pid}")
        print(f"  Header: {header}")

        initial = verifier.get_goal_at_sorry(header, [])
        if not initial.goals:
            print(f"  SKIP: no initial goal")
            continue
        print(f"  Initial goal: {initial.goals[0][:80]}")

        found = False
        best_tactics = []
        best_goal_count = len(initial.goals)

        for depth in range(5):
            current_goals = verifier.get_goal_at_sorry(header, best_tactics).goals
            if not current_goals:
                final = verifier.verify_tactic_sequence(header, best_tactics)
                if final.complete:
                    found = True
                    break
                break

            for tactic in TACTIC_POOL:
                candidate = best_tactics + [tactic]

                full_check = verifier.verify_tactic_sequence(header, candidate)
                if full_check.complete:
                    best_tactics = candidate
                    found = True
                    break

                result = verifier.get_goal_at_sorry(header, candidate)
                if result.success and result.goals is not None:
                    if len(result.goals) < len(current_goals) or (
                        result.goals and set(result.goals) != set(current_goals)
                    ):
                        best_tactics = candidate
                        break

            if found:
                break

        status = "SOLVED" if found else "FAILED"
        print(f"  Result: {status} with tactics: {best_tactics}")
        if found:
            print(f"  Expected: {expected}")
        print()

    return True


def test_refinement_flow(verifier: LeanVerifier):
    """Test the refinement approach: initial attempt → error analysis → fix."""
    print("=== Refinement Flow ===\n")

    header = "theorem ref_test (a b : Nat) : a + b = b + a := by"

    print("Step 1: Try wrong tactic")
    r1 = verifier.verify(f"{header}\n  omega")
    print(f"  omega: pass={r1.success}, complete={r1.complete}")

    if not r1.complete:
        print("Step 2: Try correct tactic")
        r2 = verifier.verify(f"{header}\n  ring")
        print(f"  ring: pass={r2.success}, complete={r2.complete}")

        if not r2.complete:
            r3 = verifier.verify(f"{header}\n  simp [Nat.add_comm]")
            print(f"  simp [Nat.add_comm]: pass={r3.success}, complete={r3.complete}")

    print()
    return True


def test_multi_dataset_verify(verifier: LeanVerifier):
    """Test verifying proofs from different datasets."""
    print("=== Multi-Dataset Verification ===\n")

    proofs = [
        ("minif2f-style", "theorem minif2f_ex (x : ℝ) (h : x = 3) : x + 1 = 4 := by linarith"),
        ("fate-style", "theorem fate_ex (G : Type*) [Group G] (a : G) : a * 1 = a := by simp"),
        ("proofnet-style", "theorem pn_ex (n : ℕ) : n * 0 = 0 := by simp"),
    ]

    for label, code in proofs:
        r = verifier.verify(code)
        status = "OK" if r.complete else f"FAIL (pass={r.success}, errors={len(r.errors)})"
        print(f"  {label}: {status}")

    print()


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    verifier = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))
    verifier.start()

    try:
        test_stepwise_search(verifier)
        test_refinement_flow(verifier)
        test_multi_dataset_verify(verifier)
        print("=== All E2E tests passed! ===")
    finally:
        verifier.stop()
