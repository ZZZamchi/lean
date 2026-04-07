#!/usr/bin/env bash
# 兼容入口：等同于 minif2f_subproblem_mvp.sh full
exec "$(cd "$(dirname "$0")" && pwd)/minif2f_subproblem_mvp.sh" full "$@"
