# 计算三轮平均 Pass@32 的剩余工作

## 当前状态

- **round_1**：2/5 参考，已有 `pass_at_32_summary.txt`（Pass@32 = 0.9180）。
- **round_2**：本次第一轮，已有 `code_compilation_repl.json` 与 `pass_at_32_summary.txt`（当前为 0.0000）。
- **round_3**：本次第二轮，仅有推理结果（`to_inference_codes.json`、`full_records.json`），**尚未跑编译**，故无 `code_compilation_repl.json` 与 `pass_at_32_summary.txt`。

## 剩余工作（按顺序）

1. **研究并修复编译流程**  
   当前在 Zam 环境下对 round_2 的编译全部失败（Pass@32 = 0），需先排查：
   - Lean / mathlib4 版本与构建（与 2/5 或 goedel_EXPERIMENT 是否一致）；
   - REPL 的 cwd、search path、env 传递；
   - 必要时对照 [goedel_EXPERIMENT](https://github.com/ZZZamchi/goedel_EXPERIMENT) 的 `lean_compiler` 与运行方式，确保能复现 2/5 的编译行为。

2. **对 round_3 跑编译**  
   在编译流程可用后，对 round_3 的推理结果跑一次编译：
   ```bash
   python3 src/compile.py \
     --input_path results/minif2f/round_3/to_inference_codes.json \
     --output_path results/minif2f/round_3/code_compilation_repl.json \
     --cpu <N>
   ```
   得到 `round_3/code_compilation_repl.json`。

3. **生成 round_3 的 Pass@32**  
   ```bash
   python3 scripts/calculate_pass_at_k.py results/minif2f/round_3/code_compilation_repl.json 32
   ```
   会写入 `round_3/pass_at_32_summary.txt`。

4. **计算三轮平均 Pass@32**  
   当 round_1、round_2、round_3 均有 `pass_at_32_summary.txt` 后，执行：
   ```bash
   python3 scripts/compute_average_pass_at_k.py results/minif2f
   ```
   会在 `results/minif2f/average_pass_at_32.txt` 中写入：
   - round_1 (2/5) Pass@32
   - round_2 Pass@32
   - round_3 Pass@32
   - average(round_2, round_3) Pass@32  

   若需**三轮数值平均**（(r1+r2+r3)/3），可在 `compute_average_pass_at_k.py` 中增加一行输出，或自行用三份 summary 计算。

## 小结

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 研究并修复编译（使 round_2/round_3 能正确编译） | Lean/mathlib4/REPL 环境 |
| 2 | 对 round_3 跑 compile | 步骤 1 |
| 3 | 对 round_3 跑 calculate_pass_at_k 得到 pass_at_32_summary.txt | 步骤 2 |
| 4 | 跑 compute_average_pass_at_k 得到三轮与平均 Pass@32 | 步骤 3；round_1 已有 summary |

当前阻塞点在**步骤 1**：编译未通过，需先解决环境或 REPL 用法后再完成 2→3→4。

---

## 给新对话的提示词（简略）

本仓库有三轮结果：round_1=2/5 参考（Pass@32 已有），round_2 已编译但全 0，round_3 仅推理未编译。要算三轮平均 Pass@32，需先：① 研究并修复编译（对照 docs/REFERENCE_2_5.md 与 lean_compiler）；② 对 round_3 跑 compile → calculate_pass_at_k；③ 运行 `scripts/compute_average_pass_at_k.py results/minif2f` 得到 average_pass_at_32.txt。若需 (r1+r2+r3)/3，在 compute_average_pass_at_k.py 中加一行即可。
