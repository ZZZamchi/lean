"""
Lean 4 REPL verifier with support for:
- Whole-proof verification
- Step-by-step tactic verification with goal state extraction
- Partial proof assessment (sorry counting, goal extraction)
"""
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

import pexpect

from .config import VerifierConfig


@dataclass
class VerifyResult:
    success: bool = False
    complete: bool = False
    errors: list[dict] = field(default_factory=list)
    sorries: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    env: Optional[int] = None
    code: str = ""
    elapsed: float = 0.0
    system_error: Optional[str] = None


class LeanVerifier:
    """
    Manages a Lean 4 REPL process for proof verification.

    Key capability: step-by-step verification.
    1. Send theorem header + partial proof ending with `sorry`
    2. REPL returns goal states at each sorry position
    3. Use these goals to guide next tactic generation
    """

    def __init__(self, config: Optional[VerifierConfig] = None):
        self.config = config or VerifierConfig()
        self._child: Optional[pexpect.spawn] = None
        self._base_env: Optional[int] = None
        self._proofs_since_recycle = 0
        self._lean_path: Optional[str] = None

    def start(self):
        self._lean_path = self._get_lean_path()
        self._child, init_resp = self._spawn_repl()
        if init_resp and "env" in init_resp:
            self._base_env = init_resp["env"]
        else:
            self._base_env = 0
        self._proofs_since_recycle = 0

    def stop(self):
        if self._child and self._child.isalive():
            try:
                pid = self._child.pid
                if pid:
                    os.killpg(os.getpgid(pid), 9)
            except Exception:
                pass
            try:
                self._child.close(force=True)
            except Exception:
                pass
        self._child = None

    def _get_lean_path(self) -> str:
        home = os.path.expanduser("~")
        lake = os.path.join(home, ".elan", "bin", "lake")
        if not os.path.isfile(lake):
            lake = "lake"
        cwd = os.path.join(os.getcwd(), self.config.mathlib_path)
        if not os.path.isdir(cwd):
            cwd = os.path.join(os.path.dirname(__file__), "..", self.config.mathlib_path)
        result = subprocess.run(
            [lake, "env", "sh", "-c", 'echo "$LEAN_PATH"'],
            capture_output=True, text=True, cwd=cwd, timeout=60,
        )
        path = (result.stdout or "").strip()
        if result.returncode == 0 and path:
            return path
        raise RuntimeError(f"Cannot get LEAN_PATH from {cwd}: {result.stderr[:500]}")

    def _spawn_repl(self):
        home = os.path.expanduser("~")
        lake = os.path.join(home, ".elan", "bin", "lake")
        if not os.path.isfile(lake):
            lake = "lake"
        cwd = os.path.join(os.getcwd(), self.config.mathlib_path)
        if not os.path.isdir(cwd):
            cwd = os.path.join(os.path.dirname(__file__), "..", self.config.mathlib_path)
        spawn_env = {**os.environ}
        if self._lean_path:
            spawn_env["LEAN_PATH"] = self._lean_path
        child = pexpect.spawn(
            "/bin/bash",
            cwd=cwd,
            encoding="utf-8",
            maxread=1_000_000,
            echo=False,
            env=spawn_env,
        )
        child.sendline("stty -icanon")
        child.sendline(f"cd {cwd}")
        if self._lean_path:
            cmd = f"env LEAN_PATH={repr(self._lean_path)} {lake} exe repl"
        else:
            cmd = f"{lake} exe repl"
        child.sendline(cmd)
        resp = self._send_and_wait(child, self.config.imports, timeout=self.config.import_timeout)
        return child, resp

    def _recycle_if_needed(self):
        if self._proofs_since_recycle >= self.config.repl_recycle_after:
            self.stop()
            self.start()

    def _send_and_wait(self, child, command: str, env=None, timeout=None) -> Optional[dict]:
        timeout = timeout or self.config.timeout
        cmd_dict = {"cmd": command}
        if env is not None:
            cmd_dict["env"] = env
        child.sendline(json.dumps(cmd_dict))
        child.sendline("")

        try:
            child.expect(["\r\n\r\n", "\n\n"], timeout=timeout)
        except (pexpect.TIMEOUT, pexpect.EOF):
            self._kill_child(child)
            raise

        block = child.before.strip()
        brace = block.find("{")
        if brace >= 0:
            block = block[brace:]
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _kill_child(child):
        """Force-kill a pexpect child and its entire process group."""
        try:
            os.killpg(os.getpgid(child.pid), 9)
        except Exception:
            pass
        try:
            child.close(force=True)
        except Exception:
            pass

    def verify(self, code: str, env: Optional[int] = None) -> VerifyResult:
        """Verify a complete proof or partial proof (with sorry)."""
        if self._child is None or not self._child.isalive():
            self.start()
        self._recycle_if_needed()

        use_env = env if env is not None else self._base_env
        t0 = time.time()

        try:
            result = self._send_and_wait(self._child, "\n" + code, env=use_env)
        except (pexpect.TIMEOUT, pexpect.EOF) as e:
            self._child = None
            try:
                self.start()
            except Exception:
                pass
            return VerifyResult(
                code=code, elapsed=time.time() - t0,
                system_error=f"REPL timeout after {self.config.timeout}s"
            )
        except Exception as e:
            return VerifyResult(
                code=code, elapsed=time.time() - t0,
                system_error=str(e)
            )

        self._proofs_since_recycle += 1

        if result is None:
            return VerifyResult(
                code=code, elapsed=time.time() - t0,
                system_error="REPL returned unparseable output"
            )

        errors = [m for m in result.get("messages", []) if m.get("severity") == "error"]
        warnings = [m for m in result.get("messages", []) if m.get("severity") == "warning"]
        sorries = result.get("sorries", [])

        is_pass = len(errors) == 0
        is_complete = (
            is_pass and not sorries
            and not any(
                "declaration uses 'sorry'" in w.get("data", "") or "failed" in w.get("data", "")
                for w in warnings
            )
        )

        goals = []
        for s in sorries:
            goal_str = s.get("goal", "")
            if goal_str:
                goals.append(goal_str)

        return VerifyResult(
            success=is_pass,
            complete=is_complete,
            errors=errors,
            sorries=sorries,
            warnings=warnings,
            goals=goals,
            env=result.get("env"),
            code=code,
            elapsed=time.time() - t0,
        )

    def get_goal_at_sorry(self, theorem_header: str, tactics_so_far: list[str]) -> VerifyResult:
        """
        Core capability for stepwise proving:
        Given a theorem header and a list of tactics applied so far,
        construct a partial proof ending with `sorry` and return the goal state.
        """
        if tactics_so_far:
            tactic_block = "\n  ".join(tactics_so_far)
            code = f"{theorem_header}\n  {tactic_block}\n  sorry"
        else:
            code = f"{theorem_header}\n  sorry"
        return self.verify(code)

    def verify_tactic_sequence(self, theorem_header: str, tactics: list[str]) -> VerifyResult:
        """Verify a complete tactic sequence (no sorry)."""
        tactic_block = "\n  ".join(tactics)
        code = f"{theorem_header}\n  {tactic_block}"
        return self.verify(code)

    def check_tactic_progress(
        self, theorem_header: str,
        existing_tactics: list[str],
        new_tactic: str
    ) -> tuple[bool, VerifyResult]:
        """
        Check if adding `new_tactic` after `existing_tactics` makes progress.
        Returns (makes_progress, result_after_adding).
        "Progress" = fewer goals or different goals than before.
        """
        before = self.get_goal_at_sorry(theorem_header, existing_tactics)

        full_check = self.verify_tactic_sequence(
            theorem_header, existing_tactics + [new_tactic]
        )
        if full_check.complete:
            return True, full_check

        after = self.get_goal_at_sorry(theorem_header, existing_tactics + [new_tactic])

        if after.system_error or not after.success:
            return False, after

        if not after.goals and after.success:
            return True, full_check

        if len(after.goals) < len(before.goals):
            return True, after
        if set(after.goals) != set(before.goals):
            return True, after

        return False, after
