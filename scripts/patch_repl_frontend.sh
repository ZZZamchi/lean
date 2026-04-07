#!/bin/bash
# 为 REPL Frontend 增加 LEAN_PATH 支持，使 import Mathlib 能解析（修复 init pass: False / unknown namespace BigOperators）
set -e
FRONTEND="${1:-.lake/packages/REPL/REPL/Frontend.lean}"
cd "$(dirname "$0")/../mathlib4"
if [ ! -f "$FRONTEND" ]; then
  echo "Run from Zam/lean: first run 'cd mathlib4 && lake exe repl' once to fetch REPL, then run this script."
  exit 1
fi
# 在 "Lean.initSearchPath" 前插入 LEAN_PATH 分支
if grep -q "IO.getEnv \"LEAN_PATH\"" "$FRONTEND" 2>/dev/null; then
  echo "Already patched: $FRONTEND"
  exit 0
fi
sed -i.bak 's|  Lean.initSearchPath (← Lean.findSysroot)|  let pathStr ← IO.getEnv "LEAN_PATH"\n  match pathStr with\n  | some s => Lean.searchPathRef.set (s.splitOn ":")\n  | none => Lean.initSearchPath (← Lean.findSysroot)|' "$FRONTEND"
echo "Patched $FRONTEND (backup: ${FRONTEND}.bak). Rebuild with: cd mathlib4 && lake build REPL"
exit 0
