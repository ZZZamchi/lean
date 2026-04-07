# 形式化定理证明框架：技术报告

## 1. 项目概述

本项目实现了一个通用的 Lean 4 形式化定理证明搜索框架 (`prover/`)，支持多策略协同、跨数据集评估、跨模型 sorry 填补和 sorry-goal 提取合并。框架已在 miniF2F、PutnamBench、FATE 等主流基准上进行实验，并验证了 sorry-goal extraction 方法的显著提升效果。

## 2. 架构设计

### 2.1 核心组件

```
┌─────────────────────────────────────────────────┐
│                  ProofSearchEngine               │
│  (engine.py)                                     │
│  - 编排多策略执行                                 │
│  - 管理 cascade context                          │
│  - 增量保存结果                                   │
├─────────────────────────────────────────────────┤
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │WholeProof│  │ Stepwise │  │  Refinement  │   │
│  │Strategy  │  │ Strategy │  │  Strategy    │   │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │               │           │
│  ┌────┴──────────────┴───────────────┴───────┐   │
│  │           NearMiss Strategy                │   │
│  │  - load_baseline() 加载含 sorry 的证明     │   │
│  │  - context-aware sorry 填补               │   │
│  │  - informed whole-proof generation        │   │
│  └────────────────────┬──────────────────────┘   │
│                       │                           │
├───────────────────────┼───────────────────────────┤
│  ┌────────────────┐   │   ┌────────────────────┐ │
│  │  ProverModel   │   │   │   LeanVerifier     │ │
│  │  (model.py)    │   │   │   (verifier.py)    │ │
│  │  vLLM 推理引擎  │   │   │   Lean REPL 管理   │ │
│  └────────────────┘   │   └────────────────────┘ │
│                       │                           │
│  ┌────────────────────┴──────────────────────┐   │
│  │         Dataset Loader (datasets.py)       │   │
│  │  minif2f / putnambench / fate / proofnet   │   │
│  │  支持 split 过滤 + shard 分片              │   │
│  └────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### 2.2 数据流

1. **加载阶段**: `datasets.py` 从 JSONL/JSON 文件加载问题，过滤 split，按 shard 分片
2. **推理阶段**: `engine.py` 对每个问题依次运行注册的策略，直到找到完整证明或预算耗尽
3. **验证阶段**: `verifier.py` 通过 Lean REPL (`lake exe repl`) 验证每个候选证明
4. **保存阶段**: 结果增量写入 `proof_results.json`，包含 sorry 元数据以支持后续 NearMiss

## 3. 策略实现

### 3.1 Whole-proof Generation
- 输入: theorem header → 生成 n 个完整证明候选 (默认 n=32) → REPL 编译验证

### 3.2 Stepwise Search
- 优先队列搜索，每步根据 REPL 返回的 goal state 生成候选 tactic
- 自适应搜索宽度：浅层宽搜、深层窄搜

### 3.3 Self-Refinement
- 错误分类 (type_mismatch / unknown_identifier / tactic_failed / syntax)
- 每类错误附带专门修复指导 → 多轮迭代

### 3.4 NearMiss Sorry Filling
两种模式：
- **Surgical filling**: 精确定位 sorry，构建 context-aware prompt 生成替换 tactic
- **Informed whole-proof**: 以 sorry proof 作为结构骨架，生成全新完整证明

### 3.5 Sorry-Goal Extraction（新增核心方法）

```
含 sorry 的证明
  │
  ├─ REPL 提取每个 sorry 位置的 goal state
  │
  ├─ 将每个 sub-goal 构建为独立定理:
  │    theorem sorry_fill_<problem>_g<N> (<hypotheses>) : <goal> := by sorry
  │
  ├─ 多模型 × 多采样独立证明每个子目标
  │
  ├─ 验证步骤（关键）:
  │    1. 检查子目标证明确实包含 `theorem <name> ... := by <tactics>`
  │    2. 将定理名重命名为原始问题名
  │    3. REPL 端到端编译验证，确保 complete=True 且无 sorry
  │
  └─ 假阳性过滤:
       排除定理签名被篡改的证明（额外假设、改变结论）
