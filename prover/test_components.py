#!/usr/bin/env python3
"""
Test framework components without GPU (verifier + dataset loader).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_dataset_loader():
    from prover.datasets import load_dataset, list_datasets
    print("=== Dataset Loader ===")
    print(f"Available: {list_datasets()}")

    for name in ["minif2f", "putnambench", "fate_h"]:
        try:
            problems = load_dataset(name, limit=3)
            print(f"\n{name}: {len(problems)} loaded (showing first)")
            p = problems[0]
            print(f"  id: {p.problem_id}")
            print(f"  split: {p.split}")
            print(f"  header: {p.theorem_header[:120]}...")
            print(f"  informal: {p.informal_statement[:100]}...")
        except Exception as e:
            print(f"\n{name}: ERROR - {e}")

    print("\nDataset loader: OK\n")


def test_verifier():
    from prover.verifier import LeanVerifier
    from prover.config import VerifierConfig

    print("=== Lean Verifier ===")
    v = LeanVerifier(VerifierConfig(mathlib_path="mathlib4"))

    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    print("Starting REPL...")
    t0 = time.time()
    v.start()
    print(f"  REPL started in {time.time()-t0:.1f}s")

    # Test 1: Simple complete proof
    print("\nTest 1: Simple complete proof")
    r = v.verify("theorem test1 (n : Nat) (h : n = 0) : n + 1 = 1 := by omega")
    print(f"  pass={r.success}, complete={r.complete}, errors={len(r.errors)}")
    assert r.complete, f"Expected complete, got errors: {r.errors}"

    # Test 2: Proof with sorry (should extract goal)
    print("\nTest 2: Proof with sorry → extract goal")
    r = v.verify("theorem test2 (n : Nat) (h : n > 5) : n > 3 := by sorry")
    print(f"  pass={r.success}, complete={r.complete}, goals={r.goals}")
    assert r.success and not r.complete, "Expected pass but not complete"
    assert len(r.goals) > 0, "Expected at least one goal from sorry"

    # Test 3: Step-by-step goal extraction
    print("\nTest 3: Step-by-step goal extraction")
    header = "theorem test3 (a b : Nat) (ha : a > 0) (hb : b > 0) : a + b > 0 := by"
    r0 = v.get_goal_at_sorry(header, [])
    print(f"  Initial goals: {r0.goals}")
    assert len(r0.goals) > 0

    r1 = v.get_goal_at_sorry(header, ["omega"])
    print(f"  After 'omega': complete={r1.complete}, goals={r1.goals}")

    # Test 4: Multi-step proof with goal tracking
    print("\nTest 4: Multi-step with goal tracking")
    header = "theorem test4 (p q : Prop) (hp : p) (hq : q) : p ∧ q := by"
    r0 = v.get_goal_at_sorry(header, [])
    print(f"  Initial goals: {r0.goals}")

    r1 = v.get_goal_at_sorry(header, ["constructor"])
    print(f"  After 'constructor': goals={r1.goals}")

    r2 = v.get_goal_at_sorry(header, ["constructor", "exact hp"])
    print(f"  After 'exact hp': goals={r2.goals}")

    r3 = v.verify_tactic_sequence(header, ["constructor", "exact hp", "exact hq"])
    print(f"  Full proof: complete={r3.complete}")
    assert r3.complete

    # Test 5: Error detection
    print("\nTest 5: Error detection")
    r = v.verify("theorem test5 : 1 + 1 = 3 := by omega")
    print(f"  pass={r.success}, errors={len(r.errors)}")
    assert not r.success

    # Test 6: Check tactic progress
    print("\nTest 6: Tactic progress detection")
    header = "theorem test6 (n : Nat) : n + 0 = n := by"
    progress, result = v.check_tactic_progress(header, [], "simp")
    print(f"  'simp' makes progress: {progress}, complete: {result.complete}")

    v.stop()
    print("\nVerifier: ALL TESTS PASSED\n")


if __name__ == "__main__":
    test_dataset_loader()
    test_verifier()
    print("=== All component tests passed! ===")
