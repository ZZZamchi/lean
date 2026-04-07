from .base import ProofStrategy, ProofAttempt
from .whole_proof import WholeProofStrategy
from .stepwise import StepwiseStrategy
from .refinement import RefinementStrategy
from .near_miss import NearMissStrategy

STRATEGY_REGISTRY: dict[str, type[ProofStrategy]] = {
    "whole_proof": WholeProofStrategy,
    "stepwise": StepwiseStrategy,
    "refinement": RefinementStrategy,
    "near_miss": NearMissStrategy,
}
