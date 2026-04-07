import os
import signal
import sys
import time
import json
import ctypes
import resource
import tempfile
import traceback
import threading
import pexpect
import subprocess
import multiprocessing as mp
from pprint import pprint
# from memory_profiler import profile

import re
import random

import numpy as np

def split_list_randomly(lst, k):
    random.shuffle(lst)  # Shuffle the list randomly
    return list(map(list, np.array_split(lst, k)))  # Split into k approximately equal parts


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


sys.path.append(os.path.abspath(os.path.join(CURRENT_DIR, "../../")))


IMPORT_TIMEOUT = int(os.environ.get("IMPORT_TIMEOUT", "180"))
# PROOF_TIMEOUT = 120
PROOF_TIMEOUT = int(os.environ.get("PROOF_TIMEOUT", 300))
# send_command_and_wait 在 pexpect 上多等的秒数；超时后杀进程树并 close(force) 以解除 expect 阻塞（默认 8，原 20 易掩盖未 close 导致的假死）
REPL_WATCHDOG_GRACE_SEC = int(os.environ.get("REPL_WATCHDOG_GRACE_SEC", "8"))
# 每处理多少条证明后重启 REPL，以限制单进程内存增长；0 表示不主动回收
# 典型每进程每条约 6–7 MB，80 条约 0.5 GB 额外/进程；150 约 1 GB。建议 80–100 更稳。
REPL_RECYCLE_AFTER = int(os.environ.get("REPL_RECYCLE_AFTER", "80"))
# 回收/重启后是否额外等待再起新 REPL（0=不等待，依赖 REPL 正常退出释放；需时可设 1–5）
REPL_RECYCLE_SLEEP_AFTER_KILL = int(os.environ.get("REPL_RECYCLE_SLEEP_AFTER_KILL", "0"))

HOME_DIR = os.path.expanduser('~')

DEFAULT_LAKE_PATH = f'{HOME_DIR}/.elan/bin/lake'

# 项目根（Zam）上一级目录；spawn 时用绝对路径避免相对 cwd 歧义
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ZAM_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
DEFAULT_LEAN_WORKSPACE = os.environ.get("LEAN_WORKSPACE", os.path.join(_ZAM_ROOT, "mathlib4"))
# 与官方 Goedel-Prover-V2 一致（init + env=0 增量编译）
# maxHeartbeats：0=不限制。设为正数可限制单证明内 tactic 步数，减轻 Aesop/递归搜索导致的内存暴增（见下方注释）。
_REPL_MAX_HEARTBEATS = int(os.environ.get("REPL_MAX_HEARTBEATS", "0"))
# 单 REPL 进程虚拟内存上限（GB），超过则进程被系统终止；0=不限制。用于将单证明 >30GB 的异常证明终止并跳过。
REPL_MAX_MEM_GB = int(os.environ.get("REPL_MAX_MEM_GB", "30"))
# pexpect 每次从 PTY 读取的字节数。maxread=1 时若 REPL 返回较大 JSON，逐字节读可能极慢，
# 在 IMPORT_TIMEOUT 内仍看不到结尾的 \n\n，表现为「init 永远超时」（mathlib 已预编也如此）。
REPL_PEXPECT_MAXREAD = int(os.environ.get("REPL_PEXPECT_MAXREAD", "8192"))

def _default_imports():
    hb = "set_option maxHeartbeats 0" if _REPL_MAX_HEARTBEATS <= 0 else f"set_option maxHeartbeats {_REPL_MAX_HEARTBEATS}"
    return f"import Mathlib\nimport Aesop\n\n{hb}\n\nopen BigOperators Real Nat Topology Rat\n\n"

DEFAULT_IMPORTS = _default_imports()

