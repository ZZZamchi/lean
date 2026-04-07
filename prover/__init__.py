"""
General-purpose mathematical reasoning framework for Lean 4.
Supports multiple proof strategies, step-by-step search with compiler feedback,
and unified evaluation across benchmarks (miniF2F, Putnam, FATE, ProofNet).
"""
from .config import ProverConfig
from .engine import ProofSearchEngine
