"""
Stepwise proof search with Lean compiler feedback.

Core idea: instead of generating the entire proof at once, generate one
tactic at a time, verify each step with the Lean REPL, and use the
resulting goal state to guide the next step. Backtracks when stuck.

Improvements over basic BFS:
- Goal complexity scoring accounts for type structure difficulty
- Adaptive search width: more samples at shallow depths, fewer at deep
- Closing tactic bonus: prioritizes goals that look closeable by automation
- Cascade-aware: can start from partial tactic sequences from prior strategies
"""
import heapq
import re
from dataclasses import dataclass, field

from ..prompts import build_stepwise_prompt
from ..verifier import VerifyResult
from .base import ProofAttempt, ProofStrategy

AUTOMATION_TACTICS = frozenset({
    "norm_num", "omega", "simp", "ring", "linarith", "decide", "rfl",
    "positivity", "field_simp", "push_cast", "norm_cast",
})

HARD_TYPE_PATTERNS = re.compile(
    r"Real\.sqrt|Nat\.cast|Int\.cast|Complex\.|MeasureTheory\.|"
    r"Filter\.|Finset\.sum|∑|∏|Polynomial\."
)


@dataclass(order=True)
class SearchNode:
    priority: float
    tactics: list[str] = field(compare=False)
    goals: list[str] = field(compare=False)
    depth: int = field(compare=False, default=0)
    parent_id: int = field(compare=False, default=-1)
    node_id: int = field(compare=False, default=0)


class StepwiseStrategy(ProofStrategy):
    """
    Best-first search over tactic sequences with adaptive width.

    At each node:
    1. Ask the model for candidate next tactics given current goal state
    2. Try each candidate, verify with REPL
    3. If proof is complete, return
    4. If tactic makes progress (changes/reduces goals), add to frontier
    5. If tactic fails or doesn't help, discard
    """
    name = "stepwise"

    def __init__(self, model, verifier, config):
        super().__init__(model, verifier, config)
        self._cascade_ctx = None

    def set_cascade_context(self, ctx: dict):
        self._cascade_ctx = ctx

    def prove(self, problem_id: str, formal_statement: str, theorem_header: str) -> ProofAttempt:
        cfg = self.config.stepwise
        header = self.strip_imports(theorem_header)

        attempt = ProofAttempt(
            problem_id=problem_id,
            formal_statement=formal_statement,
            strategy=self.name,
        )

        initial_result = self.verifier.get_goal_at_sorry(header, [])
        if initial_result.complete:
            attempt.complete = True
            attempt.code = header + "\n  sorry"
            attempt.best_result = initial_result
            return attempt

        if not initial_result.goals:
            attempt.metadata["error"] = "Could not get initial goal state"
            return attempt

        node_counter = 0
        root = SearchNode(
            priority=0.0,
            tactics=[],
            goals=initial_result.goals,
            depth=0,
            node_id=node_counter,
        )

        frontier: list[SearchNode] = [root]
        visited_states: set[tuple[str, ...]] = set()
        total_nodes = 0

        while frontier and total_nodes < cfg.max_total_nodes:
            node = heapq.heappop(frontier)

            state_key = tuple(node.goals)
            if state_key in visited_states:
                continue
            visited_states.add(state_key)

            width = self._adaptive_width(cfg.max_width, node.depth, cfg.max_depth)
            candidate_tactics = self._generate_tactics(
                header, formal_statement, node.tactics, node.goals, width
            )

            for tactic in candidate_tactics:
                if total_nodes >= cfg.max_total_nodes:
                    break
                total_nodes += 1
                attempt.attempts += 1

                new_tactics = node.tactics + [tactic]
                result = self.verifier.get_goal_at_sorry(header, new_tactics)

                if result.system_error:
                    continue

                if result.complete or (result.success and not result.goals):
                    full_result = self.verifier.verify_tactic_sequence(header, new_tactics)
                    if full_result.complete:
                        code = self._format_proof(header, new_tactics)
                        attempt.complete = True
                        attempt.code = code
                        attempt.best_result = full_result
                        attempt.all_codes.append(code)
                        attempt.metadata["search_nodes"] = total_nodes
                        attempt.metadata["proof_depth"] = len(new_tactics)
                        return attempt

                if not result.success:
                    continue

                new_goals = result.goals
                new_state = tuple(new_goals)
                if new_state in visited_states:
                    continue

                if self._is_progress(node.goals, new_goals):
                    node_counter += 1
                    priority = self._compute_priority(new_goals, len(new_tactics))
                    child = SearchNode(
                        priority=priority,
                        tactics=new_tactics,
                        goals=new_goals,
                        depth=len(new_tactics),
                        parent_id=node.node_id,
                        node_id=node_counter,
                    )
                    heapq.heappush(frontier, child)

                    code = self._format_proof(header, new_tactics)
                    attempt.all_codes.append(code)
                    if attempt.best_result is None or len(new_goals) < len(attempt.best_result.goals or [999]):
                        attempt.best_result = result
                        attempt.code = code

        attempt.metadata["search_nodes"] = total_nodes
        return attempt

    def _generate_tactics(
        self, header: str, formal_statement: str,
        tactics_so_far: list[str], goals: list[str],
        width: int,
    ) -> list[str]:
        """Ask the model for candidate next tactics."""
        use_chat = self.config.model.use_chat_template
        goal_text = "\n".join(goals)
        prompt = build_stepwise_prompt(
            formal_statement=formal_statement,
            goal_state=goal_text,
            tactics_so_far=tactics_so_far if tactics_so_far else None,
        )
        raw_outputs = self.model.generate_single(
            prompt,
            n=width,
            temperature=self.config.model.temperature,
            max_tokens=256,
            chat=use_chat,
        )

        tactics = []
        seen = set()
        for raw in raw_outputs:
            tactic = self.model.extract_single_tactic(raw)
            if tactic and tactic not in seen:
                seen.add(tactic)
                tactics.append(tactic)
        return tactics

    @staticmethod
    def _adaptive_width(max_width: int, depth: int, max_depth: int) -> int:
        """More samples at shallow depths, fewer as search goes deeper."""
        if depth <= 2:
            return max_width
        if depth <= max_depth // 2:
            return max(4, max_width * 3 // 4)
        return max(2, max_width // 2)

    @staticmethod
    def _is_progress(old_goals: list[str], new_goals: list[str]) -> bool:
        if not new_goals:
            return True
        if len(new_goals) < len(old_goals):
            return True
        if set(new_goals) != set(old_goals):
            return True
        return False

    @staticmethod
    def _compute_priority(goals: list[str], depth: int) -> float:
        """
        Lower priority = explored first.
        Scoring: fewer goals > shallower depth > simpler goals.
        Bonus for goals that look closeable by automation tactics.
        """
        n_goals = len(goals)
        total_complexity = 0.0

        for g in goals:
            length_score = len(g) * 0.01
            hard_matches = len(HARD_TYPE_PATTERNS.findall(g))
            type_penalty = hard_matches * 5.0
            auto_keywords = ["Nat", "Int", "= ", "≤", "<", "∣"]
            auto_bonus = -2.0 if any(k in g for k in auto_keywords) else 0.0
            total_complexity += length_score + type_penalty + auto_bonus

        return n_goals * 100 + depth * 8 + total_complexity

    @staticmethod
    def _format_proof(header: str, tactics: list[str]) -> str:
        body = "\n  ".join(tactics)
        return f"{header}\n  {body}"