# 异常证明内存暴增可能原因（本地单文件能正常显示时，REPL 批量编译仍可能 OOM）：
# 1) REPL 使用 env=0 增量编译，同一进程内会累积多条证明的上下文，长证明的项树和类型推导会占大量内存。
# 2) set_option maxHeartbeats 0 使单条证明内 tactic 无步数上限，linarith/nlinarith/interval_cases 等可能在某些情况下展开极大搜索空间。
# 3) 已 import Aesop：即使用户证明未显式写 aesop，Mathlib 或其它库在证明中可能调用 Aesop，其递归搜索在复杂目标下可能指数膨胀。
# 4) 多 worker 并行时，若多条“问题证明”同时编译，总内存 = 单进程内存 × worker 数，易触发 OOM。
# 缓解：将异常题加入 results/abnormal_problems.json 由 compile 跳过；或设 REPL_MAX_HEARTBEATS>0（如 500000）让 Lean 在超时前抛出 heartbeat 异常而非占满内存。


statement_sample = "\n/-- Show that $\frac{9x^2\\sin^2 x + 4}{x\\sin x} \\geq 12$ for $0 < x < \\pi$.-/\ntheorem aime_1983_p9 (x : ℝ) (h₀ : 0 < x ∧ x < Real.pi) :\n  12 ≤ (9 * (x ^ 2 * Real.sin x ^ 2) + 4) / (x * Real.sin x) :="

proof_code_sample_1 = " by\n  /-\n  To find the minimum value of $\frac{9x^2\\sin^2 x + 4}{x\\sin x}$ for $0 < x < \\pi$, we need to show that it is at least 12. We start by noting that the expression can be rewritten using the division property of inequalities. We then use the fact that \\$sin x$ and $x$ are positive in the given range to establish the necessary inequalities. Finally, we apply these results to conclude that the minimum value is indeed 12.\n  -/\n  -- We start by ensuring that the product x * sin x is positive in the given range.\n  have h₁ : 0 < x * Real.sin x := by\n    apply mul_pos\n    -- x is positive in the range (0, π).\n    exact h₀.1\n    -- sin x is positive in the range (0, π).\n    exact Real.sin_pos_of_pos_of_lt_pi h₀.1 h₀.2\n  -- Using the division property of inequalities, we rewrite the expression.\n  rw [le_div_iff h₁]\n  /- tactic state:\n    x : ℝ\n    h₀ : 0 < x ∧ x < π\n    h₁ : 0 < x * x.sin\n    ⊢ 12 * (x * x.sin) ≤ 9 * (x ^ 2 * x.sin ^ 2) + 4\n  -/\n  -- This is equivalent to showing that 9x^2 sin^2 x - 12x sin x + 4 ≥ 0, and the left hand side can be rewritten as a perfect square (3x sin x - 2)^2.\n  -- We use the fact that (3x sin x - 2)^2 is non-negative to establish this.\n  nlinarith [sq_nonneg (3 * x * Real.sin x - 2)]\n"

proof_code_sample_2 = " by sorry"

proof_code_sample_3 = "\n/-- For a series $\\{a_n\\}$, we have $\\sum_{n=0}^{99} a_{n+1}^2 = 1$. Show that $\\sum_{n=0}^{98} (a_{n+1}^2 a_{n+2}) + a_{100}^2 * a_1 < \\frac{12}{25}$.-/\ntheorem imosl_2007_algebra_p6 (a : \u2115 \u2192 NNReal) (h\u2080 : (\u2211 x in Finset.range 100, a (x + 1) ^ 2) = 1) :\n    (\u2211 x in Finset.range 99, a (x + 1) ^ 2 * a (x + 2)) + a 100 ^ 2 * a 1 < 12 / 25 := by\n  /-\n  Given a series \\(\\{a_n\\}\\), we know that \\(\\sum_{n=0}^{99} a_{n+1}^2 = 1\\). We need to show that \\(\\sum_{n=0}^{98} (a_{n+1}^2 a_{n+2}) + a_{100}^2 * a_1 < \\frac{12}{25}\\).\n  -/\n  -- Simplify the given sum condition using basic arithmetic properties.\n  simp_all [Finset.sum_range_succ, mul_add, mul_comm, mul_left_comm, mul_assoc, add_assoc,\n    add_left_comm, add_comm]\n  -- Use linear arithmetic to prove the inequality.\n  <;> nlinarith [h\u2080]"

