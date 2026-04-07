"""
Base class for proof strategies.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..config import ProverConfig
from ..model import ProverModel
from ..verifier import LeanVerifier, VerifyResult


@dataclass
class ProofAttempt:
    problem_id: str = ""
    formal_statement: str = ""
    code: str = ""
    complete: bool = False
    strategy: str = ""
    attempts: int = 0
    best_result: Optional[VerifyResult] = None
    all_codes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ProofStrategy(ABC):
    """Base class for a proof generation strategy."""

    name: str = "base"

    def __init__(self, model: ProverModel, verifier: LeanVerifier, config: ProverConfig):
        self.model = model
        self.verifier = verifier
        self.config = config

    @abstractmethod
    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        """
        Attempt to prove the given theorem.

        Args:
            problem_id: Unique identifier for the problem
            formal_statement: The full Lean 4 code with `:= by sorry`
            theorem_header: Just the `theorem ... := by` part (no sorry)

        Returns:
            ProofAttempt with the best proof found
        """
        ...

    @staticmethod
    def extract_theorem_header(lean4_code: str) -> str:
        """Extract `theorem ... := by` from full code."""
        parts = lean4_code.split(":= by")
        if len(parts) >= 2:
            return parts[0].strip() + " := by"
        return lean4_code

    @staticmethod
    def strip_imports(code: str) -> str:
        """Remove import/set_option/open lines (REPL provides env)."""
        lines = code.splitlines()
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("set_option ") or stripped.startswith("open "):
                continue
            result.append(line)
        return "\n".join(result).strip()