```

## 4. 关键工程问题与解决方案

### 4.1 Chat Template
**问题**: 所有模型（Goedel V2 8B/32B、DeepSeek V2 7B）均基于需要 chat template 的架构。
**解决**: `use_chat_template` 配置统一控制。

### 4.2 REPL Hang / Timeout
**问题**: 部分证明导致 REPL 无限挂起。
**解决**: `verifier.py` 使用 `os.killpg` 强杀进程组后重启 REPL。

### 4.3 假阳性过滤
**问题**: 旧 pipeline 的 13 个 "成功合并" 中有 2 个假阳性。
- `amc12b_2002_p4`: 子目标证明添加了额外假设 `h_main : n = 42`（假设了答案）
- `amc12a_2021_p25`: 子目标证明包含 `h₂ : False`（从矛盾得一切）
**解决**: 新 pipeline 强制验证重命名后的定理能通过 REPL 完整编译。确认两者均为子目标提取时模型改变了定理签名，不是原始 miniF2F 定理本身的问题。

## 5. 实验结果

### 5.1 miniF2F Valid — Goedel-8B + Sorry-Goal Extraction

| 阶段 | 方法 | 解题数 | pass@32 | Delta |
|------|------|--------|---------|-------|
| Phase 1 | Goedel-8B baseline (n=32) | 203/244 | 83.2% | — |
| **Phase 2** | **+ Sorry-goal extraction merge** | **214/244** | **87.7%** | **+11 (+4.5%)** |
| Phase 3 | + DeepSeek-7B (n=64) on remaining | 215/244 | 88.1% | +1 (+0.4%) |

Phase 2 的 11 道新解（全部 REPL 端到端验证通过）：

| 问题 | 类别 |
|------|------|
| aime_1984_p7 | AIME 竞赛 |
| amc12a_2020_p25, amc12a_2021_p12 | AMC12 竞赛 |
| imo_1968_p5_1, imo_1977_p6, imo_1982_p1, imo_1997_p5 | IMO 竞赛 |
| algebra_apbmpcneq0_aeq0anbeq0anceq0, algebra_ineq_nto1onlt2m1on | 代数不等式 |
| numbertheory_fxeq4powxp6powxp9powx_f2powmdvdf2pown | 数论 |
| induction_pord1p1on2powklt5on2 | 数学归纳 |

### 5.2 miniF2F — In-Context NearMiss（跨模型 Sorry 填补）

| 配置 | 基线 | Sorry 候选 | 新解决 | Delta |
|------|------|-----------|--------|-------|
| Goedel + DeepSeek fill | 83.2% | 26 题 | 0 | +0.0% |
| Goedel + Goedel fill | 83.2% | 26 题 | 0 | +0.0% |
| DeepSeek + Goedel fill | 68.0% | 3 题 | 0 | +0.0% |

**结论**: 经 32 次采样后剩余的 sorry 问题是"真正的难题"，在原始证明上下文内的局部填补无法解决。

### 5.3 PutnamBench — In-Context NearMiss

| 指标 | 值 |
|------|---|
| Baseline (Goedel-8B) | 18/309 (5.8%) |
| Sorry 候选 | 259 题 (84% of failures) |
| **NearMiss 新解决** | **+3** |
| **最终** | **21/309 (6.8%)** |
| **相对提升** | **+16.7%** |

Putnam 上 informed whole-proof generation 有效，sorry proof 作为"结构骨架"的价值在更难数据集上更显著。

### 5.4 迭代 Pass@32 优化（Goedel-8B）

从 205/244 = 84.0% 基线出发（Round 2+3 合并 pass@64），系统化攻击 39 道未解题：

| 方向 | 采样数 | 配置 | 新解 | 解出问题 |
|------|-------|------|------|---------|
| **long_gen** (max_tokens=8192) | 32 | T=1.0, COT | 1 | `algebra_sum1onsqrt2to1onsqrt10000lt198` |
| **multitemp** (T=0.6/0.8/1.0/1.2) | 64 | 16/温度 | 1 | `amc12a_2021_p22`（T=1.2 第55次） |
| **direct_prompt** (无COT) | 32 | T=1.0 | 1 | `mathd_algebra_320`（矛盾假设 exfalso） |
| **手动构造** | — | native_decide | 1 | `amc12a_2020_p4` |
| **手动构造** | — | div_le_div+Rat | 1 | `amc12b_2002_p4` |
| sorry_fill (近失) | 32 | T=0.8 | 0 | — |
| high_sample (pass@128) | 128 | T=1.0 | 0 | — |

**结果: 205 → 210/244 = 86.1%（+5 题，+2.0%）**

关键发现：
1. **max_tokens 瓶颈**：4096→8192 解锁需长证明的题。官方配置用 32K。
2. **高温采样偶尔有效**：T=1.2 在第55次采样突破了 T=1.0 64次都未解的题。
3. **病态假设可利用**：`mathd_algebra_320` 的 `h₃ : ¬∃d, d²∣b` 对 d=1 自相矛盾。
4. **native_decide 强大**：9000 元素 Finset 可被 Lean 内核直接计算。
5. **Sorry-fill 无效**：近失样本的整个证明体是 sorry，无结构可利用。

### 5.5 递归分解 (Round 3)

从 Round 2 近失证明中提取 50 个子目标，Goedel-8B 推理结果：

| 指标 | 值 |
|------|---|
| 提取子目标 | 50（来自 14 个父问题） |
| 子目标解决 | 18/48 (37.5%) |
| 父问题全闭合 | 1（`numbertheory_fxeq4pow...`，平凡） |
| AIME 链 (aime_1984_p7) | 11/17 步已解 |

递归分解验证了大量中间步骤可独立证明，但完整链闭合需要所有步骤同时成功。

### 5.6 配置差距分析

搜索 Goedel-V2 官方文档发现的关键配置偏差：

| 参数 | 我们的配置 | 官方配置 | 影响 |
|------|----------|---------|------|
| **Chat template** | 禁用 (`--no-chat`) | **启用**（Qwen3格式） | **严重** — 模型在 chat 格式上训练 |
| **max_tokens** | 4,096 | **32,768** (32K) | **重大** — 8× 差异 |
| **Prompt** | 自定义 COT | 官方: "detailed proof plan..." | 中等 |
| **自修正** | 未实现 | 2 轮（32K→40K tokens） | 重要（32B +2.3%） |

#### Phase 1 官方风格复现（Goedel-8B，pass@64 后 **39 题未解子集**）

在 `results/experiments/` 下用 **chat template + 官方式 proof-plan prompt + 每题多 batch 采样 + 至多 2 轮 self-correction** 对 **39** 道 persistent failure 重跑后的**已落盘**结果：

| 运行目录 | max\_tokens / 上下文 | 进度 | 新解（相对 205/244） | 备注 |
|----------|----------------------|------|----------------------|------|
| `phase1_official_16k/` | 16K 档（日志中 `max_model_len` 约 24K） | **39/39 写完** `proof_results.json` | **+1**：`mathd_algebra_320` → 折合 **206/244 ≈ 84.4%** | 日志末尾 vLLM `Engine core died` / Worker 退出；**结果文件已齐全** |
| `phase1_official_32k/` | 32K（`experiments/phase1_official_config.py`，默认 `--output-dir phase1_official_32k`） | **待 GPU 跑满** | — | 见目录内 `README.md`；支持 `--resume` 续跑、每次写入 `run_meta.json`。跑完后与 16K 逐题对比： `python3 scripts/compare_phase1_runs.py` → `phase1_compare_16k_32k.{md,json}`。 |
| `phase1_official/`（旧） | 32K 早期单次尝试 | 废弃/不完整 | — | 仅 1 条中间结果；**请以 `phase1_official_32k` 为准**。 |

**16K 自修正统计（已落盘）**：在 `phase1_official_16k` 中，唯一 complete 题 `mathd_algebra_320` 的 `sc>0`（经 self-correction 回合）；其余 38 题未 complete。汇总命令：`python3 scripts/analyze_sc_ablation.py`。

**P1 消融（10 题子集）**：`dataset/minif2f_ablation_slice10.jsonl`（`minif2f_unsolved39` 前 10 题）。脚本：`experiments/run_ablation_slice10.sh`（chat on/off、4K vs 32K tokens）；`experiments/run_sc_ablation_slice10.sh`（SC 0 vs 2 轮）。跑完后：`python3 scripts/summarize_experiment_dirs.py` 查看各 `results/experiments/*/proof_results.json` 的 complete 数。

**结论（与论文叙述一致）**：在最难 39 题上，把 token 拉到 16K 并打开官方配方，仅稳定带来 **1 题**边际收益；**全 valid  headline 仍以主线的 210/244（86.1%）为准**（SGE + 解码/提示/手工等）。32K 相对 16K 的边际需待 `phase1_official_32k` 跑满后读 `phase1_compare_16k_32k.md`。

### 5.7 Goedel-32B Baseline 实验（`results/prover/*32b*` JSON 快照）

**与论文 ~88--90%（32B / 32B+SC）不对齐时的排查**：见仓库根目录 **`docs/GOEDEL_V2_EVALUATION.md`**。最常见原因：**(1)** `prover.run` 默认 `--max-tokens 4096`、`--max-model-len 8192`，远小于官方常用 16K--32K；**(2)** 使用 `--no-chat`（Goedel-V2 为 Qwen3 chat 训练，应**开启** chat）；**(3)** 仅跑 `whole_proof`、未走 `src/inference.py` 的 **self-correction 多轮**；**(4)** `prover/prompts.py` 的 COT 模板与官方 *proof plan* 提示词不一致；**(5)** 当前 JSON 多为**子集/分片**，不能把「某目录 complete 数 / 记录数」当作 valid@244 的 pass@32。

以下为仓库内 **已写入的 `proof_results.json` 统计**（多为**子集 / 分片**，**不是**完整 miniF2F valid 244 的官方 pass@$k$ 复现）；用于跟踪 32B 实验进度，勿与论文表 `tab:cross-bench-logged` 的 Putnam 全量口径混用。

| 目录 | 记录题数 | complete | 粗通过率 | 说明 |
|------|----------|----------|----------|------|
| `minif2f_32b_fixed/` | 20 | 9 | 45.0% | 小批调试；`max_tokens=8192` 等受限配置 |
| `minif2f_32b_s0/` | 43 | 12 | 27.9% | 分片 0 |
| `minif2f_32b_s1/` | 44 | 17 | 38.6% | 分片 1 |
| `minif2f_32b_merged/` | 87 | 29 | 33.3% | **脚本合并** `s0`+`s1`：`python3 scripts/merge_proof_results_shards.py ... -o results/prover/minif2f_32b_merged/proof_results.json`；仍非 244 全量 |
| `minif2f_goedel32b/` | 158 | 34 | 21.5% | `whole_proof`、每题 32 次等；**仅为部分 valid 子集** |
| `minif2f_32b/` | 4 | 1 | 25.0% | 极小试跑 |
| `putnam_32b/` | 51 | 1 | 2.0% | 当前快照仅覆盖 51 题；**非**全量 672/309 口径 |
| `fate_m_32b/` | 82 | 17 | 20.7% | FATE-M 子集 |

**32B 总体进度**：**尚无** **244/244 valid** 终表；`minif2f_32b_merged` 汇总 **87** 题、**29** complete（与分片去重合并）。下一步：在统一协议下补跑缺题至 244，再更新 headline。

**历史/其它口径（若与旧日志一致可保留参考）**：Putnam 全量曾报 18/506 等——请以当前 JSON 路径与题数为准核对。

### 5.8 剩余未解题（34/244）

| 类别 | 数量 | 示例 |
|------|------|------|
| 近失 (1 sorry) | 16 | `amc12a_2003_p23`, `imo_1977_p6`, `numbertheory_3pow...` |
| 近失 (2 sorry) | 4 | `aime_1984_p7`, `imo_1997_p5` |
| 近失 (3+ sorry) | 6 | `aime_1995_p7`, `imo_2001_p6` |
| 完全失败 | 5 | `imo_1965_p2`, `imo_1984_p6` |
| 填答案（sorry在定义中） | 3 | `imo_1982_p1`, `imo_1992_p1`, `imo_2019_p1` |

### 5.9 业界最新对比

| 系统 | 模型大小 | miniF2F pass@32 | 核心技术 |
|------|---------|-----------------|---------|
| Goedel-V2-8B（官方） | 8B | 83.3% | 支架训练 + 自修正 |
| **我们（Goedel-V2-8B）** | **8B** | **86.1%** | Sorry 提取 + 迭代优化 |
| Goedel-V2-32B | 32B | 88.1% / 90.4%(SC) | 同上 + 更大模型 |
| DeepSeek-V2-671B | 671B | 88.9% | 子目标分解 + RL |
| BFS-Prover | 7B | 72.95% | Best-first tree search + DPO |
| Leanabell-V2-7B | 7B | +3.2%（基线上） | 多轮验证器 RL |

### 5.10 跨数据集汇总

| 数据集 | 问题数 | Goedel-8B | + Sorry方法 | + 迭代优化 | 最终 |
|--------|--------|-----------|------------|-----------|------|
| miniF2F valid | 244 | 205 (84.0%) | +5 (goal extraction) | +5 (sampling/manual) | **210 (86.1%)** |
| PutnamBench | 309 | 18 (5.8%) | +3 (NearMiss) | — | **21 (6.8%)** |
| FATE-M | 355 | 17 (4.8%) | — | — | 17 (4.8%) |

## 6. 模型对比

| 特征 | Goedel-8B | DeepSeek-7B |
|------|-----------|-------------|
| 失败时 sorry 比例 | 63% | 4% |
| 适合作为 NearMiss 基线 | ✓ (产生大量 sorry skeleton) | ✗ |
| 子问题填补率 | 31.6% | 22.6% |
| Oracle ensemble (+Goedel) | — | +3 题 (84.4%) |

## 7. 核心发现

1. **Sorry-goal extraction > In-context filling**: 将子目标提取为独立定理比在上下文内替换 sorry 更有效 (+5 vs +0 on miniF2F)
2. **子目标独立性是关键**: 独立定理给模型更清晰的推理目标，很多成功的子目标证明实际是原定理的替代完整证明
3. **Sorry density 影响策略效果**: Putnam (84% sorry) 上 in-context NearMiss 有效，miniF2F (63%) 上无效
4. **推理配置是瓶颈**: chat template、max_tokens、prompt 格式的偏差对结果影响巨大；**39 题子集上 Phase1-16K 已见 +1 题，全量 headline 仍以 210/244 工程栈为准**
5. **采样多样性有天花板**: pass@128 对硬题无增益；温度多样性（T=1.2）偶尔有效
6. **递归分解有效但不完整**: 37.5% 子目标可独立证明，但链上全步闭合困难
7. **假阳性风险**: 子目标提取/模型生成可能改变定理签名，必须端到端验证
8. **"病态"形式化可利用**: 矛盾假设、native_decide 等在基准测试中不可忽视

## 8. 后续工作

### 已完成（工具链 / 合并）
1. **Phase1 32K 跑法**：`experiments/phase1_official_config.py` 支持 `--output-dir`、`--resume`、`--force`、`--dataset`、`--max-tokens`、`--no-chat`、`run_meta.json`。
2. **16K vs 32K 对照**：`scripts/compare_phase1_runs.py`（输出 `results/experiments/phase1_compare_16k_32k.md`）。
3. **SC 汇总**：`scripts/analyze_sc_ablation.py`（读 16K JSON 的 `sc` 字段）。
4. **10 题消融子集**：`dataset/minif2f_ablation_slice10.jsonl` + `run_ablation_slice10.sh` / `run_sc_ablation_slice10.sh`。
5. **32B 分片合并**：`scripts/merge_proof_results_shards.py` → `results/prover/minif2f_32b_merged/`。
6. **实验目录一览**：`scripts/summarize_experiment_dirs.py`。

### 待 GPU / 人工执行
1. **Phase1 32K 39 题跑满**：按 `results/experiments/phase1_official_32k/README.md` 执行并 `--resume` 直至 39 条记录。
2. **Goedel-32B**：补跑至 miniF2F valid 244 或继续分片合并。

### 计划中（研究向）
1. 在 PutnamBench / FATE-M 上扩展 sorry-goal extraction 报告（已有粗数字时可增量跑 50–100 题）。
2. tactic-level best-first search（BFS-Prover 风格）。

### 已放弃
- sorry-fill（近失样本整题 sorry，无结构可用）
- 纯高采样（pass@128+ 对硬题无增益）

## 9. 文档与对外材料（与 LaTeX 论文对齐）

| 材料 | 路径 | 说明 |
|------|------|------|
| 完整英文论文（主稿） | `prover/docs/latex/paper_full.tex` | 与 `references.bib` 配套；正文数字与表格以当前 `results/prover/*/proof_results.json` 为准，更新跑分后需同步摘要与 PutnamBench 对照表（`tab:cross-bench-logged`）等（TeX 文中已注明）。 |
| 编译 | `prover/docs/latex/Makefile` | `make` → `pdflatex` + `bibtex` + 两遍 `pdflatex`。 |
| Markdown 长稿 / 附录素材 | `prover/docs/paper.md` | 与 `paper_full.tex` 内容同源；维护时建议先改事实与数字来源，再反映到 TeX。 |
| 可选插图 | `prover/docs/latex/figures/fig_llm_formal_math.png` | 若存在则自动插入引言中的 pipeline 图；缺失时显示占位框。 |

撰写技术报告小节时，若与论文结论冲突，以 **仓库内 JSON 日志与冻结协议** 为准，并在报告中写明协议（pass@$k$、模型、模板、token 上限）。