proof_code_sample_4 = "BUG" * 4096

proof_code_sample_5 = DEFAULT_IMPORTS

proof_code_sample_nonneg="\n/-- Suppose $a, b, c$ are the sides of a triangle. Prove that \n\n$a^2(b+c-a)+b^2(c+a-b)+c^2(a+b-c)\\le{3abc}.$-/\ntheorem imo_1964_p2 (a b c : \u211d) (h\u2080 : 0 < a \u2227 0 < b \u2227 0 < c) (h\u2081 : c < a + b) (h\u2082 : b < a + c)\n    (h\u2083 : a < b + c) :\n    a ^ 2 * (b + c - a) + b ^ 2 * (c + a - b) + c ^ 2 * (a + b - c) \u2264 3 * a * b * c := by\n  /-\n  To prove the inequality \\(a^2(b+c-a) + b^2(c+a-b) + c^2(a+b-c) \\leq 3abc\\) for the sides \\(a, b, c\\) of a triangle, we can use the non-negativity of squares and some algebraic manipulations. Specifically, we will use the fact that the square of any real number is non-negative, and then apply these properties to the differences \\(a - b\\), \\(b - c\\), and \\(c - a\\). By leveraging these non-negative terms, we can derive the desired inequality.\n  -/\n  -- Use the non-negativity of squares to derive the inequality.\n  -- Specifically, we use the fact that the square of any real number is non-negative.\n  nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a),\n    sq_nonneg (a + b - c), sq_nonneg (b + c - a), sq_nonneg (c + a - b)]"

# proof_code_list_sample = [proof_code_sample] * 1
# proof_code_list_sample = [statement_sample + proof_code_sample_1, statement_sample + proof_code_sample_2] * 2

# proof_code_list_sample = ([{"name": "test_problem", "code": statement_sample + proof_code_sample_1}] + [{"name": "test_problem", "code": statement_sample + proof_code_sample_2}]) * 1

# proof_code_list_sample = [{"name": "test_problem", "code": statement_sample + proof_code_sample_1}] * 1

proof_code_list_sample = [{"name": "nonneg_problem", "code": statement_sample + proof_code_sample_2}]


# proof_code_list_sample.append({'name': 'timeout_problem', 'code': proof_code_sample_3})
# proof_code_list_sample.append({'name': 'timeout_problem', 'code': proof_code_sample_5})

problem_list_sample = [proof_code_list_sample] * 64 #each item in problem_list_sample is a proof_code_list which I want a single process to do

def _normalize_duplicate_theorem_assign(proof_code: str) -> str:
    """修复模型输出中「类型行末多余 := 且下一行 := by」导致的 unexpected token ':='。
    正确 Lean4 为 theorem name : type := proof；模型常写成类型行末 := 换行后 := by，此处去掉行末多余 :=。"""
    if not proof_code or ":=" not in proof_code:
        return proof_code
    return re.sub(r":=\s*\n(\s*:=)", r"\n\1", proof_code)


def _split_putnam_abbrev_theorem(proof_code: str):
    """Putnam 题目为 abbrev + theorem 两条声明；单块送 REPL 会报 unexpected 'theorem'。
    若代码为「先 abbrev 再 theorem」则拆成 (part1, part2)，否则返回 None。"""
    if not proof_code or "abbrev" not in proof_code or "theorem" not in proof_code:
        return None
    m = re.search(r"\n\s*theorem\s+", proof_code)
    if not m:
        return None
    before = proof_code[: m.start()].strip()
    if "abbrev" not in before:
        return None
    part2 = proof_code[m.start() :].strip()
    if not before or not part2:
        return None
    # abbrev 若仅有 "abbrev name : Type :=" 无右端，Lean 会报 unexpected end of input
    before_stripped = before.rstrip()
    if before_stripped.endswith(":=") and not before[before_stripped.rfind(":=") + 2 :].strip():
        before = before_stripped + " sorry"
    return (before, part2)


def send_command_and_wait(child, command, allTactics=False, ast=False, premises=False, tactics=False, env=None, timeout=PROOF_TIMEOUT, imports=DEFAULT_IMPORTS):
    """
    Send a JSON command to the Lean REPL and wait for the output.
    The REPL output is expected to be a JSON dict (possibly spanning multiple lines)
    ending with a double newline.
    """
    # Build the JSON command
    if env is None:
        json_cmd = json.dumps({"cmd": command})
    else:
        json_cmd = json.dumps({"cmd": command, "allTactics" : allTactics, "ast":ast, "premises" : premises, "tactics" : tactics, "env": env})

    child.sendline(json_cmd)
    child.sendline("")  # This sends the extra newline.

    code = imports + command
    done = [False]
    watchdog_killed = [False]

    def _close_pexpect_force(ch):
        """关闭 pexpect 的 PTY，使卡在 expect() 里的主线程能返回；仅杀进程有时不足以唤醒阻塞的 read。"""
        try:
            ch.close(force=True)
        except Exception:
            pass

    def _watchdog():
        time.sleep(timeout + REPL_WATCHDOG_GRACE_SEC)
        if done[0]:
            return
        watchdog_killed[0] = True
        try:
            if child.pid is not None:
                _kill_process_group(child.pid)
        except Exception:
            pass
        _close_pexpect_force(child)

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    try:
        # Wait for the output delimiter (double newline)
        # expect 返回后必须立刻标记 done，否则 watchdog 可能在解析 JSON 前 close(force)，下一条 send 会 Bad file descriptor
        try:
            child.expect(["\r\n\r\n", "\n\n"], timeout=timeout)
        finally:
            done[0] = True
        # pexpect.before contains everything up to the matched delimiter.
        response = child.before.strip()

        block = response
        # lake 构建输出会出现在 REPL JSON 前，只解析从第一个 '{' 起的 JSON
        brace = block.find("{")
        if brace >= 0:
            block = block[brace:]

        try:
            result = json.loads(block)
            # ast_results = lean4_parser(command, result['ast']) if 'ast' in result and result['ast'] else {}
            ast_results = {}
            parsed_result = {
                "sorries": result.get("sorries", []),
                "tactics": result.get("tactics", []),
                "errors": [m for m in result.get("messages", []) if m.get("severity") == "error"],
                "warnings": [m for m in result.get("messages", []) if m.get("severity") == "warning"],
                "infos": [m for m in result.get("messages", []) if m.get("severity") == "info"],
                "ast" : ast_results,
                # "verified_code": code,
                # "problem_id": problem_id
                "system_errors": None
            }
            parsed_result["pass"] = not parsed_result["errors"]
            parsed_result["complete"] = (
                parsed_result["pass"]
                and not parsed_result["sorries"]
                and not any(
                    "declaration uses 'sorry'" in warning["data"] or "failed" in warning["data"]
                    for warning in parsed_result["warnings"]
                )
            )

            response = {"code": command, "compilation_result": parsed_result}
            if "env" in result:
                response["env"] = result["env"]

        except json.JSONDecodeError as e:
            if os.environ.get("REPL_DEBUG_JSON"):
                try:
                    with open("/tmp/repl_json_decode_error.txt", "a", encoding="utf-8") as f:
                        f.write(f"block repr: {repr(block)[:2000]}\n---\n")
                except Exception:
                    pass
            parsed_result = {
                "pass": False,
                "complete": False,
                "system_errors": f"JSONDECODE ERROR: {e}"
            }
            response = {"code": command, "compilation_result": parsed_result}

    except pexpect.TIMEOUT as e:
        # expect 若超时，内层 finally 已置 done；此处兜底
        done[0] = True
        # 杀整棵进程树（bash→lake→lean），避免只杀 bash 导致 lean 成孤儿继续占内存
        try:
            if getattr(child, "pid", None) is not None:
                _kill_process_group(child.pid)
        except Exception:
            pass
        _close_pexpect_force(child)
        response = {"code": command, "compilation_result": {"pass": False, "complete": False, "system_errors": f"TIMEOUT ERROR: {e}"}}
    except pexpect.EOF as e:
        done[0] = True
        err = f"WATCHDOG KILL (REPL hung)" if watchdog_killed[0] else f"EOF ERROR: {e}"
        response = {"code": command, "compilation_result": {"pass": False, "complete": False, "system_errors": err}}
    except Exception as e:  # Catch any other unexpected errors
        done[0] = True
        err = f"WATCHDOG KILL (REPL hung)" if watchdog_killed[0] else f"UNEXPECTED ERROR: {e}"
        response = {"code": command, "compilation_result": {"pass": False, "complete": False, "system_errors": err}}
    finally:
        done[0] = True
    return response


def _get_lean_path_for_repl():
    """获取 mathlib4 下 lake 的 LEAN_PATH，供 spawn 传入以便 REPL 能解析 import Mathlib。"""
    try:
        r = subprocess.run(
            [DEFAULT_LAKE_PATH, "env", "sh", "-c", "echo \"$LEAN_PATH\""],
            cwd=DEFAULT_LEAN_WORKSPACE,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


def _problem_base(pid):
    """amc12a_2020_p4_g0 -> amc12a_2020_p4，用于 OOM 异常记录。"""
    if not pid:
        return ""
    import re
    return re.sub(r"_g\d+$", "", str(pid))


def initiate_child(imports=DEFAULT_IMPORTS):
    """启动 REPL，发送 init 后返回。若设 LEAN_PATH 且 REPL Frontend 已支持，可正确加载 Mathlib。REPL_MAX_MEM_GB>0 时对 REPL 进程设虚拟内存上限（GB），超限进程被终止并视为异常证明。"""
    last_err = None
    for _attempt in range(3):
        spawn_env = {**os.environ}
        lean_path = _get_lean_path_for_repl()
        if lean_path:
            spawn_env["LEAN_PATH"] = lean_path
        child = pexpect.spawn(
            "/bin/bash",
            cwd=DEFAULT_LEAN_WORKSPACE,
            encoding="utf-8",
            maxread=REPL_PEXPECT_MAXREAD,
            echo=False,
            env=spawn_env,
        )
        child.sendline("stty -icanon")
        child.sendline(f"cd {DEFAULT_LEAN_WORKSPACE}")
        if lean_path:
            cmd = f"env LEAN_PATH={repr(lean_path)} {DEFAULT_LAKE_PATH} exe repl"
        else:
            cmd = f"{DEFAULT_LAKE_PATH} exe repl"
        if REPL_MAX_MEM_GB > 0:
            # ulimit -v 在 bash 下单位为 KiB（Linux）。必须用 Python 展开数值：若写 $((REPL_MAX_MEM_GB*...))
            # 则 REPL_MAX_MEM_GB 为 shell 变量未导出，算术为 0 → ulimit -v 0，与「30GB 上限」意图不符。
            ulimit_v_kb = REPL_MAX_MEM_GB * 1024 * 1024
            cmd = f"ulimit -v {ulimit_v_kb} && {cmd}"
        child.sendline(cmd)
        response = send_command_and_wait(child, imports, timeout=IMPORT_TIMEOUT)
        se = (response.get("compilation_result") or {}).get("system_errors")
        if se is None:
            return child, response
        last_err = se
        pid = getattr(child, "pid", None)
        _kill_process_group(pid)
        try:
            child.close(force=True)
        except Exception:
            pass
        _wait_pid_gone(pid, max_wait_s=5)
    raise RuntimeError(f"Lean REPL init failed after 3 attempts (last error: {last_err!r})")


def _get_used_gb():
    """当前整机已用内存 (GB)，用于回收时打点；读 /proc/meminfo，失败返回 None。"""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            total = avail = None
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total is not None and avail is not None:
                    return int((total - avail) / 1024 / 1024)
    except Exception:
        pass
    return None


def _wait_pid_gone(pid, max_wait_s=5, check_interval=0.1):
    """等待进程退出，避免旧 REPL 未退出就起新进程导致瞬时双倍进程数。"""
    if pid is None:
        return
    for _ in range(int(max_wait_s / check_interval)):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(check_interval)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    time.sleep(0.5)
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)


def _get_descendant_pids(root_pid):
    """返回 root_pid 及其所有后代 pid 集合（读 /proc，仅 Linux）。"""
    if root_pid is None:
        return set()
    seen = set()
    to_visit = [root_pid]
    while to_visit:
        pid = to_visit.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                try:
                    p = int(name)
                    if p in seen:
                        continue
                    with open("/proc/%s/status" % name, encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("PPid:"):
                                ppid = int(line.split()[1])
                                if ppid == pid:
                                    to_visit.append(p)
                                break
                except (OSError, ValueError):
                    pass
        except OSError:
            pass
    return seen


def _kill_process_group(pid):
    """杀死 pid 及其整棵子进程树（bash→lake→lean），确保 REPL 完全退出并释放内存。先递归杀子孙再杀自身。"""
    if pid is None:
        return
    my_pid = os.getpid()
    pids = _get_descendant_pids(pid)
    for p in pids:
        if p == pid or p == my_pid:
            continue
        try:
            os.kill(p, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        pgid = os.getpgid(pid)
        if pgid != my_pid and pgid != pid:
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _recycle_repl(child, worker_id, imports, proofs_since_repl=0):
    """关闭当前 REPL 并启动新进程，释放 Lean 进程内累积内存。杀树后等 root 退出即可，REPL 正常退出会释放内存。"""
    pid = getattr(child, "pid", None)
    _kill_process_group(pid)
    try:
        child.close()
    except Exception:
        try:
            child.terminate(force=True)
        except Exception:
            pass
    _wait_pid_gone(pid, max_wait_s=5)
    if REPL_RECYCLE_SLEEP_AFTER_KILL > 0:
        time.sleep(REPL_RECYCLE_SLEEP_AFTER_KILL)
    child, init_resp = initiate_child(imports=imports)
    print(f"Worker {worker_id}: REPL recycled (proofs_since_repl={proofs_since_repl}).", flush=True)
    return child


# 任务队列结束哨兵：每个 worker 取到一次后退出。禁止用 Queue.empty() 判断剩余任务（多进程下不可靠）。
_TASK_SENTINEL = None


def worker(worker_id, task_queue, result_list, total_restarts, lock, allTactics=False, ast=False, premises=False, tactics=False, timeout=PROOF_TIMEOUT, imports=DEFAULT_IMPORTS, result_queue=None, progress_count=None, oom_list=None):
    """Worker：init 后每条证明用 env=0 发送；每 REPL_RECYCLE_AFTER 条主动重启 REPL 以限制内存增长。"""
    child, init_resp = initiate_child(imports=imports)
    print(f"Worker {worker_id} started Lean REPL.", flush=True)
    start_time = time.time()
    proofs_since_repl = 0  # 当前 REPL 实例已处理的证明数，用于定期回收

    while True:
        # 定期回收：每处理 REPL_RECYCLE_AFTER 条后重启 REPL 释放内存（REPL_RECYCLE_AFTER<=0 不回收）
        if REPL_RECYCLE_AFTER > 0 and proofs_since_repl >= REPL_RECYCLE_AFTER:
            child = _recycle_repl(child, worker_id, imports, proofs_since_repl=proofs_since_repl)
            proofs_since_repl = 0

        proof_code_dict = task_queue.get()
        if proof_code_dict is _TASK_SENTINEL:
            break

        proof_code = (proof_code_dict.get("code") or "").strip()
        proof_code = _normalize_duplicate_theorem_assign(proof_code)
        proof_name = proof_code_dict["name"]
        proof_id = proof_code_dict.get("problem_id", proof_name)

        if len(proof_code) == 0:
            response = {"code": proof_code, "compilation_result": {"pass": False, "complete": False, "system_errors": None}}
            response["name"] = proof_name
            response["problem_id"] = proof_code_dict.get("problem_id", proof_name)
            response["verify_time"] = round(time.time() - start_time, 2)
            start_time = time.time()
            proofs_since_repl += 1
            if result_list is not None:
                with lock:
                    result_list.append(response)
            if result_queue is not None and progress_count is not None:
                result_queue.put(response)
                with progress_count.get_lock():
                    progress_count.value += 1
        else:
            # Putnam：abbrev + theorem 分两次提交，先 abbrev 再 theorem（用第一次的 env）
            parts = _split_putnam_abbrev_theorem(proof_code)
            if parts is not None:
                part1, part2 = parts
                cmd1 = "\n" + part1
                resp1 = send_command_and_wait(child, cmd1, env=0, allTactics=allTactics, ast=ast, premises=premises, tactics=tactics, imports=imports, timeout=timeout)
                if not resp1.get("compilation_result", {}).get("pass", False):
                    response = resp1
                    response["code"] = proof_code
                else:
                    env_next = resp1.get("env", 0)
                    cmd2 = "\n" + part2
                    resp2 = send_command_and_wait(child, cmd2, env=env_next, allTactics=allTactics, ast=ast, premises=premises, tactics=tactics, imports=imports, timeout=timeout)
                    response = resp2
                    response["code"] = proof_code
            else:
                # 与 goedel_EXPERIMENT 一致：固定 env=0；前导换行便于 REPL 识别为新声明
                cmd = "\n" + proof_code if proof_code else proof_code
                response = send_command_and_wait(child, cmd, env=0, allTactics=allTactics, ast=ast, premises=premises, tactics=tactics, imports=imports, timeout=timeout)
            response["name"] = proof_name
            response["problem_id"] = proof_id
            response["verify_time"] = round(time.time() - start_time, 2)

            start_time = time.time()
            proofs_since_repl += 1

            if result_list is not None:
                with lock:
                    result_list.append(response)
            if result_queue is not None and progress_count is not None:
                result_queue.put(response)
                with progress_count.get_lock():
                    progress_count.value += 1

            if response["compilation_result"]["system_errors"] is not None:


                with total_restarts.get_lock():  # Ensure atomic update
                    total_restarts.value += 1  # Increment total restart count 

                if "EOF" in response["compilation_result"]["system_errors"]:
                    if oom_list is not None:
                        try:
                            base = _problem_base(proof_id)
                            if base and base not in oom_list:
                                oom_list.append(base)
                                print(f"Worker {worker_id}: OOM/EOF for {proof_id}, added to abnormal list.", flush=True)
                        except Exception:
                            pass
                    previous_id = getattr(child, "pid", None)
                    _kill_process_group(previous_id)
                    try:
                        child.close()
                    except Exception:
                        try:
                            child.terminate(force=True)
                        except Exception:
                            pass
                    _wait_pid_gone(previous_id, max_wait_s=5)
                    if REPL_RECYCLE_SLEEP_AFTER_KILL > 0:
                        time.sleep(REPL_RECYCLE_SLEEP_AFTER_KILL)

                    # 不使用 task_queue.empty()：多进程下常误判为「空」，导致 worker 提前退出、剩余任务无人处理。
                    child, init_resp = initiate_child(imports=imports)
                    proofs_since_repl = 0
                    if init_resp is not None:
                        env = init_resp.get("env", 0)
                else:
                    previous_id = getattr(child, "pid", None)
                    _kill_process_group(previous_id)
                    try:
                        child.close()
                    except Exception:
                        try:
                            child.terminate(force=True)
                        except Exception:
                            pass
                    _wait_pid_gone(previous_id, max_wait_s=5)
                    if REPL_RECYCLE_SLEEP_AFTER_KILL > 0:
                        time.sleep(REPL_RECYCLE_SLEEP_AFTER_KILL)

                    child, init_resp = initiate_child(imports=imports)
                    proofs_since_repl = 0
                    if init_resp is not None:
                        env = init_resp.get("env", 0)

                    # print("restart because of", response["compilation_result"]["system_errors"], previous_id, "replaced with", child.pid, flush = True) 
                    # print("Timemout restart", previous_id, "replaced with", child.pid, flush = True) 


    pid = getattr(child, "pid", None)
    _kill_process_group(pid)
    try:
        child.close()
    except Exception:
        try:
            child.terminate(force=True)
        except Exception:
            pass
    _wait_pid_gone(pid, max_wait_s=5)
    print(f"Worker {worker_id} terminated Lean REPL.", flush = True)
    




def _writer_thread(result_queue, output_stream_path):
    """从 result_queue 取结果并逐行写入 JSONL，收到 None 时结束。"""
    try:
        with open(output_stream_path, "w", encoding="utf-8") as f:
            while True:
                r = result_queue.get()
                if r is None:
                    break
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
    except Exception as e:
        print(f"[writer_thread] failed writing {output_stream_path!r}: {e}", flush=True)
        raise


def scheduler(proofs, num_workers=64, allTactics=False, ast=False, premises=False, tactics=False, timeout=PROOF_TIMEOUT, imports=DEFAULT_IMPORTS, output_stream_path=None, oom_list=None):
    """Scheduler：若 output_stream_path 已设置则流式写 JSONL；oom_list 为 Manager().list() 时收集因 OOM/EOF 终止的证明的 problem_base 供调用方写入异常列表。"""
    task_queue = mp.Queue()
    total_restarts = mp.Value("i", 0)
    manager = mp.Manager()
    result_list = manager.list() if output_stream_path is None else None
    lock = manager.Lock() if output_stream_path is None else manager.Lock()
    result_queue = mp.Queue() if output_stream_path else None
    progress_count = mp.Value("i", 0) if output_stream_path else None

    for proof in proofs:
        task_queue.put(proof)
    for _ in range(num_workers):
        task_queue.put(_TASK_SENTINEL)

    if output_stream_path:
        writer = threading.Thread(target=_writer_thread, args=(result_queue, output_stream_path))
        writer.start()

    workers = []
    for i in range(num_workers):
        process = mp.Process(
            target=worker,
            args=(i, task_queue, result_list, total_restarts, lock, allTactics, ast, premises, tactics, timeout, imports),
            kwargs={"result_queue": result_queue, "progress_count": progress_count, "oom_list": oom_list},
        )
        process.start()
        workers.append(process)

    total_proofs = len(proofs)
    while any(w.is_alive() for w in workers):
        time.sleep(10)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if output_stream_path and progress_count is not None:
            n = progress_count.value
        else:
            n = len(result_list) if result_list is not None else 0
        print(f"[{ts}] Progress: {n}/{total_proofs} proofs processed. REPL errors: {total_restarts.value}", flush=True)

    for process in workers:
        process.join()

    if output_stream_path:
        result_queue.put(None)
        writer.join()
        task_queue.close()
        task_queue.join_thread()
        print(f"All proofs processed! Total REPL Errors: {total_restarts.value}", flush=True)
        return None
    task_queue.close()
    task_queue.join_thread()
    print(f"All proofs processed! Total REPL Errors: {total_restarts.value}", flush=True)
    return list(result_list)






if __name__ == '__main__':
    print(scheduler(proof_code_list_sample, num_workers=16, allTactics=False, ast=False, premises=False, tactics=False))
